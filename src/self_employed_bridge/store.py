"""SQLite record for the staff page: jobs, decisions and bridges. One file, no server."""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from typing import Optional

from .collections import LiveBridge, Task
from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, kind TEXT NOT NULL,
  data TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bridges (
  bridge_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, borrower_id TEXT NOT NULL, supplier_id TEXT NOT NULL,
  cohort TEXT NOT NULL, released_date TEXT NOT NULL, closed_date TEXT, quote_hours REAL,
  supplier_paid_directly INTEGER NOT NULL, fee REAL NOT NULL, cost REAL NOT NULL,
  tranches TEXT NOT NULL, live TEXT NOT NULL,
  new_to_formal_credit INTEGER, would_not_proceed INTEGER);
"""
# Columns added after the first release; older bridge.db files get them on open.
MIGRATIONS = [("bridges", "new_to_formal_credit", "INTEGER"), ("bridges", "would_not_proceed", "INTEGER")]


def _live_to_json(b: LiveBridge) -> str:
    return json.dumps(dataclasses.asdict(b))


def _live_from_json(s: str) -> LiveBridge:
    d = json.loads(s)
    d["history"] = tuple(d["history"])
    d["tasks"] = tuple(Task(**t) for t in d["tasks"])
    return LiveBridge(**d)


def _tri(v):
    """True/False/None to 1/0/None for SQLite."""
    return None if v is None else int(bool(v))


class Store:
    def __init__(self, path: str):
        # The staff page serves one request at a time (http.server.HTTPServer), so one shared
        # connection is safe even though tests run the server in a separate thread.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if col not in have:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.db.commit()

    # jobs
    def save_job(self, job: Job, now: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?, ?)",
                        (job.job_id, json.dumps(dataclasses.asdict(job)), now))
        self.db.commit()

    def get_job(self, job_id: str) -> Optional[Job]:
        row = self.db.execute("SELECT data FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return Job.from_dict(json.loads(row["data"])) if row else None

    def jobs(self) -> list[Job]:
        return [Job.from_dict(json.loads(r["data"])) for r in self.db.execute("SELECT data FROM jobs ORDER BY job_id")]

    # decisions (audit trail)
    def log_decision(self, job_id: str, kind: str, decision, now: str) -> None:
        self.db.execute("INSERT INTO decisions (job_id, kind, data, created_at) VALUES (?, ?, ?, ?)",
                        (job_id, kind, json.dumps(dataclasses.asdict(decision)), now))
        self.db.commit()

    def decisions(self, job_id: str) -> list[dict]:
        return [dict(r) | {"data": json.loads(r["data"])} for r in self.db.execute(
            "SELECT * FROM decisions WHERE job_id = ? ORDER BY id", (job_id,))]

    # bridges
    def next_bridge_id(self) -> str:
        n = self.db.execute("SELECT COUNT(*) FROM bridges").fetchone()[0]
        return f"BR{n + 1:05d}"

    def add_bridge(self, rec: dict) -> None:
        self.db.execute(
            "INSERT INTO bridges (bridge_id, job_id, borrower_id, supplier_id, cohort, released_date, closed_date, "
            "quote_hours, supplier_paid_directly, fee, cost, tranches, live, new_to_formal_credit, would_not_proceed) "
            "VALUES (:bridge_id, :job_id, :borrower_id, :supplier_id, :cohort, :released_date, :closed_date, "
            ":quote_hours, :supplier_paid_directly, :fee, :cost, :tranches, :live, :new_to_formal_credit, :would_not_proceed)",
            {"new_to_formal_credit": None, "would_not_proceed": None} | rec
            | {"tranches": json.dumps(rec["tranches"]), "live": _live_to_json(rec["live"]),
               "supplier_paid_directly": int(bool(rec["supplier_paid_directly"])),
               "new_to_formal_credit": _tri(rec.get("new_to_formal_credit")),
               "would_not_proceed": _tri(rec.get("would_not_proceed"))})
        self.db.commit()

    def update_bridge(self, bridge_id: str, live: LiveBridge, closed_date: Optional[str]) -> None:
        self.db.execute("UPDATE bridges SET live = ?, closed_date = COALESCE(closed_date, ?) WHERE bridge_id = ?",
                        (_live_to_json(live), closed_date, bridge_id))
        self.db.commit()

    def records(self) -> list[dict]:
        out = []
        for r in self.db.execute("SELECT * FROM bridges ORDER BY bridge_id"):
            d = dict(r)
            d["live"] = _live_from_json(d["live"])
            d["tranches"] = json.loads(d["tranches"])
            out.append(d)
        return out

    def record(self, bridge_id: str) -> Optional[dict]:
        return next((r for r in self.records() if r["bridge_id"] == bridge_id), None)
