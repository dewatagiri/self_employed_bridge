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
python -m pytest                                    # 77 tests

bridge check-config config/params.template.yaml     # what must be set before live use (exit 1)
bridge screen  data/example_job.json --config config/params.demo.yaml
bridge decide  data/example_job.json --config config/params.demo.yaml --exposure data/example_exposure.json
bridge waterfall --loss 25000 --config config/params.demo.yaml
bridge gates   data/sample_log.csv --config config/params.demo.yaml --jobs data/sample_jobs.csv --out gates.html
```

Add `--json` to any command for machine-readable output. Run any live command against the
template and it refuses, naming each null it needs (exit 2).

## The worked example

A painter wins a RM12,000 job; the customer pays RM2,000 deposit; materials cost RM5,000.
`screen` → `BRIDGE_CANDIDATE`. `decide` → release **RM3,000 to the supplier**, auto review.
A RM25,000 write-off under the demo layers → reserve RM10,000, guarantor RM5,000 (capped), financier RM10,000.

## What's where

| Step | Module | Does |
|---|---|---|
| Four questions | `screen.py` | confirmed job, materials share, payer type, deposit below materials |
| Release | `decide.py` | amount, every cap, ten checks, two-step release, review level |
| Loss layers | `waterfall.py` | reserve → guarantor (capped) → financier; cohort pool |
| Pricing | `pricing.py` | flat fee + guarantee fee on drawn; break-even; fee-ceiling warning |
| Compliance | `compliance.py` | effective rate vs moneylender caps, controlled-account flag, PDPA export guard |
| Recovery | `collections.py` | state machine, tasks by days past due, write-off, claim file |
| Gates | `gates.py` | gates 0–3, cohort measures, second-cohort rule |
| Output | `report.py`, `cli.py` | offline HTML, command line |

Design and data flow: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Every interpretation made in the build, and what is still open: [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

Phases 1 (core) and 2 (collections, gates, CLI) done. Phase 3 (simulator, sensitivity report) next.
