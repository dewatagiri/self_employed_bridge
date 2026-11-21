"""Self-contained HTML reports: white background, plain tables, inline SVG only.
No external fonts, scripts or stylesheets, so a page opens offline."""
from __future__ import annotations

import html
import math
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
               "on_time_share": "pct", "bypass_rate": "pct", "loss_to_reserve": "ratio", "fee_cover_ratio": "ratio",
               "share_new_to_formal_credit": "pct", "share_job_needed_bridge": "pct"}
MEASURE_ROWS = [
    ("bridges", "Bridges", "num"), ("jobs_completed", "Jobs completed", "num"),
    ("on_time_share", "Share repaid on time", "pct"), ("total_loss", "Total loss", "rm"),
    ("loss_to_reserve", "Loss / first-loss reserve", "ratio"), ("customers_bypassed", "Customers who bypassed", "num"),
    ("hours_quote_to_supplier_median", "Hours quote → supplier payment (median)", "num"),
    ("hours_quote_to_supplier_max", "Hours quote → supplier payment (max)", "num"),
    ("share_within_target_hours", "Share within target hours", "pct"),
    ("cost_to_serve_per_bridge", "Cost to serve per bridge", "rm"),
    ("share_new_to_formal_credit", "Borrowers new to formal credit", "pct"),
    ("share_job_needed_bridge", "Borrowers who say the job needed the bridge", "pct"),
    ("cost_per_fully_additional_borrower", "Funders' cost per fully additional borrower", "rm"),
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
            "The first-loss reserve is held per cohort (author decision A3), so the all-cohort "
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


# ---------- simulation report ----------

import json as _json  # noqa: E402

from .config import get  # noqa: E402
from .pricing import fee_ceiling_check  # noqa: E402
from .waterfall import allocate_loss  # noqa: E402

# Categorical slots 1-3 of the validated reference palette (light mode; the handover asks for a white page).
C_RESERVE, C_GUARANTOR, C_FINANCIER = "#2a78d6", "#eb6834", "#1baf7a"
C_LOW, C_HIGH = "#2a78d6", "#eb6834"
INK, INK2, GRID = "#111", "#52514e", "#e4e4e0"

SIM_CSS = """
.chart{margin:8px 0 4px} .chart svg{width:100%;height:auto;display:block}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:#52514e;margin:4px 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
details{margin:4px 0 12px;font-size:13px} summary{cursor:pointer;color:#52514e}
.lead{font-size:15px;max-width:720px}
.sliders{border:1px solid #ccc;padding:12px 14px;margin:8px 0}
.sliders label{display:grid;grid-template-columns:200px 1fr 90px;gap:10px;align-items:center;margin:6px 0}
.verdict{border:3px solid;border-radius:6px;padding:10px 14px;margin:10px 0;font-weight:700;font-size:15px}
.verdict.v0{border-color:#b42318;color:#b42318;background:#fff5f4}.verdict.v1{border-color:#b54708;color:#b54708;background:#fdf6ec}
.verdict.v2{border-color:#16794a;color:#16794a;background:#eef8f2}
.sliders input{width:100%} .sliders output{font-weight:600;text-align:right;font-variant-numeric:tabular-nums}
@media (max-width:560px){.sliders label{grid-template-columns:1fr 70px}.sliders label span{grid-column:1/3}}
"""


def _rm(v: float) -> str:
    return fmt(v, "rm")


def _legend(items: list[tuple[str, str]]) -> str:
    return '<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{esc(t)}</span>' for t, c in items) + "</div>"


def _nice_step(span: float, n: int = 5) -> float:
    raw = span / n if span > 0 else 1
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def chart_histogram(values: list[float], marks: list[tuple[float, str]], bins: int = 30) -> str:
    """Histogram of total loss per cohort, with vertical reference lines (reserve, reserve + guarantor cap)."""
    W, L, R, B = 640, 52, 16, 40
    T = 10 + 14 * len(marks)            # one label row per reference line, above the bars
    H = 230 + T
    hi = max(values + [m for m, _ in marks] + [1.0]) * 1.02
    width = hi / bins
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, int(v / width))] += 1
    top = max(counts) or 1
    pw, ph = W - L - R, H - T - B
    x = lambda v: L + pw * v / hi  # noqa: E731
    y = lambda c: T + ph * (1 - c / top)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Histogram of total loss per cohort">']
    ystep = max(1, int(_nice_step(top, 4)))
    for c in range(0, top + 1, ystep):
        out.append(f'<line x1="{L}" x2="{W-R}" y1="{y(c):.1f}" y2="{y(c):.1f}" stroke="{GRID}"/>'
                   f'<text x="{L-6}" y="{y(c)+4:.1f}" text-anchor="end">{c}</text>')
    xstep = _nice_step(hi, 5)
    v = 0.0
    while v <= hi:
        out.append(f'<text x="{x(v):.1f}" y="{H-B+16}" text-anchor="middle">RM{v/1000:,.0f}k</text>')
        v += xstep
    for i, c in enumerate(counts):
        if c:
            x0, x1 = x(i * width) + 1, x((i + 1) * width) - 1
            out.append(f'<rect x="{x0:.1f}" y="{y(c):.1f}" width="{max(0.5, x1-x0):.1f}" height="{T+ph-y(c):.1f}" '
                       f'rx="2" fill="{C_RESERVE}"><title>RM{i*width:,.0f}–RM{(i+1)*width:,.0f}: {c} runs</title></rect>')
    for i, (m, label) in enumerate(marks):
        ty = 12 + 14 * i
        out.append(f'<line x1="{x(m):.1f}" x2="{x(m):.1f}" y1="{ty+3}" y2="{T+ph}" stroke="{INK}" stroke-dasharray="4 3"/>'
                   + (f'<text x="{x(m)-4:.1f}" y="{ty}" text-anchor="end" fill="{INK}">{esc(label)}</text>'
                      if x(m) > W - R - 170 else f'<text x="{x(m)+4:.1f}" y="{ty}" fill="{INK}">{esc(label)}</text>'))
    out.append(f'<line x1="{L}" x2="{W-R}" y1="{T+ph}" y2="{T+ph}" stroke="{INK2}"/>'
               f'<text x="{L+pw/2}" y="{H-6}" text-anchor="middle" fill="{INK2}">Total loss in one cohort</text>'
               f'<text x="12" y="{T+ph/2}" transform="rotate(-90 12 {T+ph/2})" text-anchor="middle" fill="{INK2}">Runs</text></svg>')
    return "".join(out)


def chart_layers(rows: list[tuple[str, dict]]) -> str:
    """Stacked horizontal bars: who absorbs the loss in each named run."""
    W, L, R, bar, gap, T = 640, 120, 16, 30, 26, 10
    H = T + len(rows) * (bar + gap) + 20
    hi = max([sum(a.values()) for _, a in rows] + [1.0])
    pw = W - L - R
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Who absorbs the loss">']
    for i, (label, a) in enumerate(rows):
        y0 = T + i * (bar + gap)
        out.append(f'<text x="{L-8}" y="{y0+bar/2+4}" text-anchor="end" fill="{INK}">{esc(label)}</text>')
        xc = L
        for key, colour, name in (("first_loss", C_RESERVE, "First-loss reserve"),
                                  ("guarantor", C_GUARANTOR, "Guarantor"), ("financier", C_FINANCIER, "Financier")):
            w = pw * a[key] / hi
            if w > 0.5:
                out.append(f'<rect x="{xc:.1f}" y="{y0}" width="{max(0.5, w-2):.1f}" height="{bar}" rx="2" fill="{colour}">'
                           f'<title>{name}: RM{a[key]:,.0f}</title></rect>')
                if w > 70:
                    out.append(f'<text x="{xc+6:.1f}" y="{y0+bar/2+4}" fill="#fff" style="fill:#fff;font-weight:600">'
                               f'RM{a[key]:,.0f}</text>')
            xc += w
        out.append(f'<text x="{min(xc+6, W-R):.1f}" y="{y0+bar+14}" text-anchor="end" fill="{INK2}">'
                   f'total RM{sum(a.values()):,.0f}</text>')
    out.append("</svg>")
    return "".join(out)


