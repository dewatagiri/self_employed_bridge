import pytest

from self_employed_bridge.config import ConfigIncomplete
from self_employed_bridge.decide import decide
from self_employed_bridge.models import Exposure


def test_worked_example(make_job, demo, exposure):
    d = decide(make_job(), exposure, demo)
    assert d.route == "RELEASE" and d.approved_amount == 3000
    assert d.payee == "S1" and d.review_level == "auto" and d.tranches == [3000]


def test_cap_limits_amount(make_job, demo):
    demo["caps"]["per_bridge"] = 1000
    d = decide(make_job(), Exposure(), demo)
    assert d.approved_amount == 1000 and "AMOUNT_LIMITED_BY_CAP" in d.flags


def test_headroom_exhausted(make_job, demo):
    d = decide(make_job(), Exposure(pilot_live_amount=500000), demo)
    assert d.route == "BLOCKED" and d.reasons[0].code == "CAP_REACHED"


def test_duplicate_job_declines(make_job, demo):
    assert decide(make_job(), Exposure(live_job_ids=("J1",)), demo).route == "DECLINE"


def test_missing_pdpa_blocked(make_job, demo, exposure):
    d = decide(make_job(pdpa_consent=False), exposure, demo)
    assert d.route == "BLOCKED" and d.approved_amount == 0


def test_adverse_declines(make_job, demo, exposure):
    assert decide(make_job(borrower_credit_flag="adverse"), exposure, demo).route == "DECLINE"


def test_template_mismatch_goes_manual(make_job, demo, exposure):
    d = decide(make_job(materials_list_match=0.5), exposure, demo)
    assert d.route == "RELEASE" and d.review_level == "manual"


def test_above_auto_limit_manual(make_job, demo, exposure):
    d = decide(make_job(materials_cost=10000, invoice_amount=10000, quote_total=30000,
                        deposit_amount=1000), exposure, demo)
    assert d.approved_amount == 9000 and d.review_level == "manual"
    assert d.tranches == [8000, 1000]


def test_variation_unsigned_manual(make_job, demo, exposure):
    d = decide(make_job(invoice_amount=6000), exposure, demo)
    assert d.approved_amount == 3000 and d.review_level == "manual"
    assert d.reasons[0].code == "VARIATION_UNSIGNED"


def test_live_limit(make_job, demo):
    assert decide(make_job(), Exposure(borrower_live_count=2), demo).route == "BLOCKED"


def test_supplier_not_on_panel(make_job, demo, exposure):
    assert decide(make_job(supplier_on_panel=False), exposure, demo).route == "BLOCKED"


def test_deposit_not_from_payer(make_job, demo, exposure):
    assert decide(make_job(deposit_from_payer_account=False), exposure, demo).route == "BLOCKED"


def test_null_config_names_keys(make_job, template, exposure):
    with pytest.raises(ConfigIncomplete) as e:
        decide(make_job(), exposure, template)
    assert "caps.per_bridge" in e.value.keys


def test_deterministic(make_job, demo, exposure):
    assert decide(make_job(), exposure, demo) == decide(make_job(), exposure, demo)


@pytest.mark.parametrize("status,route,code", [
    ("failed", "DECLINE", "KYC_FAILED"), ("pending", "BLOCKED", "KYC_NOT_VERIFIED"), (None, "BLOCKED", "KYC_NOT_VERIFIED")])
def test_kyc(make_job, demo, exposure, status, route, code):
    d = decide(make_job(borrower_kyc_status=status), exposure, demo)
    assert d.route == route and code in [r.code for r in d.reasons]


def test_screening(make_job, demo, exposure):
    assert decide(make_job(screening_result="true_match"), exposure, demo).route == "DECLINE"
    d = decide(make_job(screening_result="pep"), exposure, demo)
    assert d.route == "RELEASE" and d.review_level == "manual" and d.reasons[0].code == "SCREENING_REVIEW"
    assert decide(make_job(screening_result=None), exposure, demo).route == "BLOCKED"


def test_payer_identity(make_job, demo, exposure):
    d = decide(make_job(payer_identity_confirmed=None), exposure, demo)
    assert d.route == "BLOCKED" and d.reasons[0].code == "PAYER_ID_NOT_CONFIRMED"


def test_kyc_switch_off(make_job, demo, exposure):
    demo["release"]["require_kyc_verified"] = False
    demo["release"]["require_payer_identity_confirmed"] = False
    d = decide(make_job(borrower_kyc_status=None, payer_identity_confirmed=None), exposure, demo)
    assert d.route == "RELEASE"


def test_margin_of_advance_limits_amount(make_job, demo, exposure):
    demo["release"]["margin_of_advance"] = 0.5          # 50% of RM5,000 materials = RM2,500 < need RM3,000
    d = decide(make_job(), exposure, demo)
    assert d.approved_amount == 2500 and "AMOUNT_LIMITED_BY_MARGIN_OF_ADVANCE" in d.flags


def test_margin_of_advance_never_above_materials(make_job, demo, exposure):
    from self_employed_bridge.config import ConfigInvalid
    demo["release"]["margin_of_advance"] = 1.1
    with pytest.raises(ConfigInvalid):
        decide(make_job(), exposure, demo)


def test_advance_limit_is_shared_rule(demo):
    from self_employed_bridge.decide import advance_limit
    assert advance_limit(5000, 2000, demo) == (3000, 3000, "need")
    assert advance_limit(5000, 0, demo) == (4750, 5000, "margin_of_advance")   # demo MOA 0.95
