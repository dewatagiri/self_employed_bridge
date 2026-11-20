"""Pilot gates scored from a job log. Pass thresholds are not in the design: each one comes from
config (`gates.*`) and stays null until set. A null threshold gives NO_THRESHOLD_SET, never a guess.

    Gate 0 Size         share of confirmed quotes with deposit below materials cost (needs the jobs file)
    Gate 1 Mechanics    share of bridges with supplier paid directly AND customer paid into the controlled account
    Gate 2 Performance  share repaid on time from the customer's payment; bypass rate; loss against reserve
    Gate 3 Economics    fee collected against cost to serve plus loss
    Gate 4 Additionality  who the bridge reached (developmental pricing): new to formal credit, job needed it

Rule from the design: a second cohort may start only if cohort 1 is PASS on gates 1 and 2.
"""
from __future__ import annotations

import csv
import statistics
import typing
from dataclasses import dataclass, field, fields
from typing import Optional

from .config import get
from .models import Bridge, Job

PASS, FAIL, NO_THRESHOLD_SET, NO_DATA = "PASS", "FAIL", "NO_THRESHOLD_SET", "NO_DATA"


# ---------- reading (I/O kept out of the scoring functions) ----------

def _coerce(raw: str, typ):
    if raw is None or raw == "":
        return None
    t = typing.get_args(typ)[0] if typing.get_origin(typ) is typing.Union else typ
    if t is bool:
        return raw.strip().lower() in ("true", "1", "yes")
    if t is float:
        return float(raw)
    if t is int:
        return int(float(raw))
    return raw


def _read(path: str, cls):
    hints = typing.get_type_hints(cls)
    synthetic = False
    with open(path, encoding="utf-8", newline="") as fh:
        lines = []
        for line in fh:
            if line.startswith("#"):
                synthetic = synthetic or "SYNTHETIC" in line.upper()
                continue
            lines.append(line)
    rows = [cls(**{f.name: _coerce(r.get(f.name), hints[f.name]) for f in fields(cls) if f.name in r})
            for r in csv.DictReader(lines)]
    return rows, synthetic


def read_log(path: str) -> tuple[list[Bridge], bool]:
    """Returns (rows, synthetic). `synthetic` is true when the file header says SYNTHETIC."""
    return _read(path, Bridge)


def read_jobs(path: str) -> tuple[list[Job], bool]:
    return _read(path, Job)


# ---------- scoring ----------

@dataclass(frozen=True)
class Check:
    metric: str
    value: Optional[float]
    threshold: Optional[float]
    direction: str                       # "min" (value must be >=) or "max" (value must be <=)
    status: str


@dataclass
class GateResult:
    gate: int
    name: str
    value: Optional[float]               # headline value of the gate
    threshold: Optional[float]           # headline threshold
    status: str
    checks: list[Check] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def _check(metric, value, threshold, direction) -> Check:
    if threshold is None:
        st = NO_THRESHOLD_SET
    elif value is None:
        st = NO_DATA
    elif direction == "min":
        st = PASS if value >= threshold else FAIL
    else:
        st = PASS if value <= threshold else FAIL
    return Check(metric, value, threshold, direction, st)


def _combine(checks: list[Check]) -> str:
    sts = [c.status for c in checks]
    if FAIL in sts:
        return FAIL
    if all(s == PASS for s in sts):
        return PASS
    if NO_DATA in sts:
        return NO_DATA
    return NO_THRESHOLD_SET


def _share(n, d):
    return n / d if d else None


def gate0(jobs: Optional[list[Job]], cfg: dict) -> GateResult:
    thr = get(cfg, "gates.gate0_min_share")
    if jobs is None:
        value, detail = None, {"note": "no jobs file given"}
    else:
        confirmed = [j for j in jobs if j.payer_id and j.payer_id != j.borrower_id]
        short = [j for j in confirmed if j.deposit_amount < j.materials_cost]
        value = _share(len(short), len(confirmed))
        detail = {"confirmed_quotes": len(confirmed), "deposit_below_materials": len(short)}
    c = _check("share_deposit_below_materials", value, thr, "min")
    return GateResult(0, "Size", value, thr, c.status, [c], detail)


