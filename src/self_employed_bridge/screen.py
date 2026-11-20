"""The four screening questions. Pure. Order matters; stops at the first failure."""
from __future__ import annotations

from .config import SCREEN_REQUIRED, get, require
from .models import Decision, Job, Reason


def screen(job: Job, cfg: dict) -> Decision:
    require(cfg, SCREEN_REQUIRED)

    # Q1: confirmed job with a named payer who is not the borrower.
    if not job.payer_id or job.payer_id == job.borrower_id:
        return Decision("REFER_GENERAL", reasons=[Reason(
            "NO_CONFIRMED_JOB", "No confirmed job with a named payer other than the borrower.")])
    if job.payer_related_to_borrower:
        return Decision("DECLINE", reasons=[Reason(
            "RELATED_PAYER", "Payer is related to the borrower.")])

    # Q2: main cost is a purchasable input.
    min_share = get(cfg, "screen.min_materials_share_of_quote")
    share = job.materials_cost / job.quote_total if job.quote_total else 0.0
    if share < min_share:
        return Decision("REFER_GENERAL", reasons=[Reason(
            "COST_NOT_MATERIALS",
            f"Materials are {share:.0%} of the quote, below the {min_share:.0%} setting.")])

    # Q3: payer type.
    if job.payer_type in get(cfg, "screen.refer_contract_payer_types", []):
        return Decision("REFER_CONTRACT_INVOICE", reasons=[Reason(
            "CONTRACT_PAYER", f"Payer type '{job.payer_type}' goes to contract or invoice financing.")])
    if job.payer_type not in get(cfg, "screen.allowed_payer_types", []):
        return Decision("REFER_GENERAL", reasons=[Reason(
            "PAYER_TYPE_NOT_ALLOWED", f"Payer type '{job.payer_type}' is not in the allowed list.")])

    # Q4: deposit below materials cost.
    if job.deposit_amount >= job.materials_cost:
        return Decision("NO_BRIDGE_NEEDED", reasons=[Reason(
            "DEPOSIT_COVERS_MATERIALS", "Deposit already covers the materials cost.")])

    return Decision("BRIDGE_CANDIDATE", reasons=[Reason(
        "PASSED_SCREEN", "All four screening questions passed.")])
