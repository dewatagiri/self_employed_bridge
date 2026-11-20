# Architecture

## One job, end to end

```
 confirmed job (quote, named payer, deposit)            exposure snapshot
        │                                                       │
        ▼                                                       │
┌──────────────────────────────┐                                │
│ screen.py   four questions   │  stop at first failure         │
│ 1 named payer, not borrower  │──▶ REFER_GENERAL / DECLINE     │
│ 2 materials share ≥ setting  │──▶ REFER_GENERAL               │
│ 3 payer type                 │──▶ REFER_CONTRACT_INVOICE      │
│ 4 deposit < materials        │──▶ NO_BRIDGE_NEEDED            │
└──────────────┬───────────────┘                                │
               │ BRIDGE_CANDIDATE                               │
               ▼                                                ▼
┌──────────────────────────────────────────────────────────────────┐
│ decide.py                                                        │
│  checks: KYC · screening · payer identity · credit record ·      │
│  trade record · payer not related ·                              │
│  deposit from payer's account · PDPA · supplier on panel ·       │
│  one live bridge per job · borrower not blocked · live limit     │
│  amount = min(need, margin of advance × materials, per-bridge,   │
│               invoice, headroom under borrower / supplier /      │
│               cohort / pilot caps)          ◀── advance_limit()  │
│  > two-step amount → 2 tranches · review auto | manual           │
└──────────────┬───────────────────────────────────────────────────┘
               │ RELEASE, payee = supplier
               ▼
     supplier paid ─▶ job done ─▶ customer pays controlled account
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ collections.py   LIVE ─▶ PAID_ON_TIME                            │
│                  LIVE ─▶ LATE ─(reminder, notice, escalate)─┐    │
│                  LIVE ─▶ BYPASS (hold, block; cure or 2 = out)┤    │
│                  LIVE ─▶ DISPUTE (hold part, mediate) ──────┤    │
│                  LIVE ─▶ ABANDONED (supplier take-back) ────┤    │
│                                                  RECOVERY ◀─┘    │
│                          should_chase? ─▶ WRITTEN_OFF + claim file│
└──────────────┬───────────────────────────────────────────────────┘
               ▼
┌──────────────────────────────┐     ┌───────────────────────────┐
│ waterfall.py                 │     │ gates.py (from the log)   │
│ 1 sponsor first-loss reserve │     │ 0 size  1 mechanics       │
│ 2 guarantor, % up to a cap   │     │ 2 performance 3 economics │
│ 3 financier, the remainder   │     │ next cohort only if 1+2 PASS│
└──────────────────────────────┘     └───────────────────────────┘
```

## Simulation

```
 seed ─▶ draws per cohort (materials, deposit share, outcome uniform)   made once, reused
           │
           ├─▶ run_cohort(base config)            ─▶ summary: mean, p5, p50, p95, probabilities
           ├─▶ run_cohort(each input ±25%)        ─▶ sensitivity table and chart
           └─▶ run_cohort(each margin of advance) ─▶ re-allocate per reserve, re-price per fee
                                                    ─▶ slider grid (125 cells) embedded in the report
```

The bridge amount in a simulated cohort comes from `decide.advance_limit`, the same function the
live decision uses. The report's sliders look results up in the precomputed grid, so the page can
never disagree with the engine. A test checks that the grid cell at the base settings equals the
full simulation.

## Rules the code keeps

- **Pure core.** `screen`, `decide`, `waterfall`, `pricing`, `compliance`, `collections` and the
  scoring half of `gates` do no I/O and read no clock. Same input and config give the same output.
  Files are read only in `cli.py` and the two `read_*` functions in `gates.py`.
- **Null means stop.** Each function names the config keys it needs and raises
  `ConfigIncomplete([...])` listing every null one. `config.requirements()` maps keys to commands;
  `bridge check-config` prints that map.
- **Never invent a threshold.** Gate pass marks and stop lines are config keys that default to null.
  A null gate threshold reports `NO_THRESHOLD_SET`; a null stop line is simply off.
- **The borrower is never paid.** A `RELEASE` decision always names the supplier as payee.
- **The engine contacts nobody.** Collections returns tasks with an owner (job source, financier,
  collections owner, supplier). No task asks for a home or workplace visit (Act 400, s.29(B)).
- **Flags, not legal conclusions.** Compliance returns `OK`, `MONEYLENDER_CAP_BREACH`,
  `CHECK_REQUIRED` or a standing `OPEN_ITEM` for legal to confirm.

## Config

| File | Use |
|---|---|
| `config/params.template.yaml` | production shape; pilot values null |
| `config/params.demo.yaml` | made-up values so everything runs; `meta.demo: true` drives the DEMO banner |

## Tests

One file per module under `tests/`. They cover every acceptance test in the handover, plus:
conservation of loss across layers, each threshold firing once when the clock jumps, closed
bridges never writing off twice, the bypass block reaching `decide`, hand-counted gate values on
the sample log, offline HTML (no external links or resources), and that every filled demo value
carries the DEMO ONLY marker. Simulation: same seed same output, a new seed changes it, layers add
up to total loss in every run, a huge reserve leaves nothing for the guarantor or financier, pool and
single allocation totals agree, cohort cap and margin of advance hold, the stop line pauses, and the
slider grid matches the full simulation.
