import pytest

from self_employed_bridge.config import ConfigIncomplete, is_demo, null_keys, require


def test_template_is_all_null_for_pilot_values(template):
    nulls = null_keys(template)
    assert "caps.per_bridge" in nulls and "simulation.outcome_probs" in nulls
    assert not is_demo(template)


def test_demo_flag(demo):
    assert is_demo(demo)


def test_require_names_keys(template):
    with pytest.raises(ConfigIncomplete) as e:
        require(template, ["caps.per_bridge", "layers.first_loss_reserve"])
    assert e.value.keys == ["caps.per_bridge", "layers.first_loss_reserve"]


def test_check_config_maps_keys_to_commands(template):
    from self_employed_bridge.config import check_config
    r = check_config(template)
    assert r["blocking"]["screen.min_materials_share_of_quote"] == ["screen", "decide"]
    assert "layers.guarantor_cap" in r["open"]          # guarantor is off in the template
    template["layers"]["guarantor_enabled"] = True
    assert "layers.guarantor_cap" in check_config(template)["blocking"]


def test_demo_values_all_marked():
    from tests.conftest import ROOT
    text = (ROOT / "config" / "params.demo.yaml").read_text()
    import yaml
    from self_employed_bridge.config import null_keys
    template = yaml.safe_load((ROOT / "config" / "params.template.yaml").read_text())
    # every key null in the template that the demo fills must carry the DEMO ONLY marker
    for key in null_keys(template):
        leaf = key.split(".")[-1]
        lines = [ln for ln in text.splitlines() if ln.strip().startswith(leaf + ":")]
        filled = [ln for ln in lines if not ln.split(":", 1)[1].strip().startswith("null")]
        for ln in filled:
            assert "# DEMO ONLY, not a finding" in ln, ln
