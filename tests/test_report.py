import json
import re

import pytest

from self_employed_bridge import report, simulate as sim


@pytest.fixture
def built(demo):
    demo["simulation"]["n_runs"] = 150
    out = sim.simulate(demo)
    return demo, out, sim.sensitivity(demo, out["draws"]), sim.slider_grid(demo, out["draws"])


def test_report_is_self_contained_with_three_charts(built):
    cfg, out, sens, grid = built
    h = report.render_simulation(out, sens, grid, cfg, "config/params.demo.yaml")
    assert h.count("<svg") == 3
    assert "DEMO PARAMETERS" in h and "Sensitivity tool, not a forecast" in h
    assert not re.search(r"(src|href)\s*=", h), "no external resources"
    assert "http://" not in h and "https://" not in h
    assert "background:#fff" in h


def test_market_reference_marked_pending(built):
    cfg, out, sens, grid = built
    h = report.render_simulation(out, sens, grid, cfg, "x")
    assert "PENDING AUTHOR APPROVAL" in h
    cfg["market_reference"]["approved_by_author"] = True
    assert "PENDING AUTHOR APPROVAL" not in report.render_simulation(out, sens, grid, cfg, "x")


def test_slider_data_is_keyed_by_position(built):
    cfg, out, sens, grid = built
    h = report.render_simulation(out, sens, grid, cfg, "x")
    data = json.loads(re.search(r'<script type="application/json" id="grid">(.*?)</script>', h).group(1))
    assert len(data["cells"]) == 125 and "4|0|0" in data["cells"]       # position 4 = margin of advance 1.0
    base = data["cells"]["3|2|2"]                                          # 0.95, RM60, RM10,000
    assert base["financier_net_per_bridge"] == pytest.approx(out["summary"]["financier_net_per_bridge"], abs=1e-4)


def test_no_sliders_without_grid(built):
    cfg, out, sens, _ = built
    h = report.render_simulation(out, sens, None, cfg, "x")
    assert "<script" not in h and "Try other settings" not in h


def test_money_format():
    assert report.fmt(-8400, "rm") == "−RM8,400" and report.fmt(900, "rm") == "RM900"


def test_developmental_section(built):
    cfg, out, sens, grid = built
    dev = sim.dev_grid(cfg, out["draws"])
    h = report.render_simulation(out, sens, grid, cfg, "x", dev)
    assert "DEVELOPMENTAL PRICING" in h and "priced below a commercial return on purpose" in h
    assert "assumes <strong>no</strong> additionality" in h
    assert h.count("<svg") == 3 and "https://" not in h and "http://" not in h
    import json, re
    data = json.loads(re.search(r'<script type="application/json" id="dgrid">(.*?)</script>', h).group(1))
    assert len(data["cells"]) == 4 * 4 * 4 * 5 and data["budget"] == 2000
    assert "programme_cost_per_loan" in next(c for c in data["cells"].values() if c)


def test_developmental_section_hidden_without_sliders(built):
    cfg, out, sens, grid = built
    cfg["dev_sliders"]["all_in_cap_pa"] = None
    assert sim.dev_grid(cfg, out["draws"]) is None
    h = report.render_simulation(out, sens, grid, cfg, "x", None)
    assert "DEVELOPMENTAL PRICING" not in h


def test_damage_section_and_trip_wire(built):
    import json, re
    cfg, out, sens, grid = built
    cfg["damage_sliders"] = {"damage_rate": [0.03, 0.05], "loss_per_damaged_loan": [0.5, 1.0], "trip_wire": [None, 0.03]}
    dg = sim.damage_grid(cfg, out["draws"])
    h = report.render_simulation(out, sens, grid, cfg, "x", None, dg)
    assert "Damage rate and the loss trip wire" in h and "trades <strong>reach for loss</strong>" in h
    data = json.loads(re.search(r'<script type="application/json" id="mgrid">(.*?)</script>', h).group(1))
    assert len(data["cells"]) == 2 * 2 * 2 and data["axes"]["trip_wire"] == [None, 0.03]
    assert "loss_avoided" in data["cells"]["1|1|1"] and data["cells"]["1|1|0"]["loss_avoided"] is None
    assert "https://" not in h and "http://" not in h


def test_damage_section_hidden_without_sliders(built):
    cfg, out, sens, grid = built
    h = report.render_simulation(out, sens, grid, cfg, "x", None, None)
    assert "Damage rate and the loss trip wire" not in h


def test_risk_return_section(built):
    import json, re
    from self_employed_bridge import riskreturn
    cfg, out, sens, grid = built
    cfg["layers"]["guarantor_cover_pct"] = 0.7
    rg = riskreturn.rr_grid(cfg, out["draws"])
    h = report.render_simulation(out, sens, grid, cfg, "x", None, None, rg)
    assert "Risk and return: the DFI and the guarantor" in h and "Each party carries its own costs" in h and "demo placeholders" in h
    data = json.loads(re.search(r'<script type="application/json" id="rgrid">(.*?)</script>', h).group(1))
    assert len(data["cells"]) == 4 * 4 * 4 * 5
    cell = next(c for c in data["cells"].values() if c)
    assert {"dfi", "guarantor", "loss_split", "gap_pa", "gap_per_loan"} <= set(cell)
    assert "https://" not in h and "http://" not in h


def test_risk_return_hidden_without_costs(built):
    from self_employed_bridge import riskreturn
    cfg, out, sens, grid = built
    cfg["guarantor"]["cost_of_capital_pa"] = None
    assert riskreturn.rr_grid(cfg, out["draws"]) is None
    assert "Risk and return: the DFI and the guarantor" not in report.render_simulation(out, sens, grid, cfg, "x", None, None, None)


def test_reserve_section(built):
    from self_employed_bridge import riskreturn
    cfg, out, sens, grid = built
    cfg["layers"]["guarantor_cover_pct"] = 0.7
    rows = riskreturn.reserve_table(cfg, out["draws"])
    h = report.render_simulation(out, sens, grid, cfg, "x", None, None, None, rows)
    assert "The reserve: funded by the DFI and the guarantor" in h and "no outside sponsor" in h and "ring-fenced account" in h
    assert "goes back to the two of them" in h and "<strong>RM10,000 (config)</strong>" in h and "Joint result per group" in h
    cfg["layers"]["unused_reserve_returned"] = False
    h2 = report.render_simulation(out, sens, grid, cfg, "x", None, None, None, riskreturn.reserve_table(cfg, out["draws"]))
    assert "forfeited" in h2 and "goes back to the two of them" not in h2
