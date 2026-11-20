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

The reserve (author decisions A16, A17): the DFI and the guarantor are the sponsors. They fund the first-loss reserve between them,
up front, and what is not spent goes back. Each party's result is also shown *after funding its share*, with the money tied up
charged at that party's own hurdle. Not included: tax. The DFI bears the cost to serve. Nothing here is a forecast.
"""
from __future__ import annotations

import copy
import math
import statistics
from typing import Optional

from .config import ConfigInvalid, get, require
from .simulate import ADDITIONAL_SHARES, Draw, Run, pct, run_cohort

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

    # The reserve: the DFI and the guarantor fund it between them (A17)
    rf = reserve_funding(runs, cfg)
    be_after = dfi_be_after = g_be_after = None
    if rf:
        for who, party, hurdle, base_years in (("dfi", dfi, coe, d_eq_years), ("guarantor", guar, gcoc, cap_years)):
            if party is None:
                continue
            share = rf[f"{who}_share"]
            lost_unused = 0.0 if rf["is_returned"] else share * rf["expected_unused"]
            tied = share * rf["committed"] * rf["hold_years"]                  # RM-years of this party's money held in the reserve
            after = party["result"] - share * rf["expected_used"] - lost_unused
            party.update({"ar_committed": share * rf["committed"], "ar_spent": share * rf["expected_used"] + lost_unused,
                          "ar_result": after, "ar_return_on_capital_pa": after / (base_years + tied),
                          "ar_economic_profit": after - hurdle * (base_years + tied)})
            party["ar_spread"] = party["ar_return_on_capital_pa"] - hurdle
            party["ar_break_even_fee_pa"] = party["break_even_fee_pa"] + (share * rf["expected_used"] + lost_unused + hurdle * tied) / ey
        dfi_be_after = dfi["ar_break_even_fee_pa"]
        g_be_after = guar["ar_break_even_fee_pa"] if guar else 0.0
        be_after = dfi_be_after + g_be_after

    # Who takes the credit loss
    total = m([r.total_loss for r in runs]) or 1e-9
    split = {"reserve": m([r.first_loss for r in runs]) / total, "guarantor": m(g_draw) / total, "dfi": m(d_loss) / total}
    be = dfi["break_even_fee_pa"] + (guar["break_even_fee_pa"] if guar else 0.0)
    out = {"dfi": dfi, "guarantor": guar, "loss_split": split, "reserve": rf,
           "reserve_used": m([r.first_loss for r in runs]), "p_reserve_out": sum(r.reserve_exhausted for r in runs) / len(runs),
           "cost_covering_all_in_pa": be, "all_in_cap_pa": cap_pa, "gap_pa": be - cap_pa,
           "gap_per_loan": (be - cap_pa) * ey / nm, "avg_loan": m([r.released for r in runs]) / nm}
    if rf:
        out["joint_result"] = dfi["ar_result"] + (guar["ar_result"] if guar else 0.0)
        out["cost_covering_all_in_after_reserve_pa"] = be_after
        out["gap_after_reserve_pa"] = be_after - cap_pa
        out["gap_after_reserve_per_loan"] = (be_after - cap_pa) * ey / nm
    return out


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


# ---------- the reserve, funded by the DFI and the guarantor (author decisions A16, A17) ----------
#
# There is no outside sponsor. The DFI and the guarantor fund the first-loss reserve between them, up front, into a ring-fenced
# account; `layers.reserve_funded_by_guarantor_pct` is the guarantor's share and the DFI funds the rest. Losses use the reserve
# first. What the cohort does not spend goes back to the two of them once its loans are closed and recoveries are in
# (`layers.unused_reserve_returned`). Each party's cost is its share of what is spent plus the cost of its money tied up for the
# hold period (cohort days + the write-off period), at that party's own required return. If unused reserve were forfeited, each
# party would lose its share of that too.

RESERVE_KEYS = ["layers.first_loss_reserve", "layers.reserve_funded_by_guarantor_pct", "simulation.cohort_days",
                "collections.write_off_after_days"]


def reserve_funding(runs: list[Run], cfg: dict) -> Optional[dict]:
    """The reserve for one size and split, or None while its settings are missing."""
    if any(get(cfg, k) is None for k in RESERVE_KEYS):
        return None
    reserve = get(cfg, "layers.first_loss_reserve")
    gs = get(cfg, "layers.reserve_funded_by_guarantor_pct")
    if not 0 <= gs <= 1:
        raise ConfigInvalid(f"layers.reserve_funded_by_guarantor_pct must be between 0 and 1; got {gs}.")
    hold_years = (get(cfg, "simulation.cohort_days") + get(cfg, "collections.write_off_after_days")) / 365
    used = [min(r.first_loss, reserve) for r in runs]
    m = statistics.fmean
    return {"committed": reserve, "guarantor_share": gs, "dfi_share": 1 - gs, "hold_years": hold_years, "hold_days": hold_years * 365,
            "expected_used": m(used), "expected_unused": reserve - m(used), "is_returned": bool(get(cfg, "layers.unused_reserve_returned")),
            "p_reserve_out": sum(r.reserve_exhausted for r in runs) / len(runs), "worst_5pct_used": pct(used, 95)}


def reserve_table(cfg: dict, draws: list[list[Draw]]) -> Optional[list[dict]]:
    """One row per reserve size in `sliders.first_loss_reserve`: what it costs the DFI and the guarantor, and what it does for
    each, at the config's own cover, split, guarantee fee, all-in cap and cost to serve."""
    sizes = get(cfg, "sliders.first_loss_reserve")
    cap = get(cfg, "pricing.all_in_rate_cap_pa")
    if not sizes or cap is None or any(get(cfg, k) is None for k in COST_KEYS + RESERVE_KEYS):
        return None
    require(cfg, ["pricing.guarantee_fee_rate_on_drawn", "pricing.cost_to_serve_per_bridge"])
    rows = []
    for size in sizes:
        c = copy.deepcopy(cfg)
        c["layers"]["first_loss_reserve"] = size
        runs = [run_cohort(d, c) for d in draws]
        x = risk_return(runs, c, cap, get(c, "pricing.guarantee_fee_rate_on_drawn"), get(c, "pricing.cost_to_serve_per_bridge"))
        if x is None or x["reserve"] is None:
            continue
        rows.append({"reserve": size, "funding": x["reserve"], "dfi": x["dfi"], "guarantor": x["guarantor"],
                     "joint_result": x["joint_result"], "dfi_roc": x["dfi"]["ar_return_on_capital_pa"],
                     "guarantor_roc": x["guarantor"]["ar_return_on_capital_pa"] if x["guarantor"] else None,
                     "p_reserve_out": x["reserve"]["p_reserve_out"]})
    return rows


