import pytest

from self_employed_bridge.config import ConfigIncomplete
from self_employed_bridge.pricing import breakeven_fee, bridge_revenue, fee_ceiling_check


def test_fee_ceiling_900(demo):
    c = fee_ceiling_check(1000, 20000, 90, demo)
    assert c.ceiling == pytest.approx(900) and c.above and "stated reason" in c.message
    assert not fee_ceiling_check(900, 20000, 90, demo).above


def test_revenue(demo):
    assert bridge_revenue(3000, 30, demo) == pytest.approx(60 + 0.02 * 3000 * 30 / 365)


def test_breakeven():
    assert breakeven_fee(10, 25, 5) == 40


def test_revenue_needs_config(template):
    with pytest.raises(ConfigIncomplete):
        bridge_revenue(1000, 30, template)
