"""Pure functions over the record of released bridges. The staff page stores bridges; these turn
that record into what the engine needs: exposure for a new decision, the reserve and guarantor cap
left for a write-off, and the outcome log for the gates. No I/O here.

A record is a dict with: bridge_id, job_id, borrower_id, supplier_id, cohort, released_date,
closed_date, quote_hours, supplier_paid_directly, fee, cost, live (a collections.LiveBridge).
"""
from __future__ import annotations

from typing import Optional

from .collections import CLOSED, DISPUTE, PAID_LATE, PAID_ON_TIME, RECOVERY, WRITTEN_OFF, blocked_borrowers
from .config import get
from .models import Bridge, Exposure


def _opt(v) -> Optional[bool]:
    return None if v is None else bool(v)


def is_open(rec: dict) -> bool:
    return rec["live"].state not in CLOSED


def cohort_loss_status(cohort: str, records: list[dict]) -> dict:
    """Loss so far in a cohort, for the loss trip wire (A14).

    A bridge's outcome is *known* once it is closed, or has gone into recovery or dispute. Loss so far is the
    amount written off plus, until it is recovered, the full balance of bridges still in recovery or dispute
    (the cautious view). The rate is that loss over the money lent on the known bridges. Bridges still out and
    paying are not counted either way, which is the lag the simulation also builds in.
    """
    known = [r for r in records if r["cohort"] == cohort and (r["live"].state in CLOSED or r["live"].state in (RECOVERY, DISPUTE))]
    lent = sum(r["live"].amount for r in known)
    loss = sum((r["live"].loss or 0.0) if r["live"].state == WRITTEN_OFF
               else r["live"].outstanding if r["live"].state in (RECOVERY, DISPUTE) else 0.0 for r in known)
    return {"cohort": cohort, "known": len(known), "lent": lent, "loss": loss, "rate": (loss / lent) if lent else 0.0}


def trip_wire_status(cfg: dict, records: list[dict]) -> list[dict]:
    """One entry per cohort with the trip wire state. Empty when no trip wire is set."""
    wire = get(cfg, "stop_lines.pause_if_loss_rate_over")
    if wire is None:
        return []
    min_n = get(cfg, "stop_lines.loss_rate_min_bridges") or 0
    out = []
    for coh in sorted({r["cohort"] for r in records}):
        st = cohort_loss_status(coh, records)
        out.append(st | {"wire": wire, "min": min_n, "tripped": st["known"] >= min_n and st["known"] > 0 and st["rate"] > wire})
    return out


def exposure_for(borrower_id: str, supplier_id: str, cohort: str, records: list[dict]) -> Exposure:
    """Live exposure before a new decision, built from the record of bridges."""
    live = [r for r in records if is_open(r)]
    mine = [r for r in records if r["borrower_id"] == borrower_id]
    wire = cohort_loss_status(cohort, records)
    return Exposure(
        borrower_live_amount=sum(r["live"].amount for r in live if r["borrower_id"] == borrower_id),
        borrower_live_count=sum(1 for r in live if r["borrower_id"] == borrower_id),
        supplier_live_amount=sum(r["live"].amount for r in live if r["supplier_id"] == supplier_id),
        cohort_live_amount=sum(r["live"].amount for r in live if r["cohort"] == cohort),
        pilot_live_amount=sum(r["live"].amount for r in live),
        live_job_ids=tuple(r["job_id"] for r in live),
        borrower_blocked=borrower_id in blocked_borrowers([r["live"] for r in records]),
        borrower_prior_bridges=len(mine),
        borrower_clean_repayments=sum(1 for r in mine if r["live"].state == PAID_ON_TIME),
        cohort_known_bridges=wire["known"], cohort_loss_rate=wire["rate"],
    )


def layers_left(cohort: str, records: list[dict], cfg: dict) -> dict:
    """Reserve left in this cohort (A3: one pool per cohort) and guarantor cap left in the programme."""
    done = [r for r in records if r["live"].state == WRITTEN_OFF and r["live"].allocation]
    used_reserve = sum(r["live"].allocation["first_loss"] for r in done if r["cohort"] == cohort)
    used_cap = sum(r["live"].allocation["guarantor"] for r in done)
    reserve = get(cfg, "layers.first_loss_reserve")
    cap = get(cfg, "layers.guarantor_cap")
    return {"reserve_remaining": None if reserve is None else max(0.0, reserve - used_reserve),
            "guarantor_cap_remaining": None if cap is None else max(0.0, cap - used_cap)}


def outcome(rec: dict) -> Optional[str]:
    """Outcome for the gates log, or None while the bridge is open."""
    b = rec["live"]
    if b.state == PAID_ON_TIME:
        return "on_time"
    if b.state == PAID_LATE:
        return {"bypass": "bypass", "dispute": "dispute", "abandoned": "abandoned"}.get(b.cause, "late")
    if b.state == WRITTEN_OFF:
        return b.cause if b.cause in ("bypass", "dispute", "abandoned") else "lost"
    return None


def log_rows(records: list[dict]) -> list[Bridge]:
    """Closed bridges as rows of the gates log."""
    rows = []
    for r in records:
        out = outcome(r)
        if out is None:
            continue
        b = r["live"]
        rows.append(Bridge(
            bridge_id=r["bridge_id"], job_id=r["job_id"], released_date=r["released_date"],
            released_amount=b.amount, paid_supplier_directly=bool(r["supplier_paid_directly"]),
            customer_paid_into_controlled_account=out in ("on_time", "late"),
            repaid_date=r["closed_date"] if b.state != WRITTEN_OFF else None, outcome=out,
            loss_amount=b.loss or 0.0, cost_to_serve=r["cost"], fee_charged=r["fee"],
            quote_to_supplier_payment_hours=r["quote_hours"], sponsor_cohort=r["cohort"],
            new_to_formal_credit=_opt(r.get("new_to_formal_credit")),
            would_not_proceed_without_bridge=_opt(r.get("would_not_proceed"))))
    return rows
