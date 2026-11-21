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
        if get(cfg, "compliance.all_in_cap_legal_status") == "confirmed":
            return {"flag": "CONFIRMED_BY_LEGAL", "effective_rate": rate,
                    "message": f"Financier type '{ftype}': legal has confirmed the all-in cap (recorded by the author). Keep the written advice on file."}
        return {"flag": "CHECK_REQUIRED", "effective_rate": rate,
                "message": f"Financier type '{ftype}': confirm which rules apply. Legal to confirm."}
    cap = get(cfg, "financier.moneylender_caps." + ("secured" if secured else "unsecured"))
    if rate > cap:
        return {"flag": "MONEYLENDER_CAP_BREACH", "effective_rate": rate, "cap": cap,
                "message": "A flat fee may be treated as interest. Legal to confirm."}
    return {"flag": "OK", "effective_rate": rate, "cap": cap, "message": "Within cap on a simple basis."}


def controlled_account_flag(cfg: dict | None = None) -> dict:
    """The controlled-account legal point. An open item until the config records that legal has confirmed it.

    The engine takes no view on the law: `compliance.controlled_account_legal_status: confirmed` is the author's statement
    that legal has confirmed the position, shown as such, and the written advice should be kept on file.
    """
    if cfg is not None and get(cfg, "compliance.controlled_account_legal_status") == "confirmed":
        return {"flag": "CONFIRMED_BY_LEGAL", "message": "Legal has confirmed the controlled-account position (recorded by the "
                "author). Keep the written advice on file."}
    return {"flag": "OPEN_ITEM", "message": "Confirm whether the controlled account needs central-bank "
            "approval as e-money or a payment service."}


def check_export_consent(job: Job) -> None:
    """Refuse to export a job-history record to a third party without PDPA consent."""
    if not job.pdpa_consent:
        raise ConsentError(f"Job {job.job_id}: no PDPA consent, cannot export to a third party.")
