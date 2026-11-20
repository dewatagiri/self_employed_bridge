"""Self-contained HTML reports: white background, plain tables, inline SVG only.
No external fonts, scripts or stylesheets, so a page opens offline."""
from __future__ import annotations

import html
from typing import Any, Optional

FOOTER = "Sensitivity tool, not a forecast. All parameters are pilot settings. Views are the author's own. Not financial advice."

CSS = """
body{background:#fff;color:#111;font:14px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;
     margin:0 auto;max-width:960px;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:28px 0 8px;border-bottom:1px solid #ddd;padding-bottom:4px}
h3{font-size:15px;margin:18px 0 6px}
.meta{color:#555;font-size:13px}
.banner{border:2px solid #b00;color:#b00;font-weight:700;padding:6px 10px;margin:12px 0;letter-spacing:.04em}
.banner.syn{border-color:#a60;color:#a60}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;margin:6px 0 10px;font-size:13px}
th,td{border:1px solid #ccc;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#f4f4f4;font-weight:600} td.n{text-align:right;font-variant-numeric:tabular-nums}
.PASS{color:#0a6b2d;font-weight:700} .FAIL{color:#b00;font-weight:700}
.NO_THRESHOLD_SET,.NO_DATA{color:#666;font-weight:600}
.note{color:#555;font-size:13px} footer{margin-top:32px;border-top:1px solid #ddd;padding-top:8px;color:#555;font-size:12px}
svg text{font:11px -apple-system,Segoe UI,Helvetica,Arial,sans-serif;fill:#333}
"""


def esc(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def fmt(v: Any, kind: str = "num") -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if kind == "pct":
            return f"{v:.1%}"
        if kind == "rm":
            return f"−RM{-v:,.0f}" if v < 0 else f"RM{v:,.0f}"
        if kind == "ratio":
            return f"{v:.2f}"
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return esc(v)


def table(headers: list[str], rows: list[list[str]], numeric: Optional[set[int]] = None) -> str:
    numeric = numeric or set()
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f'<td class="n">{c}</td>' if i in numeric else f"<td>{c}</td>"
                                     for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="wrap"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def status(s: str) -> str:
    return f'<span class="{esc(s)}">{esc(s)}</span>'


def page(title: str, config_path: str, demo: bool, body: str, synthetic: bool = False,
         subtitle: str = "") -> str:
    banners = ""
    if demo:
        banners += ('<div class="banner">DEMO PARAMETERS: every limit, rate and probability in this '
                    "report is made up. Nothing here is a finding.</div>")
    if synthetic:
        banners += '<div class="banner syn">SYNTHETIC DATA: the input log is made up.</div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
<header><h1>{esc(title)}{" — DEMO PARAMETERS" if demo else ""}</h1>
<div class="meta">Config: <code>{esc(config_path)}</code>{(" · " + esc(subtitle)) if subtitle else ""}</div>
{banners}</header>
{body}
<footer>{esc(FOOTER)}</footer>
</body></html>
"""


# ---------- gates ----------

METRIC_KIND = {"share_deposit_below_materials": "pct", "share_supplier_direct_and_controlled_account": "pct",
               "on_time_share": "pct", "bypass_rate": "pct", "loss_to_reserve": "ratio", "fee_cover_ratio": "ratio"}
MEASURE_ROWS = [
    ("bridges", "Bridges", "num"), ("jobs_completed", "Jobs completed", "num"),
    ("on_time_share", "Share repaid on time", "pct"), ("total_loss", "Total loss", "rm"),
    ("loss_to_reserve", "Loss / first-loss reserve", "ratio"), ("customers_bypassed", "Customers who bypassed", "num"),
    ("hours_quote_to_supplier_median", "Hours quote → supplier payment (median)", "num"),
    ("hours_quote_to_supplier_max", "Hours quote → supplier payment (max)", "num"),
    ("share_within_target_hours", "Share within target hours", "pct"),
    ("cost_to_serve_per_bridge", "Cost to serve per bridge", "rm"),
]


def _gate_rows(result: dict) -> list[list[str]]:
    rows = []
    for gr in result["gates"]:
        for c in gr.checks:
            k = METRIC_KIND.get(c.metric, "num")
            rows.append([f"{gr.gate} · {esc(gr.name)}", esc(c.metric.replace("_", " ")), fmt(c.value, k),
                         ("≥ " if c.direction == "min" else "≤ ") + fmt(c.threshold, k) if c.threshold is not None
                         else "not set", status(c.status), status(gr.status)])
    return rows


def render_gates(res: dict, config_path: str, demo: bool, synthetic: bool, log_path: str) -> str:
    hdr = ["Gate", "Metric", "Value", "Threshold", "Check", "Gate status"]
    body = ['<p class="note">Thresholds come from <code>gates.*</code> in the config. The design leaves them open, '
            "so a null threshold shows NO_THRESHOLD_SET rather than a guessed pass mark. "
            "The first-loss reserve is assumed to be held per cohort (open item 2), so the all-cohort "
            "loss is measured against one reserve per cohort.</p>",
            "<h2>All cohorts</h2>", table(hdr, _gate_rows(res["overall"]), {2})]
    g3 = res["overall"]["gates"][3].detail
    body.append("<h3>Economics</h3>" + table(
        ["", "Total", "Per bridge"],
        [["Fee collected", fmt(g3["fee_total"], "rm"), fmt(g3["fee_per_bridge"], "rm")],
         ["Cost to serve", fmt(g3["cost_to_serve_total"], "rm"), fmt(g3["cost_per_bridge"], "rm")],
         ["Loss", fmt(g3["loss_total"], "rm"), fmt(g3["loss_per_bridge"], "rm")],
         ["Net", fmt(g3["net_total"], "rm"), fmt(g3["net_per_bridge"], "rm")]], {1, 2}))

    names = list(res["cohorts"])
    body.append("<h2>Measures by cohort</h2>")
    body.append(table(["Measure"] + names + ["All"],
                      [[label] + [fmt(res["cohorts"][c]["measures"][k], kind) for c in names]
                       + [fmt(res["overall"]["measures"][k], kind)] for k, label, kind in MEASURE_ROWS],
                      set(range(1, len(names) + 2))))
    for c in names:
        body.append(f"<h3>Cohort {esc(c)}</h3>" + table(hdr, _gate_rows(res["cohorts"][c]), {2}))
    if res["next_cohort"]:
        body.append("<h2>Next cohort rule</h2>")
        body.append(table(["Cohort", "May start", "Reason"],
                          [[esc(c), f'<span class="{"PASS" if ok else "FAIL"}">{"yes" if ok else "no"}</span>', esc(why)] for c, (ok, why) in res["next_cohort"].items()]))
    return page("Pilot gates", config_path, demo, "\n".join(body), synthetic, f"Log: {log_path}")
