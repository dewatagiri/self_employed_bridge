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
