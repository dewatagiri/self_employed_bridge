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


# ---- the reserve, funded by the DFI and the guarantor (A16, A17) ----

def test_reserve_funding_split_and_hold(world):
    demo, o = world
    rf = rr.reserve_funding(o["runs"], demo)
    assert rf["committed"] == 10000 and rf["guarantor_share"] == 0.5 and rf["dfi_share"] == 0.5
    assert rf["hold_days"] == pytest.approx(90 + 120)                         # cohort days + write-off period
    assert rf["expected_used"] + rf["expected_unused"] == pytest.approx(10000)


def test_each_party_pays_its_share_of_the_reserve(world):
    demo, o = world
    demo["layers"]["reserve_funded_by_guarantor_pct"] = 0.3
    x = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)
    d, g, rf = x["dfi"], x["guarantor"], x["reserve"]
    used = rf["expected_used"]
    assert d["ar_result"] == pytest.approx(d["result"] - 0.7 * used)
    assert g["ar_result"] == pytest.approx(g["result"] - 0.3 * used)
    assert x["joint_result"] == pytest.approx(d["ar_result"] + g["ar_result"])
    assert d["ar_committed"] + g["ar_committed"] == pytest.approx(10000)
    # return on capital counts the money each party tied up in the reserve, at its own hurdle
    eq_years = d["capital"] * 90 / 365
    tied = 0.7 * 10000 * rf["hold_years"]
    assert d["ar_return_on_capital_pa"] == pytest.approx(d["ar_result"] / (eq_years + tied))
    assert d["ar_economic_profit"] == pytest.approx(d["ar_result"] - 0.12 * (eq_years + tied))
    assert g["ar_economic_profit"] == pytest.approx(g["ar_result"] - 0.10 * (5000 * 90 / 365 + 0.3 * 10000 * rf["hold_years"]))


def test_the_two_parties_carry_all_the_loss(world):
    """With no outside sponsor the reserve, the guarantor and the DFI together take the whole credit loss."""
    demo, o = world
    x = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)
    assert set(x["loss_split"]) == {"reserve", "guarantor", "dfi"} and sum(x["loss_split"].values()) == pytest.approx(1.0)


def test_forfeited_reserve_costs_each_party_its_whole_share(world):
    demo, o = world
    demo["layers"]["unused_reserve_returned"] = False
    x = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)
    assert x["dfi"]["ar_spent"] == pytest.approx(0.5 * 10000) and x["guarantor"]["ar_spent"] == pytest.approx(0.5 * 10000)


def test_break_even_after_the_reserve_gives_zero_economic_profit(world):
    demo, o = world
    x = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)
    d_be, g_be = x["dfi"]["ar_break_even_fee_pa"], x["guarantor"]["ar_break_even_fee_pa"]
    y = rr.risk_return(o["runs"], demo, d_be + g_be, g_be, 25.0)
    assert y["dfi"]["ar_economic_profit"] == pytest.approx(0, abs=1e-6)
    assert y["guarantor"]["ar_economic_profit"] == pytest.approx(0, abs=1e-6)
    assert y["gap_after_reserve_pa"] == pytest.approx(0, abs=1e-9)
    assert x["gap_after_reserve_pa"] > x["gap_pa"]               # funding the reserve only widens the gap


def test_extreme_splits_and_bad_split(world):
    demo, o = world
    demo["layers"]["reserve_funded_by_guarantor_pct"] = 0.0
    x = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)
    assert x["guarantor"]["ar_committed"] == 0 and x["dfi"]["ar_committed"] == 10000
    demo["layers"]["reserve_funded_by_guarantor_pct"] = 1.4
    from self_employed_bridge.config import ConfigInvalid
    with pytest.raises(ConfigInvalid):
        rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)


def test_reserve_settings_missing_hides_it(world):
    demo, o = world
    demo["layers"]["reserve_funded_by_guarantor_pct"] = None
    assert rr.reserve_funding(o["runs"], demo) is None and rr.reserve_table(demo, o["draws"]) is None
    x = rr.risk_return(o["runs"], demo, 0.18, 0.035, 25.0)
    assert x["reserve"] is None and "joint_result" not in x and "ar_result" not in x["dfi"]


def test_reserve_table_rows(demo):
    demo["simulation"]["n_runs"] = 300
    demo["layers"]["guarantor_cover_pct"] = 0.7
    demo["pricing"]["guarantee_fee_rate_on_drawn"] = 0.035
    out = sim.simulate(demo)
    rows = rr.reserve_table(demo, out["draws"])
    assert [r["reserve"] for r in rows] == demo["sliders"]["first_loss_reserve"]
    for r in rows:
        assert r["dfi"]["ar_committed"] + r["guarantor"]["ar_committed"] == pytest.approx(r["reserve"])
        assert r["joint_result"] == pytest.approx(r["dfi"]["ar_result"] + r["guarantor"]["ar_result"])
    assert rows[-1]["p_reserve_out"] <= rows[0]["p_reserve_out"]
