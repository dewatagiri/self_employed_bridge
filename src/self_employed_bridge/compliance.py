"""Compliance flags for legal to confirm. No legal conclusions are made here."""
from __future__ import annotations

from .config import get, require
from .models import Job


class ConsentError(Exception):
    pass


def effective_annual_rate(flat_fee: float, amount: float, tenor_days: float) -> float:
    """Simple-interest basis."""
    return flat_fee / amount * 365 / tenor_days


def moneylender_check(flat_fee: float, amount: float, tenor_days: float, cfg: dict,
                      secured: bool = False) -> dict:
    require(cfg, ["financier.type"])
    rate = effective_annual_rate(flat_fee, amount, tenor_days)
    ftype = get(cfg, "financier.type")
    if ftype != "licensed_moneylender":
        return {"flag": "CHECK_REQUIRED", "effective_rate": rate,
                "message": f"Financier type '{ftype}': confirm which rules apply. Legal to confirm."}
    cap = get(cfg, "financier.moneylender_caps." + ("secured" if secured else "unsecured"))
    if rate > cap:
        return {"flag": "MONEYLENDER_CAP_BREACH", "effective_rate": rate, "cap": cap,
                "message": "A flat fee may be treated as interest. Legal to confirm."}
    return {"flag": "OK", "effective_rate": rate, "cap": cap, "message": "Within cap on a simple basis."}


def controlled_account_flag() -> dict:
    """Standing open item, not a calculation."""
    return {"flag": "OPEN_ITEM", "message": "Confirm whether the controlled account needs central-bank "
            "approval as e-money or a payment service."}


def check_export_consent(job: Job) -> None:
    """Refuse to export a job-history record to a third party without PDPA consent."""
    if not job.pdpa_consent:
        raise ConsentError(f"Job {job.job_id}: no PDPA consent, cannot export to a third party.")