# ---------- path to viability (author decision A18) ----------
#
# Can the product work at the all-in cap, and what would it take? The cap earns by time (cap x days / 365 of a loan) while losses come
# per loan, so a short tenor, cash payments to the painter, damaged projects and a high cost to serve all work against it. This runs the
# whole picture over five levers: the chance the customer pays the painter in cash (bypass), the damage rate, how much is lost on bad
# loans, the tenor, and the cost to serve. Verdicts compare each party's result after funding the reserve with its own hurdle.
#
# Assumptions: the chance of damage, lateness and cash per loan does not change with the tenor; the loss on bad loans is the config's
# own recovery rates scaled (1.0 = as in the config, 0.75 = a quarter less lost) for the three bad outcomes: rejected, not
# completed, and cash to the painter.

VIABILITY_AXES = ("bypass_chance", "damage_rate", "loss_on_bad_loans_scale", "tenor_days", "cost_to_serve_per_bridge")
BAD_OUTCOMES = ("dispute", "abandoned", "bypass")
VERDICTS = {0: "Priced below cost: the two parties lose money together",
            1: "Costs are covered, but no split of the cap gives both parties their required return",
            2: "A split of the cap exists where both parties earn their required return"}


def viability_config(cfg: dict, bypass: float, damage: float, scale: float) -> Optional[dict]:
    """cfg with the cash-payment chance, damage rate and loss scale set; None if the chances add to more than 100%."""
    share = get(cfg, "simulation.damage_dispute_share")
    c = copy.deepcopy(cfg)
    p = c["simulation"]["outcome_probs"]
    p["bypass"], p["dispute"], p["abandoned"] = bypass, damage * share, damage * (1 - share)
    p["on_time"] = 1 - p["late"] - bypass - damage
    if p["on_time"] < -1e-12:
        return None
    p["on_time"] = max(0.0, p["on_time"])
    rec = c["simulation"]["recovery_rate_by_outcome"]
    for o in BAD_OUTCOMES:
        rec[o] = 1 - (1 - rec[o]) * scale
    return c


