"""Staff page: a small local web app around the engine, for running a first cohort by hand.

    py -3.13 -m self_employed_bridge.cli serve --config config/params.demo.yaml --db bridge.db
    then open http://127.0.0.1:8000

Standard library only (http.server + sqlite3). Listens on 127.0.0.1 by default, so only this PC can
reach it. Every decision is made by the engine (`screen`, `decide`, `decide_variation`,
`collections`, `gates`); this module only collects input, stores the record and shows results.
The engine contacts nobody, and neither does this page: it records what staff did.
"""
from __future__ import annotations

import csv
import dataclasses
import datetime
import io
import typing
import urllib.parse
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

from . import collections as col
from . import gates, ledger, report
from .collections import InvalidTransition, LiveBridge
from .compliance import controlled_account_flag
from .config import ConfigIncomplete, ConfigInvalid, get, is_demo, require
from .decide import decide, decide_variation
from .models import Bridge, Job
from .report import esc, fmt
from .store import Store

# ---------- the job form ----------

ENUMS = {
    "payer_type": ["household", "individual", "small_business", "company", "agency", "glc", "other"],
    "borrower_credit_flag": ["ok", "adverse", "none"],
    "borrower_kyc_status": ["", "verified", "pending", "failed"],
    "screening_result": ["", "clear", "possible_match", "pep", "true_match"],
    "variation_order_signed": ["", "yes", "no"],
}
GROUPS = [
    ("Job and payer", [("job_id", "Job ID"), ("trade", "Trade"), ("sponsor_cohort", "Sponsor cohort"),
                       ("payer_id", "Payer ID (blank = no confirmed payer)"), ("payer_type", "Payer type"),
                       ("payer_related_to_borrower", "Payer is related to the borrower"),
                       ("payer_identity_confirmed", "Payer identity confirmed")]),
    ("Money (RM)", [("quote_total", "Quote total"), ("materials_cost", "Materials cost in the quote"),
                    ("deposit_amount", "Deposit paid"), ("deposit_date", "Deposit date"),
                    ("deposit_from_payer_account", "Deposit came from the payer's own account")]),
    ("Supplier", [("supplier_id", "Supplier ID"), ("supplier_on_panel", "Supplier is on the approved panel"),
                  ("invoice_amount", "Supplier invoice amount"),
                  ("materials_list_match", "Match to trade template (0 to 1)"),
                  ("variation_order_signed", "Variation order signed by the payer")]),
    ("Borrower", [("borrower_id", "Borrower ID"), ("borrower_kyc_status", "eKYC result"),
                  ("screening_result", "Financial-crime screening result"),
                  ("borrower_credit_flag", "Credit bureau record"), ("borrower_registered", "Business registered"),
                  ("borrower_trade_months", "Months in the trade"), ("borrower_completed_jobs", "Completed jobs"),
                  ("pdpa_consent", "PDPA consent given")]),
]
EXAMPLE = {"job_id": "J-0001", "trade": "painter", "sponsor_cohort": "C1", "payer_id": "P-0001",
           "payer_type": "household", "payer_identity_confirmed": True, "quote_total": 12000,
           "materials_cost": 5000, "deposit_amount": 2000, "deposit_from_payer_account": True,
           "supplier_id": "S-01", "supplier_on_panel": True, "invoice_amount": 5000, "materials_list_match": 0.92,
           "borrower_id": "B-0001", "borrower_kyc_status": "verified", "screening_result": "clear",
           "borrower_credit_flag": "ok", "borrower_registered": True, "borrower_trade_months": 30,
           "borrower_completed_jobs": 12, "pdpa_consent": True}
HINTS = typing.get_type_hints(Job)


def _base(t):
    return typing.get_args(t)[0] if typing.get_origin(t) is typing.Union else t


def parse_job(form: dict[str, str]) -> Job:
    """Form fields to a Job. Unticked boxes are False; blank optional fields are None."""
    values = {}
    for f in dataclasses.fields(Job):
        raw = form.get(f.name, "").strip()
        t = _base(HINTS[f.name])
        if f.name == "variation_order_signed":
            values[f.name] = {"yes": True, "no": False}.get(raw)
        elif t is bool:
            values[f.name] = raw == "on"
        elif t is float:
            values[f.name] = float(raw) if raw else 0.0
        elif t is int:
            values[f.name] = int(float(raw)) if raw else 0
        else:
            values[f.name] = raw or None
    for key in ("job_id", "borrower_id", "supplier_id"):
        if not values.get(key):
            raise ValueError(f"{key} is required")
    values["trade"] = values["trade"] or ""
    values["sponsor_cohort"] = values["sponsor_cohort"] or "C1"
    values["payer_type"] = values["payer_type"] or "other"
    values["borrower_credit_flag"] = values["borrower_credit_flag"] or "none"
    return Job(**values)


