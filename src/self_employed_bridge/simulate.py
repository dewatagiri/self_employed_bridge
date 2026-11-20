"""Cohort Monte Carlo. A sensitivity tool, not a forecast: every probability, rate and
distribution comes from config, and no Malaysian loss data exists to set them.

One run = one cohort:
  1. draw each job's materials cost and deposit share; the bridge amount comes from the same
     rule `decide` uses (`advance_limit`), stopping when the cohort cap is used up;
  2. draw an outcome per bridge from `outcome_probs`;
     loss = amount * (1 - recovery_rate_by_outcome[outcome]);
  3. optional stop lines. Loss trip wire (A14): when the loss so far, after recoveries, as a share of money
     lent on loans whose outcome is already known (all but the last `outcome_lag_bridges`) passes
     `pause_if_loss_rate_over`, stop releasing. Bypass stop line: once `bypass_rate_min_bridges` are out, stop releasing when the
     bypass rate to date exceeds `pause_if_bypass_rate_over`; record the pause point;
  4. allocate losses with `allocate_pool` (reserve shared across the cohort);
  5. financier result = flat fees - cost to serve - financier loss. The guarantee fee is charged
     to the borrower on drawn amounts and passed to the guarantor (author decision A4).

Random draws are made once per run and reused across scenarios (common random numbers), so a
difference between scenarios comes from the parameter, not from noise.
"""
from __future__ import annotations

import copy
import math
import random
import statistics
from dataclasses import dataclass
from typing import Optional

from .config import ConfigInvalid, get, layer_keys, require, requirements
from .decide import advance_limit
from .pricing import breakeven_fee
from .waterfall import allocate_loss, allocate_pool

OUTCOMES = ("on_time", "late", "bypass", "dispute", "abandoned")


@dataclass(frozen=True)
class Draw:
    materials: float
    deposit_share: float
    u: float                      # uniform for the outcome, mapped at run time


@dataclass(frozen=True)
class Run:
    n_released: int
    released: float
    materials: float              # quoted materials cost of the released bridges
    total_loss: float
    first_loss: float
    guarantor: float
    financier_loss: float
    fee_income: float
    guarantee_fee: float
    cost_to_serve: float
    financier_net: float
    bypasses: int
    paused_at: Optional[int]
    reserve_exhausted: bool
    guarantor_cap_hit: bool
    paused_by: Optional[str] = None          # "bypass" or "loss"


# ---------- config checks ----------

def validate(cfg: dict) -> None:
    require(cfg, requirements(cfg)["simulate"])
    probs = get(cfg, "simulation.outcome_probs")
    rec = get(cfg, "simulation.recovery_rate_by_outcome")
    if set(probs) != set(OUTCOMES):
        raise ConfigInvalid(f"simulation.outcome_probs needs exactly {OUTCOMES}")
    if any(p < 0 for p in probs.values()) or not math.isclose(sum(probs.values()), 1.0, abs_tol=1e-9):
        raise ConfigInvalid("simulation.outcome_probs must be non-negative and sum to 1")
    if set(rec) != set(OUTCOMES) or not all(0 <= r <= 1 for r in rec.values()):
        raise ConfigInvalid(f"simulation.recovery_rate_by_outcome needs {OUTCOMES}, each in [0, 1]")
    dist = get(cfg, "simulation.amount_distribution")
    if dist.get("kind") != "lognormal" or dist.get("mean") is None or dist.get("sigma") is None:
        raise ConfigInvalid("simulation.amount_distribution must be {kind: lognormal, mean, sigma}")
    dep = get(cfg, "simulation.deposit_share_of_materials")
    if not (0 <= dep.get("low", -1) <= dep.get("high", -1)):
        raise ConfigInvalid("simulation.deposit_share_of_materials must be {low, high} with 0 <= low <= high")


# ---------- drawing and one run ----------

def draw_cohort(rng: random.Random, cfg: dict) -> list[Draw]:
    dist = get(cfg, "simulation.amount_distribution")
    dep = get(cfg, "simulation.deposit_share_of_materials")
    return [Draw(rng.lognormvariate(dist["mean"], dist["sigma"]), rng.uniform(dep["low"], dep["high"]), rng.random())
            for _ in range(get(cfg, "simulation.n_bridges"))]


def _outcome(u: float, probs: dict) -> str:
    acc = 0.0
    for o in OUTCOMES:
        acc += probs[o]
        if u < acc:
            return o
    return OUTCOMES[-1]


