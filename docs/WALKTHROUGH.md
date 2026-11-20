# Walkthrough: one job, one cohort, one pilot

Every output below was produced by the commands shown, on `config/params.demo.yaml` and the synthetic
sample files. **Demo values, not findings.** Run them yourself after `pip install -e ".[dev]"`.

## 1. One job

The painter from the design: RM12,000 quote, RM5,000 materials, RM2,000 deposit, household payer,
KYC verified, screening clear.

```bash
bridge decide data/example_job.json --config config/params.demo.yaml --exposure data/example_exposure.json
```

```
DEMO PARAMETERS: made-up values, not findings.
Route:    RELEASE
Amount:   RM3,000.00
Payee:    supplier S-EX1 (never the borrower)
Review:   auto
Reasons:
  ALL_CHECKS_PASSED        All checks passed.
Advance:  60% of quoted materials cost (setting: up to 95%)
Open item: Confirm whether the controlled account needs central-bank approval as e-money or a payment service.
```

The bridge covers the gap the deposit leaves (RM5,000 − RM2,000), not the whole materials bill. That is
why the advance is 60% of materials even though the setting allows 95%.

**Same job, borrower KYC still pending:**

```
DEMO PARAMETERS: made-up values, not findings.
Route:    BLOCKED
Reasons:
  KYC_NOT_VERIFIED         Borrower identity is not yet verified.
Open item: Confirm whether the controlled account needs central-bank approval as e-money or a payment service.
```

**A larger job** (RM10,000 materials, RM1,000 deposit): above the auto-approve limit, so it goes to a
named officer, and above the two-step amount, so it releases in two tranches.

```
DEMO PARAMETERS: made-up values, not findings.
Route:    RELEASE
Amount:   RM9,000.00
Payee:    supplier S-EX1 (never the borrower)
Review:   manual
Tranches: RM8,000.00 now; RM1,000.00 after stage 1 is confirmed
Reasons:
  ABOVE_AUTO_LIMIT         Amount is above the auto-approve limit.
Advance:  90% of quoted materials cost (setting: up to 95%)
Open item: Confirm whether the controlled account needs central-bank approval as e-money or a payment service.
```

## 2. When the customer does not pay

The engine contacts nobody: it produces tasks with an owner. A bridge that goes late and is never paid:

```python
from self_employed_bridge.config import load_config
from self_employed_bridge.collections import LiveBridge, advance_days, claim_file

cfg = load_config("config/params.demo.yaml")
b = LiveBridge("BR-EX1", "J-EX1", "B-EX1", amount=3000)
for day in (3, 14, 30, 120):
    b, tasks = advance_days(b, day, cfg)
```

```
day   3  LATE         job source         Job source reminds the payer.
day  14  LATE         financier          Financier sends notice under the payment instruction.
day  30  RECOVERY     collections owner  Escalate to the collections owner; start recovery.
day 120  WRITTEN_OFF  financier          Write-off RM3,000.00. Prepare the claim file.
loss split: {'first_loss': 3000, 'guarantor': 0, 'financier': 0}
claim file missing: ['Controlled-account receipts']
```

The whole RM3,000 lands on the sponsor's reserve because this cohort had not used it yet. In a cohort
that has, pass the remaining reserve and guarantor cap to `write_off`.

## 3. One cohort, a thousand times

```bash
bridge simulate --config config/params.demo.yaml --out report.html
```

```
DEMO PARAMETERS: made-up values, not findings.
1,000 cohorts, seed 42. Sensitivity tool, not a forecast.
Per cohort                        mean          p5         p50         p95
Total loss                       9,164       3,801       8,703      16,007
Reserve used                     8,000       3,801       8,703      10,000
Guarantor draw                     575           0           0       3,003
Financier loss                     590           0           0       3,003
Financier net                    1,495        -791       2,030       2,590
Financier net per bridge   RM25.10
Break-even flat fee        RM34.90
Reserve used up            36.5% of cohorts
Guarantor cap hit          1.1% of cohorts
Paused by bypass stop line 22.0% of cohorts
Borrower cost a month      2.21%
```

Read it as: under these made-up settings the reserve takes most losses, the financier loses money in a
bad cohort (p5 net −RM791), and the flat fee is about RM25 above break-even per bridge. The report
([`docs/demo_report.html`](demo_report.html)) shows which input moves that most (recovery rate) and has
sliders for margin of advance, fee and reserve.

## 4. One pilot

```bash
bridge gates data/sample_log.csv --config config/params.demo.yaml --jobs data/sample_jobs.csv --out gates.html
```

```
DEMO PARAMETERS: made-up values, not findings.
SYNTHETIC DATA
Gate                 Value  Status
0 Size               0.650  NO_THRESHOLD_SET
1 Mechanics          0.850  NO_THRESHOLD_SET
2 Performance        0.775  NO_THRESHOLD_SET
3 Economics          0.259  NO_THRESHOLD_SET
Cohort C2 may start: no. Previous cohort must PASS gates 1 and 2 (gate 1: NO_THRESHOLD_SET, gate 2: NO_THRESHOLD_SET).
```

Every gate has a value and no pass mark, so cohort 2 cannot start. That is deliberate: the design leaves
the stop lines open and the engine will not invent them.

## 5. Going live: who sets what, in what order

`bridge check-config config/params.template.yaml` lists 30 nulls that block live use. They fall to
different owners. Suggested order, because each step depends on the one before:

| # | Owner | Keys | Why this order |
|---|---|---|---|
| 1 | Legal | `financier.type`; the controlled-account open item; `market_reference` approval | Decides whether the product can run at all, and which fee rules apply. |
| 2 | Risk / credit | `screen.*`, `release.*` (incl. `margin_of_advance`), `borrower.min_trade_months_or_jobs`, `caps.*`, `tenor.two_step_release_over_amount` | Who gets a bridge and how much. Needed before any release. |
| 3 | Sponsor | `layers.first_loss_reserve` (and guarantor terms if one joins) | Sized against the cohort cap from step 2. |
| 4 | Collections owner | `collections.*` | Days past due for each step and the write-off point. |
| 5 | Pilot steering group | `gates.*`, `stop_lines.*` | **Set before cohort 1 data comes in**, so the pass marks are not fitted to the results. |
| 6 | Finance | `pricing.*`, `tenor.typical_days` | Fee from measured cost to serve plus expected loss; the first cohort measures both. |
| 7 | Analysis | `simulation.*` | From cohort 1 data. Until then the simulator is a what-if tool only. |