def gate1(rows: list[Bridge], cfg: dict) -> GateResult:
    thr = get(cfg, "gates.gate1_min_share")
    ok = [b for b in rows if b.paid_supplier_directly and b.customer_paid_into_controlled_account]
    value = _share(len(ok), len(rows))
    c = _check("share_supplier_direct_and_controlled_account", value, thr, "min")
    return GateResult(1, "Mechanics", value, thr, c.status, [c], {
        "bridges": len(rows), "both_ok": len(ok),
        "supplier_paid_directly": sum(b.paid_supplier_directly for b in rows),
        "customer_paid_controlled_account": sum(b.customer_paid_into_controlled_account for b in rows)})


def _reserve(cfg: dict, n_cohorts: int) -> Optional[float]:
    """The reserve is held per cohort (author decision A3), so n cohorts hold n reserves."""
    r = get(cfg, "layers.first_loss_reserve")
    return r * n_cohorts if r else None


def gate2(rows: list[Bridge], cfg: dict, n_cohorts: int = 1) -> GateResult:
    n = len(rows)
    on_time = [b for b in rows if b.outcome == "on_time" and b.customer_paid_into_controlled_account]
    bypass = [b for b in rows if b.outcome == "bypass"]
    loss = sum(b.loss_amount for b in rows)
    reserve = _reserve(cfg, n_cohorts)
    loss_to_reserve = loss / reserve if reserve else None
    checks = [
        _check("on_time_share", _share(len(on_time), n), get(cfg, "gates.gate2_min_on_time_share"), "min"),
        _check("bypass_rate", _share(len(bypass), n), get(cfg, "gates.gate2_max_bypass_rate"), "max"),
        _check("loss_to_reserve", loss_to_reserve, get(cfg, "gates.gate2_max_loss_to_reserve"), "max"),
    ]
    return GateResult(2, "Performance", checks[0].value, checks[0].threshold, _combine(checks), checks, {
        "on_time": len(on_time), "bypass_count": len(bypass), "total_loss": loss, "first_loss_reserve": reserve})


def gate3(rows: list[Bridge], cfg: dict) -> GateResult:
    fee = sum(b.fee_charged for b in rows)
    cost = sum(b.cost_to_serve for b in rows)
    loss = sum(b.loss_amount for b in rows)
    n = len(rows) or 1
    ratio = fee / (cost + loss) if (cost + loss) else None
    c = _check("fee_cover_ratio", ratio, get(cfg, "gates.gate3_min_fee_cover_ratio"), "min")
    return GateResult(3, "Economics", ratio, c.threshold, c.status, [c], {
        "fee_total": fee, "cost_to_serve_total": cost, "loss_total": loss, "net_total": fee - cost - loss,
        "fee_per_bridge": fee / n, "cost_per_bridge": cost / n, "loss_per_bridge": loss / n,
        "net_per_bridge": (fee - cost - loss) / n})


def _share_asked(rows: list[Bridge], field: str) -> tuple[Optional[float], int]:
    """Share of True among rows where the question was asked, and how many were asked."""
    asked = [getattr(b, field) for b in rows if getattr(b, field) is not None]
    return (sum(asked) / len(asked) if asked else None), len(asked)


