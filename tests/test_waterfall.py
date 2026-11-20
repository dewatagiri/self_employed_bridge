from self_employed_bridge.waterfall import allocate_loss, allocate_pool


def test_guarantor_on():
    r = allocate_loss(10000, 4000, 0.5, 2000, True)
    assert r == {"first_loss": 4000, "guarantor": 2000, "financier": 4000}


def test_guarantor_off():
    r = allocate_loss(10000, 4000, 0.5, 2000, False)
    assert r == {"first_loss": 4000, "guarantor": 0, "financier": 6000}


def test_loss_below_reserve():
    r = allocate_loss(3000, 4000, 0.5, 2000, True)
    assert r == {"first_loss": 3000, "guarantor": 0, "financier": 0}


def test_pool_shares_reserve_and_conserves():
    r = allocate_pool([3000, 3000, 4000], 4000, 0.5, 2000, True)
    assert [e["reserve_after"] for e in r["events"]] == [1000, 0, 0]
    assert sum(r["total"].values()) == 10000
    assert r["total"]["first_loss"] == 4000
    assert r["total"]["guarantor"] == 2000  # cap shared across the cohort
