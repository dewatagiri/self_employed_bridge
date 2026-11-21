"""The author's base case: the demo file with the author's own assumptions on top. Nothing else may differ from the demo."""
import re

import pytest
import yaml

from self_employed_bridge import riskreturn as rr
from self_employed_bridge import report, simulate as sim
from self_employed_bridge.config import is_demo, load_config
from tests.conftest import ROOT

BASE = ROOT / "config" / "params.base_case.yaml"
DEMO = ROOT / "config" / "params.demo.yaml"

# exactly the values the author chose or implied; every other value must equal the demo's
AUTHOR_KEYS = {"tenor.typical_days", "pricing.cost_to_serve_per_bridge", "financier.cost_of_funds_pa", "simulation.amount_distribution.mean",
               "caps.per_bridge", "caps.per_borrower_live", "caps.step_up_tiers", "layers.guarantor_cover_pct", "pricing.guarantee_fee_rate_on_drawn", "pricing.flat_fee_per_bridge",
               "simulation.outcome_probs.on_time", "simulation.outcome_probs.late",
               "simulation.outcome_probs.dispute", "simulation.outcome_probs.abandoned",
               "simulation.recovery_rate_by_outcome.late", "simulation.recovery_rate_by_outcome.bypass",
               "simulation.recovery_rate_by_outcome.dispute", "viability_sliders.bypass_chance",
               "layers.reserve_funded_by_guarantor_pct", "development.funder_loss_budget_per_cohort", "compliance.controlled_account_legal_status", "compliance.all_in_cap_legal_status"}
# placeholders scaled with the author's cohort of 100 loans (batch 4 Q2); every one is still marked DEMO ONLY, not an assumption
SCALED_KEYS = {"layers.first_loss_reserve", "layers.guarantor_cap", "caps.per_sponsor_cohort", "caps.pilot_total", "caps.per_supplier_live", "sliders.first_loss_reserve"}
# thresholds proposed by me, not the author
SUGGESTED_KEYS = {"stop_lines.bypass_rate_min_bridges", "stop_lines.loss_rate_min_bridges"}


def flat(d, p=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flat(v, p + k + ".")
        else:
            yield p + k, v


@pytest.fixture
def base():
    return load_config(BASE)


def test_only_the_authors_assumptions_differ_from_the_demo(base):
    demo = dict(flat(load_config(DEMO)))
    mine = dict(flat(base))
    assert set(mine) - set(demo) == {"meta.case"} and not set(demo) - set(mine)
    assert {k for k in demo if demo[k] != mine[k]} == AUTHOR_KEYS | SCALED_KEYS | SUGGESTED_KEYS


def test_the_answers_are_recorded_as_given(base):
    assert base["tenor"]["typical_days"] == 90                                       # batch 3 Q2: 90 days
    assert base["layers"]["guarantor_cover_pct"] == 0.7 and base["pricing"]["guarantee_fee_rate_on_drawn"] == 0.035
    assert base["pricing"]["all_in_rate_cap_pa"] == 0.18
    p, r = base["simulation"]["outcome_probs"], base["simulation"]["recovery_rate_by_outcome"]
    assert p["dispute"] + p["abandoned"] == pytest.approx(0.03)                      # Q3: 3% damage
    assert p["bypass"] == 0.05 and p["late"] == 0.20                                 # batch 4 Q1: 5% cash with a controlled account only; 20% late
    assert sum(p.values()) == pytest.approx(1.0) and p["on_time"] == pytest.approx(0.72)
    assert r["dispute"] == r["abandoned"] == pytest.approx(0.3)                      # Q4: 70% of a damaged loan lost
    assert r["bypass"] == 0.25 and r["late"] == 1.0                                  # 25% recovered on cash; late payers do pay
    assert base["pricing"]["cost_to_serve_per_bridge"] == 5                          # batch 3 Q3: RM5 with automation
    assert base["financier"]["cost_of_funds_pa"] == 0.03                             # batch 3 Q5: 3%
    assert base["simulation"]["amount_distribution"]["mean"] == 9.55                 # batch 3 Q4: average bridge about RM10,000


def test_batch_four_answers(base):
    assert base["simulation"]["n_bridges"] == 100 and base["layers"]["reserve_funded_by_guarantor_pct"] == 0.0
    assert base["development"]["funder_loss_budget_per_cohort"] is None             # not decided yet
    assert base["compliance"] == {"controlled_account_legal_status": "confirmed", "all_in_cap_legal_status": "confirmed"}
    assert base["layers"]["first_loss_reserve"] == 50000 and base["layers"]["guarantor_cap"] == 25000


def test_every_assumption_is_marked_and_it_still_says_demo(base):
    text = BASE.read_text(encoding="utf-8")
    assert "assumptions, not findings" in text and is_demo(base) and "case" in base["meta"]
    lines = text.splitlines()
    for needle in ("typical_days: 90", "guarantee_fee_rate_on_drawn: 0.035", "guarantor_cover_pct: 0.7  ", "all_in_rate_cap_pa: 0.18",
                   "outcome_probs: {on_time: 0.72", "recovery_rate_by_outcome: {on_time: 1.0, late: 1.0, bypass: 0.25, dispute: 0.3", "bypass_chance: [0.01, 0.03, 0.05, 0.08]"):
        hits = [ln for ln in lines if needle in ln]
        assert len(hits) == 1 and "AUTHOR ASSUMPTION" in hits[0], needle
    # the one derived number is a placeholder, not an assumption of the author
    assert [ln for ln in lines if "flat_fee_per_bridge: 360" in ln][0].count("DEMO ONLY") == 1


def test_it_runs_and_the_report_opens_on_the_authors_case(base):
    base["simulation"]["n_runs"] = 60
    base["viability_sliders"]["cost_to_serve_per_bridge"] = [5, 25]
    out = sim.simulate(base)
    vg = rr.viability_grid(base, out["draws"])
    h = report.render_simulation(out, sim.sensitivity(base, out["draws"]), None, base, "config/params.base_case.yaml", None, None, None, None, vg)
    assert "Author&#x27;s base case, 21 Nov 2026" in h or "Author's base case, 21 Nov 2026" in h
    assert "DEMO PARAMETERS" in h
    # the viability sliders start on the author's answers: 90 days (position 3), 3% damage (position 1), 5% cash (position 2), RM5 to serve (position 0)
    for key, pos in (("tenor_days", 3), ("damage_rate", 1), ("bypass_chance", 2), ("cost_to_serve_per_bridge", 0)):
        assert re.search(rf'id="vz_{key}"[^>]*value="{pos}"', h), key