SENS_LABEL = {"bypass_probability": "Bypass probability", "recovery_rate": "Recovery rate (non-on-time)",
              "first_loss_reserve": "First-loss reserve", "flat_fee": "Flat fee per bridge"}


def chart_sensitivity(rows: list[dict], metric: str = "financier_net_per_bridge") -> str:
    """Tornado: financier net result per bridge when each input moves -25% and +25%."""
    W, L, R, bar, gap, T = 640, 190, 70, 14, 16, 22
    H = T + len(rows) * (2 * bar + gap) + 26
    base = rows[0]["base"][metric]
    vals = [r[k][metric] for r in rows for k in ("low", "high")] + [base]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.25 or 1        # room inside the plot for the value labels
    lo, hi = lo - pad, hi + pad
    pw = W - L - R
    x = lambda v: L + pw * (v - lo) / (hi - lo)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Sensitivity of financier result per bridge">']
    xstep = _nice_step(hi - lo, 5)
    v = math.ceil(lo / xstep) * xstep
    while v <= hi:
        out.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{T-6}" y2="{H-22}" stroke="{GRID}"/>'
                   f'<text x="{x(v):.1f}" y="{H-8}" text-anchor="middle">{"−" if v < 0 else ""}RM{abs(v):,.0f}</text>')
        v += xstep
    for i, r in enumerate(rows):
        y0 = T + i * (2 * bar + gap)
        out.append(f'<text x="{L-10}" y="{y0+bar+4}" text-anchor="end" fill="{INK}">{esc(SENS_LABEL[r["param"]])}</text>')
        for j, (k, colour, tag) in enumerate((("low", C_LOW, "−25%"), ("high", C_HIGH, "+25%"))):
            v = r[k][metric]
            x0, x1 = sorted((x(base), x(v)))
            yy = y0 + j * bar
            out.append(f'<rect x="{x0:.1f}" y="{yy+1}" width="{max(1.0, x1-x0):.1f}" height="{bar-2}" rx="2" fill="{colour}">'
                       f'<title>{SENS_LABEL[r["param"]]} {tag}: RM{v:,.2f} per bridge</title></rect>'
                       f'<text x="{(x1+4) if v >= base else (x0-4):.1f}" y="{yy+bar-3}" '
                       f'text-anchor="{"start" if v >= base else "end"}" fill="{INK2}">{tag} {"−" if v < 0 else ""}RM{abs(v):,.0f}</text>')
    out.append(f'<line x1="{x(base):.1f}" x2="{x(base):.1f}" y1="{T-10}" y2="{H-22}" stroke="{INK}"/>'
               f'<text x="{x(base):.1f}" y="{T-12}" text-anchor="middle" fill="{INK}">base RM{base:,.0f}</text></svg>')
    return "".join(out)


def _inputs_rows(cfg: dict) -> list[list[str]]:
    g = lambda k: get(cfg, k)  # noqa: E731
    probs = g("simulation.outcome_probs") or {}
    rec = g("simulation.recovery_rate_by_outcome") or {}
    dist = g("simulation.amount_distribution") or {}
    dep = g("simulation.deposit_share_of_materials") or {}
    return [
        ["Cohorts simulated × jobs offered", f'{g("simulation.n_runs"):,} × {g("simulation.n_bridges")}', "simulation"],
        ["Seed", esc(g("simulation.seed")), "simulation.seed"],
        ["Materials cost per job", f'lognormal, median {_rm(math.exp(dist.get("mean", 0)))}, σ {dist.get("sigma")}',
         "simulation.amount_distribution"],
        ["Deposit as share of materials", f'uniform {fmt(dep.get("low"), "pct")}–{fmt(dep.get("high"), "pct")}',
         "simulation.deposit_share_of_materials"],
        ["Deposit applied to materials", fmt(g("screen.deposit_to_materials_share"), "pct"), "screen.deposit_to_materials_share"],
        ["Margin of advance", f'up to {fmt(g("release.margin_of_advance"), "pct")} of quoted materials', "release.margin_of_advance"],
        ["Per-bridge cap / cohort cap", f'{_rm(g("caps.per_bridge"))} / {_rm(g("caps.per_sponsor_cohort"))}', "caps"],
        ["Outcome probabilities", ", ".join(f"{k.replace('_', ' ')} {v:.0%}" for k, v in probs.items()), "simulation.outcome_probs"],
        ["Recovery rate by outcome", ", ".join(f"{k.replace('_', ' ')} {v:.0%}" for k, v in rec.items()),
         "simulation.recovery_rate_by_outcome"],
        ["First-loss reserve (per cohort)", _rm(g("layers.first_loss_reserve")), "layers.first_loss_reserve"],
        ["Guarantor", (f'on: {fmt(g("layers.guarantor_cover_pct"), "pct")} of loss above reserve, cap {_rm(g("layers.guarantor_cap"))}'
                       if g("layers.guarantor_enabled") else "off"), "layers"],
        ["Flat fee / cost to serve per bridge", f'{_rm(g("pricing.flat_fee_per_bridge"))} / {_rm(g("pricing.cost_to_serve_per_bridge"))}',
         "pricing"],
        ["Guarantee fee on drawn amount", f'{fmt(g("pricing.guarantee_fee_rate_on_drawn"), "pct")} a year', "pricing.guarantee_fee_rate_on_drawn"],
        ["Typical days to repayment", esc(g("tenor.typical_days")), "tenor.typical_days"],
        ["Bypass stop line", (f'pause above {fmt(g("stop_lines.pause_if_bypass_rate_over"), "pct")} after '
                              f'{g("stop_lines.bypass_rate_min_bridges")} bridges') if g("stop_lines.pause_if_bypass_rate_over") is not None
         else "off", "stop_lines"],
    ]


def _results_rows(s: dict) -> list[list[str]]:
    rows = []
    for key, label in (("total_loss", "Total loss"), ("reserve_drawdown", "First-loss reserve used"),
                       ("guarantor_draw", "Guarantor draw"), ("financier_loss", "Financier loss"),
                       ("financier_net", "Financier net result"), ("released", "Amount released")):
        d = s[key]
        rows.append([label] + [_rm(d[k]) for k in ("mean", "p5", "p50", "p95")])
    d = s["bridges_per_run"]
    rows.append(["Bridges released"] + [fmt(round(d[k])) for k in ("mean", "p5", "p50", "p95")])
    return rows


def _market_rows(cfg: dict, s: dict) -> tuple[str, list[list[str]]]:
    mr = get(cfg, "market_reference") or {}
    status_note = ("approved by the author" if mr.get("approved_by_author")
                   else "PENDING AUTHOR APPROVAL: public sources, not yet checked by the author")
    rows = [["Margin of advance", f'up to {fmt(get(cfg, "release.margin_of_advance"), "pct")} of quoted materials cost; '
             f'{fmt(s["advance_share_of_materials"], "pct")} on average after the deposit', "this engine (setting)"]]
    for m in mr.get("margin_of_advance") or []:
        rows.append(["", f'up to {fmt(m["max"], "pct")} of {esc(m["basis"])}', esc(m["source"])])
    rows.append(["Borrower cost a month", f'{fmt(s["borrower_monthly_cost"], "pct")} (flat fee + guarantee fee on the average bridge)',
                 "this engine (result)"])
    for m in mr.get("monthly_cost") or []:
        rng = fmt(m["low"], "pct") if m["low"] == m["high"] else f'{fmt(m["low"], "pct")}–{fmt(m["high"], "pct")}'
        rows.append(["", f'{rng}{"; plus " + esc(m["plus"]) if m.get("plus") else ""}', esc(m["source"])])
    return status_note, rows


