"""Risk and return for the two parties that carry the credit risk above the sponsor's reserve: the DFI (the
financier) and the guarantor. Pure functions over simulated groups of loans (author decision A15).

Each party has its own costs, all settings (demo values are made up, the real template leaves them null):

  DFI        earns the financier fee (the all-in cap less the guarantee fee) on the drawn amount.
             pays   cost to serve per loan, interest on the debt that funds the drawn amount, and bears the credit
                    loss left after the sponsor's reserve and the guarantor.
             capital: equity held against the drawn amount, which must earn `cost_of_equity_pa`.
  Guarantor  earns the guarantee fee on the drawn amount.
             pays   an admin cost per bridge and the draws on its guarantee, up to its cap.
             capital: the guarantee cap, set aside for the length of a cohort, which must earn `cost_of_capital_pa`.

For each party: result before the cost of capital, return on capital a year, the spread over its hurdle, economic
profit (result less the capital charge), and risk (bad group, chance of a loss-making group, the average of the worst
5% of groups). Break-even rates are the fees at which economic profit is exactly zero. Their sum is the all-in rate
that would cover every cost; the gap to the cap is what developmental pricing deliberately gives up.

Not included: the sponsor's reserve use, which is shown for context only; tax; the DFI's cost to serve is borne by
the DFI. Nothing here is a forecast.
"""
from __future__ import annotations

import copy
import math
import statistics
from typing import Optional

from .config import get, require
from .simulate import Draw, Run, pct, run_cohort

COST_KEYS = ["financier.cost_of_funds_pa", "financier.capital_pct_of_drawn", "financier.cost_of_equity_pa",
             "guarantor.cost_of_capital_pa", "guarantor.admin_cost_per_bridge", "simulation.cohort_days",
             "tenor.typical_days", "layers.guarantor_cap"]


def risk_stats(xs: list[float]) -> dict:
    """Mean, spread and downside of one party's result per group."""
    n = len(xs)
    k = max(1, math.ceil(0.05 * n))
    worst = sorted(xs)[:k]
    sd = statistics.pstdev(xs) if n > 1 else 0.0
    mean = statistics.fmean(xs)
    return {"mean": mean, "std": sd, "p5": pct(xs, 5), "p50": pct(xs, 50), "p95": pct(xs, 95),
            "p_loss": sum(x < 0 for x in xs) / n, "es5": statistics.fmean(worst),
            "return_per_risk": (mean / sd) if sd > 0 else None}


