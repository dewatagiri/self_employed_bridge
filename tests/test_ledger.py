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


# ---- loss trip wire in live use (A14) ----

def _wire(demo, line=0.05, min_n=2):
    c = __import__("copy").deepcopy(demo)
    c["stop_lines"].update(pause_if_loss_rate_over=line, loss_rate_min_bridges=min_n, outcome_lag_bridges=0)
    return c


def test_cohort_loss_counts_only_known_outcomes(demo):
    live = rec("1", amount=3000)                                   # still out and paying: not known
    paid = rec("2", amount=3000); paid["live"], _ = col.payment(paid["live"], 3000)
    bad = rec("3", amount=3000); bad["live"], _ = col.bypass(bad["live"])                    # in recovery: full balance counts
    gone = rec("4", amount=3000); gone["live"], _ = col.abandon(gone["live"]); gone["live"], _ = col.payment(gone["live"], 1000)
    gone["live"], _ = col.write_off(gone["live"], demo)                                       # written off: RM2,000 lost
    st = ledger.cohort_loss_status("C1", [live, paid, bad, gone])
    assert st["known"] == 3 and st["lent"] == 9000 and st["loss"] == pytest.approx(3000 + 2000)
    assert st["rate"] == pytest.approx(5000 / 9000)
    assert ledger.cohort_loss_status("C2", [live, paid, bad, gone])["known"] == 0


def test_trip_wire_status_and_off_by_default(demo):
    paid = rec("1"); paid["live"], _ = col.payment(paid["live"], 3000)
    bad = rec("2"); bad["live"], _ = col.bypass(bad["live"])
    assert ledger.trip_wire_status(demo, [paid, bad]) == []                  # demo has it off
    on = ledger.trip_wire_status(_wire(demo, 0.05, 2), [paid, bad])
    assert on[0]["tripped"] and on[0]["rate"] == pytest.approx(0.5)
    assert not ledger.trip_wire_status(_wire(demo, 0.60, 2), [paid, bad])[0]["tripped"]   # under the line
    assert not ledger.trip_wire_status(_wire(demo, 0.05, 3), [paid, bad])[0]["tripped"]   # too few known bridges


def test_exposure_carries_the_cohort_loss(demo):
    paid = rec("1"); paid["live"], _ = col.payment(paid["live"], 3000)
    bad = rec("2"); bad["live"], _ = col.bypass(bad["live"])
    e = ledger.exposure_for("B9", "S9", "C1", [paid, bad])
    assert e.cohort_known_bridges == 2 and e.cohort_loss_rate == pytest.approx(0.5)