def _binding_note(cfg: dict) -> str:
    """Above this margin of advance the setting cannot bind: the deposit already covers the rest."""
    low = (get(cfg, "simulation.deposit_share_of_materials") or {}).get("low")
    share = get(cfg, "screen.deposit_to_materials_share")
    if low is None or share is None:
        return ""
    ceiling = 1 - low * share
    return (f'<p class="note">With every simulated deposit at least {fmt(low, "pct")} of materials, the bridge never needs '
            f'more than {fmt(ceiling, "pct")} of the materials cost, so a margin of advance above that changes nothing.</p>')


def _slider_block(grid: dict, cfg: dict) -> str:
    def nearest(lst, v):
        return min(range(len(lst)), key=lambda i: abs(lst[i] - (v or 0)))
    axes = [("margin_of_advance", "Margin of advance", "pct", get(cfg, "release.margin_of_advance")),
            ("flat_fee_per_bridge", "Flat fee per bridge", "rm", get(cfg, "pricing.flat_fee_per_bridge")),
            ("first_loss_reserve", "First-loss reserve", "rm", get(cfg, "layers.first_loss_reserve"))]
    ctl = []
    for key, label, kind, cur in axes:
        lst = grid[key]
        i = nearest(lst, cur)
        ctl.append(f'<label><span>{esc(label)}</span><input type="range" id="s_{key}" min="0" max="{len(lst)-1}" step="1" '
                   f'value="{i}" aria-label="{esc(label)}"><output id="o_{key}">{fmt(lst[i], kind)}</output></label>')
    outs = [("advance_share", "Average advance, share of materials", "pct"),
            ("avg_bridge", "Average bridge", "rm"),
            ("financier_net_per_bridge", "Financier net result per bridge", "rm"),
            ("financier_net_mean", "Financier net result per cohort (mean)", "rm"),
            ("financier_loss_p95", "Financier loss, bad cohort (p95)", "rm"),
            ("p_reserve_exhausted", "Chance the reserve is used up", "pct"),
            ("breakeven_flat_fee", "Break-even flat fee", "rm"),
            ("borrower_monthly_cost", "Borrower cost a month", "pct")]
    base_key = "|".join(str(grid[k][nearest(grid[k], cur)]) for k, _, _, cur in axes)
    base = grid["cells"][base_key]
    trs = "".join(f'<tr><td>{esc(lbl)}</td><td class="n" id="r_{k}">{fmt(base[k], kind)}</td></tr>' for k, lbl, kind in outs)
    # Key the cells by slider position, not by value: Python writes 1.0 where JavaScript writes 1.
    keys = [k for k, _, _, _ in axes]
    by_index = {}
    for i, a in enumerate(grid[keys[0]]):
        for j, b in enumerate(grid[keys[1]]):
            for k, c in enumerate(grid[keys[2]]):
                cell = grid["cells"][f"{a}|{b}|{c}"]
                by_index[f"{i}|{j}|{k}"] = {n: round(v, 6) for n, v in cell.items()}
    data = _json.dumps({"axes": {k: grid[k] for k, _, _, _ in axes}, "kinds": {k: kind for k, _, kind in outs},
                        "cells": by_index},
                       separators=(",", ":"))
    js = """
(function(){var D=JSON.parse(document.getElementById('grid').textContent);
var ax=['margin_of_advance','flat_fee_per_bridge','first_loss_reserve'],kind={margin_of_advance:'pct',flat_fee_per_bridge:'rm',first_loss_reserve:'rm'};
function f(v,k){if(k==='pct')return (v<0?'\\u2212':'')+(Math.abs(v)*100).toFixed(1)+'%';var a=Math.abs(v).toLocaleString('en-MY',{maximumFractionDigits:0});return (v<0?'\\u2212RM':'RM')+a;}
function upd(){var key=ax.map(function(a){var i=+document.getElementById('s_'+a).value;document.getElementById('o_'+a).textContent=f(D.axes[a][i],kind[a]);return i;}).join('|');
var c=D.cells[key];if(!c)return;for(var k in D.kinds){var el=document.getElementById('r_'+k);if(el)el.textContent=f(c[k],D.kinds[k]);}}
ax.forEach(function(a){document.getElementById('s_'+a).addEventListener('input',upd);});upd();})();
"""
    return (f'<div class="sliders">{"".join(ctl)}</div>'
            f'<div class="wrap"><table><thead><tr><th>Result</th><th>Value</th></tr></thead><tbody>{trs}</tbody></table></div>'
            f'<script type="application/json" id="grid">{data}</script><script>{js}</script>')


