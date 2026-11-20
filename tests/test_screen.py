import pytest

from self_employed_bridge.config import ConfigIncomplete
from self_employed_bridge.screen import screen


def test_bridge_candidate(make_job, demo):
    assert screen(make_job(), demo).route == "BRIDGE_CANDIDATE"


def test_no_bridge_needed(make_job, demo):
    assert screen(make_job(deposit_amount=5000), demo).route == "NO_BRIDGE_NEEDED"
    assert screen(make_job(deposit_amount=6000), demo).route == "NO_BRIDGE_NEEDED"


def test_company_payer(make_job, demo):
    assert screen(make_job(payer_type="company"), demo).route == "REFER_CONTRACT_INVOICE"


def test_related_payer_declines(make_job, demo):
    assert screen(make_job(payer_related_to_borrower=True), demo).route == "DECLINE"


def test_no_job(make_job, demo):
    r = screen(make_job(payer_id=None), demo)
    assert r.route == "REFER_GENERAL" and r.reasons[0].code == "NO_CONFIRMED_JOB"
    assert screen(make_job(payer_id="B1"), demo).route == "REFER_GENERAL"


def test_cost_not_materials(make_job, demo):
    r = screen(make_job(materials_cost=1000), demo)
    assert r.reasons[0].code == "COST_NOT_MATERIALS"


def test_unknown_payer_type(make_job, demo):
    assert screen(make_job(payer_type="charity"), demo).route == "REFER_GENERAL"


def test_null_param_raises(make_job, template):
    with pytest.raises(ConfigIncomplete) as e:
        screen(make_job(), template)
    assert "screen.min_materials_share_of_quote" in e.value.keys
