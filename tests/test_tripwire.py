import copy

import pytest

from self_employed_bridge import simulate as sim
from self_employed_bridge.config import ConfigIncomplete, stop_line_keys


def cfg_with(demo, wire, lag=0, min_n=1, bypass_line=None):
    c = copy.deepcopy(demo)
    c["simulation"]["n_runs"] = 300
    c["stop_lines"].update(pause_if_loss_rate_over=wire, loss_rate_min_bridges=min_n, outcome_lag_bridges=lag,
                           pause_if_bypass_rate_over=bypass_line)
    return c


def test_off_by_default_in_demo(demo):
    assert demo["stop_lines"]["pause_if_loss_rate_over"] is None
    assert all(r.paused_by != "loss" for r in sim.simulate(demo)["runs"])


def test_wire_stops_releasing_and_cuts_loss(demo):
    off = sim.simulate(cfg_with(demo, None))
    on = sim.simulate(cfg_with(demo, 0.02, lag=0, min_n=5))
    # same random draws in both: any difference comes from the trip wire
    assert sum(r.paused_by == "loss" for r in on["runs"]) > 0
    for a, b in zip(off["runs"], on["runs"]):
        assert b.n_released <= a.n_released and b.released <= a.released + 1e-9
        assert b.total_loss <= a.total_loss + 1e-9
    assert sum(r.total_loss for r in on["runs"]) < sum(r.total_loss for r in off["runs"])


def test_tripped_run_really_was_above_the_line(demo):
    c = cfg_with(demo, 0.03, lag=0, min_n=5)
    for r in sim.simulate(c)["runs"]:
        if r.paused_by == "loss":
            assert r.paused_at == r.n_released and r.paused_at >= 5


def test_min_loans_before_it_can_fire(demo):
    c = cfg_with(demo, 0.0, lag=0, min_n=30)           # any loss at all trips it, but not before 30 loans
    for r in sim.simulate(c)["runs"]:
        if r.paused_by == "loss":
            assert r.paused_at >= 30


def test_lag_lets_loans_out_before_it_fires(demo):
    quick = sim.simulate(cfg_with(demo, 0.0, lag=0, min_n=1))
    slow = sim.simulate(cfg_with(demo, 0.0, lag=20, min_n=1))
    # with a lag the wire reacts later, so more loans are released and more loss gets through
    assert sum(r.n_released for r in slow["runs"]) > sum(r.n_released for r in quick["runs"])
    for r in slow["runs"]:
        if r.paused_by == "loss":
            assert r.paused_at > 20


def test_layers_still_conserve_with_a_wire(demo):
    for r in sim.simulate(cfg_with(demo, 0.02, lag=5, min_n=5))["runs"]:
        assert r.first_loss + r.guarantor + r.financier_loss == pytest.approx(r.total_loss)


def test_summary_splits_pauses_by_cause(demo):
    s = sim.simulate(cfg_with(demo, 0.02, lag=5, min_n=5, bypass_line=0.10))["summary"]
    assert s["p_paused"] >= max(s["p_paused_loss"], s["p_paused_bypass"])
    assert s["p_paused_loss"] > 0


def test_wire_needs_its_sample_and_lag(demo, template):
    c = copy.deepcopy(demo)
    c["stop_lines"]["pause_if_loss_rate_over"] = 0.03
    assert "stop_lines.loss_rate_min_bridges" in stop_line_keys(c) and "stop_lines.outcome_lag_bridges" in stop_line_keys(c)
    c["stop_lines"]["loss_rate_min_bridges"] = None
    with pytest.raises(ConfigIncomplete) as e:
        sim.simulate(c)
    assert "stop_lines.loss_rate_min_bridges" in e.value.keys
    assert stop_line_keys(template) == []


# ---- the damage / trip wire grid ----

@pytest.fixture
def small(demo):
    c = copy.deepcopy(demo)
    c["simulation"]["n_runs"] = 200
    c["damage_sliders"] = {"damage_rate": [0.03, 0.05], "loss_per_damaged_loan": [0.5, 1.0], "trip_wire": [None, 0.02, 0.04]}
    return c


def test_damage_config_sets_the_two_outcomes(demo):
    c = sim.damage_config(demo, 0.05, 0.7, 0.03)
    p = c["simulation"]["outcome_probs"]
    assert p["dispute"] == pytest.approx(0.03) and p["abandoned"] == pytest.approx(0.02)
    assert sum(p.values()) == pytest.approx(1.0) and p["on_time"] == pytest.approx(0.80)   # late 10%, cash 5% kept
    assert c["simulation"]["recovery_rate_by_outcome"]["dispute"] == pytest.approx(0.3)
    assert c["stop_lines"]["pause_if_loss_rate_over"] == 0.03
    assert sim.damage_config(demo, 0.9, 0.7, None) is None                                  # more than 100% in total


def test_grid_shape_and_pairing(small):
    out = sim.simulate(small)
    g = sim.damage_grid(small, out["draws"])
    assert len(g["cells"]) == 2 * 2 * 3
    off = g["cells"]["0|0|0"]
    assert off["p_tripped"] == 0 and off["loss_avoided"] is None
    for key in ("0|0|1", "0|0|2", "1|1|1"):
        c = g["cells"][key]
        assert c["loss_avoided"] >= -1e-9 and c["loans_given_up"] >= -1e-9        # a trip wire never adds loss or loans
    tight, loose = g["cells"]["1|1|1"], g["cells"]["1|1|2"]
    assert tight["p_tripped"] >= loose["p_tripped"] and tight["loans"] <= loose["loans"] + 1e-9


def test_trip_wire_trades_reach_for_loss(small):
    out = sim.simulate(small)
    g = sim.damage_grid(small, out["draws"])
    c = g["cells"]["1|1|1"]                    # 5% damage, lose all of it, 2% line
    assert c["loss_avoided"] > 0 and c["loans_given_up"] > 0
    assert c["loss"] < g["cells"]["1|1|0"]["loss"]


def test_off_cell_matches_the_plain_simulation(small):
    out = sim.simulate(small)
    c = sim.damage_config(small, 0.05, 1.0, None)
    runs = [sim.run_cohort(d, c) for d in out["draws"]]
    cell = sim.damage_cell(runs, c)
    g = sim.damage_grid(small, out["draws"])
    assert g["cells"]["1|1|0"]["loss"] == pytest.approx(cell["loss"])


def test_grid_hidden_and_checked(small):
    out = sim.simulate(small)
    c = copy.deepcopy(small); c["damage_sliders"]["trip_wire"] = None
    assert sim.damage_grid(c, out["draws"]) is None
    c = copy.deepcopy(small); c["simulation"]["damage_dispute_share"] = None
    with pytest.raises(ConfigIncomplete):
        sim.damage_grid(c, out["draws"])
    c = copy.deepcopy(small); c["stop_lines"]["outcome_lag_bridges"] = None
    with pytest.raises(ConfigIncomplete):
        sim.damage_grid(c, out["draws"])