def run_cohort(draws: list[Draw], cfg: dict) -> Run:
    probs = get(cfg, "simulation.outcome_probs")
    rec = get(cfg, "simulation.recovery_rate_by_outcome")
    cohort_cap = get(cfg, "caps.per_sponsor_cohort")
    pause_rate = get(cfg, "stop_lines.pause_if_bypass_rate_over")
    pause_min = get(cfg, "stop_lines.bypass_rate_min_bridges")
    reserve = get(cfg, "layers.first_loss_reserve")
    on = bool(get(cfg, "layers.guarantor_enabled"))
    cover = get(cfg, "layers.guarantor_cover_pct") or 0.0
    gcap = get(cfg, "layers.guarantor_cap") or 0.0
    g_rate = get(cfg, "pricing.guarantee_fee_rate_on_drawn") if on else 0.0
    tenor = get(cfg, "tenor.typical_days")

    loss_wire = get(cfg, "stop_lines.pause_if_loss_rate_over")
    loss_min = get(cfg, "stop_lines.loss_rate_min_bridges") or 0
    lag = get(cfg, "stop_lines.outcome_lag_bridges") or 0
    cum_amt: list[float] = []                # running totals, so the trip wire test is O(1) per loan
    cum_loss: list[float] = []

    released = materials = gfee = 0.0
    n = bypasses = 0
    losses: list[float] = []
    paused_at = None
    paused_by = None
    for d in draws:
        amount, _, _ = advance_limit(d.materials, d.deposit_share * d.materials, cfg)
        amount = min(amount, cohort_cap - released)
        if amount <= 0:
            if released >= cohort_cap:
                break                      # cohort cap used up
            continue                       # deposit covers materials: no bridge needed
        outcome = _outcome(d.u, probs)
        released += amount
        materials += d.materials
        gfee += g_rate * amount * tenor / 365
        n += 1
        losses.append(amount * (1 - rec[outcome]))
        cum_amt.append((cum_amt[-1] if cum_amt else 0.0) + amount)
        cum_loss.append((cum_loss[-1] if cum_loss else 0.0) + losses[-1])
        bypasses += outcome == "bypass"
        if pause_rate is not None and n >= pause_min and bypasses / n > pause_rate:
            paused_at, paused_by = n, "bypass"
            break
        if loss_wire is not None:
            # Loss trip wire (A14): only outcomes already known count. The last `lag` loans are still out, so
            # they cannot be stopped even when the wire fires.
            k = n - lag
            if k >= max(loss_min, 1) and cum_amt[k - 1] > 0 and cum_loss[k - 1] / cum_amt[k - 1] > loss_wire:
                paused_at, paused_by = n, "loss"
                break

    pool = allocate_pool(losses, reserve, cover, gcap, on)["total"]
    total = sum(losses)
    fee = get(cfg, "pricing.flat_fee_per_bridge") * n
    cost = get(cfg, "pricing.cost_to_serve_per_bridge") * n
    return Run(n, released, materials, total, pool["first_loss"], pool["guarantor"], pool["financier"],
               fee, gfee, cost, fee - cost - pool["financier"], bypasses, paused_at,
               total >= reserve and total > 0, on and gcap > 0 and pool["guarantor"] >= gcap - 1e-9, paused_by)


# ---------- summaries ----------

def pct(xs: list[float], q: float) -> float:
    """Percentile by linear interpolation (q in 0..100)."""
    s = sorted(xs)
    if not s:
        return 0.0
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def dist(xs: list[float]) -> dict:
    return {"mean": statistics.fmean(xs) if xs else 0.0, "p5": pct(xs, 5), "p50": pct(xs, 50), "p95": pct(xs, 95)}