def viability_cell(runs: list[Run], cfg: dict, cap_pa: float, gfee_pa: float, cts: float, tenor: int) -> Optional[dict]:
    """One setting of the five levers. `cfg` must already carry the outcome settings the runs were made with."""
    c = copy.deepcopy(cfg)
    c["tenor"]["typical_days"] = tenor
    x = risk_return(runs, c, cap_pa, gfee_pa, cts)
    if x is None or x["reserve"] is None:
        return None
    m = statistics.fmean
    n, lent = m([r.n_released for r in runs]) or 1.0, m([r.released for r in runs]) or 1.0
    d, g = x["dfi"], x["guarantor"]
    d_ok = d["ar_return_on_capital_pa"] >= d["hurdle"]
    g_ok = True if g is None else g["ar_return_on_capital_pa"] >= g["hurdle"]
    joint = x["joint_result"]
    # 2: the two fees each party needs (its break-even after funding the reserve) fit inside the cap, so a working split exists.
    needed = x["cost_covering_all_in_after_reserve_pa"]
    verdict = 2 if needed <= cap_pa else (1 if joint >= 0 else 0)
    per_loan = joint / n
    cell = {"loans": n, "loss_pct": m([r.total_loss for r in runs]) / lent, "revenue_pct": cap_pa * tenor / 365,
            "joint_group": joint, "joint_loan": per_loan, "joint_per_1000": joint / lent * 1000,
            "dfi_roc": d["ar_return_on_capital_pa"], "guarantor_roc": g["ar_return_on_capital_pa"] if g else None,
            "dfi_hurdle": d["hurdle"], "guarantor_hurdle": g["hurdle"] if g else None,
            "rate_needed": x["cost_covering_all_in_after_reserve_pa"], "gap_per_loan": x["gap_after_reserve_per_loan"],
            "p_reserve_out": x["reserve"]["p_reserve_out"], "verdict": verdict, "split_works_now": d_ok and g_ok,
            "dfi_fee_needed": d["ar_break_even_fee_pa"], "guarantor_fee_needed": g["ar_break_even_fee_pa"] if g else 0.0,
            "dfi_fee_now": d["fee_pa"], "guarantor_fee_now": gfee_pa}
    for sh in ADDITIONAL_SHARES:
        cell[f"per_additional_{int(sh * 100)}"] = (-per_loan / sh) if per_loan < 0 else 0.0
    return cell


def viability_grid(cfg: dict, draws: list[list[Draw]]) -> Optional[dict]:
    """The grid for the report's sliders, keyed by slider position (bypass|damage|loss scale|tenor|cost to serve)."""
    sl = {k: get(cfg, f"viability_sliders.{k}") for k in VIABILITY_AXES}
    cap = get(cfg, "pricing.all_in_rate_cap_pa")
    if not all(sl.values()) or cap is None or any(get(cfg, k) is None for k in COST_KEYS + RESERVE_KEYS + ["simulation.damage_dispute_share"]):
        return None
    require(cfg, ["pricing.guarantee_fee_rate_on_drawn"])
    gfee = get(cfg, "pricing.guarantee_fee_rate_on_drawn")
    cells = {}
    for bi, bypass in enumerate(sl["bypass_chance"]):
        for di, damage in enumerate(sl["damage_rate"]):
            for ci, scale in enumerate(sl["loss_on_bad_loans_scale"]):
                c = viability_config(cfg, bypass, damage, scale)
                runs = [run_cohort(d, c) for d in draws] if c is not None else None
                for ti, tenor in enumerate(sl["tenor_days"]):
                    for si, cts in enumerate(sl["cost_to_serve_per_bridge"]):
                        cells[f"{bi}|{di}|{ci}|{ti}|{si}"] = None if runs is None else viability_cell(runs, c, cap, gfee, cts, tenor)
    return {"axes": sl, "cells": cells, "cap": cap, "verdicts": VERDICTS}
