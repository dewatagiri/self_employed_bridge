# Job-Linked Bridge engine

A parametric engine for a job-linked materials bridge: screen a confirmed job, decide whether to
release a bridge to the supplier, run the loss waterfall and pricing checks, simulate a cohort and
score the pilot gates. Every limit, rate and threshold is a parameter in a config file.

**Sensitivity tool, not a forecast. Not financial advice. All parameters are pilot settings.**

## Run

```bash
pip install -e ".[dev]"
python -m pytest
```

## Config

- `config/params.template.yaml`: every key, pilot values `null`. The engine refuses a live decision
  while a required parameter is `null` and raises `ConfigIncomplete` naming each key.
- `config/params.demo.yaml`: made-up values so the engine runs end to end. Each carries
  `# DEMO ONLY, not a finding`. Reports built from it print "DEMO PARAMETERS".

No Malaysian loss data exists. Do not fill the template from guesses.

## Status

Phase 1 (core logic) done. Phases 2 (collections, gates, CLI) and 3 (simulator, report) pending.
Open items for the author are in the handover, section 9.
