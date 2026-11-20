"""Release decision. Pure: same job, exposure and config give the same Decision.

Interpretations to confirm with the author (open item 1):
- need = max(0, materials_cost - deposit_amount * deposit_to_materials_share)
- approved = min(need, materials_cost, invoice_amount, per_bridge, every cap headroom)
- Never above the materials cost. A variation order signed by the payer raises that cost to the
  varied total (author decision A5); an unsigned one does not. Either way a named officer reviews it.
- margin_of_advance caps the bridge at that share of the quoted materials cost (at most 1.0).
- KYC: the engine reads the provider's results; it does not verify identity itself.
- Hard-check failures give DECLINE (adverse record, related payer, duplicate job) or BLOCKED.
  A template mismatch is not a block: the bridge goes to manual review.
"""
from __future__ import annotations

from .config import DECIDE_REQUIRED, ConfigInvalid, get, require
from .models import Decision, Exposure, Job, Reason
from .screen import screen


def advance_limit(materials_cost: float, deposit_amount: float, cfg: dict) -> tuple[float, float, str]:
    """Bridge amount before exposure caps: (amount, need, binding_limit).

    need   = max(0, materials - deposit * deposit_to_materials_share)
    amount = min(need, margin_of_advance * materials, per_bridge cap)
    Used by `decide` and by the simulator, so both apply the same rule.
    """
    require(cfg, ["screen.deposit_to_materials_share", "release.margin_of_advance", "caps.per_bridge"])
    share = get(cfg, "screen.deposit_to_materials_share")
    if not 0 <= share <= 1.0:
        raise ConfigInvalid(f"screen.deposit_to_materials_share must be in [0, 1]; got {share}.")
    moa = get(cfg, "release.margin_of_advance")
    if not 0 < moa <= 1.0:
        raise ConfigInvalid(f"release.margin_of_advance must be in (0, 1]; got {moa}. "
                            "The bridge is never above the materials cost.")
    need = max(0.0, materials_cost - deposit_amount * share)
    limits = {"need": need, "margin_of_advance": moa * materials_cost, "caps.per_bridge": get(cfg, "caps.per_bridge")}
    binding = min(limits, key=limits.get)
    return limits[binding], need, binding


def decide(job: Job, exposure: Exposure, cfg: dict) -> Decision:
    require(cfg, DECIDE_REQUIRED)
    sc = screen(job, cfg)
    if sc.route != "BRIDGE_CANDIDATE":
        return sc

    declines: list[Reason] = []
    blocks: list[Reason] = []
    manual: list[Reason] = []
    flags: list[str] = []

    # Identity (KYC results from the provider) and credit record.
    if get(cfg, "release.require_kyc_verified"):
        if job.borrower_kyc_status == "failed":
            declines.append(Reason("KYC_FAILED", "Borrower identity verification failed."))
        elif job.borrower_kyc_status != "verified":
            blocks.append(Reason("KYC_NOT_VERIFIED", "Borrower identity is not yet verified."))
    if job.screening_result == "true_match" and get(cfg, "borrower.decline_on_screening_true_match"):
        declines.append(Reason("SCREENING_TRUE_MATCH", "Financial-crime screening returned a true match."))
    elif job.screening_result in ("possible_match", "pep"):
        manual.append(Reason("SCREENING_REVIEW", f"Screening result '{job.screening_result}': "
                             "enhanced due diligence by a named officer."))
    elif job.screening_result not in ("clear", "true_match"):
        blocks.append(Reason("SCREENING_NOT_DONE", "No financial-crime screening result."))
    if get(cfg, "release.require_payer_identity_confirmed") and job.payer_identity_confirmed is not True:
        blocks.append(Reason("PAYER_ID_NOT_CONFIRMED", "Payer identity is not confirmed."))
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
    if exposure.borrower_blocked:
        blocks.append(Reason("BORROWER_BLOCKED", "New bridges are blocked for this borrower after a bypass."))
    if job.job_id in exposure.live_job_ids:
        declines.append(Reason("DUPLICATE_JOB", "A live bridge already exists for this job_id."))
    if exposure.borrower_live_count >= get(cfg, "caps.max_live_bridges_per_borrower"):
        blocks.append(Reason("LIVE_LIMIT", "Borrower is at the live-bridge limit."))
    if job.materials_list_match < get(cfg, "release.template_match_min"):
        manual.append(Reason("TEMPLATE_MISMATCH", "Invoice does not match the trade template."))

    # Variation order: anything above the quoted materials cost needs the payer's signed change.
    materials = job.materials_cost
    if job.invoice_amount > job.materials_cost:
        if job.variation_order_signed is True:
            materials = job.invoice_amount            # the varied materials total
            manual.append(Reason("VARIATION_SIGNED",
                f"Payer signed a variation: materials RM{job.materials_cost:,.2f} -> RM{materials:,.2f}."))
        else:
            manual.append(Reason("VARIATION_UNSIGNED",
                f"Invoice exceeds quoted materials by RM{job.invoice_amount - job.materials_cost:,.2f}; "
                "extra blocked until the payer signs a change."))

    # Amount.
    base, need, binding = advance_limit(materials, job.deposit_amount, cfg)
    if binding == "margin_of_advance":
        flags.append("AMOUNT_LIMITED_BY_MARGIN_OF_ADVANCE")
    headrooms = {
        "caps.per_borrower_live": get(cfg, "caps.per_borrower_live") - exposure.borrower_live_amount,
        "caps.per_supplier_live": get(cfg, "caps.per_supplier_live") - exposure.supplier_live_amount,
        "caps.per_sponsor_cohort": get(cfg, "caps.per_sponsor_cohort") - exposure.cohort_live_amount,
        "caps.pilot_total": get(cfg, "caps.pilot_total") - exposure.pilot_live_amount,
    }
    amount = min(base, materials, job.invoice_amount, *headrooms.values())
    amount = max(0.0, amount)
    if amount <= 0 and need > 0:
        full = [k for k, v in headrooms.items() if v <= 0]
        blocks.append(Reason("CAP_REACHED", "No headroom under: " + ", ".join(full or ["caps.per_bridge"])))
    else:
        if binding == "caps.per_bridge" or any(amount == v and v < base for v in headrooms.values()):
            flags.append("AMOUNT_LIMITED_BY_CAP")
        if job.invoice_amount < base and amount == job.invoice_amount:
            flags.append("AMOUNT_LIMITED_BY_INVOICE")

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


