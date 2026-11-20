import copy
import random

import pytest

from self_employed_bridge import simulate as sim
from self_employed_bridge.config import ConfigIncomplete, ConfigInvalid
from self_employed_bridge.waterfall import allocate_loss, allocate_pool


@pytest.fixture
def small(demo):
    demo["simulation"]["n_runs"] = 200
    return demo


def test_same_seed_same_output(small):
    assert sim.simulate(small)["summary"] == sim.simulate(copy.deepcopy(small))["summary"]


def test_different_seed_changes_output(small):
    other = copy.deepcopy(small)
    other["simulation"]["seed"] = 43
    assert sim.simulate(small)["summary"] != sim.simulate(other)["summary"]


def test_layers_conserve_loss_in_every_run(small):
    for r in sim.simulate(small)["runs"]:
        assert r.first_loss + r.guarantor + r.financier_loss == pytest.approx(r.total_loss)


def test_huge_reserve_means_no_guarantor_or_financier_loss(small):
    small["layers"]["first_loss_reserve"] = 1e12
    s = sim.simulate(small)["summary"]
    assert s["guarantor_draw"]["p95"] == 0 and s["financier_loss"]["p95"] == 0
    assert s["p_reserve_exhausted"] == 0


def test_pool_totals_equal_single_allocation():
    rng = random.Random(1)
    for _ in range(200):
        losses = [rng.uniform(0, 3000) for _ in range(rng.randint(0, 20))]
        args = (rng.uniform(0, 20000), rng.uniform(0, 1), rng.uniform(0, 10000), rng.random() < 0.7)
        pool = allocate_pool(losses, *args)["total"]
        one = allocate_loss(sum(losses), *args)
        for k in pool:
            assert pool[k] == pytest.approx(one[k], abs=1e-6)


def test_cohort_cap_and_margin_of_advance_hold(small):
    small["release"]["margin_of_advance"] = 0.5
    for r in sim.simulate(small)["runs"]:
        assert r.released <= small["caps"]["per_sponsor_cohort"] + 1e-6
        assert r.released <= 0.5 * r.materials + 1e-6


def test_stop_line_pauses(small):
    small["stop_lines"].update(pause_if_bypass_rate_over=0.0, bypass_rate_min_bridges=1)
    runs = sim.simulate(small)["runs"]
    for r in runs:
        if r.bypasses:
            assert r.paused_at == r.n_released          # stops right after the first bypass
    small["stop_lines"]["pause_if_bypass_rate_over"] = None
    assert all(r.paused_at is None for r in sim.simulate(small)["runs"])


def test_null_parameters_refused(template):
    with pytest.raises(ConfigIncomplete) as e:
        sim.simulate(template)
    assert "simulation.outcome_probs" in e.value.keys and "release.margin_of_advance" in e.value.keys


def test_bad_probabilities_refused(small):
    small["simulation"]["outcome_probs"]["on_time"] = 0.5
    with pytest.raises(ConfigInvalid):
        sim.simulate(small)


def test_sensitivity_moves_one_thing_at_a_time(small):
    out = sim.simulate(small)
    rows = {r["param"]: r for r in sim.sensitivity(small, out["draws"])}
    fee = rows["flat_fee"]
    assert fee["high"]["financier_net_per_bridge"] - fee["base"]["financier_net_per_bridge"] == pytest.approx(15)
    res = rows["first_loss_reserve"]
    assert res["low"]["total_loss"] == res["base"]["total_loss"] == res["high"]["total_loss"]
    byp = rows["bypass_probability"]
    assert byp["low"]["financier_net_per_bridge"] >= byp["high"]["financier_net_per_bridge"]
    assert rows["recovery_rate"]["high"]["total_loss"]["mean"] < rows["recovery_rate"]["low"]["total_loss"]["mean"]


def test_slider_grid_matches_full_simulation_at_base(small):
    out = sim.simulate(small)
    grid = sim.slider_grid(small, out["draws"])
    cell = grid["cells"]["0.95|60|10000"]
    s = out["summary"]
    assert cell["financier_net_per_bridge"] == pytest.approx(s["financier_net_per_bridge"])
    assert cell["breakeven_flat_fee"] == pytest.approx(s["breakeven_flat_fee"])
    assert cell["p_reserve_exhausted"] == pytest.approx(s["p_reserve_exhausted"])
    assert cell["borrower_monthly_cost"] == pytest.approx(s["borrower_monthly_cost"])
    assert len(grid["cells"]) == 125


def test_slider_grid_off_when_not_set(small):
    small["sliders"]["margin_of_advance"] = None
    assert sim.slider_grid(small, []) is None