def summarise(runs: list[Run], cfg: dict) -> dict:
    bridges = sum(r.n_released for r in runs) or 1
    exp_fin_loss = sum(r.financier_loss for r in runs) / bridges
    cts = get(cfg, "pricing.cost_to_serve_per_bridge")
    gfee_pb = sum(r.guarantee_fee for r in runs) / bridges
    released = sum(r.released for r in runs) or 1.0
    months = get(cfg, "tenor.typical_days") / 30
    flat = get(cfg, "pricing.flat_fee_per_bridge")
    paused = [r.paused_at for r in runs if r.paused_at is not None]
    return {
        "total_loss": dist([r.total_loss for r in runs]),
        "financier_loss": dist([r.financier_loss for r in runs]),
        "reserve_drawdown": dist([r.first_loss for r in runs]),
        "guarantor_draw": dist([r.guarantor for r in runs]),
        "financier_net": dist([r.financier_net for r in runs]),
        "released": dist([r.released for r in runs]),
        "bridges_per_run": dist([r.n_released for r in runs]),
        "p_reserve_exhausted": sum(r.reserve_exhausted for r in runs) / len(runs),
        "p_guarantor_cap_hit": sum(r.guarantor_cap_hit for r in runs) / len(runs),
        "p_paused": len(paused) / len(runs),
        "p_paused_bypass": sum(r.paused_by == "bypass" for r in runs) / len(runs),
        "p_paused_loss": sum(r.paused_by == "loss" for r in runs) / len(runs),
        "median_pause_point": statistics.median(paused) if paused else None,
        "avg_bridge": released / bridges,
        "advance_share_of_materials": released / (sum(r.materials for r in runs) or 1.0),
        "expected_financier_loss_per_bridge": exp_fin_loss,
        "financier_net_per_bridge": sum(r.financier_net for r in runs) / bridges,
        # flat fee that covers cost to serve + expected financier loss. The borrower pays the guarantee
        # fee on top and it passes to the guarantor (author decision A4), so it is not in this figure.
        "breakeven_flat_fee": breakeven_fee(exp_fin_loss, cts, 0.0),
        # borrower's all-in cost per month on the average bridge, for comparison with market rates
        "borrower_monthly_cost": (flat + gfee_pb) / (released / bridges) / months,
    }


def simulate(cfg: dict) -> dict:
    """Run the cohort `n_runs` times. Returns {'runs': [...], 'summary': {...}}."""
    validate(cfg)
    rng = random.Random(get(cfg, "simulation.seed"))
    draws = [draw_cohort(rng, cfg) for _ in range(get(cfg, "simulation.n_runs"))]
    runs = [run_cohort(d, cfg) for d in draws]
    return {"runs": runs, "summary": summarise(runs, cfg), "draws": draws}


# ---------- sensitivity and slider grid ----------

def _scaled(cfg: dict, param: str, f: float) -> dict:
    c = copy.deepcopy(cfg)
    if param == "bypass_probability":
        p = c["simulation"]["outcome_probs"]
        new = p["bypass"] * f
        p["on_time"] -= new - p["bypass"]          # the difference moves to or from on-time
        p["bypass"] = new
        if p["on_time"] < 0:
            raise ConfigInvalid("bypass probability +25% leaves on_time below zero")
    elif param == "recovery_rate":
        r = c["simulation"]["recovery_rate_by_outcome"]
        for o in OUTCOMES:
            if o != "on_time":                     # on-time bridges are repaid in full by definition
                r[o] = min(1.0, r[o] * f)
    elif param == "first_loss_reserve":
        c["layers"]["first_loss_reserve"] *= f
    elif param == "flat_fee":
        c["pricing"]["flat_fee_per_bridge"] *= f
    else:
        raise ValueError(param)
    return c


SENSITIVITY_PARAMS = ("bypass_probability", "recovery_rate", "first_loss_reserve", "flat_fee")


def sensitivity(cfg: dict, draws: list[list[Draw]], step: float = 0.25) -> list[dict]:
    """Move each parameter by -step and +step of its base value, one at a time, on the same draws."""
    base = summarise([run_cohort(d, cfg) for d in draws], cfg)
    rows = []
    for param in SENSITIVITY_PARAMS:
        row = {"param": param, "base": base}
        for label, f in (("low", 1 - step), ("high", 1 + step)):
            c = _scaled(cfg, param, f)
            row[label] = summarise([run_cohort(d, c) for d in draws], c)
        rows.append(row)
    return rows