def decide_variation(job: Job, already_released: float, exposure: Exposure, cfg: dict) -> Decision:
    """Top-up on a live bridge after the payer signs a variation order (author decision A5).

    `job` carries the varied materials total in `invoice_amount`. `exposure` already includes the
    live bridge. The top-up is the new bridge size minus what was released, within every cap, paid
    to the supplier, and always reviewed by a named officer.
    """
    require(cfg, DECIDE_REQUIRED)
    if exposure.borrower_blocked:
        return Decision("BLOCKED", reasons=[Reason("BORROWER_BLOCKED", "New releases are blocked for this borrower.")])
    if job.variation_order_signed is not True:
        return Decision("BLOCKED", reasons=[Reason("VARIATION_UNSIGNED", "The payer has not signed the variation order.")])
    if job.invoice_amount <= job.materials_cost:
        return Decision("NO_TOP_UP_NEEDED", reasons=[Reason("NO_EXTRA_MATERIALS",
                        "The variation does not raise the materials cost.")])
    base, _, binding = advance_limit(job.invoice_amount, job.deposit_amount, cfg)
    extra = base - already_released
    headrooms = {
        "caps.per_borrower_live": get(cfg, "caps.per_borrower_live") - exposure.borrower_live_amount,
        "caps.per_supplier_live": get(cfg, "caps.per_supplier_live") - exposure.supplier_live_amount,
        "caps.per_sponsor_cohort": get(cfg, "caps.per_sponsor_cohort") - exposure.cohort_live_amount,
        "caps.pilot_total": get(cfg, "caps.pilot_total") - exposure.pilot_live_amount,
    }
    amount = max(0.0, min(extra, *headrooms.values()))
    if extra <= 0:
        return Decision("NO_TOP_UP_NEEDED", reasons=[Reason("LIMIT_ALREADY_RELEASED",
                        f"The bridge already reaches its limit ({binding}).")])
    if amount <= 0:
        full = [k for k, v in headrooms.items() if v <= 0]
        return Decision("BLOCKED", reasons=[Reason("CAP_REACHED", "No headroom under: " + ", ".join(full))])
    flags = ["AMOUNT_LIMITED_BY_CAP"] if amount < extra or binding == "caps.per_bridge" else []
    return Decision("RELEASE_VARIATION", approved_amount=amount, review_level="manual",
                    reasons=[Reason("VARIATION_SIGNED", f"Payer signed a variation: materials RM{job.materials_cost:,.2f} "
                                    f"-> RM{job.invoice_amount:,.2f}. Top-up after RM{already_released:,.2f} released.")],
                    flags=flags, payee=job.supplier_id, tranches=[amount])