def _field(name: str, label: str, value) -> str:
    t = _base(HINTS[name])
    if name in ENUMS:
        cur = {True: "yes", False: "no"}.get(value, value) if name == "variation_order_signed" else value
        opts = "".join(f'<option value="{esc(o)}"{" selected" if (cur or "") == o else ""}>{esc(o or "not done")}</option>'
                       for o in ENUMS[name])
        return f'<label>{esc(label)}<select name="{name}">{opts}</select></label>'
    if t is bool:
        return (f'<label class="check"><input type="checkbox" name="{name}"{" checked" if value else ""}> '
                f'{esc(label)}</label>')
    kind = "date" if name == "deposit_date" else "number" if t in (float, int) else "text"
    step = ' step="0.01"' if name == "materials_list_match" else ' step="any"' if t is float else ""
    return f'<label>{esc(label)}<input type="{kind}" name="{name}" value="{esc(value if value is not None else "")}"{step}></label>'


# ---------- page shell ----------

APP_CSS = """
nav{display:flex;gap:18px;flex-wrap:wrap;border-bottom:1px solid #ddd;padding:0 0 10px;margin:0 0 14px}
nav a{color:#111;font-weight:600;text-decoration:none} nav a:hover{text-decoration:underline}
fieldset{border:1px solid #ccc;padding:10px 12px;margin:0 0 12px}
legend{font-weight:600;padding:0 4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px 16px}
label{display:flex;flex-direction:column;gap:3px;font-size:13px}
label.check{flex-direction:row;align-items:center;gap:6px}
input,select{font:inherit;padding:5px 6px;border:1px solid #aaa;border-radius:3px;background:#fff;color:#111}
button{font:inherit;font-weight:600;padding:7px 14px;border:1px solid #111;background:#111;color:#fff;border-radius:3px;cursor:pointer}
button.ghost{background:#fff;color:#111}
.route{display:inline-block;font-weight:700;padding:3px 10px;border:2px solid currentColor;border-radius:3px}
.RELEASE,.RELEASE_VARIATION,.BRIDGE_CANDIDATE{color:#0a6b2d} .DECLINE{color:#b00} .BLOCKED{color:#a60}
.REFER_GENERAL,.REFER_CONTRACT_INVOICE,.NO_BRIDGE_NEEDED,.NO_TOP_UP_NEEDED{color:#52514e}
.msg{border-left:4px solid #2a78d6;background:#f3f7fc;padding:8px 12px;margin:0 0 14px}
.err{border-left-color:#b00;background:#fbf2f2}
.actions{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.actions form{border:1px solid #ccc;padding:10px;display:flex;flex-direction:column;gap:8px}
"""


