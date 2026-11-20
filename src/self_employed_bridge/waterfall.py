"""Loss layers: first-loss reserve, then guarantor, then financier."""
from __future__ import annotations


def allocate_loss(loss: float, first_loss_reserve: float, guarantor_cover_pct: float,
                  guarantor_cap: float, guarantor_enabled: bool) -> dict:
    after_first = max(0.0, loss - first_loss_reserve)
    first_loss = min(loss, first_loss_reserve)
    guarantor = min(guarantor_cover_pct * after_first, guarantor_cap) if guarantor_enabled else 0.0
    return {"first_loss": first_loss, "guarantor": guarantor, "financier": after_first - guarantor}


def allocate_pool(losses: list[float], first_loss_reserve: float, guarantor_cover_pct: float,
                  guarantor_cap: float, guarantor_enabled: bool) -> dict:
    """Cohort allocation. Reserve and guarantor cap are shared and drawn down in event order."""
    reserve_left = first_loss_reserve
    cap_left = guarantor_cap
    events = []
    totals = {"first_loss": 0.0, "guarantor": 0.0, "financier": 0.0}
    for loss in losses:
        first = min(loss, reserve_left)
        reserve_left -= first
        after_first = loss - first
        g = min(guarantor_cover_pct * after_first, cap_left) if guarantor_enabled else 0.0
        cap_left -= g
        ev = {"first_loss": first, "guarantor": g, "financier": after_first - g,
              "reserve_after": reserve_left}
        events.append(ev)
        for k in totals:
            totals[k] += ev[k]
    return {"events": events, "total": totals, "reserve_after": reserve_left}