def slider_grid(cfg: dict, draws: list[list[Draw]]) -> Optional[dict]:
    """Precompute results over the `sliders` values (margin of advance x flat fee x reserve).

    The report's sliders only look results up, so there is one engine and the page cannot disagree
    with the tests. Reserve and fee do not change the draws or amounts, so each margin of advance is
    run once and re-allocated per reserve: cohort totals from `allocate_loss` on the summed loss
    equal `allocate_pool` totals (tested).
    """
    moas = get(cfg, "sliders.margin_of_advance")
    fees = get(cfg, "sliders.flat_fee_per_bridge")
    reserves = get(cfg, "sliders.first_loss_reserve")
    if not (moas and fees and reserves):
        return None
    on = bool(get(cfg, "layers.guarantor_enabled"))
    cover = get(cfg, "layers.guarantor_cover_pct") or 0.0
    gcap = get(cfg, "layers.guarantor_cap") or 0.0
    cts = get(cfg, "pricing.cost_to_serve_per_bridge")
    months = get(cfg, "tenor.typical_days") / 30
    cells = {}
    for moa in moas:
        c = copy.deepcopy(cfg)
        c["release"]["margin_of_advance"] = moa
        runs = [run_cohort(d, c) for d in draws]
        bridges = sum(r.n_released for r in runs) or 1
        released = sum(r.released for r in runs) or 1.0
        gfee_pb = sum(r.guarantee_fee for r in runs) / bridges
        for reserve in reserves:
            allocs = [allocate_loss(r.total_loss, reserve, cover, gcap, on) for r in runs]
            fin = [a["financier"] for a in allocs]
            exp_fin = sum(fin) / bridges
            for fee in fees:
                net = [fee * r.n_released - cts * r.n_released - f for r, f in zip(runs, fin)]
                cells[f"{moa}|{fee}|{reserve}"] = {
                    "advance_share": released / (sum(r.materials for r in runs) or 1.0),
                    "avg_bridge": released / bridges,
                    "financier_net_mean": statistics.fmean(net),
                    "financier_net_per_bridge": sum(net) / bridges,
                    "financier_loss_p95": pct(fin, 95),
                    "p_reserve_exhausted": sum(r.total_loss >= reserve and r.total_loss > 0 for r in runs) / len(runs),
                    "breakeven_flat_fee": cts + exp_fin,
                    "borrower_monthly_cost": (fee + gfee_pb) / (released / bridges) / months,
                }
    return {"margin_of_advance": moas, "flat_fee_per_bridge": fees, "first_loss_reserve": reserves, "cells": cells}


# ---------- developmental pricing (author decision A13) ----------
#
# The product is priced below a commercial return on purpose. The funders (the DFI and the guarantor)
# accept a planned loss in return for additionality: reaching borrowers the market does not serve.
# This section works out what that planned loss is. It does not claim a return, and it does not assume
# any additionality: how many borrowers are truly additional is measured in the pilot (see gates.py).
#
# All-in charge to the borrower, per annum, simple interest = financier fee + guarantee fee <= all_in_rate_cap_pa.
# Financier fee = cap - guarantee fee, charged on the drawn amount over the tenor.
# Funders' budget covers the DFI and guarantor. Programme cost adds the sponsor's reserve that was used.

ADDITIONAL_SHARES = (0.25, 0.5, 0.75, 1.0)    # illustration only: what if this share of borrowers were truly additional?


