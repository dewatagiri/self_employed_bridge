"""Command line. All I/O lives here; the modules it calls are pure.

    bridge screen    job.json --config params.yaml
    bridge decide    job.json --config params.yaml --exposure exposure.json
    bridge waterfall --loss 10000 --config params.yaml
    bridge simulate  --config params.demo.yaml --out report.html
    bridge gates     data/sample_log.csv --config params.yaml [--jobs data/sample_jobs.csv] --out gates.html
    bridge serve     --config params.yaml [--db bridge.db] [--port 8000]
    bridge check-config params.yaml

Exit codes: 0 ok, 1 check-config found blocking nulls, 2 config incomplete or bad input.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from . import compliance, gates, report, riskreturn, simulate
from .config import ConfigIncomplete, ConfigInvalid, check_config, get, is_demo, layer_keys, load_config, require
from .decide import decide, decide_variation
from .models import Exposure, Job
from .screen import screen
from .waterfall import allocate_loss


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _out(args, obj, text: str) -> None:
    if args.json:
        print(json.dumps(obj, indent=2, default=lambda o: dataclasses.asdict(o)))
    else:
        print(text)


def _banner(cfg: dict) -> str:
    return "DEMO PARAMETERS: made-up values, not findings.\n" if is_demo(cfg) else ""


def _decision_text(d) -> str:
    lines = [f"Route:    {d.route}"]
    if d.route in ("RELEASE", "RELEASE_VARIATION"):
        lines += [f"Amount:   RM{d.approved_amount:,.2f}",
                  f"Payee:    supplier {d.payee} (never the borrower)",
                  f"Review:   {d.review_level}"]
        if len(d.tranches) > 1:
            lines.append(f"Tranches: RM{d.tranches[0]:,.2f} now; RM{d.tranches[1]:,.2f} after stage 1 is confirmed")
    lines.append("Reasons:")
    lines += [f"  {r.code:<24} {r.text}" for r in d.reasons]
    if d.flags:
        lines.append("Flags:    " + ", ".join(d.flags))
    return "\n".join(lines)


def cmd_screen(args, cfg):
    d = screen(Job.from_dict(_load_json(args.job)), cfg)
    _out(args, d, _banner(cfg) + _decision_text(d))


def cmd_decide(args, cfg):
    exposure = Exposure.from_dict(_load_json(args.exposure)) if args.exposure else Exposure()
    job = Job.from_dict(_load_json(args.job))
    if args.top_up_after is not None:
        d = decide_variation(job, args.top_up_after, exposure, cfg)
    else:
        d = decide(job, exposure, cfg)
    standing = compliance.controlled_account_flag()
    text = _banner(cfg) + _decision_text(d)
    if d.route == "RELEASE_VARIATION":
        text += f"\nTop-up:   paid to supplier {d.payee}; a named officer reviews it"
    if d.route == "RELEASE" and job.materials_cost:
        text += (f"\nAdvance:  {d.approved_amount / job.materials_cost:.0%} of quoted materials cost "
                 f"(setting: up to {get(cfg, 'release.margin_of_advance'):.0%})")
    _out(args, {"decision": d, "open_items": [standing]}, text + f"\nOpen item: {standing['message']}")


def cmd_waterfall(args, cfg):
    require(cfg, layer_keys(cfg))
    on = bool(get(cfg, "layers.guarantor_enabled"))
    r = allocate_loss(args.loss, get(cfg, "layers.first_loss_reserve"), get(cfg, "layers.guarantor_cover_pct") or 0.0,
                      get(cfg, "layers.guarantor_cap") or 0.0, on)
    text = (f"Loss RM{args.loss:,.2f} (guarantor {'on' if on else 'off'})\n"
            f"  1 first-loss reserve  RM{r['first_loss']:>12,.2f}\n"
            f"  2 guarantor           RM{r['guarantor']:>12,.2f}\n"
            f"  3 financier           RM{r['financier']:>12,.2f}")
    _out(args, r, _banner(cfg) + text)


def cmd_gates(args, cfg):
    rows, synthetic = gates.read_log(args.log)
    jobs = gates.read_jobs(args.jobs)[0] if args.jobs else None
    res = gates.score_by_cohort(rows, cfg, jobs)
    lines = [_banner(cfg) + ("SYNTHETIC DATA\n" if synthetic else "") + f"{'Gate':<16}{'Value':>10}  Status"]
    for gr in res["overall"]["gates"]:
        v = "—" if gr.value is None else f"{gr.value:.3f}"
        lines.append(f"{gr.gate} {gr.name:<14}{v:>10}  {gr.status}")
    for c, (ok, why) in res["next_cohort"].items():
        lines.append(f"Cohort {c} may start: {'yes' if ok else 'no'}. {why}")
    if args.out:
        Path(args.out).write_text(report.render_gates(res, args.config, is_demo(cfg), synthetic, args.log),
                                  encoding="utf-8")
        lines.append(f"Wrote {args.out}")
    _out(args, res, "\n".join(lines))


def cmd_simulate(args, cfg):
    out = simulate.simulate(cfg)
    s = out["summary"]
    lines = [_banner(cfg) + f"{get(cfg, 'simulation.n_runs'):,} cohorts, seed {get(cfg, 'simulation.seed')}. "
             "Sensitivity tool, not a forecast.",
             f"{'Per cohort':<26}{'mean':>12}{'p5':>12}{'p50':>12}{'p95':>12}"]
    for key, label in (("total_loss", "Total loss"), ("reserve_drawdown", "Reserve used"),
                       ("guarantor_draw", "Guarantor draw"), ("financier_loss", "Financier loss"),
                       ("financier_net", "Financier net")):
        d = s[key]
        lines.append(f"{label:<26}" + "".join(f"{d[k]:>12,.0f}" for k in ("mean", "p5", "p50", "p95")))
    lines += [f"Financier net per bridge   RM{s['financier_net_per_bridge']:,.2f}",
              f"Break-even flat fee        RM{s['breakeven_flat_fee']:,.2f}",
              f"Reserve used up            {s['p_reserve_exhausted']:.1%} of cohorts",
              f"Guarantor cap hit          {s['p_guarantor_cap_hit']:.1%} of cohorts",
              f"Paused by a stop line     {s['p_paused']:.1%} of cohorts (bypass {s['p_paused_bypass']:.1%}, loss trip wire {s['p_paused_loss']:.1%})",
              f"Borrower cost a month      {s['borrower_monthly_cost']:.2%}"]
    dev = simulate.dev_base(cfg, out["draws"])
    if dev:
        lines += ["", "Developmental pricing (priced below a commercial return on purpose; additionality is measured in the pilot):",
                  f"  Borrower all-in cap {get(cfg, 'pricing.all_in_rate_cap_pa'):.1%} a year = RM{dev['borrower_per_loan']:,.1f} per loan "
                  f"(guarantee fee RM{dev['guarantee_fee_per_loan']:,.1f}, financier fee RM{dev['financier_fee_per_loan']:,.1f})",
                  f"  Financier net RM{dev['financier_net_mean']:,.0f} per group = {dev['financier_return_pa']:.1%} a year on drawn, before funding cost",
                  f"  Guarantor net RM{dev['guarantor_net_mean']:,.0f} per group = {dev['guarantor_return_pa']:.1%} a year on drawn",
                  f"  Sponsor reserve used RM{dev['sponsor_reserve_used_mean']:,.0f} per group",
                  f"  Planned programme cost (all funders) RM{dev['programme_cost_per_loan']:,.2f} per loan, "
                  f"RM{dev['programme_cost_per_1000_lent']:,.2f} per RM1,000 lent"]
    rrb = riskreturn.rr_base(cfg, out["draws"])
    if rrb:
        d, g = rrb["dfi"], rrb["guarantor"]
        lines += ["", "Risk and return, each party with its own costs (placeholders until the DFI and guarantor supply theirs):",
                  f"  DFI        return on capital {d['return_on_capital_pa']:.1%} vs hurdle {d['hurdle']:.0%} (spread {d['spread']:+.1%}); "
                  f"loss-making groups {d['p_loss']:.0%}; worst-5% average RM{d['es5']:,.0f}"]
        if g:
            lines.append(f"  Guarantor  return on capital {g['return_on_capital_pa']:.1%} vs hurdle {g['hurdle']:.0%} (spread {g['spread']:+.1%}); "
                         f"loss-making groups {g['p_loss']:.0%}; worst-5% average RM{g['es5']:,.0f}")
        sv = riskreturn.sponsor_view([simulate.run_cohort(d, cfg) for d in out["draws"]], cfg)   # None while its settings are missing
        if sv:
            lines.append(f"  Sponsor    reserve RM{sv['committed']:,.0f} funded up front; expected spent RM{sv['expected_used']:,.0f}, "
                         f"{'returned' if sv['is_returned'] else 'forfeited'} RM{sv['expected_unused']:,.0f}; net cost RM{sv['net_cost']:,.0f} per group "
                         f"(RM{sv['net_cost_per_1000_lent']:,.2f} per RM1,000 lent)")
        lines.append(f"  Cost-covering all-in rate {rrb['cost_covering_all_in_pa']:.1%} a year vs cap {rrb['all_in_cap_pa']:.1%}: "
                     f"gap {rrb['gap_pa']:+.1%} = RM{rrb['gap_per_loan']:,.2f} per loan")
    if args.out:
        sens = simulate.sensitivity(cfg, out["draws"])
        grid = simulate.slider_grid(cfg, out["draws"])
        dev_grid = simulate.dev_grid(cfg, out["draws"])
        damage_grid = simulate.damage_grid(cfg, out["draws"])
        rr_grid = riskreturn.rr_grid(cfg, out["draws"])
        reserve_rows = riskreturn.reserve_table(cfg, out["draws"])
        Path(args.out).write_text(report.render_simulation(out, sens, grid, cfg, args.config, dev_grid, damage_grid, rr_grid, reserve_rows), encoding="utf-8")
        lines.append(f"Wrote {args.out}")
    _out(args, {"summary": s}, "\n".join(lines))


def cmd_serve(args, cfg):
    from .app import serve
    serve(cfg, args.config, args.db, args.host, args.port)


def cmd_check_config(args):
    cfg = load_config(args.path)
    r = check_config(cfg)
    lines = [_banner(cfg).rstrip()] if is_demo(cfg) else []
    if r["blocking"]:
        lines.append(f"{len(r['blocking'])} null parameter(s) block live use:")
        lines += [f"  {k:<46} blocks: {', '.join(cmds)}" for k, cmds in r["blocking"].items()]
    else:
        lines.append("No null parameter blocks live use.")
    if r["open"]:
        lines.append(f"{len(r['open'])} open setting(s), null but not blocking:")
        lines.append("  (gate thresholds report NO_THRESHOLD_SET; stop lines stay off; guarantor keys unused while it is off)")
        lines += [f"  {k}" for k in r["open"]]
    _out(args, r, "\n".join(lines))
    return 1 if r["blocking"] else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bridge", description="Job-linked bridge engine. Sensitivity tool, not a forecast.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.set_defaults(fn=fn)
        return sp

    sp = add("screen", cmd_screen, "run the four screening questions")
    sp.add_argument("job"); sp.add_argument("--config", required=True)
    sp = add("decide", cmd_decide, "release decision for a job")
    sp.add_argument("job"); sp.add_argument("--config", required=True); sp.add_argument("--exposure")
    sp.add_argument("--top-up-after", type=float, metavar="RM",
                    help="variation order on a live bridge: amount already released")
    sp = add("waterfall", cmd_waterfall, "allocate one loss through the layers")
    sp.add_argument("--loss", type=float, required=True); sp.add_argument("--config", required=True)
    sp = add("gates", cmd_gates, "score the pilot gates from a bridge log")
    sp.add_argument("log"); sp.add_argument("--config", required=True)
    sp.add_argument("--jobs", help="jobs CSV for gate 0"); sp.add_argument("--out", help="write an HTML report")
    sp = add("simulate", cmd_simulate, "cohort Monte Carlo and sensitivity report")
    sp.add_argument("--config", required=True); sp.add_argument("--out", help="write the HTML report")
    sp = add("serve", cmd_serve, "staff page on this PC (http://127.0.0.1:8000)")
    sp.add_argument("--config", required=True); sp.add_argument("--db", default="bridge.db")
    sp.add_argument("--host", default="127.0.0.1"); sp.add_argument("--port", type=int, default=8000)
    sp = add("check-config", None, "list every null that blocks live use")
    sp.add_argument("path")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "check-config":
            return cmd_check_config(args)
        args.fn(args, load_config(args.config))
        return 0
    except ConfigIncomplete as e:
        print("Config incomplete. Set these before live use:", file=sys.stderr)
        for k in e.keys:
            print(f"  {k}", file=sys.stderr)
        return 2
    except ConfigInvalid as e:
        print(f"Config invalid: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"Bad input: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
