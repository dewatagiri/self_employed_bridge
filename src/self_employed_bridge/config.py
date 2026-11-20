"""Config loading and the null guard. Nothing is hard-coded: every limit lives in YAML."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml


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
]
