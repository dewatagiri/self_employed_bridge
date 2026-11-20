"""Release decision. Pure: same job, exposure and config give the same Decision.

Interpretations to confirm with the author (open item 1):
- need = max(0, materials_cost - deposit_amount * deposit_to_materials_share)
- approved = min(need, materials_cost, invoice_amount, per_bridge, every cap headroom)
- Never above the quoted materials cost, even when a variation order is signed.
- Hard-check failures give DECLINE (adverse record, related payer, duplicate job) or BLOCKED.
  A template mismatch is not a block: the bridge goes to manual review.
"""
from __future__ import annotations

from .config import DECIDE_REQUIRED, get, require
from .models import Decision, Exposure, Job, Reason
from .screen import screen


def decide(job: Job, exposure: Exposure, cfg: dict) -> Decision:
    require(cfg, DECIDE_REQUIRED)
    sc = screen(job, cfg)
    if sc.route != "BRIDGE_CANDIDATE":
        return sc

    declines: list[Reason] = []
    blocks: list[Reason] = []
    manual: list[Reason] = []
    flags: list[str] = []

    # Identity and credit record.
    if get(cfg, "borrower.require_credit_bureau_check") and job.borrower_credit_flag == "none":
        blocks.append(Reason("NO_CREDIT_CHECK", "No credit bureau check on file."))
    if job.borrower_credit_flag == "adverse" and get(cfg, "borrower.decline_on_adverse_record"):
        declines.append(Reason("ADVERSE_RECORD", "Adverse credit record."))
    # Trade record: months in trade OR completed jobs.
    mn = get(cfg, "borrower.min_trade_months_or_jobs")
    if max(job.borrower_trade_months, job.borrower_completed_jobs) < mn:
        blocks.append(Reason("TRADE_RECORD_SHORT", f"Trade record below the minimum of {mn}."))
    if get(cfg, "release.require_payer_not_related") and job.payer_related_to_borrower:
        declines.append(Reason("RELATED_PAYER", "Payer is related to the borrower."))
    if get(cfg, "release.require_deposit_from_payer_account") and not job.deposit_from_payer_account:
        blocks.append(Reason("DEPOSIT_NOT_FROM_PAYER", "Deposit did not come from the payer's own account."))
    if get(cfg, "release.require_pdpa_consent") and not job.pdpa_consent:
        blocks.append(Reason("NO_PDPA_CONSENT", "No PDPA consent."))
    if not job.supplier_on_panel:
        blocks.append(Reason("SUPPLIER_NOT_ON_PANEL", "Supplier is not on the approved panel."))
    if job.job_id in exposure.live_job_ids:
        declines.append(Reason("DUPLICATE_JOB", "A live bridge already exists for this job_id."))
    if exposure.borrower_live_count >= get(cfg, "caps.max_live_bridges_per_borrower"):
        blocks.append(Reason("LIVE_LIMIT", "Borrower is at the live-bridge limit."))
    if job.materials_list_match < get(cfg, "release.template_match_min"):
        manual.append(Reason("TEMPLATE_MISMATCH", "Invoice does not match the trade template."))

    # Variation order: anything above the quoted materials cost needs a signed change.
    if job.invoice_amount > job.materials_cost:
        if job.variation_order_signed is True:
            flags.append("VARIATION_SIGNED_EXTRA_NOT_BRIDGED")
        else:
            manual.append(Reason("VARIATION_UNSIGNED",
                f"Invoice exceeds quoted materials by RM{job.invoice_amount - job.materials_cost:,.2f}; "
                "extra blocked until the payer signs a change."))

    # Amount.
    share = get(cfg, "screen.deposit_to_materials_share")
    need = max(0.0, job.materials_cost - job.deposit_amount * share)
    headrooms = {
        "caps.per_borrower_live": get(cfg, "caps.per_borrower_live") - exposure.borrower_live_amount,
        "caps.per_supplier_live": get(cfg, "caps.per_supplier_live") - exposure.supplier_live_amount,
        "caps.per_sponsor_cohort": get(cfg, "caps.per_sponsor_cohort") - exposure.cohort_live_amount,
        "caps.pilot_total": get(cfg, "caps.pilot_total") - exposure.pilot_live_amount,
    }
    amount = min(need, job.materials_cost, job.invoice_amount,
                 get(cfg, "caps.per_bridge"), *headrooms.values())
    amount = max(0.0, amount)
    if amount <= 0 and need > 0:
        full = [k for k, v in headrooms.items() if v <= 0]
        blocks.append(Reason("CAP_REACHED", "No headroom under: " + ", ".join(full or ["caps.per_bridge"])))
    elif amount < need:
        flags.append("AMOUNT_LIMITED_BY_CAP")

    if declines:
        return Decision("DECLINE", reasons=declines + blocks, flags=flags)
    if blocks:
        return Decision("BLOCKED", reasons=blocks, flags=flags)

    auto = (not manual and amount <= get(cfg, "release.auto_approve_max_amount"))
    if not auto and not manual:
        manual.append(Reason("ABOVE_AUTO_LIMIT", "Amount is above the auto-approve limit."))
    step = get(cfg, "tenor.two_step_release_over_amount")
    tranches = [step, amount - step] if amount > step else [amount]
    return Decision("RELEASE", approved_amount=amount, review_level="auto" if auto else "manual",
                    reasons=manual or [Reason("ALL_CHECKS_PASSED", "All checks passed.")],
                    flags=flags, payee=job.supplier_id, tranches=tranches)