def _dev_block(dev_grid: dict, cfg: dict) -> str:
    """Developmental pricing section (A13): the planned loss the funders accept, with sliders over a precomputed grid."""
    ax = dev_grid["axes"]
    cur = {"guarantor_cover_pct": get(cfg, "layers.guarantor_cover_pct"), "all_in_cap_pa": get(cfg, "pricing.all_in_rate_cap_pa"),
           "guarantee_fee_pa": get(cfg, "pricing.guarantee_fee_rate_on_drawn"),
           "cost_to_serve_per_bridge": get(cfg, "pricing.cost_to_serve_per_bridge")}
    spec = [("guarantor_cover_pct", "Guarantor covers", "pct"), ("all_in_cap_pa", "All-in cap on the borrower, a year", "pct"),
            ("guarantee_fee_pa", "Guarantee fee, a year", "pct"), ("cost_to_serve_per_bridge", "Cost to serve per loan", "rm")]

    def near(lst, v):
        return min(range(len(lst)), key=lambda i: abs(lst[i] - (v or 0)))
    ctl = []
    for key, label, kind in spec:
        lst = ax[key]; i = near(lst, cur[key])
        ctl.append(f'<label><span>{esc(label)}</span><input type="range" id="dv_{key}" min="0" max="{len(lst)-1}" step="1" '
                   f'value="{i}" aria-label="{esc(label)}"><output id="dvo_{key}">{fmt(lst[i], kind)}</output></label>')
    rows = [("borrower_per_loan", "Borrower pays per loan, all-in", "rm"),
            ("guarantee_fee_per_loan", "…of which guarantee fee (to the guarantor)", "rm"),
            ("financier_fee_per_loan", "…of which financier fee", "rm"),
            ("financier_net_mean", "Financier net per group (mean)", "rm"),
            ("financier_net_p5", "Financier net, bad group (p5)", "rm"),
            ("financier_return_pa", "Financier net return a year on drawn, before funding cost", "pct"),
            ("guarantor_net_mean", "Guarantor net per group (mean)", "rm"),
            ("guarantor_return_pa", "Guarantor net return a year on drawn", "pct"),
            ("funders_net_mean", "DFI + guarantor combined net per group", "rm"),
            ("sponsor_reserve_used_mean", "First-loss reserve used per group (DFI + guarantor money)", "rm"),
            ("programme_net_mean", "Whole programme net per group (DFI + guarantor, the reserve included)", "rm"),
            ("programme_cost_per_loan", "Planned programme cost per loan (+ = a loss)", "rm"),
            ("programme_cost_per_1000_lent", "Planned programme cost per RM1,000 lent", "rm"),
            ("p_group_loses", "Chance the DFI and guarantor lose money in a group", "pct"),
            ("p_over_budget", "Chance the programme loss (reserve included) is above the agreed budget", "pct"),
            ("breakeven_cost_to_serve", "Cost to serve at which the financier alone breaks even", "rm"),
            ("cost_per_additional_loan_100", "Cost per additional loan if all borrowers are additional (illustration)", "rm"),
            ("cost_per_additional_loan_50", "…if half are (illustration)", "rm"),
            ("cost_per_additional_loan_25", "…if a quarter are (illustration)", "rm")]
    trs = "".join(f'<tr><td>{esc(lbl)}</td><td class="n" id="dr_{k}">—</td></tr>' for k, lbl, _ in rows)
    idx = {}
    n_a, n_g, n_s = len(ax["all_in_cap_pa"]), len(ax["guarantee_fee_pa"]), len(ax["cost_to_serve_per_bridge"])
    cells = {k: (None if v is None else {n: (None if x is None else round(x, 4)) for n, x in v.items()})
             for k, v in dev_grid["cells"].items()}
    data = _json.dumps({"axes": ax, "kinds": {k: kind for k, _, kind in rows}, "cells": cells,
                        "budget": dev_grid["budget"]}, separators=(",", ":"))
    js = """
(function(){var D=JSON.parse(document.getElementById('dgrid').textContent);
var ax=['guarantor_cover_pct','all_in_cap_pa','guarantee_fee_pa','cost_to_serve_per_bridge'],kind={guarantor_cover_pct:'pct',all_in_cap_pa:'pct',guarantee_fee_pa:'pct',cost_to_serve_per_bridge:'rm'};
function f(v,k){if(v===null||v===undefined)return '\u2014';if(k==='pct')return (v<0?'\\u2212':'')+(Math.abs(v)*100).toFixed(1)+'%';var a=Math.abs(v).toLocaleString('en-MY',{maximumFractionDigits:v!==0&&Math.abs(v)<10?1:0});return (v<0?'\u2212RM':'RM')+a;}
function upd(){var key=ax.map(function(a){var i=+document.getElementById('dv_'+a).value;document.getElementById('dvo_'+a).textContent=f(D.axes[a][i],kind[a]);return i;}).join('|');
var c=D.cells[key];var note=document.getElementById('dnote');
if(!c){note.style.display='block';for(var k in D.kinds){document.getElementById('dr_'+k).textContent='\u2014';}return;}
note.style.display='none';for(var k in D.kinds){document.getElementById('dr_'+k).textContent=f(c[k],D.kinds[k]);}}
ax.forEach(function(a){document.getElementById('dv_'+a).addEventListener('input',upd);});upd();})();
"""
    budget = dev_grid["budget"]
    return (
        '<div class="banner syn" style="border-color:#13263a;color:#13263a">DEVELOPMENTAL PRICING: this product is priced below a commercial '
        "return on purpose. The funders accept a planned loss in return for additionality.</div>"
        '<p class="note">The DFI and the guarantor knowingly price at or below cost to reach borrowers the market does not serve. '
        "This section shows that planned loss, counting everything the DFI and the guarantor put in, the reserve included (they are the sponsors): it is the price, not a forecast. It assumes <strong>no</strong> additionality; whether the bridge "
        "reaches new-to-credit borrowers and unlocks jobs is measured in the pilot (gate 4), and the cost per additional borrower below is an "
        "illustration across shares, not a finding. The borrower's all-in charge is capped: financier fee + guarantee fee ≤ the cap, charged on "
        "the drawn amount, simple interest."
        + (f" Funders' loss budget per cohort: {_rm(budget)}." if budget is not None else " No loss budget is set yet.") + "</p>"
        f'<div class="sliders">{"".join(ctl)}</div>'
        '<p id="dnote" class="note" style="display:none;color:#b00">The guarantee fee is above the all-in cap, so nothing is left for the financier. Choose a lower guarantee fee or a higher cap.</p>'
        f'<div class="wrap"><table><thead><tr><th>Result</th><th>Value</th></tr></thead><tbody>{trs}</tbody></table></div>'
        f'<script type="application/json" id="dgrid">{data}</script><script>{js}</script>')


def _damage_block(dg: dict, cfg: dict) -> str:
    """Damage rate, loss per damaged loan and the loss trip wire (A14), with sliders over a precomputed grid."""
    ax = dg["axes"]

    def near(lst, v):
        return min(range(len(lst)), key=lambda i: abs((lst[i] if lst[i] is not None else -1) - (v if v is not None else -1)))
    base_damage = (get(cfg, "simulation.outcome_probs.dispute") or 0) + (get(cfg, "simulation.outcome_probs.abandoned") or 0)
    start = {"damage_rate": near(ax["damage_rate"], base_damage), "loss_per_damaged_loan": near(ax["loss_per_damaged_loan"], 0.5),
             "trip_wire": near(ax["trip_wire"], get(cfg, "stop_lines.pause_if_loss_rate_over"))}
    spec = [("damage_rate", "Damage rate (not completed or rejected)", "pct"),
            ("loss_per_damaged_loan", "Lost on each damaged loan", "pct"),
            ("trip_wire", "Trip wire: pause new loans above this loss", "wire")]
    ctl = []
    for key, label, kind in spec:
        lst = ax[key]
        txt = "off" if lst[start[key]] is None else f"{lst[start[key]]:.1%}".replace(".0%", "%")
        ctl.append(f'<label><span>{esc(label)}</span><input type="range" id="dm_{key}" min="0" max="{len(lst)-1}" step="1" '
                   f'value="{start[key]}" aria-label="{esc(label)}"><output id="dmo_{key}">{txt}</output></label>')
    rows = [("loans", "Loans released per group (reach)", "num"), ("lent", "Money lent per group", "rm"),
            ("loss", "Loss per group", "rm"), ("loss_pct_lent", "Loss as a share of money lent", "pct"),
            ("p_tripped", "Chance the trip wire fires", "pct"), ("median_loans_at_trip", "Loans released when it fires (median)", "num"),
            ("loss_avoided", "Loss avoided by the trip wire, per group", "rm"),
            ("loans_given_up", "Loans given up by the trip wire, per group", "num"),
            ("p_reserve_out", "Chance the reserve runs out", "pct"), ("reserve_used", "Reserve used per group", "rm"),
            ("financier_return_pa", "DFI net return a year on drawn, before funding cost", "pct"),
            ("guarantor_return_pa", "Guarantor net return a year on drawn", "pct"),
            ("programme_cost_per_1000_lent", "Planned programme cost per RM1,000 lent", "rm"),
            ("p_over_budget", "Chance the programme loss (reserve included) is above the agreed budget", "pct")]
    trs = "".join(f'<tr><td>{esc(lbl)}</td><td class="n" id="dmr_{k}">—</td></tr>' for k, lbl, _ in rows)
    cells = {k: (None if v is None else {n: (None if x is None else round(x, 4)) for n, x in v.items()}) for k, v in dg["cells"].items()}
    data = _json.dumps({"axes": ax, "kinds": {k: kind for k, _, kind in rows}, "cells": cells}, separators=(",", ":"))
    js = """
(function(){var D=JSON.parse(document.getElementById('mgrid').textContent);
var ax=['damage_rate','loss_per_damaged_loan','trip_wire'];
function f(v,k){if(v===null||v===undefined)return '\u2014';if(k==='pct')return (v<0?'\\u2212':'')+(Math.abs(v)*100).toFixed(1)+'%';if(k==='num')return v.toLocaleString('en-MY',{maximumFractionDigits:1});var a=Math.abs(v).toLocaleString('en-MY',{maximumFractionDigits:v!==0&&Math.abs(v)<10?1:0});return (v<0?'\u2212RM':'RM')+a;}
function lab(a,v){return v===null?'off':(v*100).toFixed(1).replace('.0','')+'%';}
function upd(){var key=ax.map(function(a){var i=+document.getElementById('dm_'+a).value;document.getElementById('dmo_'+a).textContent=lab(a,D.axes[a][i]);return i;}).join('|');
var c=D.cells[key],note=document.getElementById('mnote');
if(!c){note.style.display='block';for(var k in D.kinds){document.getElementById('dmr_'+k).textContent='\u2014';}return;}
note.style.display='none';for(var k in D.kinds){document.getElementById('dmr_'+k).textContent=f(c[k],D.kinds[k]);}}
ax.forEach(function(a){document.getElementById('dm_'+a).addEventListener('input',upd);});upd();})();
"""
    return (
        '<p class="note">A <strong>trip wire</strong> pauses new loans when the loss so far, after recoveries, passes a line, counted as a share of the '
        "money lent on loans whose outcome is already known. It trades <strong>reach for loss</strong>: every loan not made is a borrower not reached, "
        "which is what developmental pricing is paying for. It also cannot stop loans already out: outcomes arrive about "
        f"{dg['lag']} loans late here, and the wire cannot fire before {dg['min_loans']} loans have a known outcome. "
        "Damage is the two endings abandoned and rejected; late payments and cash to the painter keep the chances in the config. "
        "Each setting is run on the same random draws as the no-trip-wire case, so the loss avoided and loans given up are paired, not noise.</p>"
        f'<div class="sliders">{"".join(ctl)}</div>'
        '<p id="mnote" class="note" style="display:none;color:#b00">Damage, late and cash chances add to more than 100% for this setting.</p>'
        f'<div class="wrap"><table><thead><tr><th>Result</th><th>Value</th></tr></thead><tbody>{trs}</tbody></table></div>'
        f'<script type="application/json" id="mgrid">{data}</script><script>{js}</script>')


