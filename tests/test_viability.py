import copy

import pytest

from self_employed_bridge import riskreturn as rr
from self_employed_bridge import simulate as sim


@pytest.fixture
def world(demo):
    demo["simulation"]["n_runs"] = 300
    demo["layers"]["guarantor_cover_pct"] = 0.7
    demo["pricing"]["guarantee_fee_rate_on_drawn"] = 0.035
    return demo, sim.simulate(demo)


def cell(demo, o, bypass=0.05, damage=0.05, scale=1.0, tenor=30, cts=15.0):
    c = rr.viability_config(demo, bypass, damage, scale)
    runs = [sim.run_cohort(d, c) for d in o["draws"]]
    return rr.viability_cell(runs, c, 0.18, 0.035, cts, tenor)


def test_config_sets_chances_and_scales_losses(world):
    demo, _ = world
    c = rr.viability_config(demo, 0.01, 0.03, 0.75)
    p = c["simulation"]["outcome_probs"]
    assert p["bypass"] == 0.01 and p["dispute"] == pytest.approx(0.018) and p["abandoned"] == pytest.approx(0.012)
    assert sum(p.values()) == pytest.approx(1.0) and p["late"] == 0.10                       # late is kept
    rec = c["simulation"]["recovery_rate_by_outcome"]
    assert rec["bypass"] == pytest.approx(1 - 0.5 * 0.75) and rec["dispute"] == pytest.approx(1 - 0.3 * 0.75)
    assert rec["on_time"] == 1.0 and rec["late"] == demo["simulation"]["recovery_rate_by_outcome"]["late"]   # only the bad outcomes move
    assert rr.viability_config(demo, 0.6, 0.5, 1.0) is None                                  # more than 100%


def test_each_lever_helps_in_the_right_direction(world):
    demo, o = world
    base = cell(demo, o)
    assert cell(demo, o, bypass=0.01)["joint_loan"] > base["joint_loan"]
    assert cell(demo, o, damage=0.02)["joint_loan"] > base["joint_loan"]
    assert cell(demo, o, scale=0.5)["joint_loan"] > base["joint_loan"]
    assert cell(demo, o, cts=5.0)["joint_loan"] > base["joint_loan"]
    assert cell(demo, o, tenor=90)["joint_loan"] > base["joint_loan"]        # the cap earns by time


def test_revenue_is_the_cap_over_the_tenor(world):
    demo, o = world
    assert cell(demo, o, tenor=30)["revenue_pct"] == pytest.approx(0.18 * 30 / 365)
    assert cell(demo, o, tenor=90)["revenue_pct"] == pytest.approx(0.18 * 90 / 365)


def test_joint_result_is_fees_less_every_cost_and_every_loss(world):
    """Checked independently: the two parties together = fees at the cap - cost to serve - DFI debt interest - guarantor admin
    - all credit loss (the reserve, the guarantor and the DFI together take all of it)."""
    demo, o = world
    c = rr.viability_config(demo, 0.05, 0.05, 1.0)
    runs = [sim.run_cohort(d, c) for d in o["draws"]]
    x = rr.viability_cell(runs, c, 0.18, 0.035, 15.0, 30)
    mean = lambda f: sum(f(r) for r in runs) / len(runs)          # noqa: E731
    direct = mean(lambda r: 0.18 * r.released * 30 / 365 - 15.0 * r.n_released - 0.04 * 0.92 * r.released * 30 / 365
                  - 2.0 * r.n_released - r.total_loss)
    assert x["joint_group"] == pytest.approx(direct, rel=1e-9)


def test_verdicts(world):
    demo, o = world
    bad = cell(demo, o, bypass=0.05, damage=0.05, tenor=30, cts=25.0)
    assert bad["verdict"] == 0 and bad["joint_loan"] < 0 and not bad["split_works_now"]
    # every lever pulled at the 18% cap: a working split of the cap exists, but today's 3.5% guarantee fee is not it
    best = cell(demo, o, bypass=0.01, damage=0.02, scale=0.5, tenor=90, cts=5.0)
    assert best["verdict"] == 2 and best["rate_needed"] <= 0.18
    assert best["dfi_fee_needed"] + best["guarantor_fee_needed"] == pytest.approx(best["rate_needed"])
    assert best["guarantor_fee_needed"] > best["guarantor_fee_now"] and not best["split_works_now"]


def test_a_working_split_really_works(world):
    """Charge each party exactly the fee the cell says it needs, inside the cap: both earn their required return."""
    demo, o = world
    c = rr.viability_config(demo, 0.01, 0.02, 0.5)
    runs = [sim.run_cohort(d, c) for d in o["draws"]]
    x = rr.viability_cell(runs, c, 0.18, 0.035, 5.0, 90)
    y = rr.viability_cell(runs, c, 0.18, x["guarantor_fee_needed"] + 0.001, 5.0, 90)
    assert y["split_works_now"] and y["dfi_roc"] >= y["dfi_hurdle"] and y["guarantor_roc"] >= y["guarantor_hurdle"]


def test_costs_covered_but_no_split_works(world):
    """Between the cap that just covers costs and the cap that also pays both required returns, the verdict is 1."""
    demo, o = world
    c = rr.viability_config(demo, 0.05, 0.03, 1.0)
    runs = [sim.run_cohort(d, c) for d in o["draws"]]
    seen = {}
    for i in range(36, 200):                                  # caps from 18% to 100% in half-point steps
        cap = i * 0.005
        x = rr.viability_cell(runs, c, cap, 0.035, 5.0, 90)
        seen.setdefault(x["verdict"], x)
    assert set(seen) == {0, 1, 2}                             # the cap walks through all three verdicts, in order
    assert seen[1]["joint_loan"] >= 0 and seen[1]["rate_needed"] > 0.18
    assert seen[0]["joint_loan"] < 0 <= seen[2]["joint_loan"]


def test_gap_is_priced_per_additional_borrower(world):
    demo, o = world
    c = cell(demo, o)
    assert c["joint_loan"] < 0
    assert c["per_additional_100"] == pytest.approx(-c["joint_loan"]) and c["per_additional_50"] == pytest.approx(-c["joint_loan"] / 0.5)
    assert c["per_additional_25"] == pytest.approx(4 * -c["joint_loan"])
    ok = cell(demo, o, bypass=0.01, damage=0.02, scale=0.5, tenor=90, cts=5.0)
    assert ok["per_additional_50"] == 0.0


def test_grid_shape_matches_a_direct_cell_and_hides(demo):
    demo["simulation"]["n_runs"] = 120
    demo["layers"]["guarantor_cover_pct"] = 0.7
    demo["pricing"]["guarantee_fee_rate_on_drawn"] = 0.035
    demo["viability_sliders"] = {"bypass_chance": [0.01, 0.05], "damage_rate": [0.03, 0.05], "loss_on_bad_loans_scale": [1.0, 0.75],
                                 "tenor_days": [30, 60], "cost_to_serve_per_bridge": [5, 15]}
    o = sim.simulate(demo)
    g = rr.viability_grid(demo, o["draws"])
    assert len(g["cells"]) == 2 ** 5
    direct = cell(demo, o, bypass=0.05, damage=0.03, scale=0.75, tenor=60, cts=5.0)
    assert g["cells"]["1|0|1|1|0"]["joint_group"] == pytest.approx(direct["joint_group"])
    demo["viability_sliders"]["tenor_days"] = None
    assert rr.viability_grid(demo, o["draws"]) is None
    demo["viability_sliders"]["tenor_days"] = [30]
    demo["simulation"]["damage_dispute_share"] = None
    assert rr.viability_grid(demo, o["draws"]) is None