class App:
    def __init__(self, cfg: dict, config_path: str, store: Store, today: Callable[[], str] = None):
        self.cfg, self.config_path, self.store = cfg, config_path, store
        self.today = today or (lambda: datetime.date.today().isoformat())

    def layout(self, title: str, body: str, msg: str = "", error: bool = False) -> str:
        banner = ('<div class="banner">DEMO PARAMETERS: made-up limits and rates. Do not use for real lending.</div>'
                  if is_demo(self.cfg) else "")
        note = f'<div class="msg{" err" if error else ""}">{msg}</div>' if msg else ""
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · Bridge desk</title>
<style>{report.CSS}{APP_CSS}</style></head><body>
<nav><a href="/job">New job</a><a href="/bridges">Bridges and tasks</a><a href="/gates">Pilot gates</a>
<a href="/log.csv">Download log (CSV)</a></nav>
<h1>{esc(title)}</h1><div class="meta">Config: <code>{esc(self.config_path)}</code></div>{banner}{note}
{body}<footer>Every decision on this page is made by the engine. Staff carry out the tasks; the page contacts nobody.
Open item: {esc(controlled_account_flag()["message"])}</footer></body></html>"""

    # ----- pages -----

    def page_job(self, values: Optional[dict] = None, msg: str = "", error: bool = False) -> str:
        values = values or {}
        sets = "".join(f'<fieldset><legend>{esc(g)}</legend><div class="grid">'
                       + "".join(_field(n, lbl, values.get(n)) for n, lbl in items) + "</div></fieldset>"
                       for g, items in GROUPS)
        body = (f'<form method="post" action="/decide">{sets}<button type="submit">Decide</button> '
                f'<a href="/job?example=1">Fill the example job</a></form>')
        return self.layout("New job", body, msg, error)

    def _decision_html(self, job: Job, d, exposure) -> str:
        rows = [["Route", f'<span class="route {esc(d.route)}">{esc(d.route)}</span>']]
        if d.approved_amount:
            mats = job.invoice_amount if job.variation_order_signed and job.invoice_amount > job.materials_cost \
                else job.materials_cost
            rows += [["Amount", fmt(d.approved_amount, "rm")],
                     ["Pay to", f"supplier <strong>{esc(d.payee)}</strong> (never the borrower)"],
                     ["Review", "automatic" if d.review_level == "auto" else "a named credit officer must approve"],
                     ["Advance", f'{d.approved_amount / mats:.0%} of materials cost' if mats else "—"]]
            if len(d.tranches) > 1:
                rows.append(["Release", f"{fmt(d.tranches[0], 'rm')} now; {fmt(d.tranches[1], 'rm')} after stage 1 is confirmed"])
        if d.flags:
            rows.append(["Flags", esc(", ".join(d.flags))])
        reasons = report.table(["Code", "Reason"], [[esc(r.code), esc(r.text)] for r in d.reasons])
        exp = report.table(["Exposure the engine used", "Value"], [
            ["Borrower live", f"{fmt(exposure.borrower_live_amount, 'rm')} in {exposure.borrower_live_count} bridge(s)"],
            ["Supplier live", fmt(exposure.supplier_live_amount, "rm")],
            ["Cohort live / pilot live", f"{fmt(exposure.cohort_live_amount, 'rm')} / {fmt(exposure.pilot_live_amount, 'rm')}"],
            ["Borrower history", f"{exposure.borrower_prior_bridges} earlier bridge(s), "
                                 f"{exposure.borrower_clean_repayments} repaid on time"],
            ["Borrower blocked after a bypass", "yes" if exposure.borrower_blocked else "no"]])
        return kv(rows) + "<h2>Reasons</h2>" + reasons + "<h2>Inputs</h2>" + exp

    def page_decision(self, job: Job, d, exposure) -> str:
        body = self._decision_html(job, d, exposure)
        if d.route == "RELEASE":
            body += f"""<h2>Record the release</h2>
