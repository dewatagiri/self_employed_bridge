"""Config loading and the null guard. Nothing is hard-coded: every limit lives in YAML."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml


class ConfigInvalid(ValueError):
    """A parameter is set to a value the design does not allow."""


class ConfigIncomplete(Exception):
    """A required parameter is null or missing. `.keys` names every one."""

    def __init__(self, keys: Iterable[str]):
        self.keys = list(keys)
        super().__init__("Config incomplete, set before live use: " + ", ".join(self.keys))


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get(cfg: dict, dotted: str, default: Any = None) -> Any:
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def missing(cfg: dict, keys: Iterable[str]) -> list[str]:
    return [k for k in keys if get(cfg, k) is None]


def require(cfg: dict, keys: Iterable[str]) -> None:
    gone = missing(cfg, keys)
    if gone:
        raise ConfigIncomplete(gone)


def is_demo(cfg: dict) -> bool:
    return bool(get(cfg, "meta.demo", False))


def null_keys(cfg: dict, prefix: str = "") -> list[str]:
    """Every dotted key whose value is null. Used by `check-config`."""
    out: list[str] = []
    for k, v in cfg.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out.extend(null_keys(v, key + "."))
        elif v is None:
            out.append(key)
    return out


SCREEN_REQUIRED = ["screen.min_materials_share_of_quote"]
DECIDE_REQUIRED = SCREEN_REQUIRED + [
    "screen.deposit_to_materials_share",
    "release.auto_approve_max_amount",
    "release.template_match_min",
    "caps.per_bridge",
    "caps.per_borrower_live",
    "caps.per_supplier_live",
    "caps.per_sponsor_cohort",
    "caps.pilot_total",
    "caps.max_live_bridges_per_borrower",
    "borrower.min_trade_months_or_jobs",
    "tenor.two_step_release_over_amount",
    "release.margin_of_advance",
]

PRICING_REQUIRED = ["pricing.flat_fee_per_bridge", "pricing.guarantee_fee_rate_on_drawn",
                    "pricing.cost_to_serve_per_bridge"]
COLLECTIONS_REQUIRED = ["collections.days_past_due_reminder", "collections.days_past_due_notice",
                        "collections.days_past_due_escalate", "collections.write_off_after_days",
                        "collections.min_expected_recovery_to_chase"]
SIMULATE_REQUIRED = ["simulation.n_bridges", "simulation.n_runs", "simulation.seed",
                     "simulation.amount_distribution", "simulation.deposit_share_of_materials",
                     "simulation.outcome_probs", "simulation.recovery_rate_by_outcome", "tenor.typical_days",
                     "screen.deposit_to_materials_share", "release.margin_of_advance",
                     "caps.per_bridge", "caps.per_sponsor_cohort"] + PRICING_REQUIRED


def layer_keys(cfg: dict) -> list[str]:
    keys = ["layers.first_loss_reserve"]
    if get(cfg, "layers.guarantor_enabled"):
        keys += ["layers.guarantor_cover_pct", "layers.guarantor_cap"]
    return keys


def stop_line_keys(cfg: dict) -> list[str]:
    """The bypass stop line is optional; once it is set it needs its minimum sample."""
    return ["stop_lines.bypass_rate_min_bridges"] if get(cfg, "stop_lines.pause_if_bypass_rate_over") is not None else []


def requirements(cfg: dict) -> dict[str, list[str]]:
    """Which keys each command needs. Gate thresholds and stop lines never block: they report
    NO_THRESHOLD_SET or stay switched off."""
    layers = layer_keys(cfg)
    return {
        "screen": SCREEN_REQUIRED,
        "decide": DECIDE_REQUIRED,
        "pricing": PRICING_REQUIRED,
        "compliance": ["financier.type"],
        "waterfall": layers,
        "collections": COLLECTIONS_REQUIRED + layers,
        "simulate": SIMULATE_REQUIRED + layers + stop_line_keys(cfg),
    }


def check_config(cfg: dict) -> dict:
    """{'blocking': {key: [commands]}, 'open': [keys that are null but do not block]}"""
    blocking: dict[str, list[str]] = {}
    for cmd, keys in requirements(cfg).items():
        for k in missing(cfg, keys):
            blocking.setdefault(k, []).append(cmd)
    open_ = [k for k in null_keys(cfg) if k not in blocking]
    return {"blocking": blocking, "open": open_}
