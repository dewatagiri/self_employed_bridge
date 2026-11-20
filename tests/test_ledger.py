import pytest

from self_employed_bridge import collections as col
from self_employed_bridge import ledger
from self_employed_bridge.collections import LiveBridge


def rec(bid, borrower="B1", supplier="S1", cohort="C1", amount=3000, job=None, **live):
    return {"bridge_id": bid, "job_id": job or f"J{bid}", "borrower_id": borrower, "supplier_id": supplier,
            "cohort": cohort, "released_date": "2026-11-01", "closed_date": None, "quote_hours": 3.0,
            "supplier_paid_directly": True, "fee": 60, "cost": 25,
            "live": LiveBridge(bid, job or f"J{bid}", borrower, amount, **live)}


def test_exposure_counts_only_open_bridges():
    paid = rec("1"); paid["live"], _ = col.payment(paid["live"], 3000)
    recs = [paid, rec("2", amount=2000), rec("3", borrower="B2", supplier="S2", cohort="C2", amount=1000)]
    e = ledger.exposure_for("B1", "S1", "C1", recs)
    assert e.borrower_live_amount == 2000 and e.borrower_live_count == 1
    assert e.supplier_live_amount == 2000 and e.cohort_live_amount == 2000 and e.pilot_live_amount == 3000
    assert set(e.live_job_ids) == {"J2", "J3"}
    assert e.borrower_prior_bridges == 2 and e.borrower_clean_repayments == 1 and not e.borrower_blocked


def test_bypass_blocks_in_exposure():
    r = rec("1"); r["live"], _ = col.bypass(r["live"])
    assert ledger.exposure_for("B1", "S1", "C1", [r]).borrower_blocked


def test_layers_left_per_cohort_and_programme(demo):
    a = rec("1", amount=12000); a["live"], _ = col.bypass(a["live"]); a["live"], _ = col.write_off(a["live"], demo)
    b = rec("2", cohort="C2")
    left_c1 = ledger.layers_left("C1", [a, b], demo)
    assert left_c1["reserve_remaining"] == 0                     # 10,000 reserve used up in C1
    assert left_c1["guarantor_cap_remaining"] == 4000            # 50% of 2,000 drawn from the programme cap
    assert ledger.layers_left("C2", [a, b], demo)["reserve_remaining"] == 10000


@pytest.mark.parametrize("steps,expected", [
    (lambda b: col.payment(b, 3000), "on_time"),
    (lambda b: col.payment(col.advance_days(b, 5, CFG)[0], 3000), "late"),
    (lambda b: col.payment(col.bypass(b)[0], 3000), "bypass"),
    (lambda b: col.write_off(col.abandon(b)[0], CFG), "abandoned"),
    (lambda b: col.advance_days(b, 120, CFG), "lost"),
])
def test_outcomes_for_the_log(steps, expected):
    r = rec("1")
    r["live"], _ = steps(r["live"])
    assert ledger.outcome(r) == expected
    row = ledger.log_rows([r])[0]
    assert row.outcome == expected and row.customer_paid_into_controlled_account == (expected in ("on_time", "late"))


def test_open_bridges_not_in_log():
    assert ledger.log_rows([rec("1")]) == []


from tests.conftest import ROOT  # noqa: E402
from self_employed_bridge.config import load_config  # noqa: E402
CFG = load_config(ROOT / "config" / "params.demo.yaml")