def dev_cell(runs: list[Run], cfg: dict, cap_pa: float, gfee_pa: float, cts: float,
             budget: Optional[float] = None) -> Optional[dict]:
    """Results for one setting of the all-in cap, guarantee fee and cost to serve.

    `runs` already carry the loss split for one guarantor cover, so cover is chosen by which runs you pass.
    Returns None when the guarantee fee alone is above the all-in cap (nothing is left for the financier).
    """
    fin_fee_pa = cap_pa - gfee_pa
    if fin_fee_pa < 0:
        return None
    tenor = get(cfg, "tenor.typical_days")
    yrs = [r.released * tenor / 365 for r in runs]
    n = statistics.fmean(r.n_released for r in runs) or 1.0
    ey = statistics.fmean(yrs) or 1.0
    fin = [fin_fee_pa * y - cts * r.n_released - r.financier_loss for y, r in zip(yrs, runs)]
    gua = [gfee_pa * y - r.guarantor for y, r in zip(yrs, runs)]
    both = [a + b for a, b in zip(fin, gua)]
    # Programme cost counts every funder: financier + guarantor + the sponsor's first-loss reserve that was used.
    prog = [b - r.first_loss for b, r in zip(both, runs)]
    released = statistics.fmean(r.released for r in runs) or 1.0
    cost_pg = -statistics.fmean(prog)                      # + = the programme loses this much per group
    cell = {
        "borrower_per_loan": cap_pa * released / n * tenor / 365,
        "guarantee_fee_per_loan": gfee_pa * released / n * tenor / 365,
        "financier_fee_per_loan": fin_fee_pa * released / n * tenor / 365,
        "financier_net_mean": statistics.fmean(fin), "financier_net_p5": pct(fin, 5),
        "financier_return_pa": statistics.fmean(fin) / ey, "financier_return_pa_p5": pct(fin, 5) / ey,
        "guarantor_net_mean": statistics.fmean(gua), "guarantor_return_pa": statistics.fmean(gua) / ey,
        "funders_net_mean": statistics.fmean(both),                 # DFI + guarantor
        "sponsor_reserve_used_mean": statistics.fmean(r.first_loss for r in runs),
        "programme_net_mean": statistics.fmean(prog),               # DFI + guarantor + sponsor reserve
        "programme_cost_per_loan": cost_pg / n,
        "programme_cost_per_1000_lent": cost_pg / released * 1000,
        "p_group_loses": sum(x < 0 for x in both) / len(both),
        "p_over_budget": None if budget is None else sum(-x > budget for x in both) / len(both),  # DFI + guarantor only
        "breakeven_cost_to_serve": None,
    }
    # cost to serve at which the financier alone just breaks even, from the same runs
    base = statistics.fmean(fin) + cts * n
    cell["breakeven_cost_to_serve"] = max(0.0, base / n)
    for sh in ADDITIONAL_SHARES:     # on the whole programme cost, sponsor included
        cell[f"cost_per_additional_loan_{int(sh*100)}"] = (cost_pg / n / sh) if cost_pg > 0 else 0.0
    return cell


def dev_base(cfg: dict, draws: list[list[Draw]]) -> Optional[dict]:
    """The developmental view at the config's own settings, or None while the cap is unset."""
    cap = get(cfg, "pricing.all_in_rate_cap_pa")
    if cap is None:
        return None
    require(cfg, ["pricing.guarantee_fee_rate_on_drawn", "pricing.cost_to_serve_per_bridge"])
    runs = [run_cohort(d, cfg) for d in draws]
    return dev_cell(runs, cfg, cap, get(cfg, "pricing.guarantee_fee_rate_on_drawn"),
                    get(cfg, "pricing.cost_to_serve_per_bridge"), get(cfg, "development.funder_loss_budget_per_cohort"))


def dev_grid(cfg: dict, draws: list[list[Draw]]) -> Optional[dict]:
    """Precompute developmental results over the `dev_sliders` values for the report's sliders.

    One simulation per guarantor cover; cap, guarantee fee and cost to serve are arithmetic on those runs.
    Cells are keyed by slider position (cover|cap|guarantee fee|cost to serve).
    """
    sl = {k: get(cfg, f"dev_sliders.{k}") for k in ("guarantor_cover_pct", "all_in_cap_pa", "guarantee_fee_pa", "cost_to_serve_per_bridge")}
    if not all(sl.values()):
        return None
    budget = get(cfg, "development.funder_loss_budget_per_cohort")
    cells = {}
    for ci, cover in enumerate(sl["guarantor_cover_pct"]):
        c = copy.deepcopy(cfg)
        c["layers"]["guarantor_cover_pct"] = cover
        c["layers"]["guarantor_enabled"] = True
        runs = [run_cohort(d, c) for d in draws]
        for ai, cap in enumerate(sl["all_in_cap_pa"]):
            for gi, g in enumerate(sl["guarantee_fee_pa"]):
                for si, cts in enumerate(sl["cost_to_serve_per_bridge"]):
                    cells[f"{ci}|{ai}|{gi}|{si}"] = dev_cell(runs, c, cap, g, cts, budget)
    return {"axes": sl, "cells": cells, "budget": budget}


# ---------- damage rate and the loss trip wire (author decision A14) ----------
#
# "Damage" is a project that does not finish or is rejected by the customer: the two outcomes `abandoned`
# and `dispute`. The damage rate is their combined chance; `damage_dispute_share` of it is rejected projects.
# Late payments and cash to the painter keep their config chances, so the on-time share is what is left.
# The trip wire pauses new loans when the loss so far passes a line. Each combination runs on the same draws as
# the "no trip wire" case, so the loss it avoids and the loans it gives up are paired, not noisy.