<p class="note">Press only once the supplier has been paid. The engine re-checks the decision when you press it.</p>
<form method="post" action="/release" class="grid">
<input type="hidden" name="job_id" value="{esc(job.job_id)}">
<label>Hours from quote to supplier payment<input type="number" step="any" name="quote_hours"></label>
<label class="check"><input type="checkbox" name="supplier_paid_directly" checked> Supplier was paid directly</label>
<div><button type="submit">Record release</button></div></form>"""
        body += f'<p><a href="/job?job_id={urllib.parse.quote(job.job_id)}">Edit this job and decide again</a></p>'
        return self.layout(f"Decision for job {job.job_id}", body)

    def page_bridges(self, msg: str = "") -> str:
        recs = self.store.records()
        if not recs:
            return self.layout("Bridges and tasks", '<p>No bridges recorded yet. Start with <a href="/job">a new job</a>.</p>', msg)
        rows = []
        for r in sorted(recs, key=lambda r: (not ledger.is_open(r), r["bridge_id"])):
            b = r["live"]
            last = b.tasks[-1].text if b.tasks else ""
            rows.append([f'<a href="/bridge?id={urllib.parse.quote(r["bridge_id"])}">{esc(r["bridge_id"])}</a>',
                         esc(r["job_id"]), esc(r["borrower_id"]), esc(r["supplier_id"]), esc(r["cohort"]),
                         fmt(b.amount, "rm"), fmt(b.outstanding, "rm"), esc(b.state), str(b.days_past_due), esc(last)])
        tasks = [[esc(t.bridge_id), str(t.days_past_due), esc(t.owner), esc(t.text)]
                 for r in recs if ledger.is_open(r) for t in r["live"].tasks]
        body = report.table(["Bridge", "Job", "Borrower", "Supplier", "Cohort", "Amount", "Outstanding", "State",
                             "Days past due", "Latest task"], rows, {5, 6, 8})
        body += "<h2>Tasks on open bridges</h2>" + (report.table(["Bridge", "Day", "Owner", "Task"], tasks)
                                                    if tasks else "<p>None.</p>")
        return self.layout("Bridges and tasks", body, msg)

    def page_bridge(self, rec: dict, msg: str = "", error: bool = False) -> str:
        b: LiveBridge = rec["live"]
        info = kv([
            ["State", f"<strong>{esc(b.state)}</strong> (path: {esc(' → '.join(b.history))})"],
            ["Job / borrower / supplier", f"{esc(rec['job_id'])} / {esc(rec['borrower_id'])} / {esc(rec['supplier_id'])}"],
            ["Released", f"{fmt(b.amount, 'rm')} on {esc(rec['released_date'])}"
                         + (f" (tranches {', '.join(fmt(t, 'rm') for t in rec['tranches'])})" if len(rec["tranches"]) > 1 else "")],
            ["Outstanding", fmt(b.outstanding, "rm")], ["Days past due", str(b.days_past_due)],
            ["Held (dispute)", fmt(b.held_amount, "rm")],
            ["Loss and who took it", "—" if b.loss is None else
             f"{fmt(b.loss, 'rm')}: reserve {fmt(b.allocation['first_loss'], 'rm')}, guarantor "
             f"{fmt(b.allocation['guarantor'], 'rm')}, financier {fmt(b.allocation['financier'], 'rm')}"]])
        tasks = report.table(["Day", "Owner", "Task"], [[str(t.days_past_due), esc(t.owner), esc(t.text)] for t in b.tasks]) \
            if b.tasks else "<p>None yet.</p>"
        bid = esc(rec["bridge_id"])

        def act(action: str, title: str, field: str = "", help_: str = "") -> str:
            inp = f'<label>{esc(field)}<input type="number" step="any" name="value" required></label>' if field else ""
            return (f'<form method="post" action="/bridge"><input type="hidden" name="id" value="{bid}">'
                    f'<input type="hidden" name="action" value="{action}"><strong>{esc(title)}</strong>'
                    f'<span class="note">{esc(help_)}</span>{inp}<button class="ghost" type="submit">{esc(title)}</button></form>')

        acts = []
        if b.state in ("LIVE",) + tuple(col.OPEN_PROBLEM):
            acts.append(act("payment", "Record payment", "Amount received in the controlled account (RM)"))
            acts.append(act("days", "Set days past due", "Days past due today", "Fires reminder, notice, escalation and write-off on their days."))
        if b.state in ("LIVE", "LATE"):
            acts += [act("bypass", "Customer paid the borrower", help_="Bypass: holds balances, blocks new bridges."),
                     act("dispute", "Customer disputes", "Disputed amount (RM)"),
                     act("abandon", "Borrower abandoned the job")]
            acts.append(act("topup", "Variation signed: top up", "New materials total (RM)",
                            "The payer signed a variation order. A named officer reviews the top-up."))
        if b.state == "DISPUTE":
            acts.append(act("dispute_fault", "Mediation: borrower at fault"))
        if b.state in col.OPEN_PROBLEM:
            acts.append(act("write_off", "Write off now", help_="Use when chasing costs more than it would recover."))
        if b.state == "PAID_LATE" and b.cause == "bypass" and not b.cured:
            acts.append(act("cure", "Approve cure (credit officer)", help_="Repaid in full: lift the block. A second bypass blocks for good."))
        body = info + "<h2>Actions</h2>" + (f'<div class="actions">{"".join(acts)}</div>' if acts else "<p>Closed.</p>") \
            + "<h2>Tasks</h2>" + tasks
        return self.layout(f"Bridge {rec['bridge_id']}", body, msg, error)

    def page_gates(self) -> str:
        rows = ledger.log_rows(self.store.records())
        if not rows:
            return self.layout("Pilot gates", "<p>No closed bridges yet. Gates are scored from closed bridges.</p>")
        res = gates.score_by_cohort(rows, self.cfg, self.store.jobs())
        page = report.render_gates(res, self.config_path, is_demo(self.cfg), False, "staff record (bridge.db)")
        return page.replace("<body>", '<body><nav style="display:flex;gap:18px;border-bottom:1px solid #ddd;'
                            'padding:0 0 10px;margin:0 0 14px"><a href="/job">New job</a><a href="/bridges">Bridges and tasks</a>'
                            '<a href="/log.csv">Download log (CSV)</a></nav>', 1)

    def log_csv(self) -> str:
        buf = io.StringIO()
        names = [f.name for f in dataclasses.fields(Bridge)]
        w = csv.writer(buf)
        w.writerow(names)
        for row in ledger.log_rows(self.store.records()):
            w.writerow([getattr(row, n) if getattr(row, n) is not None else "" for n in names])
        return buf.getvalue()

    # ----- actions (each returns (status, location-or-html)) -----

    def do_decide(self, form: dict) -> str:
        try:
            job = parse_job(form)
        except ValueError as e:
            return self.page_job(form_values(form), f"Check the form: {esc(e)}", True)
        self.store.save_job(job, self.today())
        exposure = ledger.exposure_for(job.borrower_id, job.supplier_id, job.sponsor_cohort, self.store.records())
        d = decide(job, exposure, self.cfg)
        self.store.log_decision(job.job_id, "decide", d, self.today())
        return self.page_decision(job, d, exposure)

    def do_release(self, form: dict) -> tuple[str, str]:
        job = self.store.get_job(form.get("job_id", ""))
        if job is None:
            return "html", self.page_job(msg="Unknown job.", error=True)
        exposure = ledger.exposure_for(job.borrower_id, job.supplier_id, job.sponsor_cohort, self.store.records())
        d = decide(job, exposure, self.cfg)           # re-check: never trust an old screen
        if d.route != "RELEASE":
            return "html", self.page_decision(job, d, exposure)
        require(self.cfg, ["pricing.flat_fee_per_bridge", "pricing.cost_to_serve_per_bridge"])
        bid = self.store.next_bridge_id()
        hours = form.get("quote_hours", "").strip()
        self.store.add_bridge({
            "bridge_id": bid, "job_id": job.job_id, "borrower_id": job.borrower_id, "supplier_id": job.supplier_id,
            "cohort": job.sponsor_cohort, "released_date": self.today(), "closed_date": None,
            "quote_hours": float(hours) if hours else None,
            "supplier_paid_directly": form.get("supplier_paid_directly") == "on",
            "fee": get(self.cfg, "pricing.flat_fee_per_bridge"), "cost": get(self.cfg, "pricing.cost_to_serve_per_bridge"),
            "tranches": d.tranches, "live": LiveBridge(bid, job.job_id, job.borrower_id, d.approved_amount)})
        self.store.log_decision(job.job_id, "release", d, self.today())
        return "redirect", f"/bridge?id={bid}&msg=" + urllib.parse.quote(f"Recorded {bid}: {d.approved_amount:,.2f} to supplier {d.payee}.")

    def do_bridge(self, form: dict) -> tuple[str, str]:
        bid, action, raw = form.get("id", ""), form.get("action", ""), form.get("value", "").strip()
        rec = self.store.record(bid)
        if rec is None:
            return "html", self.page_bridges("Unknown bridge.")
        b: LiveBridge = rec["live"]
        value = float(raw) if raw else 0.0
        layers = ledger.layers_left(rec["cohort"], self.store.records(), self.cfg)
        msg = ""
        if action == "payment":
            b, _ = col.payment(b, value)
        elif action == "days":
            b, new = col.advance_days(b, int(value), self.cfg, **layers)
            msg = f"{len(new)} new task(s)." if new else "No new tasks."
        elif action == "bypass":
            b, _ = col.bypass(b)
        elif action == "dispute":
            b, _ = col.dispute(b, value)
        elif action == "dispute_fault":
            b, _ = col.dispute_borrower_at_fault(b)
        elif action == "abandon":
            b, _ = col.abandon(b)
        elif action == "write_off":
            b, _ = col.write_off(b, self.cfg, **layers)
        elif action == "cure":
            b, _ = col.approve_cure(b)
        elif action == "topup":
            job = self.store.get_job(rec["job_id"])
            job = replace(job, invoice_amount=value, variation_order_signed=True)
            exposure = ledger.exposure_for(job.borrower_id, job.supplier_id, job.sponsor_cohort, self.store.records())
            d = decide_variation(job, b.amount, exposure, self.cfg)
            self.store.log_decision(job.job_id, "variation", d, self.today())
            if d.route != "RELEASE_VARIATION":
                return "html", self.page_bridge(rec, f"Top-up not released: {esc(d.route)}. "
                                                + esc("; ".join(r.text for r in d.reasons)), True)
            self.store.save_job(job, self.today())
            b = replace(b, amount=b.amount + d.approved_amount, outstanding=b.outstanding + d.approved_amount)
            msg = (f"Top-up {d.approved_amount:,.2f} to supplier {d.payee}. A named credit officer must approve it "
                   "before the supplier is paid.")
        else:
            return "html", self.page_bridge(rec, "Unknown action.", True)
        closed = self.today() if b.state in col.CLOSED else None
        self.store.update_bridge(bid, b, closed)
        msg = msg or f"{action.replace('_', ' ')} recorded."
        return "redirect", f"/bridge?id={urllib.parse.quote(bid)}&msg=" + urllib.parse.quote(msg)


def kv(rows: list[list[str]]) -> str:
    """Two-column table without a header row; values are already escaped HTML."""
    body = "".join(f"<tr><th scope='row' style='width:34%'>{k}</th><td>{v}</td></tr>" for k, v in rows)
    return f'<div class="wrap"><table><tbody>{body}</tbody></table></div>'


def form_values(form: dict) -> dict:
    out = dict(form)
    for _, items in GROUPS:
        for n, _ in items:
            if _base(HINTS[n]) is bool and n != "variation_order_signed":
                out[n] = form.get(n) == "on"
    return out


def job_values(job: Job) -> dict:
    return dataclasses.asdict(job)


# ---------- HTTP ----------

def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BridgeDesk/1"

        def log_message(self, fmt_, *args):      # keep the console quiet
            pass

        def _send(self, status: int, body: str, ctype: str = "text/html; charset=utf-8", extra: dict = None):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; img-src data:; form-action 'self'; frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, location: str):
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _guard(self, fn):
            try:
                return fn()
            except ConfigIncomplete as e:
                self._send(200, app.layout("Settings missing", "<p>The engine refuses to decide until these are set "
                           "in the config:</p><ul>" + "".join(f"<li><code>{esc(k)}</code></li>" for k in e.keys) + "</ul>",
                           "Config incomplete.", True))
            except (ConfigInvalid, InvalidTransition, ValueError) as e:
                self._send(200, app.layout("Not done", f"<p>{esc(e)}</p><p><a href='/bridges'>Bridges and tasks</a> · <a href='/job'>New job</a></p>",
                                           "The engine refused this step.", True))

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            msg = esc(q.get("msg", ""))

            def run():
                if url.path in ("/", "/job"):
                    if q.get("example"):
                        return self._send(200, app.page_job(EXAMPLE))
                    job = app.store.get_job(q["job_id"]) if q.get("job_id") else None
                    return self._send(200, app.page_job(job_values(job) if job else None, msg))
                if url.path == "/bridges":
                    return self._send(200, app.page_bridges(msg))
                if url.path == "/bridge":
                    rec = app.store.record(q.get("id", ""))
                    return self._send(200, app.page_bridge(rec, msg) if rec else app.page_bridges("Unknown bridge."))
                if url.path == "/gates":
                    return self._send(200, app.page_gates())
                if url.path == "/log.csv":
                    return self._send(200, app.log_csv(), "text/csv; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="bridge_log.csv"'})
                return self._send(404, app.layout("Not found", "<p>No such page.</p>"))
            self._guard(run)

        def do_POST(self):
            # Same-origin check: a form on another site must not drive this page.
            origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
            host = self.headers.get("Host", "")
            if origin and urllib.parse.urlsplit(origin).netloc != host:
                return self._send(403, app.layout("Refused", "<p>Requests must come from this page.</p>"))
            length = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"),
                                                              keep_blank_values=True).items()}
            path = urllib.parse.urlsplit(self.path).path

            def run():
                if path == "/decide":
                    return self._send(200, app.do_decide(form))
                if path in ("/release", "/bridge"):
                    kind, out = (app.do_release if path == "/release" else app.do_bridge)(form)
                    return self._redirect(out) if kind == "redirect" else self._send(200, out)
                return self._send(404, app.layout("Not found", "<p>No such action.</p>"))
            self._guard(run)
    return Handler


def serve(cfg: dict, config_path: str, db_path: str, host: str = "127.0.0.1", port: int = 8000) -> None:
    app = App(cfg, config_path, Store(db_path))
    httpd = HTTPServer((host, port), make_handler(app))
    print(f"Bridge desk on http://{host}:{port}  (record: {db_path}; Ctrl+C to stop)")
    if is_demo(cfg):
        print("DEMO PARAMETERS: made-up limits and rates. Do not use for real lending.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