def gate4(rows: list[Bridge], cfg: dict) -> GateResult:
    """Additionality (developmental pricing, A13). The funders accept a planned loss; this measures what it buys.

    Two shares, each over the borrowers who were asked: new to formal credit, and says the job would not
    have gone ahead without the bridge. A borrower counts as fully additional when both are true. Pass marks
    come from `gates.gate4_*` and stay null until set.
    """
    new, n_new = _share_asked(rows, "new_to_formal_credit")
    need, n_need = _share_asked(rows, "would_not_proceed_without_bridge")
    both = [b for b in rows if b.new_to_formal_credit and b.would_not_proceed_without_bridge]
    net = sum(b.fee_charged - b.cost_to_serve - b.loss_amount for b in rows)
    cost = max(0.0, -net)
    checks = [
        _check("share_new_to_formal_credit", new, get(cfg, "gates.gate4_min_new_to_credit_share"), "min"),
        _check("share_job_needed_bridge", need, get(cfg, "gates.gate4_min_job_needed_share"), "min"),
    ]
    return GateResult(4, "Additionality", new, checks[0].threshold, _combine(checks), checks, {
        "asked_new_to_credit": n_new, "asked_job_needed": n_need, "fully_additional_borrowers": len(both),
        "programme_net_total": net, "programme_cost_total": cost,
        "cost_per_fully_additional_borrower": (cost / len(both)) if both else None})


def measures(rows: list[Bridge], cfg: dict, n_cohorts: int = 1) -> dict:
    """The measures the design asks for in every cohort."""
    n = len(rows)
    hours = [b.quote_to_supplier_payment_hours for b in rows if b.quote_to_supplier_payment_hours is not None]
    target = get(cfg, "stop_lines.target_quote_to_supplier_payment_hours")
    reserve = _reserve(cfg, n_cohorts)
    loss = sum(b.loss_amount for b in rows)
    return {
        "bridges": n,
        "jobs_completed": sum(b.outcome != "abandoned" for b in rows),
        # same definition as gate 2: on time AND paid from the customer's payment into the controlled account
        "on_time_share": _share(sum(b.outcome == "on_time" and b.customer_paid_into_controlled_account
                                    for b in rows), n),
        "total_loss": loss,
        "loss_to_reserve": loss / reserve if reserve else None,
        "customers_bypassed": sum(b.outcome == "bypass" for b in rows),
        "hours_quote_to_supplier_median": statistics.median(hours) if hours else None,
        "hours_quote_to_supplier_max": max(hours) if hours else None,
        "share_within_target_hours": _share(sum(h <= target for h in hours), len(hours)) if target else None,
        "cost_to_serve_per_bridge": _share(sum(b.cost_to_serve for b in rows), n),
        "share_new_to_formal_credit": _share_asked(rows, "new_to_formal_credit")[0],
        "share_job_needed_bridge": _share_asked(rows, "would_not_proceed_without_bridge")[0],
        "cost_per_fully_additional_borrower": gate4(rows, cfg).detail["cost_per_fully_additional_borrower"],
    }


def score(rows: list[Bridge], cfg: dict, jobs: Optional[list[Job]] = None, n_cohorts: int = 1) -> dict:
    """Score one group of bridges. `n_cohorts` is how many first-loss reserves stand behind them."""
    return {"gates": [gate0(jobs, cfg), gate1(rows, cfg), gate2(rows, cfg, n_cohorts), gate3(rows, cfg), gate4(rows, cfg)],
            "measures": measures(rows, cfg, n_cohorts)}


def score_by_cohort(rows: list[Bridge], cfg: dict, jobs: Optional[list[Job]] = None) -> dict:
    """{'overall': score, 'cohorts': {cohort: score}, 'next_cohort': {cohort: (allowed, reason)}}"""
    names = sorted({b.sponsor_cohort for b in rows})
    cohorts = {}
    for c in names:
        cj = None if jobs is None else [j for j in jobs if j.sponsor_cohort == c]
        cohorts[c] = score([b for b in rows if b.sponsor_cohort == c], cfg, cj)
    nxt = {names[i + 1]: may_start_next_cohort(cohorts[names[i]]) for i in range(len(names) - 1)}
    return {"overall": score(rows, cfg, jobs, max(1, len(names))), "cohorts": cohorts, "next_cohort": nxt}


def may_start_next_cohort(prev: dict) -> tuple[bool, str]:
    g = {r.gate: r.status for r in prev["gates"]}
    if g[1] == PASS and g[2] == PASS:
        return True, "Previous cohort passed gates 1 and 2."
    return False, f"Previous cohort must PASS gates 1 and 2 (gate 1: {g[1]}, gate 2: {g[2]})."
