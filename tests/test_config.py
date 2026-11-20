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