def _round_deep(x, nd=4):
    if isinstance(x, dict):
        return {k: _round_deep(v, nd) for k, v in x.items()}
    return round(x, nd) if isinstance(x, float) else x


RR_ROWS = [  # label, DFI key, guarantor key, kind
    ("Fee earned per loan", "fee_per_loan", "fee_per_loan", "rm"),
    ("Income per group", "income", "income", "rm"),
    ("Operating cost per group (DFI: cost to serve, guarantor: admin)", "cost_to_serve", "admin_cost", "rm"),
    ("Funding cost per group (the DFI's debt)", "funding_cost", None, "rm"),
    ("Credit loss taken per group", "credit_loss", "credit_loss", "rm"),
    ("Result per group, before the cost of capital", "result", "result", "rm"),
    ("Capital employed (the DFI's equity, the guarantor's cap)", "capital", "capital", "rm"),
    ("Return on capital, a year", "return_on_capital_pa", "return_on_capital_pa", "pct"),
    ("Required return (its hurdle)", "hurdle", "hurdle", "pct"),
    ("Spread over the hurdle", "spread", "spread", "pct"),
    ("Economic profit per group, after the cost of capital", "economic_profit", "economic_profit", "rm"),
    ("Risk: a bad group (5th percentile result)", "p5", "p5", "rm"),
    ("Risk: average of the worst 5% of groups", "es5", "es5", "rm"),
    ("Risk: chance of a loss-making group", "p_loss", "p_loss", "pct"),
    ("Return per unit of risk (mean ÷ standard deviation)", "return_per_risk", "return_per_risk", "ratio"),
    ("Fee charged, a year on the drawn amount", "fee_pa", "fee_pa", "pct"),
    ("Break-even fee, a year (economic profit zero)", "break_even_fee_pa", "break_even_fee_pa", "pct"),
    ("Reserve funded up front by this party", "ar_committed", "ar_committed", "rm"),
    ("Reserve spent, this party's share, per group", "ar_spent", "ar_spent", "rm"),
    ("Result per group AFTER funding the reserve", "ar_result", "ar_result", "rm"),
    ("Return on capital AFTER funding the reserve, a year", "ar_return_on_capital_pa", "ar_return_on_capital_pa", "pct"),
    ("Spread over the hurdle AFTER funding the reserve", "ar_spread", "ar_spread", "pct"),
    ("Economic profit per group AFTER funding the reserve", "ar_economic_profit", "ar_economic_profit", "rm"),
    ("Break-even fee AFTER funding the reserve, a year", "ar_break_even_fee_pa", "ar_break_even_fee_pa", "pct"),
]


