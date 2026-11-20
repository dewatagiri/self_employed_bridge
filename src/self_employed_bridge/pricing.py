"""Pricing. The fee comes from measured cost to serve plus expected loss, never from a rate.
The published rate is used only as a warning benchmark."""
from __future__ import annotations

from dataclasses import dataclass

from .config import get, require


def guarantee_fee(amount: float, tenor_days: float, cfg: dict) -> float:
    require(cfg, ["pricing.guarantee_fee_rate_on_drawn"])
    return get(cfg, "pricing.guarantee_fee_rate_on_drawn") * amount * tenor_days / 365


def bridge_revenue(amount: float, tenor_days: float, cfg: dict) -> float:
    require(cfg, ["pricing.flat_fee_per_bridge", "pricing.guarantee_fee_rate_on_drawn"])
    return get(cfg, "pricing.flat_fee_per_bridge") + guarantee_fee(amount, tenor_days, cfg)


def breakeven_fee(expected_loss_to_financier: float, cost_to_serve: float, guarantee_fee_amt: float) -> float:
    """Flat fee that covers cost to serve, the guarantee fee and expected financier loss."""
    return cost_to_serve + guarantee_fee_amt + expected_loss_to_financier


@dataclass(frozen=True)
class FeeCeilingCheck:
    fee: float
    ceiling: float
    above: bool
    message: str


def fee_ceiling_check(fee: float, amount: float, tenor_days: float, cfg: dict) -> FeeCeilingCheck:
    """Compare a fee with the published benchmark. Months = tenor_days / 30. Warning only."""
    require(cfg, ["pricing.fee_ceiling_reference.rate_per_month"])
    rate = get(cfg, "pricing.fee_ceiling_reference.rate_per_month")
    ceiling = rate * (tenor_days / 30) * amount
    above = fee > ceiling
    msg = (f"Fee RM{fee:,.2f} is above the reference RM{ceiling:,.2f}: needs a stated reason."
           if above else "Fee is at or below the reference.")
    return FeeCeilingCheck(fee, ceiling, above, msg)
