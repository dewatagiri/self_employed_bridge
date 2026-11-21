import pytest

from self_employed_bridge.compliance import (ConsentError, check_export_consent,
                                             controlled_account_flag, effective_annual_rate,
                                             moneylender_check)
from self_employed_bridge.config import ConfigIncomplete


def test_effective_rate():
    assert effective_annual_rate(60, 3000, 30) == pytest.approx(0.2433, abs=1e-4)


def test_moneylender_breach(demo):
    demo["financier"]["type"] = "licensed_moneylender"
    assert moneylender_check(60, 3000, 30, demo)["flag"] == "MONEYLENDER_CAP_BREACH"
    assert moneylender_check(10, 3000, 30, demo)["flag"] == "OK"


def test_template_financier_is_dfi(template):
    assert moneylender_check(60, 3000, 30, template)["flag"] == "CHECK_REQUIRED"


def test_other_types_check_required(demo):
    assert moneylender_check(60, 3000, 30, demo)["flag"] == "CHECK_REQUIRED"


def test_type_null_raises(template):
    template["financier"]["type"] = None
    with pytest.raises(ConfigIncomplete):
        moneylender_check(60, 3000, 30, template)


def test_standing_flag():
    assert "central-bank" in controlled_account_flag()["message"]


def test_export_needs_consent(make_job):
    check_export_consent(make_job())
    with pytest.raises(ConsentError):
        check_export_consent(make_job(pdpa_consent=False))


def test_legal_confirmation_is_shown_as_such(demo):
    assert controlled_account_flag(demo)["flag"] == "OPEN_ITEM" and "central-bank" in controlled_account_flag(demo)["message"]
    demo["compliance"]["controlled_account_legal_status"] = "confirmed"
    f = controlled_account_flag(demo)
    assert f["flag"] == "CONFIRMED_BY_LEGAL" and "written advice" in f["message"]
    assert controlled_account_flag()["flag"] == "OPEN_ITEM"                 # no config: still an open item


def test_all_in_cap_confirmation_for_a_dfi(demo):
    assert moneylender_check(60, 3000, 30, demo)["flag"] == "CHECK_REQUIRED"
    demo["compliance"]["all_in_cap_legal_status"] = "confirmed"
    assert moneylender_check(60, 3000, 30, demo)["flag"] == "CONFIRMED_BY_LEGAL"
    demo["financier"]["type"] = "licensed_moneylender"                      # a confirmation for a DFI does not excuse a moneylender
    assert moneylender_check(60, 3000, 30, demo)["flag"] == "MONEYLENDER_CAP_BREACH"
