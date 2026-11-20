import pytest

from self_employed_bridge import collections as col
from self_employed_bridge.collections import (LiveBridge, InvalidTransition, abandon, advance_days,
                                              blocked_borrowers, bypass, claim_file, dispute,
                                              dispute_borrower_at_fault, payment, should_chase, write_off)
from self_employed_bridge.config import ConfigIncomplete
from self_employed_bridge.decide import decide
from self_employed_bridge.models import Exposure


def bridge(**kw):
    return LiveBridge(**{"bridge_id": "BR1", "job_id": "J1", "borrower_id": "B1", "amount": 3000, **kw})


def codes(tasks):
    return [t.code for t in tasks]


def test_paid_on_time():
    b, t = payment(bridge(), 3000)
    assert b.state == "PAID_ON_TIME" and b.outstanding == 0 and t == []


def test_partial_payment_keeps_state():
    b, _ = payment(bridge(), 1000)
    assert b.state == "LIVE" and b.outstanding == 2000


def test_late_tasks_fire_on_the_right_day(demo):
    # demo: reminder 3, notice 14, escalate 30
    b, t = advance_days(bridge(), 2, demo)
    assert b.state == "LATE" and t == []
    b, t = advance_days(b, 3, demo)
    assert codes(t) == ["REMIND_PAYER"] and t[0].owner == "job source" and t[0].days_past_due == 3
    b, t = advance_days(b, 13, demo)
    assert t == []
    b, t = advance_days(b, 14, demo)
    assert codes(t) == ["SEND_NOTICE"] and t[0].owner == "financier"
    b, t = advance_days(b, 30, demo)
    assert codes(t) == ["ESCALATE"] and b.state == "RECOVERY"
    assert b.history == ("LIVE", "LATE", "RECOVERY")


def test_jump_fires_each_threshold_once(demo):
    b, t = advance_days(bridge(), 20, demo)
    assert codes(t) == ["REMIND_PAYER", "SEND_NOTICE"]
    b, t = advance_days(b, 25, demo)
    assert t == []


def test_late_then_paid_closes_paid_late(demo):
    b, _ = advance_days(bridge(), 5, demo)
    b, _ = payment(b, 3000)
    assert b.state == "PAID_LATE"


def test_bypass_blocks_new_bridges(make_job, demo):
    b, t = bypass(bridge())
    assert b.state == "RECOVERY" and b.history == ("LIVE", "BYPASS", "RECOVERY")
    assert {"HOLD_OTHER_BALANCES", "BLOCK_NEW_BRIDGES", "START_RECOVERY"} <= set(codes(t))
    blocked = blocked_borrowers([b, bridge(bridge_id="BR2", borrower_id="B2")])
    assert blocked == {"B1"}
    d = decide(make_job(job_id="J9"), Exposure(borrower_blocked="B1" in blocked), demo)
    assert d.route == "BLOCKED" and d.reasons[0].code == "BORROWER_BLOCKED"


def test_dispute_holds_part_and_assigns_job_source():
    b, t = dispute(bridge(), 1200)
    assert b.state == "DISPUTE" and b.held_amount == 1200
    assert all(x.owner == "job source" for x in t)
    b, t = dispute_borrower_at_fault(b)
    assert b.state == "RECOVERY"


def test_abandoned_asks_supplier_then_recovery():
    b, t = abandon(bridge())
    assert codes(t)[0] == "SUPPLIER_TAKE_BACK" and t[0].owner == "supplier"
    assert b.history == ("LIVE", "ABANDONED", "RECOVERY")


def test_supplier_credit_reduces_loss(demo):
    b, _ = abandon(bridge())
    b, _ = payment(b, 1000)          # credit for returned materials
    b, _ = write_off(b, demo)
    assert b.loss == 2000


def test_write_off_calls_waterfall_once(demo, monkeypatch):
    calls = []
    real = col.allocate_loss
    monkeypatch.setattr(col, "allocate_loss", lambda *a, **k: calls.append(a) or real(*a, **k))
    b, _ = advance_days(bridge(), 119, demo)
    assert calls == []
    b, t = advance_days(b, 120, demo)
    assert len(calls) == 1 and b.state == "WRITTEN_OFF" and "OPEN_CLAIM_FILE" in codes(t)
    assert sum(b.allocation.values()) == pytest.approx(3000)
    advance_days(b, 200, demo)       # closed: no second call
    assert len(calls) == 1


def test_write_off_uses_remaining_reserve(demo):
    b, _ = bypass(bridge())
    b, _ = write_off(b, demo, reserve_remaining=1000, guarantor_cap_remaining=500)
    assert b.allocation == {"first_loss": 1000, "guarantor": 500, "financier": 1500}


def test_invalid_transitions():
    b, _ = payment(bridge(), 3000)
    with pytest.raises(InvalidTransition):
        bypass(b)
    with pytest.raises(InvalidTransition):
        write_off(bridge(), {})


def test_clock_cannot_go_back(demo):
    b, _ = advance_days(bridge(), 10, demo)
    with pytest.raises(InvalidTransition):
        advance_days(b, 5, demo)


def test_null_collections_config_raises(template):
    with pytest.raises(ConfigIncomplete) as e:
        advance_days(bridge(), 1, template)
    assert "collections.write_off_after_days" in e.value.keys


def test_should_chase(demo, template):
    assert should_chase(500, 100)
    assert not should_chase(99, 100)
    demo["collections"]["min_expected_recovery_to_chase"] = 200
    assert not should_chase(150, 100, demo) and should_chase(250, 100, demo)
    with pytest.raises(ConfigIncomplete):
        should_chase(500, 100, template)


def test_claim_file_fills_and_lists_missing(demo):
    b, _ = advance_days(bridge(), 120, demo)
    f = claim_file(b, {"job_record": "JR-1", "supplier_invoice": "INV-1"})
    present = {i["item"]: i["present"] for i in f["items"]}
    assert present["notices_sent"] and present["recovery_steps"]
    assert f["missing"] == ["Controlled-account receipts"] and not f["complete"]


def test_no_task_asks_for_a_visit(demo):
    b, _ = advance_days(bridge(), 120, demo)
    for x in [bypass(bridge())[1], abandon(bridge())[1], dispute(bridge(), 1)[1], list(b.tasks)]:
        assert not any("visit" in t.text.lower() for t in x)
