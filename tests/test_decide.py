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


def test_variation_signed_at_release_raises_materials(make_job, demo, exposure):
    d = decide(make_job(invoice_amount=6500, variation_order_signed=True), exposure, demo)
    assert d.approved_amount == 4500 and d.review_level == "manual"      # 6,500 - 2,000 deposit
    assert d.reasons[0].code == "VARIATION_SIGNED" and d.payee == "S1"


def test_variation_top_up_on_live_bridge(make_job, demo):
    from self_employed_bridge.decide import decide_variation
    live = Exposure(borrower_live_amount=3000, borrower_live_count=1, supplier_live_amount=3000,
                    cohort_live_amount=3000, pilot_live_amount=3000, live_job_ids=("J1",))
    job = make_job(invoice_amount=6500, variation_order_signed=True)
    d = decide_variation(job, 3000, live, demo)
    assert d.route == "RELEASE_VARIATION" and d.approved_amount == 1500
    assert d.review_level == "manual" and d.payee == "S1"
    assert decide_variation(make_job(invoice_amount=6500), 3000, live, demo).route == "BLOCKED"
    assert decide_variation(job, 3000, Exposure(borrower_blocked=True), demo).route == "BLOCKED"
    assert decide_variation(make_job(variation_order_signed=True), 3000, live, demo).route == "NO_TOP_UP_NEEDED"


def test_variation_top_up_respects_caps(make_job, demo):
    from self_employed_bridge.decide import decide_variation
    demo["caps"]["per_bridge"] = 4000                     # total bridge never above RM4,000
    job = make_job(invoice_amount=6500, variation_order_signed=True)
    d = decide_variation(job, 3000, Exposure(borrower_live_amount=3000), demo)
    assert d.approved_amount == 1000 and "AMOUNT_LIMITED_BY_CAP" in d.flags
    d = decide_variation(job, 3000, Exposure(borrower_live_amount=14500), demo)
    assert d.approved_amount == 500                         # borrower cap RM15,000


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


def test_deposit_share_out_of_range_refused(make_job, demo, exposure):
    from self_employed_bridge.config import ConfigInvalid
    demo["screen"]["deposit_to_materials_share"] = 1.5     # would make need 0 and release RM0
    with pytest.raises(ConfigInvalid):
        decide(make_job(), exposure, demo)


def test_invoice_limit_flagged_as_invoice(make_job, demo, exposure):
    d = decide(make_job(invoice_amount=2000), exposure, demo)
    assert d.approved_amount == 2000
    assert "AMOUNT_LIMITED_BY_INVOICE" in d.flags and "AMOUNT_LIMITED_BY_CAP" not in d.flags


def test_headroom_limit_flagged_as_cap(make_job, demo):
    d = decide(make_job(), Exposure(borrower_live_amount=14000), demo)
    assert d.approved_amount == 1000 and "AMOUNT_LIMITED_BY_CAP" in d.flags


# ---- author decision A11: registration waiver and step-up tiers ----

def test_unregistered_first_bridge_over_waiver_blocked(make_job, demo, exposure):
    d = decide(make_job(borrower_registered=None), exposure, demo)          # RM3,000 > demo waiver RM2,000
    assert d.route == "BLOCKED" and d.reasons[0].code == "REGISTRATION_REQUIRED"


def test_small_first_bridge_waives_registration(make_job, demo, exposure):
    d = decide(make_job(borrower_registered=False, deposit_amount=3500), exposure, demo)   # bridge RM1,500
    assert d.route == "RELEASE" and "REGISTRATION_WAIVED_FIRST_BRIDGE" in d.flags


def test_waiver_only_for_first_bridge(make_job, demo):
    d = decide(make_job(borrower_registered=False, deposit_amount=3500), Exposure(borrower_prior_bridges=1), demo)
    assert d.route == "BLOCKED" and "only a first bridge" in d.reasons[0].text


def test_no_waiver_when_null(make_job, demo, exposure):
    demo["release"]["registration_waiver_first_bridge_max"] = None
    assert decide(make_job(borrower_registered=False, deposit_amount=3500), exposure, demo).route == "BLOCKED"
    demo["release"]["require_registration"] = False
    assert decide(make_job(borrower_registered=False), exposure, demo).route == "RELEASE"


def test_step_up_raises_live_limit(make_job, demo):
    assert decide(make_job(), Exposure(borrower_live_count=2), demo).route == "BLOCKED"          # base limit 2
    d = decide(make_job(), Exposure(borrower_live_count=2, borrower_clean_repayments=3), demo)
    assert d.route == "RELEASE" and "STEP_UP_TIER_1" in d.flags


def test_step_up_raises_borrower_cap(make_job, demo):
    assert decide(make_job(), Exposure(borrower_live_amount=14000), demo).approved_amount == 1000
    d = decide(make_job(), Exposure(borrower_live_amount=14000, borrower_clean_repayments=8), demo)
    assert d.approved_amount == 3000 and "STEP_UP_TIER_2" in d.flags


def test_step_up_tiers_cannot_lower_limits(make_job, demo, exposure):
    from self_employed_bridge.config import ConfigInvalid
    demo["caps"]["step_up_tiers"][0]["per_borrower_live"] = 1000
    with pytest.raises(ConfigInvalid):
        decide(make_job(), exposure, demo)


def test_no_step_up_when_null(make_job, demo):
    demo["caps"]["step_up_tiers"] = None
    assert decide(make_job(), Exposure(borrower_live_count=2, borrower_clean_repayments=50), demo).route == "BLOCKED"