def _rr_block(rg: dict, cfg: dict) -> str:
    """Risk and return for the DFI and the guarantor, each with its own costs (A15), with sliders over a precomputed grid."""
    ax = dg_ax = rg["axes"]
    cur = {"guarantor_cover_pct": get(cfg, "layers.guarantor_cover_pct"), "all_in_cap_pa": get(cfg, "pricing.all_in_rate_cap_pa"),
           "guarantee_fee_pa": get(cfg, "pricing.guarantee_fee_rate_on_drawn"), "cost_to_serve_per_bridge": get(cfg, "pricing.cost_to_serve_per_bridge")}
    spec = [("guarantor_cover_pct", "Guarantor covers", "pct"), ("all_in_cap_pa", "All-in cap on the borrower, a year", "pct"),
            ("guarantee_fee_pa", "Guarantee fee, a year", "pct"), ("cost_to_serve_per_bridge", "Cost to serve per loan (the DFI bears it)", "rm")]
    near = lambda lst, v: min(range(len(lst)), key=lambda i: abs(lst[i] - (v or 0)))  # noqa: E731
    ctl = []
    for key, label, kind in spec:
        lst = ax[key]; i = near(lst, cur[key])
        ctl.append(f'<label><span>{esc(label)}</span><input type="range" id="rr_{key}" min="0" max="{len(lst)-1}" step="1" value="{i}" '
                   f'aria-label="{esc(label)}"><output id="rro_{key}">{fmt(lst[i], kind)}</output></label>')
    trs = "".join(f'<tr><td>{esc(lbl)}</td><td class="n" id="rrd_{dk}">—</td><td class="n" id="rrg_{gk or dk}">{"—" if gk else "n/a"}</td></tr>'
                  for lbl, dk, gk, _ in RR_ROWS)
    kinds = {(gk or dk): kind for _, dk, gk, kind in RR_ROWS} | {dk: kind for _, dk, gk, kind in RR_ROWS}
    cells = {k: (None if v is None else _round_deep(v)) for k, v in rg["cells"].items()}
    data = _json.dumps({"axes": ax, "kinds": kinds, "rows": [[dk, gk] for _, dk, gk, _ in RR_ROWS], "cells": cells}, separators=(",", ":"))
    js = """
(function(){var D=JSON.parse(document.getElementById('rgrid').textContent);
var ax=['guarantor_cover_pct','all_in_cap_pa','guarantee_fee_pa','cost_to_serve_per_bridge'],kind={guarantor_cover_pct:'pct',all_in_cap_pa:'pct',guarantee_fee_pa:'pct',cost_to_serve_per_bridge:'rm'};
function f(v,k){if(v===null||v===undefined)return '\u2014';if(k==='pct')return (v<0?'\\u2212':'')+(Math.abs(v)*100).toFixed(1)+'%';if(k==='ratio')return v.toFixed(2);var a=Math.abs(v).toLocaleString('en-MY',{maximumFractionDigits:v!==0&&Math.abs(v)<10?1:0});return (v<0?'\u2212RM':'RM')+a;}
function set(id,t){var e=document.getElementById(id);if(e)e.textContent=t;}
function upd(){var key=ax.map(function(a){var i=+document.getElementById('rr_'+a).value;set('rro_'+a,f(D.axes[a][i],kind[a]));return i;}).join('|');
var c=D.cells[key],note=document.getElementById('rrnote');
D.rows.forEach(function(r){var k=D.kinds[r[1]||r[0]];set('rrd_'+r[0],c?f(c.dfi[r[0]],D.kinds[r[0]]):'\u2014');if(r[1])set('rrg_'+r[1],c&&c.guarantor?f(c.guarantor[r[1]],D.kinds[r[1]]):'\u2014');});
if(!c){note.style.display='block';['sp','ga','ls','cc','cap','gap','gpl','jr','cc2','gap2','gpl2'].forEach(function(x){set('rrx_'+x,'\u2014');});return;}note.style.display='none';
set('rrx_sp',f(c.loss_split.reserve,'pct'));set('rrx_ga',f(c.loss_split.guarantor,'pct'));set('rrx_ls',f(c.loss_split.dfi,'pct'));
set('rrx_cc',f(c.cost_covering_all_in_pa,'pct'));set('rrx_cap',f(c.all_in_cap_pa,'pct'));set('rrx_gap',f(c.gap_pa,'pct'));set('rrx_gpl',f(c.gap_per_loan,'rm'));set('rrx_jr',f(c.joint_result,'rm'));set('rrx_cc2',f(c.cost_covering_all_in_after_reserve_pa,'pct'));set('rrx_gap2',f(c.gap_after_reserve_pa,'pct'));set('rrx_gpl2',f(c.gap_after_reserve_per_loan,'rm'));}
ax.forEach(function(a){document.getElementById('rr_'+a).addEventListener('input',upd);});upd();})();
"""
    return (
        '<p class="note"><strong>Each party carries its own costs.</strong> The DFI pays interest on the debt that funds the loans, holds equity '
        'against them, and bears the cost to serve. The guarantor sets its cap aside as capital for the length of a cohort and pays an admin cost per bridge. '
        'The costs are <strong>demo placeholders</strong>, empty in the real template: the DFI and the guarantor must supply their own. '
        'Return on capital is compared with each party\'s required return, and the gap is the spread it earns. Risk is shown as a bad group, the average of the '
        'worst 5% of groups, and the chance of a loss-making group. The DFI and the guarantor are the sponsors: they fund the first-loss reserve between them, so the last rows show each party <strong>after funding its share</strong>.</p>'
        f'<div class="sliders">{"".join(ctl)}</div>'
        '<p id="rrnote" class="note" style="display:none;color:#b00">The guarantee fee is above the all-in cap here, so nothing is left for the DFI.</p>'
        f'<div class="wrap"><table><thead><tr><th>Per group of loans</th><th>DFI</th><th>Guarantor</th></tr></thead><tbody>{trs}</tbody></table></div>'
        '<h3>Who takes the credit loss, and what price covers every cost</h3>'
        '<div class="wrap"><table><tbody>'
        '<tr><td>Share of the credit loss: the reserve (DFI + guarantor money) / guarantor above it / DFI above it</td><td class="n"><span id="rrx_sp">—</span> / <span id="rrx_ga">—</span> / <span id="rrx_ls">—</span></td></tr>'
        '<tr><td>All-in rate that would cover every cost BEFORE funding the reserve (both break-even fees added)</td><td class="n" id="rrx_cc">—</td></tr>'
        '<tr><td>All-in cap on the borrower</td><td class="n" id="rrx_cap">—</td></tr>'
        '<tr><td>Gap before the reserve: how far below cost the cap is, a year (+ = priced below cost)</td><td class="n" id="rrx_gap">—</td></tr>'
        '<tr><td>The same gap per loan: what developmental pricing deliberately gives up</td><td class="n" id="rrx_gpl">—</td></tr>'
        '<tr><td><strong>Joint result of the two parties per group, after funding the reserve</strong></td><td class="n" id="rrx_jr">—</td></tr>'
        '<tr><td>All-in rate that would cover every cost, including funding the reserve</td><td class="n" id="rrx_cc2">—</td></tr>'
        '<tr><td>Gap to the cap once the reserve is counted, a year</td><td class="n" id="rrx_gap2">—</td></tr>'
        '<tr><td>The same gap per loan, reserve included</td><td class="n" id="rrx_gpl2">—</td></tr>'
        f'</tbody></table></div><script type="application/json" id="rgrid">{data}</script><script>{js}</script>')


VIA_ROWS = [  # label, cell key, kind
    ("What a loan earns at the cap over this tenor (cap × days ÷ 365)", "revenue_pct", "pct"),
    ("Credit loss per loan, as a share of the loan", "loss_pct", "pct"),
    ("Loans released per group", "loans", "num"),
    ("Joint result of the DFI and the guarantor, per loan", "joint_loan", "rm"),
    ("…per RM1,000 lent", "joint_per_1000", "rm"),
    ("…per group of loans", "joint_group", "rm"),
    ("All-in rate that would cover every cost, the reserve included, a year", "rate_needed", "pct"),
    ("Gap to the cap, per loan (+ = priced below cost)", "gap_per_loan", "rm"),
    ("Guarantee fee the guarantor needs for its required return, a year", "guarantor_fee_needed", "pct"),
    ("…and what it is charged now", "guarantor_fee_now", "pct"),
    ("Financier fee the DFI needs for its required return, a year", "dfi_fee_needed", "pct"),
    ("…and what it is charged now", "dfi_fee_now", "pct"),
    ("At today's split: DFI return on capital after funding the reserve", "dfi_roc", "pct"),
    ("At today's split: guarantor return on capital after funding the reserve", "guarantor_roc", "pct"),
    ("Chance the reserve runs out", "p_reserve_out", "pct"),
    ("Planned cost per additional borrower if all borrowers are additional (illustration)", "per_additional_100", "rm"),
    ("…if half are (illustration)", "per_additional_50", "rm"),
    ("…if a quarter are (illustration)", "per_additional_25", "rm"),
]