def damage_config(cfg: dict, damage: float, loss_per_damaged: float, trip_wire: Optional[float]) -> Optional[dict]:
    """A copy of cfg with the damage rate, loss per damaged loan and trip wire set; None if the chances exceed 100%."""
    c = copy.deepcopy(cfg)
    probs = c["simulation"]["outcome_probs"]
    share = get(cfg, "simulation.damage_dispute_share")
    probs["dispute"], probs["abandoned"] = damage * share, damage * (1 - share)
    probs["on_time"] = 1 - damage - probs["late"] - probs["bypass"]
    if probs["on_time"] < -1e-12:
        return None
    probs["on_time"] = max(0.0, probs["on_time"])
    for o in ("dispute", "abandoned"):
        c["simulation"]["recovery_rate_by_outcome"][o] = 1 - loss_per_damaged
    c["stop_lines"]["pause_if_loss_rate_over"] = trip_wire
    return c


def damage_cell(runs: list[Run], cfg: dict, off_runs: Optional[list[Run]] = None) -> dict:
    """Results for one damage / loss / trip wire setting, using the config's own cap, guarantee fee and cost to serve."""
    cap = get(cfg, "pricing.all_in_rate_cap_pa")
    d = dev_cell(runs, cfg, cap, get(cfg, "pricing.guarantee_fee_rate_on_drawn"),
                 get(cfg, "pricing.cost_to_serve_per_bridge"), get(cfg, "development.funder_loss_budget_per_cohort")) if cap is not None else {}
    tripped = [r for r in runs if r.paused_by == "loss"]
    released = statistics.fmean(r.released for r in runs)
    loss = statistics.fmean(r.total_loss for r in runs)
    cell = {
        "loans": statistics.fmean(r.n_released for r in runs),
        "lent": released, "loss": loss, "loss_pct_lent": loss / released if released else 0.0,
        "p_tripped": len(tripped) / len(runs),
        "median_loans_at_trip": statistics.median(r.paused_at for r in tripped) if tripped else None,
        "p_reserve_out": sum(r.reserve_exhausted for r in runs) / len(runs),
        "reserve_used": statistics.fmean(r.first_loss for r in runs),
        "loss_avoided": None, "loans_given_up": None,
    }
    for k in ("financier_return_pa", "guarantor_return_pa", "programme_cost_per_loan", "programme_cost_per_1000_lent",
              "programme_net_mean", "p_over_budget"):
        cell[k] = d.get(k)
    if off_runs is not None:
        cell["loss_avoided"] = statistics.fmean(a.total_loss - b.total_loss for a, b in zip(off_runs, runs))
        cell["loans_given_up"] = statistics.fmean(a.n_released - b.n_released for a, b in zip(off_runs, runs))
    return cell


def damage_grid(cfg: dict, draws: list[list[Draw]]) -> Optional[dict]:
    """Precompute the damage / trip wire grid for the report. Cells are keyed by slider position
    (damage|loss per damaged loan|trip wire); a null trip wire in the list means no trip wire."""
    sl = {k: get(cfg, f"damage_sliders.{k}") for k in ("damage_rate", "loss_per_damaged_loan", "trip_wire")}
    if not all(sl.values()):
        return None
    need = ["simulation.damage_dispute_share"]
    if any(t is not None for t in sl["trip_wire"]):
        need += ["stop_lines.loss_rate_min_bridges", "stop_lines.outcome_lag_bridges"]
    require(cfg, need)
    cells = {}
    for di, dmg in enumerate(sl["damage_rate"]):
        for li, lpd in enumerate(sl["loss_per_damaged_loan"]):
            c0 = damage_config(cfg, dmg, lpd, None)
            off = [run_cohort(dr, c0) for dr in draws] if c0 is not None else None   # the paired "no trip wire" runs
            for ti, tw in enumerate(sl["trip_wire"]):
                key = f"{di}|{li}|{ti}"
                if off is None:                       # damage + late + cash chances above 100%
                    cells[key] = None
                elif tw is None:
                    cells[key] = damage_cell(off, c0)
                else:
                    c = damage_config(cfg, dmg, lpd, tw)
                    cells[key] = damage_cell([run_cohort(dr, c) for dr in draws], c, off)
    return {"axes": sl, "cells": cells, "lag": get(cfg, "stop_lines.outcome_lag_bridges"),
            "min_loans": get(cfg, "stop_lines.loss_rate_min_bridges")}
