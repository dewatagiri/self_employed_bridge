# Build decisions and open items

The handover leaves some points to the author. Where the code had to pick, the choice is listed
here so it can be confirmed or reversed. Nothing below is a finding.

## Interpretations made in the build

| # | Where | Choice | Why / how to change |
|---|---|---|---|
| D1 | `decide.py` | need = max(0, materials − deposit × `deposit_to_materials_share`); amount = min(need, materials, invoice, per-bridge cap, headroom under every cap) | Handover §6.2, flagged as open item 1. A plain cap at materials cost is `deposit_to_materials_share: 0`. |
| D2 | `decide.py` | Approved amount never exceeds the quoted materials cost, even with a signed variation order. Unsigned extra → manual review, extra blocked. Signed → flag `VARIATION_SIGNED_EXTRA_NOT_BRIDGED`. | "Never above the materials cost" read as absolute. A signed variation would need a new quote. |
| D3 | `decide.py` | Template mismatch → manual review, not a block. | The design says "matches the template or is reviewed by hand". |
| D4 | `decide.py` | Routes after screening: `DECLINE` (adverse record, related payer, duplicate job), `BLOCKED` (any other failed check, or no cap headroom), `RELEASE`. | Separates "never" from "not yet". |
| D5 | `decide.py` | Two-step release: tranche 1 = `two_step_release_over_amount`, tranche 2 = the rest. | Avoids inventing a split ratio. |
| D6 | `decide.py` | `credit flag = none` blocks when `require_credit_bureau_check` is true. | Bureau check is required at first bridge. |
| D7 | `decide.py` | Trade record is met if months in trade **or** completed jobs reach `min_trade_months_or_jobs`. | One key for both, as in the handover. |
| D8 | `pricing.py` | Fee-ceiling months = tenor days / 30 (90 days → RM900 on RM20,000). | Matches the worked test. |
| D9 | `pricing.py` | `breakeven_fee` = cost to serve + guarantee fee + expected financier loss. | Handover §6.4 as written. |
| D10 | `collections.py` | A bridge paid in full after going late closes as `PAID_LATE`. | The log has a `late` outcome; the spec's state list has no end state for it. |
| D11 | `collections.py` | Bypass and abandonment go straight to `RECOVERY` after their first-step tasks; a dispute stays in `DISPUTE` until mediation finds the borrower at fault. | Follows the design's collections table. |
| D12 | `collections.py` | A bypass blocks the borrower for the rest of the pilot (`Exposure.borrower_blocked`). | Lifting the block is a credit decision, not an engine one. |
| D13 | `collections.py` | Write-off takes the cohort's *remaining* reserve and guarantor cap (default: full config values). | Keeps single write-offs consistent with `allocate_pool`. |
| D14 | `gates.py` | Pass thresholds live in a new `gates.*` block, all null. A gate with several metrics is `FAIL` if any fails, `PASS` only if all pass. | The design leaves stop lines open; the handover asks for thresholds "from config". |
| D15 | `gates.py` | Gate 0 needs the jobs file (`--jobs`); without it the value is empty. | The log alone has no unbridged quotes. |
| D16 | `gates.py` | All-cohort loss is measured against one reserve per cohort. | Follows open item 2 (reserve per cohort, assumed). |
| D17 | config | Added `meta.demo` (drives the DEMO banner), `Exposure.live_job_ids` and `Exposure.borrower_blocked`, `Bridge.sponsor_cohort`. | Needed for the listed rules; no new behaviour. |
| D18 | config | The template comment for the fee-ceiling reference names no organisation. | Ground rule 3. The handover's §10 source note stays in the handover. |
| D19 | `decide.py` | KYC uses the provider's results: KYC failed → `DECLINE`; pending or missing → `BLOCKED`; screening true match → `DECLINE`; possible match or politically exposed person → manual review (enhanced due diligence); no screening result → `BLOCKED`; payer identity not confirmed → `BLOCKED`. Each rule has a config switch. | The author asked for standard KYC. The engine reads results; it never verifies identity itself. |
| D20 | `decide.py` | `release.margin_of_advance` caps the bridge at that share of the **quoted materials cost**. Above 1.0 is refused (`ConfigInvalid`). | Keeps the design's hard cap while allowing "better than market" (market products advance against contract or invoice value). |
| D21 | config | `market_reference` holds public, dated benchmarks, sources described without organisation names, `approved_by_author: false`. Comparison only. | The author asked for "slightly better than market"; ground rules 1 and 3. |
| D22 | `simulate.py` | `amount_distribution` draws the **materials cost** of each job, with `deposit_share_of_materials`; the bridge amount comes from `advance_limit`, the live rule. | §6.7 says "draw amounts". Drawing materials lets margin of advance, deposit offset and caps act in the simulation exactly as in `decide`. |
| D23 | config | Added `tenor.typical_days` (the guarantee fee needs a tenor). `tenor.grace_days` is not used by any module yet. | §4 has no tenor length. |
| D24 | `simulate.py` | Bypass stop line: bypass rate to date, tested once `stop_lines.bypass_rate_min_bridges` are out (new key). | A rate over 1 bridge is meaningless; the minimum is a pilot setting, not a guess. |
| D25 | `simulate.py` | The guarantee fee is paid by the borrower and passed to the guarantor. Break-even flat fee = cost to serve + expected financier loss; the report also shows it with the guarantee fee added, for the case where the financier pays it. | `bridge_revenue` (§6.4) charges both fees, while `breakeven_fee` adds the guarantee fee; both readings are shown. |
| D26 | `simulate.py` | Sensitivity: bypass ±25% moves the difference to or from on-time; recovery ±25% scales every outcome except on-time (repaid in full), capped at 100%; same random draws for every case. | One input at a time, no noise. |
| D27 | `simulate.py` | "Reserve exhausted" = a cohort's total loss reaches the reserve. `caps.per_sponsor_cohort` stops releases within a cohort. | Direct reading of §6.7. |
| D28 | `report.py` | White page only, no dark mode. | Ground rule 7. |

## Open items for the author (not guessed)

1. Bridge need formula (D1) versus a plain cap at materials cost.
2. Reserve shared across a cohort (assumed) or held per borrower.
3. Which financier types are in the pilot. `financier.type` is null, so compliance checks stop until it is set.
4. Real thresholds for stop lines and gates, and every null in `params.template.yaml`
   (`bridge check-config` lists them).
5. Whether the controlled account needs central-bank approval as e-money or a payment service
   (standing flag on every `decide`).
6. The `market_reference` sources: check each one, then set `approved_by_author: true`.
7. The fee-ceiling reference (1.5% a month): the public source found during the build ties that rate
   to a factoring product, and the build found no confirmation for contract financing. Please re-check
   the source named in handover §10.

## What the demo run shows (demo values, not findings)

- Above a 90% margin of advance nothing changes: every simulated deposit is at least 10% of materials,
  so the bridge never needs more. The deposit, not the margin, sets the bridge size.
- The demo fee (RM60) puts the borrower at about 2.2% a month, above the market's 0.8–1.5%, and above
  the fee-ceiling reference. The simulated break-even flat fee is about RM35 (about 1.3% a month), which
  is where "slightly better than market" becomes possible, if cost to serve holds.

## In the design, not built (out of the listed scope)

- Registration not required for the smallest first bridge, if the financier's rules allow.
- Live-bridge limit stepped up after clean repayments.
