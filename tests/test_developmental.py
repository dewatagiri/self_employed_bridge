import copy

import pytest

from self_employed_bridge import simulate as sim
from self_employed_bridge.config import ConfigIncomplete


@pytest.fixture
def out(demo):
    demo["simulation"]["n_runs"] = 300
    return demo, sim.simulate(demo)


def test_loan_money_adds_up(out):
    demo, o = out
    c = sim.dev_cell(o["runs"], demo, 0.18, 0.035, 25.0, 2000)
    # the borrower's all-in charge is split into the guarantee fee and the financier fee
    assert c["borrower_per_loan"] == pytest.approx(c["guarantee_fee_per_loan"] + c["financier_fee_per_loan"])
    assert c["guarantee_fee_per_loan"] / c["borrower_per_loan"] == pytest.approx(0.035 / 0.18)


def test_funders_net_is_the_sum_of_both(out):
    demo, o = out
    c = sim.dev_cell(o["runs"], demo, 0.18, 0.035, 25.0)
    assert c["funders_net_mean"] == pytest.approx(c["financier_net_mean"] + c["guarantor_net_mean"])
    # the programme also bears the sponsor's reserve
    assert c["programme_net_mean"] == pytest.approx(c["funders_net_mean"] - c["sponsor_reserve_used_mean"])


def test_planned_loss_shows_as_cost(out):
    demo, o = out
    # high cost to serve and a low cap: the funders lose money, and the engine says so as a positive cost
    c = sim.dev_cell(o["runs"], demo, 0.12, 0.05, 35.0)
    assert c["funders_net_mean"] < 0 and c["programme_cost_per_loan"] > 0 and c["programme_cost_per_1000_lent"] > 0
    assert c["cost_per_additional_loan_50"] == pytest.approx(c["programme_cost_per_loan"] / 0.5)
    assert c["cost_per_additional_loan_25"] > c["cost_per_additional_loan_100"]


def test_surplus_has_no_cost(out):
    demo, o = out
    c = sim.dev_cell(o["runs"], demo, 1.00, 0.02, 1.0)
    assert c["programme_net_mean"] > 0 and c["cost_per_additional_loan_50"] == 0.0


def test_dfi_surplus_can_hide_a_programme_loss(out):
    """At a 60% cap the DFI and guarantor are ahead, but the sponsor's reserve means the programme still loses."""
    demo, o = out
    c = sim.dev_cell(o["runs"], demo, 0.60, 0.02, 1.0)
    assert c["funders_net_mean"] > 0 and c["programme_net_mean"] < 0 and c["cost_per_additional_loan_50"] > 0


def test_guarantee_fee_above_cap_is_not_a_result(out):
    demo, o = out
    assert sim.dev_cell(o["runs"], demo, 0.03, 0.05, 25.0) is None


def test_more_cost_to_serve_never_helps(out):
    demo, o = out
    a = sim.dev_cell(o["runs"], demo, 0.18, 0.035, 5.0)
    b = sim.dev_cell(o["runs"], demo, 0.18, 0.035, 35.0)
    assert a["financier_return_pa"] > b["financier_return_pa"]
    assert a["programme_cost_per_loan"] < b["programme_cost_per_loan"]


def test_budget_probability(out):
    demo, o = out
    tight = sim.dev_cell(o["runs"], demo, 0.12, 0.05, 35.0, budget=0.0)
    loose = sim.dev_cell(o["runs"], demo, 0.12, 0.05, 35.0, budget=1e9)
    assert loose["p_over_budget"] == 0 and tight["p_over_budget"] > 0
    assert sim.dev_cell(o["runs"], demo, 0.12, 0.05, 35.0)["p_over_budget"] is None


def test_base_matches_grid_cell(demo):
    demo["simulation"]["n_runs"] = 200
    o = sim.simulate(demo)
    demo["layers"]["guarantor_cover_pct"] = 0.7            # a value on the slider list
    demo["pricing"]["guarantee_fee_rate_on_drawn"] = 0.035
    grid = sim.dev_grid(demo, o["draws"])
    base = sim.dev_base(demo, o["draws"])
    ax = grid["axes"]
    key = "|".join(str(i) for i in (ax["guarantor_cover_pct"].index(0.7), ax["all_in_cap_pa"].index(0.18),
                                    ax["guarantee_fee_pa"].index(0.035), ax["cost_to_serve_per_bridge"].index(25)))
    for k in ("financier_net_mean", "guarantor_net_mean", "programme_cost_per_loan"):
        assert grid["cells"][key][k] == pytest.approx(base[k])
    assert len(grid["cells"]) == 4 * 4 * 4 * 5


def test_hidden_when_unset(demo, template):
    demo["simulation"]["n_runs"] = 50
    o = sim.simulate(demo)
    demo["dev_sliders"]["all_in_cap_pa"] = None
    assert sim.dev_grid(demo, o["draws"]) is None
    demo["pricing"]["all_in_rate_cap_pa"] = None
    assert sim.dev_base(demo, o["draws"]) is None


def test_programme_cost_matches_the_whole_loss_picture(out):
    """Programme net = fees in - cost to serve - total loss, whoever bears it. A direct, independent check."""
    demo, o = out
    c = sim.dev_cell(o["runs"], demo, 0.18, 0.035, 25.0)
    runs = o["runs"]
    tenor = demo["tenor"]["typical_days"]
    mean = lambda xs: sum(xs) / len(xs)
    direct = mean([0.18 * r.released * tenor / 365 - 25.0 * r.n_released - r.total_loss for r in runs])
    assert c["programme_net_mean"] == pytest.approx(direct)