def _viability_block(vg: dict, cfg: dict) -> str:
    """Path to viability: can the product work at the cap, and what would it take? Five levers, a verdict, and the fee split that works."""
    ax = vg["axes"]
    probs = get(cfg, "simulation.outcome_probs") or {}
    cur = {"bypass_chance": probs.get("bypass"), "damage_rate": (probs.get("dispute") or 0) + (probs.get("abandoned") or 0),
           "loss_on_bad_loans_scale": 1.0, "tenor_days": get(cfg, "tenor.typical_days"),
           "cost_to_serve_per_bridge": get(cfg, "pricing.cost_to_serve_per_bridge")}
    near = lambda lst, v: min(range(len(lst)), key=lambda i: abs(lst[i] - (v or 0)))  # noqa: E731
    spec = [("bypass_chance", "Customer pays the painter in cash", "pct"), ("damage_rate", "Damage rate (not completed or rejected)", "pct"),
            ("loss_on_bad_loans_scale", "Lost on bad loans (recovery)", "scale"), ("tenor_days", "Tenor of a loan", "days"),
            ("cost_to_serve_per_bridge", "Cost to serve per loan", "rm")]

    def label(kind, v):
        if kind == "pct":
            return f"{v:.1%}".replace(".0%", "%")
        if kind == "scale":
            return "as in the config" if abs(v - 1) < 1e-9 else f"{(1 - v):.0%} less lost"
        if kind == "days":
            return f"{v:.0f} days"
        return fmt(v, "rm")
    ctl = []
    for key, text, kind in spec:
        lst = ax[key]; i = near(lst, cur[key])
        ctl.append(f'<label><span>{esc(text)}</span><input type="range" id="vz_{key}" min="0" max="{len(lst)-1}" step="1" value="{i}" '
                   f'aria-label="{esc(text)}"><output id="vzo_{key}">{esc(label(kind, lst[i]))}</output></label>')
    trs = "".join(f'<tr><td>{esc(lbl)}</td><td class="n" id="vr_{k}_{i}">—</td></tr>' for i, (lbl, k, _) in enumerate(VIA_ROWS))
    cells = {k: (None if v is None else _round_deep(v)) for k, v in vg["cells"].items()}
    labels = {key: [label(kind, v) for v in ax[key]] for key, _, kind in spec}
    data = _json.dumps({"axes": ax, "labels": labels, "cells": cells, "rows": [[k, kind] for _, k, kind in VIA_ROWS],
                        "verdicts": {str(k): v for k, v in vg["verdicts"].items()}, "cap": vg["cap"]}, separators=(",", ":"))
    js = """
(function(){var D=JSON.parse(document.getElementById('vgrid').textContent);
var ax=['bypass_chance','damage_rate','loss_on_bad_loans_scale','tenor_days','cost_to_serve_per_bridge'];
function f(v,k){if(v===null||v===undefined)return '\u2014';if(k==='pct')return (v<0?'\u2212':'')+(Math.abs(v)*100).toFixed(1)+'%';if(k==='num')return v.toLocaleString('en-MY',{maximumFractionDigits:1});var a=Math.abs(v).toLocaleString('en-MY',{maximumFractionDigits:v!==0&&Math.abs(v)<10?1:0});return (v<0?'\u2212RM':'RM')+a;}
function upd(){var key=ax.map(function(a){var i=+document.getElementById('vz_'+a).value;document.getElementById('vzo_'+a).textContent=D.labels[a][i];return i;}).join('|');
var c=D.cells[key],vd=document.getElementById('vv'),note=document.getElementById('vnote');
D.rows.forEach(function(r,i){var e=document.getElementById('vr_'+r[0]+'_'+i);if(e)e.textContent=c?f(c[r[0]],r[1]):'\u2014';});
if(!c){note.style.display='block';vd.style.display='none';return;}note.style.display='none';vd.style.display='block';
vd.className='verdict v'+c.verdict;
var txt=D.verdicts[String(c.verdict)];
if(c.verdict===2){txt+=': the guarantor about '+f(c.guarantor_fee_needed,'pct')+' and the DFI about '+f(c.dfi_fee_needed,'pct')+' a year, which adds up to '+f(c.rate_needed,'pct')+', within the '+f(D.cap,'pct')+' cap.';}
else if(c.verdict===1){txt+=' (the two would need '+f(c.rate_needed,'pct')+' a year against the '+f(D.cap,'pct')+' cap).';}
else{txt+=' by '+f(-c.joint_loan,'rm')+' on every loan.';}
vd.textContent=txt;}
ax.forEach(function(a){document.getElementById('vz_'+a).addEventListener('input',upd);});upd();})();
"""
    return (
        '<p class="note">Can the product work at the all-in cap, and what would it take? <strong>A loan earns by time but loses by the loan</strong>: the cap earns '
        'only a few per cent of a short loan, while cash payments to the painter, damaged projects and a high cost to serve each cost more than that. Move the five '
        'levers and watch the verdict. The DFI and the guarantor are the only funders, so the <strong>joint result</strong> is the real money they lose or earn together. '
        'When a loan can work, the section shows the fee each party would need: the cap has to be <em>split</em> so that both earn their required return, and today\'s split '
        'may not be it. When a gap remains, it is priced per additional borrower, which is what to ask a party that values additionality to pay.</p>'
        '<p class="note">Assumptions: the chance of damage, lateness and cash payments per loan does not change with the tenor, and a longer tenor earns more because '
        'the cap is a rate a year. Both are placeholders until the pilot measures them.</p>'
        f'<div class="sliders">{"".join(ctl)}</div>'
        '<div id="vv" class="verdict v0">—</div>'
        '<p id="vnote" class="note" style="display:none;color:#b00">The cash, damage and late chances add to more than 100% for this setting.</p>'
        f'<div class="wrap"><table><thead><tr><th>Result</th><th>Value</th></tr></thead><tbody>{trs}</tbody></table></div>'
        f'<script type="application/json" id="vgrid">{data}</script><script>{js}</script>')


def _reserve_block(rows: list[dict], cfg: dict) -> str:
    """The reserve, funded by the DFI and the guarantor: what each size costs them and what it does for each (A16, A17)."""
    cur = get(cfg, "layers.first_loss_reserve")
    f0 = rows[0]["funding"]
    returned = f0["is_returned"]
    body = []
    for x in rows:
        f = x["funding"]
        bold = x["reserve"] == cur
        mark = (lambda t: f"<strong>{t}</strong>") if bold else (lambda t: t)  # noqa: E731
        body.append([mark(_rm(x["reserve"]) + (" (config)" if bold else "")), mark(_rm(f["expected_used"])), mark(_rm(f["expected_unused"] if returned else 0)),
                     mark(fmt(f["p_reserve_out"], "pct")), mark(_rm(x["dfi"]["ar_committed"])), mark(_rm(x["guarantor"]["ar_committed"])),
                     mark(fmt(x["dfi_roc"], "pct")), mark(fmt(x["guarantor_roc"], "pct")), mark(_rm(x["joint_result"]))])
    tbl = table(["Reserve funded per cohort", "Expected spent", "Expected returned", "Chance it runs out", "DFI puts up", "Guarantor puts up",
                 "DFI return on capital, after funding it", "Guarantor return on capital, after funding it", "Joint result per group"],
                body, set(range(1, 9)))
    gs = f0["guarantor_share"]
    return (
        '<p class="note"><strong>There is no outside sponsor: the DFI and the guarantor are the sponsors.</strong> They fund the first-loss reserve between them, '
        f'the guarantor {gs:.0%} and the DFI {1 - gs:.0%} here (a placeholder split), <strong>up front, into a ring-fenced account</strong> '
        '(a promise is not enough: the guarantor\'s cover sits on top of it). Losses use it first. '
        + ("What the cohort does not spend <strong>goes back to the two of them</strong> once its loans are closed and recoveries are in. "
           if returned else "Unused reserve is <strong>forfeited</strong> in this configuration, so each party loses its share of that too. ")
        + f"Each party is charged for its money tied up for {f0['hold_days']:.0f} days (the cohort plus the write-off period) at its own required return. "
        "The other columns use the config's own cover, guarantee fee, all-in cap and cost to serve.</p>" + tbl +
        '<p class="note">A bigger reserve is not free here: it is the same two parties\' money. It moves the point where the guarantor starts paying further above '
        'the expected loss, but each party has to put up cash for it. The <strong>joint result</strong> is what the two of them lose or earn together, '
        'so it shows how much real money the programme costs them.</p>')


