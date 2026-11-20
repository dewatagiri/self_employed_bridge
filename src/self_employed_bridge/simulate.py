"""Cohort Monte Carlo. A sensitivity tool, not a forecast: every probability, rate and
distribution comes from config, and no Malaysian loss data exists to set them.

One run = one cohort:
  1. draw each job's materials cost and deposit share; the bridge amount comes from the same
     rule `decide` uses (`advance_limit`), stopping when the cohort cap is used up;
  2. draw an outcome per bridge from `outcome_probs`;
     loss = amount * (1 - recovery_rate_by_outcome[outcome]);
  3. optional stop line: once `bypass_rate_min_bridges` are out, stop releasing when the
     bypass rate to date exceeds `pause_if_bypass_rate_over`; record the pause point;
  4. allocate losses with `allocate_pool` (reserve shared across the cohort);
  5. financier result = flat fees - cost to serve - financier loss. The guarantee fee is charged
     to the borrower on drawn amounts and passed to the guarantor.

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

    released = materials = gfee = 0.0
    n = bypasses = 0
    losses: list[float] = []
    paused_at = None
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
        bypasses += outcome == "bypass"
        if pause_rate is not None and n >= pause_min and bypasses / n > pause_rate:
            paused_at = n
            break

    pool = allocate_pool(losses, reserve, cover, gcap, on)["total"]
    total = sum(losses)
    fee = get(cfg, "pricing.flat_fee_per_bridge") * n
    cost = get(cfg, "pricing.cost_to_serve_per_bridge") * n
    return Run(n, released, materials, total, pool["first_loss"], pool["guarantor"], pool["financier"],
               fee, gfee, cost, fee - cost - pool["financier"], bypasses, paused_at,
               total >= reserve and total > 0, on and gcap > 0 and pool["guarantor"] >= gcap - 1e-9)


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
        "median_pause_point": statistics.median(paused) if paused else None,
        "avg_bridge": released / bridges,
        "advance_share_of_materials": released / (sum(r.materials for r in runs) or 1.0),
        "expected_financier_loss_per_bridge": exp_fin_loss,
        "financier_net_per_bridge": sum(r.financier_net for r in runs) / bridges,
        # flat fee that covers cost to serve + expected financier loss (guarantee fee paid by borrower)
        "breakeven_flat_fee": breakeven_fee(exp_fin_loss, cts, 0.0),
        # if instead the financier pays the guarantee fee out of the flat fee
        "breakeven_flat_fee_if_financier_pays_guarantee": breakeven_fee(exp_fin_loss, cts, gfee_pb),
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
