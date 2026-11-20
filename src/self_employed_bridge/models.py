"""Data model. Plain dataclasses, no behaviour."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Job:
    job_id: str
    borrower_id: str
    payer_id: Optional[str]
    payer_type: str
    payer_related_to_borrower: bool
    trade: str
    quote_total: float
    materials_cost: float
    materials_list_match: float          # 0 to 1
    deposit_amount: float
    deposit_from_payer_account: bool
    deposit_date: Optional[str]
    supplier_id: str
    supplier_on_panel: bool
    invoice_amount: float
    borrower_credit_flag: str            # ok | adverse | none
    borrower_trade_months: int
    borrower_completed_jobs: int
    pdpa_consent: bool
    sponsor_cohort: str
    variation_order_signed: Optional[bool] = None
    # KYC results from the financier's eKYC and screening provider. None means not done.
    borrower_kyc_status: Optional[str] = None        # verified | pending | failed
    screening_result: Optional[str] = None           # clear | possible_match | pep | true_match
    payer_identity_confirmed: Optional[bool] = None
    borrower_registered: Optional[bool] = None       # business registration on file

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: d[k] for k in names if k in d})


@dataclass(frozen=True)
class Exposure:
    """Snapshot of live exposure (RM) before this decision."""
    borrower_live_amount: float = 0.0
    borrower_live_count: int = 0
    supplier_live_amount: float = 0.0
    cohort_live_amount: float = 0.0
    pilot_live_amount: float = 0.0
    live_job_ids: tuple[str, ...] = ()   # needed for the one-live-bridge-per-job rule
    borrower_blocked: bool = False       # set by collections after a bypass
    borrower_prior_bridges: int = 0      # bridges released to this borrower before (0 = first bridge)
    borrower_clean_repayments: int = 0   # bridges repaid on time, for the step-up tiers
    cohort_known_bridges: int = 0        # loss trip wire: bridges in this cohort whose outcome is known
    cohort_loss_rate: float = 0.0        # loss so far as a share of the money lent on those bridges

    @classmethod
    def from_dict(cls, d: dict) -> "Exposure":
        d = dict(d)
        d["live_job_ids"] = tuple(d.get("live_job_ids", ()))
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass(frozen=True)
class Reason:
    code: str
    text: str


@dataclass
class Decision:
    route: str
    approved_amount: float = 0.0
    reasons: list[Reason] = field(default_factory=list)
    review_level: str = "manual"         # auto | manual
    flags: list[str] = field(default_factory=list)
    payee: Optional[str] = None          # always the supplier, never the borrower
    tranches: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class Bridge:
    """One row of the bridge outcome log."""
    bridge_id: str
    job_id: str
    released_date: str
    released_amount: float
    paid_supplier_directly: bool
    customer_paid_into_controlled_account: bool
    repaid_date: Optional[str]
    outcome: str                         # on_time late bypass dispute abandoned lost
    loss_amount: float
    cost_to_serve: float
    fee_charged: float
    quote_to_supplier_payment_hours: float
    sponsor_cohort: str = ""
    # Additionality (developmental pricing, A13). Recorded at release; None means not asked.
    new_to_formal_credit: Optional[bool] = None            # borrower had no formal credit before this bridge
    would_not_proceed_without_bridge: Optional[bool] = None  # borrower says the job would not have gone ahead