def risk_return(runs: list[Run], cfg: dict, cap_pa: float, gfee_pa: float, cts: float) -> Optional[dict]:
    """The full picture for one setting. None when the guarantee fee alone is above the all-in cap."""
    require(cfg, COST_KEYS)
    fin_fee_pa = cap_pa - gfee_pa
    if fin_fee_pa < 0:
        return None
    tenor = get(cfg, "tenor.typical_days")
    k, cof, coe = (get(cfg, f"financier.{x}") for x in ("capital_pct_of_drawn", "cost_of_funds_pa", "cost_of_equity_pa"))
    gcoc, gadmin = get(cfg, "guarantor.cost_of_capital_pa"), get(cfg, "guarantor.admin_cost_per_bridge")
    gcap, days = get(cfg, "layers.guarantor_cap"), get(cfg, "simulation.cohort_days")
    m = statistics.fmean
    yrs = [r.released * tenor / 365 for r in runs]                  # RM-years of drawn exposure per group
    n = [r.n_released for r in runs]
    ey, nm = m(yrs) or 1e-9, m(n) or 1.0

    # DFI
    d_inc = [fin_fee_pa * y for y in yrs]
    d_cts = [cts * c for c in n]
    d_debt = [cof * (1 - k) * y for y in yrs]
    d_loss = [r.financier_loss for r in runs]
    d_op = [a - b - c - d for a, b, c, d in zip(d_inc, d_cts, d_debt, d_loss)]
    d_eq_years = k * ey
    dfi = {"income": m(d_inc), "cost_to_serve": m(d_cts), "funding_cost": m(d_debt), "credit_loss": m(d_loss),
           "result": m(d_op), "capital": d_eq_years / (days / 365), "hurdle": coe,
           "return_on_capital_pa": m(d_op) / d_eq_years, "economic_profit": m(d_op) - coe * d_eq_years,
           "fee_per_loan": fin_fee_pa * ey / nm, "fee_pa": fin_fee_pa,
           "break_even_fee_pa": (m(d_loss) + m(d_cts) + m(d_debt) + coe * d_eq_years) / ey} | risk_stats(d_op)
    dfi["spread"] = dfi["return_on_capital_pa"] - coe

    # Guarantor
    g_inc = [gfee_pa * y for y in yrs]
    g_adm = [gadmin * c for c in n]
    g_draw = [r.guarantor for r in runs]
    g_op = [a - b - c for a, b, c in zip(g_inc, g_adm, g_draw)]
    cap_years = (gcap or 0.0) * days / 365
    guar = None
    if cap_years > 0:
        guar = {"income": m(g_inc), "admin_cost": m(g_adm), "credit_loss": m(g_draw), "result": m(g_op),
                "capital": gcap, "hurdle": gcoc, "return_on_capital_pa": m(g_op) / cap_years,
                "economic_profit": m(g_op) - gcoc * cap_years, "fee_per_loan": gfee_pa * ey / nm, "fee_pa": gfee_pa,
                "break_even_fee_pa": (m(g_draw) + m(g_adm) + gcoc * cap_years) / ey,
                "p_cap_hit": sum(r.guarantor_cap_hit for r in runs) / len(runs),
                "cap_used": m(g_draw) / gcap} | risk_stats(g_op)
        guar["spread"] = guar["return_on_capital_pa"] - gcoc

    # Sponsor, for context, and who takes the credit loss
    total = m([r.total_loss for r in runs]) or 1e-9
    split = {"sponsor": m([r.first_loss for r in runs]) / total, "guarantor": m(g_draw) / total, "dfi": m(d_loss) / total}
    be = dfi["break_even_fee_pa"] + (guar["break_even_fee_pa"] if guar else 0.0)
    return {"dfi": dfi, "guarantor": guar, "loss_split": split, "sponsor_reserve_used": m([r.first_loss for r in runs]),
            "sponsor_p_reserve_out": sum(r.reserve_exhausted for r in runs) / len(runs),
            "cost_covering_all_in_pa": be, "all_in_cap_pa": cap_pa, "gap_pa": be - cap_pa,
            "gap_per_loan": (be - cap_pa) * ey / nm, "avg_loan": m([r.released for r in runs]) / nm}


def rr_base(cfg: dict, draws: list[list[Draw]]) -> Optional[dict]:
    """The risk-return view at the config's own settings, or None while the all-in cap or the costs are unset."""
    cap = get(cfg, "pricing.all_in_rate_cap_pa")
    if cap is None or any(get(cfg, k) is None for k in COST_KEYS):
        return None
    require(cfg, ["pricing.guarantee_fee_rate_on_drawn", "pricing.cost_to_serve_per_bridge"])
    runs = [run_cohort(d, cfg) for d in draws]
    return risk_return(runs, cfg, cap, get(cfg, "pricing.guarantee_fee_rate_on_drawn"), get(cfg, "pricing.cost_to_serve_per_bridge"))


def rr_grid(cfg: dict, draws: list[list[Draw]]) -> Optional[dict]:
    """Precompute over the `dev_sliders` values (cover | all-in cap | guarantee fee | cost to serve) for the report."""
    sl = {k: get(cfg, f"dev_sliders.{k}") for k in ("guarantor_cover_pct", "all_in_cap_pa", "guarantee_fee_pa", "cost_to_serve_per_bridge")}
    if not all(sl.values()) or any(get(cfg, k) is None for k in COST_KEYS):
        return None
    cells = {}
    for ci, cover in enumerate(sl["guarantor_cover_pct"]):
        c = copy.deepcopy(cfg)
        c["layers"]["guarantor_cover_pct"] = cover
        c["layers"]["guarantor_enabled"] = True
        runs = [run_cohort(d, c) for d in draws]
        for ai, cap in enumerate(sl["all_in_cap_pa"]):
            for gi, g in enumerate(sl["guarantee_fee_pa"]):
                for si, cts in enumerate(sl["cost_to_serve_per_bridge"]):
                    cells[f"{ci}|{ai}|{gi}|{si}"] = risk_return(runs, c, cap, g, cts)
    return {"axes": sl, "cells": cells}
