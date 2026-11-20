import copy

import pytest

from self_employed_bridge import riskreturn as rr
from self_employed_bridge import simulate as sim
from self_employed_bridge.config import ConfigIncomplete


@pytest.fixture
def world(demo):
    demo["simulation"]["n_runs"] = 400
    demo["layers"]["guarantor_cover_pct"] = 0.7
    return demo, sim.simulate(demo)


def test_parties_and_loss_split_add_up(world):
    demo, o = world
    x = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)
    assert sum(x["loss_split"].values()) == pytest.approx(1.0)
    # the borrower's all-in charge is split between the two parties' fees
    assert x["dfi"]["fee_per_loan"] + x["guarantor"]["fee_per_loan"] == pytest.approx(0.18 * x["avg_loan"] * 30 / 365, rel=1e-6)


def test_dfi_result_is_income_less_every_cost_and_loss(world):
    demo, o = world
    d = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)["dfi"]
    assert d["result"] == pytest.approx(d["income"] - d["cost_to_serve"] - d["funding_cost"] - d["credit_loss"])
    assert d["economic_profit"] == pytest.approx(d["result"] - 0.12 * (d["capital"] * 90 / 365))   # capital already includes the 8%
    assert d["spread"] == pytest.approx(d["return_on_capital_pa"] - 0.12)


def test_guarantor_result_and_capital(world):
    demo, o = world
    g = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)["guarantor"]
    assert g["result"] == pytest.approx(g["income"] - g["admin_cost"] - g["credit_loss"])
    assert g["capital"] == 5000 and g["hurdle"] == 0.10
    cap_years = 5000 * 90 / 365
    assert g["return_on_capital_pa"] == pytest.approx(g["result"] / cap_years)
    assert g["economic_profit"] == pytest.approx(g["result"] - 0.10 * cap_years)


def test_break_even_fee_gives_zero_economic_profit(world):
    """Charge each party exactly its break-even fee and its economic profit is zero, including its cost of capital."""
    demo, o = world
    x = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)
    g_be, d_be = x["guarantor"]["break_even_fee_pa"], x["dfi"]["break_even_fee_pa"]
    y = rr.risk_return(o["runs"], demo, g_be + d_be, g_be, 25.0)
    assert y["guarantor"]["economic_profit"] == pytest.approx(0, abs=1e-6)
    assert y["dfi"]["economic_profit"] == pytest.approx(0, abs=1e-6)
    assert y["gap_pa"] == pytest.approx(0, abs=1e-9)


def test_gap_is_how_far_the_cap_is_below_cost(world):
    demo, o = world
    low = rr.risk_return(o["runs"], demo, 0.10, 0.035, 25.0)
    high = rr.risk_return(o["runs"], demo, 0.60, 0.035, 25.0)
    assert low["gap_pa"] > 0 > high["gap_pa"] and low["gap_per_loan"] > 0
    assert low["gap_pa"] == pytest.approx(low["cost_covering_all_in_pa"] - 0.10)


def test_risk_numbers(world):
    demo, o = world
    d = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)["dfi"]
    assert d["es5"] <= d["p5"] + 1e-9 <= d["p50"] + 1e-9 and d["std"] > 0 and 0 <= d["p_loss"] <= 1
    assert d["return_per_risk"] == pytest.approx(d["mean"] / d["std"])


def test_more_cover_moves_loss_from_dfi_to_guarantor(demo):
    demo["simulation"]["n_runs"] = 300
    out = sim.simulate(demo)
    res = {}
    for cover in (0.3, 0.8):
        c = copy.deepcopy(demo); c["layers"]["guarantor_cover_pct"] = cover
        runs = [sim.run_cohort(d, c) for d in out["draws"]]
        res[cover] = rr.risk_return(runs, c, 0.18, 0.035, 25.0)
    assert res[0.8]["loss_split"]["guarantor"] > res[0.3]["loss_split"]["guarantor"]
    assert res[0.8]["loss_split"]["dfi"] < res[0.3]["loss_split"]["dfi"]


def test_guarantee_fee_above_cap_is_not_a_result(world):
    demo, o = world
    assert rr.risk_return(o["runs"], demo, 0.03, 0.05, 25.0) is None


def test_missing_costs_are_named(world, template):
    demo, o = world
    demo["guarantor"]["cost_of_capital_pa"] = None
    with pytest.raises(ConfigIncomplete) as e:
        rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)
    assert "guarantor.cost_of_capital_pa" in e.value.keys
    assert rr.rr_base(demo, o["draws"]) is None and rr.rr_grid(demo, o["draws"]) is None


def test_grid_matches_base(demo):
    demo["simulation"]["n_runs"] = 150
    demo["layers"]["guarantor_cover_pct"] = 0.7
    demo["pricing"]["guarantee_fee_rate_on_drawn"] = 0.035
    out = sim.simulate(demo)
    g = rr.rr_grid(demo, out["draws"])
    ax = g["axes"]
    key = "|".join(str(i) for i in (ax["guarantor_cover_pct"].index(0.7), ax["all_in_cap_pa"].index(0.18),
                                    ax["guarantee_fee_pa"].index(0.035), ax["cost_to_serve_per_bridge"].index(25)))
    base = rr.rr_base(demo, out["draws"])
    assert g["cells"][key]["dfi"]["result"] == pytest.approx(base["dfi"]["result"])
    assert g["cells"][key]["guarantor"]["return_on_capital_pa"] == pytest.approx(base["guarantor"]["return_on_capital_pa"])
