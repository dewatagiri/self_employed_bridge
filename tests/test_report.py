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
