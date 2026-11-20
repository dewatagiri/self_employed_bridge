import pytest

from self_employed_bridge import gates as g
from tests.conftest import ROOT

LOG, JOBS = str(ROOT / "data" / "sample_log.csv"), str(ROOT / "data" / "sample_jobs.csv")


@pytest.fixture
def log():
    rows, synthetic = g.read_log(LOG)
    assert synthetic
    return rows


@pytest.fixture
def jobs():
    return g.read_jobs(JOBS)[0]


def test_sample_files_have_40_rows(log, jobs):
    assert len(log) == 40 and len(jobs) == 40
    assert isinstance(log[0].paid_supplier_directly, bool) and isinstance(log[0].released_amount, float)


def test_all_null_thresholds_give_no_threshold_set(log, jobs, template):
    res = g.score(log, template, jobs)
    assert [r.status for r in res["gates"]] == ["NO_THRESHOLD_SET"] * 5
    assert all(r.value is not None for r in res["gates"])   # values are still computed


def test_values_match_hand_count(log, jobs, demo):
    res = {r.gate: r for r in g.score(log, demo, jobs)["gates"]}
    n = len(log)
    both = sum(b.paid_supplier_directly and b.customer_paid_into_controlled_account for b in log)
    assert res[1].value == pytest.approx(both / n)
    assert res[2].detail["bypass_count"] == 2
    assert res[2].checks[1].value == pytest.approx(2 / 40)
    loss = sum(b.loss_amount for b in log)
    assert res[2].checks[2].value == pytest.approx(loss / 10000)
    fee = 60 * 40
    cost = sum(b.cost_to_serve for b in log)
    assert res[3].value == pytest.approx(fee / (cost + loss))
    confirmed = [j for j in jobs if j.payer_id != j.borrower_id]
    assert res[0].value == pytest.approx(sum(j.deposit_amount < j.materials_cost for j in confirmed) / len(confirmed))


def test_thresholds_pass_and_fail(log, demo):
    demo["gates"].update(gate1_min_share=0.5, gate2_min_on_time_share=0.5,
                         gate2_max_bypass_rate=0.10, gate2_max_loss_to_reserve=10.0)
    res = {r.gate: r for r in g.score(log, demo)["gates"]}
    assert res[1].status == "PASS" and res[2].status == "PASS"
    demo["gates"]["gate2_max_bypass_rate"] = 0.01
    res = {r.gate: r for r in g.score(log, demo)["gates"]}
    assert res[2].status == "FAIL" and res[2].checks[1].status == "FAIL"


def test_gate0_without_jobs(log, demo):
    demo["gates"]["gate0_min_share"] = 0.5
    r = g.score(log, demo)["gates"][0]
    assert r.value is None and r.status == "NO_DATA"


def test_overall_loss_uses_one_reserve_per_cohort(log, demo):
    res = g.score_by_cohort(log, demo)
    loss = sum(b.loss_amount for b in log)
    assert res["overall"]["measures"]["loss_to_reserve"] == pytest.approx(loss / 20000)
    c1 = [b for b in log if b.sponsor_cohort == "C1"]
    assert res["cohorts"]["C1"]["measures"]["loss_to_reserve"] == pytest.approx(sum(b.loss_amount for b in c1) / 10000)


def test_second_cohort_rule(log, demo, template):
    res = g.score_by_cohort(log, template)
    assert set(res["cohorts"]) == {"C1", "C2"}
    allowed, reason = res["next_cohort"]["C2"]
    assert not allowed and "NO_THRESHOLD_SET" in reason
    demo["gates"].update(gate1_min_share=0.5, gate2_min_on_time_share=0.5,
                         gate2_max_bypass_rate=0.10, gate2_max_loss_to_reserve=10.0)
    assert g.score_by_cohort(log, demo)["next_cohort"]["C2"][0]


def test_measures(log, demo):
    m = g.measures(log, demo)
    assert m["bridges"] == 40 and m["customers_bypassed"] == 2
    assert m["jobs_completed"] == 39
    assert 0 <= m["share_within_target_hours"] <= 1


def test_measures_on_time_matches_gate2(log, demo):
    from dataclasses import replace
    # an on-time row whose payment did not reach the controlled account must not count in either place
    rows = [replace(log[0], outcome="on_time", customer_paid_into_controlled_account=False)] + log[1:]
    gate2 = g.gate2(rows, demo).checks[0].value
    assert g.measures(rows, demo)["on_time_share"] == pytest.approx(gate2)


# ---- additionality (developmental pricing, A13) ----

def test_additionality_hand_count(log, demo):
    g4 = g.gate4(log, demo)
    asked = [b for b in log if b.new_to_formal_credit is not None]
    assert len(asked) == 40
    assert g4.value == pytest.approx(sum(b.new_to_formal_credit for b in asked) / 40)
    both = [b for b in log if b.new_to_formal_credit and b.would_not_proceed_without_bridge]
    assert g4.detail["fully_additional_borrowers"] == len(both)
    net = sum(b.fee_charged - b.cost_to_serve - b.loss_amount for b in log)
    assert g4.detail["programme_net_total"] == pytest.approx(net)
    if net < 0 and both:
        assert g4.detail["cost_per_fully_additional_borrower"] == pytest.approx(-net / len(both))


def test_additionality_not_asked_is_not_zero(log, demo):
    from dataclasses import replace
    rows = [replace(b, new_to_formal_credit=None, would_not_proceed_without_bridge=None) for b in log]
    g4 = g.gate4(rows, demo)
    assert g4.value is None and g4.detail["asked_new_to_credit"] == 0
    assert g4.detail["cost_per_fully_additional_borrower"] is None


def test_additionality_threshold(log, demo):
    demo["gates"]["gate4_min_new_to_credit_share"] = 0.0
    demo["gates"]["gate4_min_job_needed_share"] = 0.0
    assert g.gate4(log, demo).status == "PASS"
    demo["gates"]["gate4_min_new_to_credit_share"] = 1.01
    assert g.gate4(log, demo).status == "FAIL"


def test_gate4_does_not_change_cohort_rule(log, template):
    res = g.score_by_cohort(log, template)
    assert not res["next_cohort"]["C2"][0]