def render_simulation(out: dict, sens: list[dict], grid, cfg: dict, config_path: str, dev_grid=None, damage_grid=None, rr_grid=None, reserve_rows=None,
                      viability=None) -> str:
    s = out["summary"]
    totals = [r.total_loss for r in out["runs"]]
    reserve = get(cfg, "layers.first_loss_reserve")
    on = bool(get(cfg, "layers.guarantor_enabled"))
    cover, gcap = get(cfg, "layers.guarantor_cover_pct") or 0.0, get(cfg, "layers.guarantor_cap") or 0.0
    marks = [(reserve, f"reserve {_rm(reserve)}")]
    if on and cover > 0:
        cap_point = reserve + gcap / cover        # loss at which the guarantor cap is reached
        if cap_point <= max(totals + [0]) * 1.5:
            marks.append((cap_point, f"guarantor cap reached {_rm(cap_point)}"))
    layer_rows = [(f"Median cohort (p50)", allocate_loss(s["total_loss"]["p50"], reserve, cover, gcap, on)),
                  (f"Bad cohort (p95)", allocate_loss(s["total_loss"]["p95"], reserve, cover, gcap, on))]

    fee = get(cfg, "pricing.flat_fee_per_bridge")
    ceiling = fee_ceiling_check(fee, s["avg_bridge"], get(cfg, "tenor.typical_days"), cfg)
    note, mrows = _market_rows(cfg, s)

    body = [
        '<p class="lead">What happens to a cohort of job-linked bridges under these settings, run '
        f'{get(cfg, "simulation.n_runs"):,} times. Use it to see which settings matter and by how much. '
        "It does not say what will happen: no Malaysian loss data exists, so every probability below is an input.</p>",
        "<h2>Key results</h2>",
        table(["", "Value"], [
            ["Financier net result per bridge", _rm(s["financier_net_per_bridge"])],
            ["Break-even flat fee (covers cost to serve + expected financier loss; the borrower pays the guarantee fee on top)",
             _rm(s["breakeven_flat_fee"])],
            ["Chance the first-loss reserve is used up", fmt(s["p_reserve_exhausted"], "pct")],
            ["Chance the guarantor cap is hit", fmt(s["p_guarantor_cap_hit"], "pct")],
            ["Cohorts paused by a stop line (bypass or loss)", fmt(s["p_paused"], "pct") +
             (f' (median pause after {s["median_pause_point"]:.0f} bridges)' if s["median_pause_point"] else "")],
            ["Fee-ceiling check on the average bridge", esc(ceiling.message)],
        ], {1}),
        "<h2>Inputs</h2>", table(["Input", "Value", "Config key"], _inputs_rows(cfg)),
        "<h2>Results across runs</h2>",
        '<p class="note">Per cohort. p5 and p95 are the 5th and 95th percentile runs.</p>',
        table(["", "Mean", "p5", "Median", "p95"], _results_rows(s), {1, 2, 3, 4}),
        "<h2>1 · How big the loss gets</h2>",
        f'<div class="chart">{chart_histogram(totals, marks)}</div>',
        '<p class="note">Total loss in each simulated cohort. Left of the reserve line, the reserve (DFI and guarantor money) absorbs all of it.</p>',
        "<details><summary>Table view</summary>" + table(["Percentile", "Total loss"],
            [[p, _rm(s["total_loss"][k])] for p, k in (("5th", "p5"), ("50th", "p50"), ("95th", "p95"))], {1}) + "</details>",
        "<h2>2 · Who absorbs the loss</h2>",
        _legend([("First-loss reserve (DFI + guarantor money)", C_RESERVE), ("Guarantor", C_GUARANTOR), ("Financier", C_FINANCIER)]),
        f'<div class="chart">{chart_layers(layer_rows)}</div>',
        "<details><summary>Table view</summary>" + table(["Run", "Reserve", "Guarantor", "Financier", "Total"],
            [[esc(lbl), _rm(a["first_loss"]), _rm(a["guarantor"]), _rm(a["financier"]), _rm(sum(a.values()))]
             for lbl, a in layer_rows], {1, 2, 3, 4}) + "</details>",
        "<h2>3 · What moves the result</h2>",
        '<p class="note">Financier net result per bridge when one input moves by 25% of its base value, the others held. '
        "Same random draws in every case, so the bars show the input, not noise.</p>",
        _legend([("Input −25%", C_LOW), ("Input +25%", C_HIGH)]),
        f'<div class="chart">{chart_sensitivity(sens)}</div>',
        "<details><summary>Table view</summary>" + table(
            ["Input", "−25%", "Base", "+25%", "p95 financier loss −25% / +25%", "Reserve used up −25% / +25%"],
            [[esc(SENS_LABEL[r["param"]]), _rm(r["low"]["financier_net_per_bridge"]), _rm(r["base"]["financier_net_per_bridge"]),
              _rm(r["high"]["financier_net_per_bridge"]),
              f'{_rm(r["low"]["financier_loss"]["p95"])} / {_rm(r["high"]["financier_loss"]["p95"])}',
              f'{fmt(r["low"]["p_reserve_exhausted"], "pct")} / {fmt(r["high"]["p_reserve_exhausted"], "pct")}'] for r in sens],
            {1, 2, 3}) + "</details>",
        "<h2>Against the market</h2>",
        f'<p class="note"><strong>{esc(note)}.</strong> Not like-for-like: market products advance against contract or '
        "invoice value and often need collateral; this bridge advances against the quoted materials cost, is paid to the "
        "supplier, and needs no collateral. The fee here comes from cost to serve plus expected loss, never from a market rate.</p>",
        table(["", "Value", "Source"], mrows),
    ]
    if grid:
        body += ["<h2>Try other settings</h2>",
                 '<p class="note">Each position was simulated in advance by the same engine, on the same draws. '
                 "Margin of advance changes bridge size only: with no data, the engine assumes it does not change how "
                 "borrowers or customers behave.</p>", _binding_note(cfg), _slider_block(grid, cfg)]
    if dev_grid:
        body += ["<h2>Developmental pricing</h2>", _dev_block(dev_grid, cfg)]
    if rr_grid:
        body += ["<h2>Risk and return: the DFI and the guarantor</h2>", _rr_block(rr_grid, cfg)]
    if reserve_rows:
        body += ["<h2>The reserve: funded by the DFI and the guarantor</h2>", _reserve_block(reserve_rows, cfg)]
    if viability:
        body += ["<h2>Path to viability</h2>", _viability_block(viability, cfg)]
    if damage_grid:
        body += ["<h2>Damage rate and the loss trip wire</h2>", _damage_block(damage_grid, cfg)]
    body += ["<h2>Method and limits</h2>", "<ul>"
             "<li>One run is one cohort. Each job draws a materials cost and a deposit; the bridge amount uses the "
             "same rule as the live release decision, and stops at the cohort cap.</li>"
             "<li>Each bridge draws one outcome. Loss = amount × (1 − recovery rate for that outcome).</li>"
             "<li>Losses run through the layers in event order: the reserve is shared across the cohort, then the guarantor up "
             "to its cap, then the financier.</li>"
             "<li>The guarantee fee is charged to the borrower on drawn amounts and passed to the guarantor.</li>"
             "<li>The stop line uses the bypass rate to date, tested once the minimum number of bridges is out.</li>"
             "<li>Not modelled: changes in behaviour from pricing or margin of advance, correlation between bridges, "
             "collection costs beyond cost to serve, timing of cash.</li></ul>"]
    case = get(cfg, "meta.case")
    html_ = page("Cohort simulation", config_path, bool(get(cfg, "meta.demo")), "\n".join(body),
                 subtitle=(f"{case} · " if case else "") + f'seed {get(cfg, "simulation.seed")} · {get(cfg, "simulation.n_runs"):,} runs')
    return html_.replace("</style>", SIM_CSS + "</style>", 1)
