import json

import pytest

from self_employed_bridge.cli import main
from tests.conftest import ROOT

DEMO = str(ROOT / "config" / "params.demo.yaml")
TEMPLATE = str(ROOT / "config" / "params.template.yaml")
JOB = str(ROOT / "data" / "example_job.json")
EXPO = str(ROOT / "data" / "example_exposure.json")
LOG = str(ROOT / "data" / "sample_log.csv")
JOBS = str(ROOT / "data" / "sample_jobs.csv")


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_screen(capsys):
    code, out, _ = run(capsys, "screen", JOB, "--config", DEMO)
    assert code == 0 and "BRIDGE_CANDIDATE" in out and "DEMO PARAMETERS" in out


def test_decide_json(capsys):
    code, out, _ = run(capsys, "decide", JOB, "--config", DEMO, "--exposure", EXPO, "--json")
    d = json.loads(out)["decision"]
    assert code == 0 and d["route"] == "RELEASE" and d["approved_amount"] == 3000 and d["payee"] == "S-EX1"


def test_decide_refuses_null_config(capsys):
    code, out, err = run(capsys, "decide", JOB, "--config", TEMPLATE)
    assert code == 2 and "caps.per_bridge" in err and out == ""


def test_waterfall(capsys):
    code, out, _ = run(capsys, "waterfall", "--loss", "25000", "--config", DEMO, "--json")
    assert code == 0 and json.loads(out) == {"first_loss": 10000, "guarantor": 5000, "financier": 10000}


def test_waterfall_null_reserve(capsys):
    code, _, err = run(capsys, "waterfall", "--loss", "100", "--config", TEMPLATE)
    assert code == 2 and "layers.first_loss_reserve" in err


def test_gates_writes_offline_html(capsys, tmp_path, template):
    out_file = tmp_path / "gates.html"
    code, out, _ = run(capsys, "gates", LOG, "--config", DEMO, "--jobs", JOBS, "--out", str(out_file))
    gate_lines = [ln for ln in out.splitlines() if ln[:2] in ("0 ", "1 ", "2 ", "3 ", "4 ")]
    assert code == 0 and len(gate_lines) == 5 and all(ln.endswith("NO_THRESHOLD_SET") for ln in gate_lines)
    assert "SYNTHETIC" in out
    h = out_file.read_text()
    assert "DEMO PARAMETERS" in h and "SYNTHETIC DATA" in h
    assert "<script" not in h and "http" not in h.replace("http-equiv", "")


def test_check_config_template_blocks(capsys):
    code, out, _ = run(capsys, "check-config", TEMPLATE)
    assert code == 1 and "caps.per_bridge" in out and "gates.gate1_min_share" in out


def test_check_config_demo_clear(capsys):
    code, out, _ = run(capsys, "check-config", DEMO)
    assert code == 0 and "No null parameter blocks live use" in out


def test_bad_input(capsys, tmp_path):
    code, _, err = run(capsys, "screen", str(tmp_path / "missing.json"), "--config", DEMO)
    assert code == 2 and "Bad input" in err


def test_simulate_writes_report(capsys, tmp_path, monkeypatch):
    import yaml
    cfg = yaml.safe_load(open(DEMO))
    cfg["simulation"]["n_runs"] = 100
    small = tmp_path / "small.yaml"
    small.write_text(yaml.safe_dump(cfg))
    out_file = tmp_path / "report.html"
    code, out, _ = run(capsys, "simulate", "--config", str(small), "--out", str(out_file))
    assert code == 0 and "Break-even flat fee" in out and "DEMO PARAMETERS" in out
    assert out_file.read_text().count("<svg") == 3


def test_simulate_refuses_template(capsys):
    code, _, err = run(capsys, "simulate", "--config", TEMPLATE)
    assert code == 2 and "simulation.outcome_probs" in err


def test_simulate_prints_developmental_lines(capsys, tmp_path):
    import yaml
    cfg = yaml.safe_load(open(DEMO)); cfg["simulation"]["n_runs"] = 100
    small = tmp_path / "s.yaml"; small.write_text(yaml.safe_dump(cfg))
    code, out, _ = run(capsys, "simulate", "--config", str(small))
    assert code == 0 and "Developmental pricing" in out and "Planned programme cost" in out and "Reserve used" in out
    cfg["pricing"]["all_in_rate_cap_pa"] = None
    small.write_text(yaml.safe_dump(cfg))
    code, out, _ = run(capsys, "simulate", "--config", str(small))
    assert code == 0 and "Developmental pricing" not in out
