"""Recovery path for one bridge, as a pure state machine.

    LIVE -> PAID_ON_TIME | LATE | BYPASS | DISPUTE | ABANDONED -> RECOVERY -> WRITTEN_OFF
    (a bridge that is paid in full after going late closes as PAID_LATE)

Every function returns a new bridge and the tasks it created. The engine contacts nobody:
people carry the tasks out. A licensed moneylender may not visit the borrower's home or
workplace to collect (Moneylenders Act 1951, Section 29(B)). No task here asks for a visit.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from .config import get, require
from .waterfall import allocate_loss

LIVE, PAID_ON_TIME, PAID_LATE = "LIVE", "PAID_ON_TIME", "PAID_LATE"
LATE, BYPASS, DISPUTE, ABANDONED = "LATE", "BYPASS", "DISPUTE", "ABANDONED"
RECOVERY, WRITTEN_OFF = "RECOVERY", "WRITTEN_OFF"
CLOSED = {PAID_ON_TIME, PAID_LATE, WRITTEN_OFF}
OPEN_PROBLEM = {LATE, DISPUTE, RECOVERY}

REQUIRED = [
    "collections.days_past_due_reminder",
    "collections.days_past_due_notice",
    "collections.days_past_due_escalate",
    "collections.write_off_after_days",
]
NOTICE_CODES = {"REMIND_PAYER", "SEND_NOTICE"}


class InvalidTransition(Exception):
    pass


@dataclass(frozen=True)
class Task:
    code: str
    owner: str            # job source | financier | collections owner | supplier
    text: str
    bridge_id: str
    days_past_due: int


@dataclass(frozen=True)
class LiveBridge:
    bridge_id: str
    job_id: str
    borrower_id: str
    amount: float
    outstanding: float = -1.0            # defaults to amount
    state: str = LIVE
    days_past_due: int = 0
    cause: Optional[str] = None          # late | bypass | dispute | abandoned
    held_amount: float = 0.0             # disputed part held by the job source
    history: tuple[str, ...] = (LIVE,)
    tasks: tuple[Task, ...] = ()
    loss: Optional[float] = None
    allocation: Optional[dict] = None
    cured: bool = False                  # bypass repaid in full and approved by a named officer

    def __post_init__(self):
        if self.outstanding < 0:
            object.__setattr__(self, "outstanding", self.amount)


def _move(b: LiveBridge, state: str, new: list[Task], **kw) -> tuple[LiveBridge, list[Task]]:
    hist = b.history if b.history[-1] == state else b.history + (state,)
    return replace(b, state=state, history=hist, tasks=b.tasks + tuple(new), **kw), new


def _task(b: LiveBridge, code: str, owner: str, text: str, dpd: Optional[int] = None) -> Task:
    return Task(code, owner, text, b.bridge_id, b.days_past_due if dpd is None else dpd)


def _guard(b: LiveBridge, allowed: set[str], event: str) -> None:
    if b.state not in allowed:
        raise InvalidTransition(f"{event} is not allowed from {b.state}")


def payment(b: LiveBridge, amount: float) -> tuple[LiveBridge, list[Task]]:
    """Money reached the controlled account (or a recovery came in)."""
    _guard(b, {LIVE} | OPEN_PROBLEM, "payment")
    left = max(0.0, b.outstanding - amount)
    if left > 0:
        return replace(b, outstanding=left), []
    final = PAID_ON_TIME if b.state == LIVE and b.days_past_due == 0 else PAID_LATE
    return _move(b, final, [], outstanding=0.0, held_amount=0.0)


def bypass(b: LiveBridge) -> tuple[LiveBridge, list[Task]]:
    """The customer paid the borrower instead of the controlled account."""
    _guard(b, {LIVE, LATE}, "bypass")
    b, _ = _move(b, BYPASS, [], cause="bypass")
    tasks = [
        _task(b, "TELL_BORROWER_TO_REMIT", "financier", "Tell the borrower to remit the payment received."),
        _task(b, "HOLD_OTHER_BALANCES", "financier", "Hold the borrower's other balances."),
        _task(b, "BLOCK_NEW_BRIDGES", "financier", f"Block new bridges for borrower {b.borrower_id}."),
        _task(b, "START_RECOVERY", "collections owner", "Start recovery from the borrower."),
    ]
    return _move(b, RECOVERY, tasks)


def dispute(b: LiveBridge, disputed_amount: float) -> tuple[LiveBridge, list[Task]]:
    _guard(b, {LIVE, LATE}, "dispute")
    held = min(disputed_amount, b.outstanding)
    tasks = [
        _task(b, "HOLD_DISPUTED_PART", "job source", f"Hold the disputed RM{held:,.2f}."),
        _task(b, "MEDIATE", "job source", "Mediate between payer and borrower."),
    ]
    return _move(b, DISPUTE, tasks, cause="dispute", held_amount=held)


def dispute_borrower_at_fault(b: LiveBridge) -> tuple[LiveBridge, list[Task]]:
    _guard(b, {DISPUTE}, "dispute_borrower_at_fault")
    t = [_task(b, "START_RECOVERY", "collections owner", "Borrower at fault: start recovery from the borrower.")]
    return _move(b, RECOVERY, t)


def abandon(b: LiveBridge) -> tuple[LiveBridge, list[Task]]:
    _guard(b, {LIVE, LATE}, "abandon")
    b, _ = _move(b, ABANDONED, [], cause="abandoned")
    tasks = [
        _task(b, "SUPPLIER_TAKE_BACK", "supplier", "Ask the supplier to take back unused materials for credit."),
        _task(b, "START_RECOVERY", "collections owner", "Start recovery from the borrower for the balance."),
    ]
    return _move(b, RECOVERY, tasks)


def advance_days(b: LiveBridge, days_past_due: int, cfg: dict, **layer_overrides) -> tuple[LiveBridge, list[Task]]:
    """Move the clock to `days_past_due`. Fires each threshold once, in order.

    LATE: reminder (job source), notice under the payment instruction (financier), then escalate
    to RECOVERY (collections owner). Any open problem state is written off at write_off_after_days.
    """
    require(cfg, REQUIRED)
    if b.state in CLOSED:
        return b, []
    if days_past_due < b.days_past_due:
        raise InvalidTransition("days_past_due cannot go backwards")
    if b.state == LIVE and days_past_due > 0:
        b, _ = _move(b, LATE, [], cause="late")
    old = b.days_past_due
    b = replace(b, days_past_due=days_past_due)
    new: list[Task] = []
    crossed = lambda key: old < get(cfg, key) <= days_past_due  # noqa: E731

    if b.state == LATE:
        if crossed("collections.days_past_due_reminder"):
            new.append(_task(b, "REMIND_PAYER", "job source", "Job source reminds the payer.",
                             get(cfg, "collections.days_past_due_reminder")))
        if crossed("collections.days_past_due_notice"):
            new.append(_task(b, "SEND_NOTICE", "financier", "Financier sends notice under the payment instruction.",
                             get(cfg, "collections.days_past_due_notice")))
        if crossed("collections.days_past_due_escalate"):
            new.append(_task(b, "ESCALATE", "collections owner", "Escalate to the collections owner; start recovery.",
                             get(cfg, "collections.days_past_due_escalate")))
            b, _ = _move(b, RECOVERY, [])
    b = replace(b, tasks=b.tasks + tuple(new))

    if b.state in OPEN_PROBLEM and days_past_due >= get(cfg, "collections.write_off_after_days"):
        b, wt = write_off(b, cfg, **layer_overrides)
        new += wt
    return b, new


def write_off(b: LiveBridge, cfg: dict, reserve_remaining: Optional[float] = None,
              guarantor_cap_remaining: Optional[float] = None) -> tuple[LiveBridge, list[Task]]:
    """Write off the outstanding balance and allocate it through the loss waterfall (one call).

    Pass the cohort's remaining reserve and guarantor cap; they default to the full config values.
    """
    _guard(b, OPEN_PROBLEM, "write_off")
    keys = ["layers.first_loss_reserve"]
    if get(cfg, "layers.guarantor_enabled"):
        keys += ["layers.guarantor_cover_pct", "layers.guarantor_cap"]
    require(cfg, keys)
    reserve = get(cfg, "layers.first_loss_reserve") if reserve_remaining is None else reserve_remaining
    cap = (get(cfg, "layers.guarantor_cap") or 0.0) if guarantor_cap_remaining is None else guarantor_cap_remaining
    loss = b.outstanding
    alloc = allocate_loss(loss, reserve, get(cfg, "layers.guarantor_cover_pct") or 0.0, cap,
                          bool(get(cfg, "layers.guarantor_enabled")))
    t = [_task(b, "OPEN_CLAIM_FILE", "financier", f"Write-off RM{loss:,.2f}. Prepare the claim file.")]
    return _move(b, WRITTEN_OFF, t, loss=loss, allocation=alloc)


def should_chase(expected_recovery: float, cost_of_chasing: float, cfg: Optional[dict] = None) -> bool:
    """Stop rule: do not chase when expected recovery is below the cost of chasing.

    With a config, also stop below `collections.min_expected_recovery_to_chase`.
    """
    floor = 0.0
    if cfg is not None:
        require(cfg, ["collections.min_expected_recovery_to_chase"])
        floor = get(cfg, "collections.min_expected_recovery_to_chase")
    return expected_recovery >= cost_of_chasing and expected_recovery >= floor


def approve_cure(b: LiveBridge) -> tuple[LiveBridge, list[Task]]:
    """Lift a bypass block (author decision A7): only after the bypassed amount is repaid in full
    into the controlled account (the bridge closed as PAID_LATE) and a named officer approves.
    Calling this function is that approval."""
    if b.cause != "bypass" or b.state != PAID_LATE:
        raise InvalidTransition("a cure needs a bypass bridge repaid in full")
    t = [_task(b, "LIFT_BLOCK", "credit officer", f"Bypass repaid in full: lift the block on borrower {b.borrower_id}.")]
    return replace(b, cured=True, tasks=b.tasks + tuple(t)), t


def blocked_borrowers(bridges: list[LiveBridge]) -> set[str]:
    """Borrowers blocked from new bridges (author decision A7).

    One bypass blocks until it is cured (`approve_cure`). A second bypass blocks for the rest of
    the pilot, cured or not.
    """
    counts: dict[str, int] = {}
    uncured: set[str] = set()
    for b in bridges:
        if b.cause == "bypass":
            counts[b.borrower_id] = counts.get(b.borrower_id, 0) + 1
            if not b.cured:
                uncured.add(b.borrower_id)
    return uncured | {who for who, n in counts.items() if n >= 2}


CLAIM_ITEMS = [
    ("job_record", "Job record (quote, confirmation, deposit)"),
    ("supplier_invoice", "Supplier invoice"),
    ("controlled_account_receipts", "Controlled-account receipts"),
    ("notices_sent", "Notices sent"),
    ("recovery_steps", "Recovery steps taken"),
]


def claim_file(b: LiveBridge, evidence: Optional[dict] = None) -> dict:
    """Checklist a guarantor will ask for. Fills what exists; lists what is missing.

    `evidence` holds document references for the first three items. Notices and recovery steps
    come from the bridge's own task history.
    """
    ev = dict(evidence or {})
    ev.setdefault("notices_sent", [t.code for t in b.tasks if t.code in NOTICE_CODES])
    ev.setdefault("recovery_steps", [t.code for t in b.tasks if t.code not in NOTICE_CODES])
    items = [{"item": key, "label": label, "present": bool(ev.get(key)), "detail": ev.get(key)}
             for key, label in CLAIM_ITEMS]
    missing = [i["label"] for i in items if not i["present"]]
    return {"bridge_id": b.bridge_id, "items": items, "missing": missing, "complete": not missing}
