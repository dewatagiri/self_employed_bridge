import copy
from pathlib import Path

import pytest

from self_employed_bridge.config import load_config
from self_employed_bridge.models import Exposure, Job

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def demo():
    return load_config(ROOT / "config" / "params.demo.yaml")


@pytest.fixture
def template():
    return load_config(ROOT / "config" / "params.template.yaml")


@pytest.fixture
def make_job():
    base = dict(job_id="J1", borrower_id="B1", payer_id="P1", payer_type="household",
                payer_related_to_borrower=False, trade="painter", quote_total=12000,
                materials_cost=5000, materials_list_match=0.9, deposit_amount=2000,
                deposit_from_payer_account=True, deposit_date="2026-11-01", supplier_id="S1",
                supplier_on_panel=True, invoice_amount=5000, borrower_credit_flag="ok",
                borrower_trade_months=24, borrower_completed_jobs=10, pdpa_consent=True,
                sponsor_cohort="C1", variation_order_signed=None)

    def _make(**kw):
        return Job(**{**copy.deepcopy(base), **kw})
    return _make


@pytest.fixture
def exposure():
    return Exposure()
