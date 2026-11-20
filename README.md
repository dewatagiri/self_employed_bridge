# Job-Linked Bridge engine

A parametric engine for a **job-linked materials bridge**: a short loan tied to one confirmed job,
capped at the materials cost, paid to the supplier (never the borrower), and repaid from the
customer's payment into a controlled account.

It screens a job, decides whether to release a bridge, allocates losses through the layers,
checks pricing and compliance flags, runs the recovery path, and scores the four pilot gates from
a bridge log. **Every limit, rate and threshold is a parameter. Nothing is hard-coded.**

> **Sensitivity tool, not a forecast.** No Malaysian loss data exists. Every value in
> `config/params.demo.yaml` is made up (`# DEMO ONLY, not a finding`) and every report built from
> it says **DEMO PARAMETERS**. The sample CSVs are synthetic. Views are the author's own. Not financial advice.

## Run

```bash
pip install -e ".[dev]"
python -m pytest                                    # 141 tests

bridge check-config config/params.template.yaml     # what must be set before live use (exit 1)
bridge screen  data/example_job.json --config config/params.demo.yaml
bridge decide  data/example_job.json --config config/params.demo.yaml --exposure data/example_exposure.json
bridge waterfall --loss 25000 --config config/params.demo.yaml
bridge gates   data/sample_log.csv --config config/params.demo.yaml --jobs data/sample_jobs.csv --out gates.html
bridge simulate --config config/params.demo.yaml --out report.html
```

Open the outputs without running anything: [`docs/demo_report.html`](docs/demo_report.html) (simulation,
charts, sliders) and [`docs/demo_gates.html`](docs/demo_gates.html) (pilot gates). Both are built from
demo parameters and synthetic data.

Add `--json` to any command for machine-readable output. Run any live command against the
template and it refuses, naming each null it needs (exit 2).

## Staff page (for running a first cohort)

```bash
bridge serve --config config/params.demo.yaml --db bridge.db
```

Open <http://127.0.0.1:8000> on the same PC. Staff enter a job and get the engine's decision, record
the release once the supplier is paid, then run each bridge to its end: payments, days past due
(reminder, notice, escalation, write-off fire on their days), bypass and cure, dispute, abandonment,
variation top-ups. The **Pilot gates** page and the CSV log are built from the same record.

- The page only listens on this PC, uses only the Python standard library, and keeps one file
  (`bridge.db`, SQLite). Back that file up; it is the record.
- Exposure, reserve left and guarantor cap left are worked out from the record; staff never add them up.
- Every release is re-checked by the engine when it is recorded. The page contacts nobody: it records
  what staff did.
- With the template config it refuses to decide and lists the settings still missing.

On Windows PowerShell, use `py -3.13 -m self_employed_bridge.cli serve --config config/params.demo.yaml`.

## The worked example

A painter wins a RM12,000 job; the customer pays RM2,000 deposit; materials cost RM5,000.
`screen` → `BRIDGE_CANDIDATE`. `decide` → release **RM3,000 to the supplier**, auto review.
A RM25,000 write-off under the demo layers → reserve RM10,000, guarantor RM5,000 (capped), financier RM10,000.

## What's where

| Step | Module | Does |
|---|---|---|
| Four questions | `screen.py` | confirmed job, materials share, payer type, deposit below materials |
| Release | `decide.py` | KYC and screening results, amount (margin of advance, every cap), two-step release, review level |
| Loss layers | `waterfall.py` | reserve → guarantor (capped) → financier; cohort pool |
| Pricing | `pricing.py` | flat fee + guarantee fee on drawn; break-even; fee-ceiling warning |
| Compliance | `compliance.py` | effective rate vs moneylender caps, controlled-account flag, PDPA export guard |
| Recovery | `collections.py` | state machine, tasks by days past due, write-off, claim file |
| Gates | `gates.py` | gates 0–3, cohort measures, second-cohort rule |
| Simulation | `simulate.py` | cohort Monte Carlo, stop line, ±25% sensitivity, slider grid |
| Staff page | `app.py`, `ledger.py`, `store.py` | local web page over the engine; exposure and log from the record (SQLite) |
| Output | `report.py`, `cli.py` | offline HTML, command line |

Design and data flow: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Every interpretation made in the build, and what is still open: [`docs/DECISIONS.md`](docs/DECISIONS.md).
Step by step with real outputs, and who sets which parameter before going live: [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md).

## Margin of advance and the market

`release.margin_of_advance` caps a bridge at a share of the quoted materials cost, never above 100%.
Market contract and invoice products advance 80–100% of contract or invoice value, often with
collateral. Those public references sit in `market_reference` (dated, organisation names left out,
**pending author approval**) and appear in the report for comparison only. They never drive a decision,
and the fee is never derived from a market rate.

## Status

Phases 1–3 done: core logic, collections and gates, simulator and report.
