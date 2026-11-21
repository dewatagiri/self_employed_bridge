# Build decisions and open items

The handover leaves some points to the author. Where the code had to pick, the choice is listed
here so it can be confirmed or reversed. Nothing below is a finding.

## Author decisions

| # | Date | Decision | Effect in the engine |
|---|---|---|---|
| A1 | 20 Nov 2026 | A development financial institution funds the bridges; a guarantee provider guarantees them. | `financier.type: development_institution` (compliance returns `CHECK_REQUIRED` for legal; moneylender caps do not apply). `layers.guarantor_enabled: true`, so guarantor cover and cap must be set before live use. |
| A2 | 20 Nov 2026 | Bridge size: the whole deposit counts against materials first; the bridge covers only the gap (confirms D1). | `screen.deposit_to_materials_share: 1.0`. Moving to a partial share later is a config change. |
| A3 | 20 Nov 2026 | First-loss reserve is one pool per sponsor cohort, not a slice per borrower. | Confirms the build: `allocate_pool` shares the reserve across a cohort; gates measure all-cohort loss against one reserve per cohort (D16). |
| A4 | 20 Nov 2026 | The borrower pays the guarantee fee on drawn amounts, on top of the flat fee; it passes to the guarantor. | Confirms D25 option one. Break-even flat fee = cost to serve + expected financier loss. The alternative figure is removed from the report. |
| A5 | 20 Nov 2026 | A variation order signed by the payer can release more on the same bridge (as the article says). | Replaces D2. At release, a signed variation raises the materials cost to the varied total. On a live bridge, `decide_variation` (CLI: `decide --top-up-after RM`) releases the difference, within margin of advance and every cap, to the supplier, always with manual review. Unsigned: extra blocked. |
| A6 | 20 Nov 2026 | An invoice that does not match the trade template goes to a named officer, not a block. | Confirms D3. |
| A7 | 20 Nov 2026 | Bypass cure path: the block lifts only after the bypassed amount is repaid in full into the controlled account and a named officer approves. A second bypass blocks for the rest of the pilot. | Replaces D12. `collections.approve_cure`; `blocked_borrowers` applies both rules. |
| A8 | 20 Nov 2026 | The simulator draws each job's materials cost and deposit, then sizes the bridge with the live rule. | Confirms D22 (departs from handover §6.7 wording on purpose). |
| A9 | 20 Nov 2026 | Market references stay pending until the author's team has opened each source. | `market_reference.approved_by_author: false`; the report keeps the PENDING label. |
| A10 | 20 Nov 2026 | Fee ceiling stays at 1.5% a month, resting on two sources: the public scheme charge (author to confirm the product) and the top of the market invoice financing range. | `pricing.fee_ceiling_reference.sources` lists both. Warning only; the fee is never derived from it. |
| A11 | 20 Nov 2026 | Build both article ideas: (1) business registration required, waived only for a borrower's first bridge at or below a set amount; (2) live-bridge limit and borrower cap step up after clean repayments. | `release.require_registration`, `release.registration_waiver_first_bridge_max` (null = no waiver), `caps.step_up_tiers` (null = no step-up; tiers may only raise limits). Inputs: `Job.borrower_registered`, `Exposure.borrower_prior_bridges`, `Exposure.borrower_clean_repayments`. Null leaves the strict default, so nothing loosens until the financier and risk team set the numbers. |
| A18 | 20 Nov 2026 | **Path to viability.** Low-ticket loans are usually not profitable, and serving them is the mandate, so the report must show whether the product can work at the cap and what it would take. | A report section with five sliders (cash-payment chance, damage rate, loss on bad loans, tenor, cost to serve), a verdict, the fee each party would need, and the planned cost per additional borrower where a gap remains. `viability_sliders` in the config; `riskreturn.viability_grid`. |
| A17 | 20 Nov 2026 | **The sponsors are the DFI and the guarantor.** There is no outside funder: the two of them fund the first-loss reserve between them, so every rand of credit loss lands on them. | `layers.reserve_funded_by_guarantor_pct` (the guarantor's share; the DFI funds the rest; null in the template, a placeholder in the demo). Each party's result is shown after funding its share, with the money tied up charged at its own hurdle. The funders' loss budget covers the whole programme, the reserve included. The third-party `sponsor.cost_of_funds_pa` setting is removed. |
| A16 | 20 Nov 2026 | **The first-loss reserve is funded up front into a ring-fenced account, and what the cohort does not spend goes back** to the funders once its loans are closed and recoveries are in. | `layers.unused_reserve_returned: true`. The report has a table of what each reserve size costs the DFI and the guarantor and what it does for each. |
| A15 | 20 Nov 2026 | **Risk and return between the DFI and the guarantor, as one section, each with its own costs.** The author asked for certain costs to be assumed on both sides. | `riskreturn.py` and a report section. DFI costs: cost of funds, equity held against the drawn amount, cost of equity, cost to serve. Guarantor costs: cost of capital on its cap, admin cost per bridge. All are settings: demo placeholders marked DEMO ONLY, null in the template. |
| A14 | 20 Nov 2026 | **Loss trip wire.** The programme pauses new bridges when the loss so far passes x% of the money lent. Damage (projects not completed or rejected) is modelled as a rate with a loss per damaged loan, so its effect can be tested live. | `stop_lines.pause_if_loss_rate_over`. Works in the simulation (with a minimum number of known loans and a lag for outcomes still out) and for real: `decide` and `decide_variation` return `BLOCKED` with `TRIP_WIRE_LOSS`, and the staff page shows a banner. The report has a damage / trip wire section with sliders. |
| A12 | 20 Nov 2026 | Build a staff page so people can use the engine (option 2 of 3), beyond handover §8's "no front end beyond the HTML report". | `bridge serve`: local page on 127.0.0.1, standard library only, SQLite record (`bridge.db`). Pure `ledger.py` derives exposure, layers left and the gates log from the record. No payments, no contact with anyone. |
| A13 | 20 Nov 2026 | **Developmental pricing.** If the product runs at the borrower's all-in charge cap, it is priced below a commercial return on purpose. The funders know they will lose money and accept it in return for additionality. | `development.pricing_basis: developmental`. The simulation report shows the planned loss (counting every funder, sponsor reserve included) with sliders, never a "return" claim. Additionality is measured, not assumed: gate 4 and two answers recorded at release. `pricing.all_in_rate_cap_pa` and `development.funder_loss_budget_per_cohort` are settings, null in the template. |

## The author's base case (21 Nov 2026)

`config/params.base_case.yaml` is the demo file with the author's own answers on top. They are **assumptions, not findings**: no
Malaysian loss data exists. Every value the author chose carries `AUTHOR ASSUMPTION` in the file; a test checks that nothing else differs from the demo.

| Question | Answer | Setting |
|---|---|---|
| Tenor (supplier paid until customer pays) | 90 days | `tenor.typical_days: 90` |
| Damage rate (not completed or rejected) | 3% | dispute 1.8% + abandoned 1.2% (3:2 as in the demo) |
| Loss on a damaged loan | 70% | `recovery_rate_by_outcome.dispute` and `.abandoned`: 0.3 (suppliers rarely take materials back) |
| Cash controls you can enforce | a controlled account (customer pays only into it) | see the next row |
| Customer pays the painter in cash, with a controlled account only | 5% (batch 4) | `outcome_probs.bypass: 0.05`; the slider runs from 1% to 8% |
| Cohort size | 100 loans (batch 4), about RM1 million lent | `simulation.n_bridges: 100`; the cohort cap, pilot cap, supplier cap, reserve and guarantor cap are scaled ×5 with it (placeholders, marked DEMO ONLY) |
| Who funds the reserve | the DFI funds all of it (batch 4) | `layers.reserve_funded_by_guarantor_pct: 0.0` |
| Funders' loss budget per cohort | not decided yet (batch 4) | `development.funder_loss_budget_per_cohort: null` |
| Legal status: controlled account (e-money or payment service) and the 18% all-in cap | the author reports legal has confirmed both (batch 4) | `compliance.*_legal_status: confirmed`; the engine records it and does not judge the law. Keep the written advice on file |
| The DFI's required return on the reserve money it ties up | 3% (batch 5) | `financier.cost_of_equity_pa: 0.03` |
| The guarantor's required return | 3% (batch 6) | `guarantor.cost_of_capital_pa: 0.03` |
| Guarantor cap | none: 70% of every loss above the reserve (batch 6) | `layers.guarantor_cap: 1500000`, equal to the cohort cap so it cannot bind (the engine reads null as 0, so "no cap" is a number too big to reach) |
| Reserve size | RM50,000 per cohort of 100 loans, confirmed (batch 8; the earlier "programme size" answer was unclear) | `layers.first_loss_reserve: 50000` |
| Guarantor exposure limit | keep no cap (batch 8) | as above |
| Programme size and late-payer share | batch 8 answers were "other" with no value: **not recorded**; programme stays 100-loan cohorts, late payers stay 20% | asked again in batch 9 |
| The guarantor's admin cost per loan | RM2 (batch 5; same as the placeholder) | `guarantor.admin_cost_per_bridge: 2` |
| Who lifts the loss trip wire | the guarantor (batch 5) | a process rule: the engine has no user roles, the line is changed in the config as a recorded decision, so keep that change under the guarantor's sign-off |
| Loss trip wire line | 5% of money lent with a known outcome (batch 7) | `stop_lines.pause_if_loss_rate_over: 0.05` (minimum 30 known loans, batch 8) |
| Additionality | 30% (batch 7); I read it as the share of borrowers new to formal credit the pilot must show | `gates.gate4_min_new_to_credit_share: 0.3`, a pass mark; the pilot measures the real share |
| Stop-line minimum loans | loss trip wire: 30 (batch 8); bypass stop line: 50, my suggestion | `stop_lines.loss_rate_min_bridges: 30`, `bypass_rate_min_bridges: 50` |
| Recovered when a customer pays the painter in cash | 10%: the fintech will not chase (batch 5; earlier 25%) | `recovery_rate_by_outcome.bypass: 0.1` |
| Pay late | 20%, and they do pay in full | `outcome_probs.late: 0.20`; `recovery_rate_by_outcome.late: 1.0` |
| Cost to serve per loan | RM5 with automation | `pricing.cost_to_serve_per_bridge: 5` |
| Average loan | about RM10,000 | `simulation.amount_distribution.mean: 9.55` (the mean of ln RM, arithmetic from that); the per-bridge and per-borrower caps are raised (placeholders) so the loans are not cut off |
| The DFI's cost of funds | 3% | `financier.cost_of_funds_pa: 0.03` |
| Said earlier in the conversation | 70% cover, 3.5% guarantee fee, 18% a year all-in cap | `layers.guarantor_cover_pct`, `pricing.guarantee_fee_rate_on_drawn`, `pricing.all_in_rate_cap_pa` |

`pricing.flat_fee_per_bridge` is 360 only so the older report sections agree with the cap (a placeholder). The reserve (RM50,000) and the guarantor cap (RM25,000) are the demo's ratios scaled ×5 to the cohort of 100; they are not the author's numbers.

**Trip wire at 5% with a 30-loan minimum:** the base case loses about 5.7% of money lent, so the line fires in about **88% of cohorts** and pauses new loans (84% of cohorts paused by any stop line). That cuts losses (the joint result before the reserve charge improves from RM29,240 to RM20,649 per group) but the programme stops lending early. Set it above the loss rate you plan for, or accept that it is a brake you expect to use.

**What it shows** (1,000 groups of about 96 loans, trip wire off; reserve RM50,000 all from the DFI; 10% recovered on cash payments; guarantor with no cap and a 3% required return). At 5% cash the DFI and guarantor together lose about **RM306 per loan** after funding the reserve.
Before the reserve's funding cost, the rate that covers every cost is 15.7% a year against the 18% cap. The guarantor, with no cap, earns about −1.3% a year on its capital against its 3% hurdle, and loses in 54% of cohorts; its worst-5% cohorts lose about RM40,000.
One caution: with no cap the engine sets aside the whole cohort cap as the guarantor's capital, which overstates the capital charge. Joint result per loan, after funding the reserve:

| Cash chance | 10% recovered (the answer) | 25% recovered | 50% recovered |
|---|---|---|---|
| 8% | −RM581 | −RM458 | −RM252 |
| **5% (the answer)** | **−RM306** | −RM228 | −RM99 |
| 3% | −RM125 | −RM78 | +RM2 |
| 2% | −RM28 | +RM4 | +RM56 |
| 1% | +RM67 | +RM83 | +RM109 |
| 0% | +RM161 | +RM161 | +RM161 |

At 10% recovered, the two together cover costs from about 1% cash, but a working split of the cap exists only at **0% cash**; at 5% the DFI would need about 25% a year and the guarantor about 10%. Chasing cash payers (25% instead of 10%) is worth about RM78 per loan at 5% cash.


## Interpretations made in the build

| # | Where | Choice | Why / how to change |
|---|---|---|---|
| D1 | `decide.py` | need = max(0, materials − deposit × `deposit_to_materials_share`); amount = min(need, materials, invoice, per-bridge cap, headroom under every cap) | Handover §6.2, flagged as open item 1. A plain cap at materials cost is `deposit_to_materials_share: 0`. |
| D2 | `decide.py` | ~~Approved amount never exceeds the quoted materials cost, even with a signed variation order.~~ | Superseded by A5. |
| D3 | `decide.py` | Template mismatch → manual review, not a block. | Confirmed by the author (A6). |
| D4 | `decide.py` | Routes after screening: `DECLINE` (adverse record, related payer, duplicate job), `BLOCKED` (any other failed check, or no cap headroom), `RELEASE`. | Separates "never" from "not yet". |
| D5 | `decide.py` | Two-step release: tranche 1 = `two_step_release_over_amount`, tranche 2 = the rest. | Avoids inventing a split ratio. |
| D6 | `decide.py` | `credit flag = none` blocks when `require_credit_bureau_check` is true. | Bureau check is required at first bridge. |
| D7 | `decide.py` | Trade record is met if months in trade **or** completed jobs reach `min_trade_months_or_jobs`. | One key for both, as in the handover. |
| D8 | `pricing.py` | Fee-ceiling months = tenor days / 30 (90 days → RM900 on RM20,000). | Matches the worked test. |
| D9 | `pricing.py` | `breakeven_fee` = cost to serve + guarantee fee + expected financier loss. | Handover §6.4 as written. |
| D10 | `collections.py` | A bridge paid in full after going late closes as `PAID_LATE`. | The log has a `late` outcome; the spec's state list has no end state for it. |
| D11 | `collections.py` | Bypass and abandonment go straight to `RECOVERY` after their first-step tasks; a dispute stays in `DISPUTE` until mediation finds the borrower at fault. | Follows the design's collections table. |
| D12 | `collections.py` | ~~A bypass blocks the borrower for the rest of the pilot.~~ | Superseded by A7 (cure path). |
| D13 | `collections.py` | Write-off takes the cohort's *remaining* reserve and guarantor cap (default: full config values). | Keeps single write-offs consistent with `allocate_pool`. |
| D14 | `gates.py` | Pass thresholds live in a new `gates.*` block, all null. A gate with several metrics is `FAIL` if any fails, `PASS` only if all pass. | The design leaves stop lines open; the handover asks for thresholds "from config". |
| D15 | `gates.py` | Gate 0 needs the jobs file (`--jobs`); without it the value is empty. | The log alone has no unbridged quotes. |
| D16 | `gates.py` | All-cohort loss is measured against one reserve per cohort. | Follows open item 2 (reserve per cohort, assumed). |
| D17 | config | Added `meta.demo` (drives the DEMO banner), `Exposure.live_job_ids` and `Exposure.borrower_blocked`, `Bridge.sponsor_cohort`. | Needed for the listed rules; no new behaviour. |
| D18 | config | The template comment for the fee-ceiling reference names no organisation. | Ground rule 3. The handover's §10 source note stays in the handover. |
| D19 | `decide.py` | KYC uses the provider's results: KYC failed → `DECLINE`; pending or missing → `BLOCKED`; screening true match → `DECLINE`; possible match or politically exposed person → manual review (enhanced due diligence); no screening result → `BLOCKED`; payer identity not confirmed → `BLOCKED`. Each rule has a config switch. | The author asked for standard KYC. The engine reads results; it never verifies identity itself. |
| D20 | `decide.py` | `release.margin_of_advance` caps the bridge at that share of the **quoted materials cost**. Above 1.0 is refused (`ConfigInvalid`). | Keeps the design's hard cap while allowing "better than market" (market products advance against contract or invoice value). |
| D21 | config | `market_reference` holds public, dated benchmarks, sources described without organisation names, `approved_by_author: false`. Comparison only. | The author asked for "slightly better than market"; ground rules 1 and 3. |
| D22 | `simulate.py` | `amount_distribution` draws the **materials cost** of each job, with `deposit_share_of_materials`; the bridge amount comes from `advance_limit`, the live rule. | §6.7 says "draw amounts". Drawing materials lets margin of advance, deposit offset and caps act in the simulation exactly as in `decide`. Confirmed by the author (A8). |
| D23 | config | Added `tenor.typical_days` (the guarantee fee needs a tenor). `tenor.grace_days` is not used by any module yet. | §4 has no tenor length. |
| D24 | `simulate.py` | Bypass stop line: bypass rate to date, tested once `stop_lines.bypass_rate_min_bridges` are out (new key). | A rate over 1 bridge is meaningless; the minimum is a pilot setting, not a guess. |
| D25 | `simulate.py` | The guarantee fee is paid by the borrower and passed to the guarantor. Break-even flat fee = cost to serve + expected financier loss. | Confirmed by the author (A4). |
| D26 | `simulate.py` | Sensitivity: bypass ±25% moves the difference to or from on-time; recovery ±25% scales every outcome except on-time (repaid in full), capped at 100%; same random draws for every case. | One input at a time, no noise. |
| D27 | `simulate.py` | "Reserve exhausted" = a cohort's total loss reaches the reserve. `caps.per_sponsor_cohort` stops releases within a cohort. | Direct reading of §6.7. |
| D28 | `report.py` | White page only, no dark mode. | Ground rule 7. |
| D29 | `simulate.py` | The all-in cap is read as 1.5% a month = 18% a year, simple interest, covering the financier fee and the guarantee fee together. Financier fee = cap − guarantee fee, on the drawn amount over `tenor.typical_days`. | From the author's brief ("1.5% incl. financing charges and guarantee fees, that's 18% pa"). Matches the fee-ceiling reference and the moneylender unsecured cap; legal to confirm how a DFI product is treated. |
| D30 | `simulate.py` | **Programme cost** = DFI + guarantor + the reserve that was used. Since the DFI and the guarantor are the sponsors (A17), the **funders' loss budget covers the whole programme**, the reserve included. | Replaces the earlier reading that the reserve was pre-funded by someone else. |
| D31 | `simulate.py` | The financier's return is before its cost of funds. | The engine has no funding-cost number and none is invented. Subtract it by hand. |
| D32 | `gates.py` | Gate 4 **Additionality**: two answers recorded at release, "new to formal credit" and "says the job would not go ahead without the bridge". A borrower is *fully additional* when both are true. Pass marks are `gates.gate4_*`, null. Not asked counts as unknown, never as no. | The article leaves additionality open; this measures it from the pilot instead of assuming it. |
| D33 | `simulate.py` | "Cost per additional borrower" in the report is an **illustration** over 25/50/75/100% additional, not a finding. | The real share comes from gate 4. |
| D35 | `simulate.py`, `ledger.py` | **Loss for the trip wire** = loss after recoveries, as a share of the money lent on bridges whose outcome is *known*. In the simulation, all but the last `outcome_lag_bridges`. Live, a bridge is known once it is closed or has gone into recovery or dispute. | Counting loans still out as fine would hide losses; counting them all as lost would trip it on day one. |
| D36 | `ledger.py` | Live loss so far = amount written off + the full outstanding balance of bridges in recovery or dispute (cautious, until recovered). | Recoveries lower it later; it does not wait for the write-off date. |
| D37 | `decide.py` | The wire does not lift itself. A named officer lifts it by changing the line in the config, a recorded decision. Top-ups are blocked too. | Pausing money must not be undone silently. |
| D38 | `simulate.py` | **Damage** = the outcomes `dispute` (rejected) and `abandoned` (not completed); `simulation.damage_dispute_share` splits the rate between them. Late payments and cash to the painter keep their config chances. | The brief gave one number for "not completed or rejected". |
| D39 | config | The demo leaves the trip wire **off** (`pause_if_loss_rate_over: null`), so earlier numbers do not move; the damage section shows its effect on its own sliders. | Keeps the published walkthrough numbers stable. |
| D40 | `riskreturn.py` | The DFI's funding is split into debt at `cost_of_funds_pa` and equity at `capital_pct_of_drawn` of the drawn amount, which must earn `cost_of_equity_pa` (its hurdle). Spread = return on that equity − the hurdle. | A DFI's real capital rules are more detailed; one equity share is the simplest honest stand-in. |
| D41 | `riskreturn.py` | The guarantor's capital is its guarantee cap (`layers.guarantor_cap`), set aside for `simulation.cohort_days`. Return on capital = result ÷ (cap × cohort days ÷ 365), compared with `guarantor.cost_of_capital_pa`. | Its worst case is the cap, so the cap is the capital at risk. |
| D42 | `riskreturn.py` | The DFI bears the cost to serve (as in the earlier returns analysis). The sponsor's reserve use is shown for context but is no party's return. | Keeps the two parties comparable; the sponsor funds first loss as a development contribution. |
| D43 | `riskreturn.py` | **Break-even fee** = the fee at which a party's economic profit (result less its capital charge) is exactly zero. The two break-even fees added are the all-in rate that covers every cost; its gap to the cap is what developmental pricing gives up. | Ties the risk-return view back to A13. |
| D44 | `riskreturn.py` | Risk is shown three ways: a bad group (5th percentile), the average of the worst 5% of groups, and the chance of a loss-making group, plus mean ÷ standard deviation. | No single measure is enough with so few loans per group. |
| D45 | `riskreturn.py` | The reserve is held for **cohort days + the write-off period** (`simulation.cohort_days` + `collections.write_off_after_days`). Each party is charged for its share of the reserve for that time at **its own required return** (the DFI's cost of equity, the guarantor's cost of capital). | No new number: the hold comes from two settings that already exist, and the charge from each party's own hurdle. |
| D46 | `riskreturn.py` | Each party's result after funding the reserve = its result − its share of what the reserve spends (and, if unused reserve is forfeited, its share of that too). Return on capital counts the money it tied up in the reserve as capital. | The reserve is real money the party puts up, so it belongs in the party's return. |
| D47 | `riskreturn.py` | Recoveries after a write-off are not added back to the reserve; the split of the reserve between the two is a setting, not a rule. | Not modelled; including recoveries would lower both parties' cost. |
| D48 | config | The names `sponsor_cohort` and `caps.per_sponsor_cohort` come from the handover and are kept; they now mean the cohort the DFI and guarantor fund. | Renaming would break the log format and the config for no gain. |
| D49 | `riskreturn.py` | A loan earns the cap × days ÷ 365 of its size. The chance of damage, lateness and cash payments **per loan** does not change with the tenor. | Placeholders: a longer tenor may raise them. The pilot has to measure it. |
| D50 | `riskreturn.py` | "Loss on bad loans" scales the config's loss on three outcomes: rejected, not completed and cash to the painter (1.0 = as configured, 0.75 = a quarter less lost). Late payments are not scaled. | One lever for recovery, not three. |
| D51 | `riskreturn.py` | **Verdict.** 2 = the two fees each party needs for its required return (its break-even after funding the reserve) add up to no more than the cap, so a working split exists. 1 = the joint result is not negative, but no split of the cap gives both their required return. 0 = the two lose money together. | Whether it works depends on how the cap is split as well as on the cap. Raising the cap alone does not help the guarantor, who earns the guarantee fee. |
| D52 | `riskreturn.py` | The fees shown as "needed" are the minimum each party needs to earn exactly its required return, not a recommendation. | Any split with both fees at or above them leaves a margin. |
| D34 | `pricing.py` | The fee rule is unchanged: a recommended fee comes from cost to serve plus expected loss, never from a rate. The developmental view is a stress test at a given cap, not a fee recommendation. Break-even stays the benchmark that shows how far below cost the product is priced. | Ground rule on pricing; developmental pricing departs from break-even on purpose, so the gap must stay visible. |

## Open items for the author (not guessed)

1. ~~Bridge need formula (D1) versus a plain cap at materials cost.~~ Decided (A2).
2. ~~Reserve shared across a cohort (assumed) or held per borrower.~~ Decided (A3).
3. ~~Which financier types are in the pilot.~~ Decided (A1).
4. Real thresholds for stop lines and gates, and every null in `params.template.yaml`
   (`bridge check-config` lists them).
5. ~~Whether the controlled account needs central-bank approval as e-money or a payment service.~~ The author reports legal has confirmed it (batch 4); the engine records the status. Keep the written advice on file.
6. The `market_reference` sources: the author's team opens each one (A9), keeps or drops it, then sets
   `approved_by_author: true`.
7. The fee-ceiling reference (1.5% a month): kept, on two sources (A10). The author's team confirms which
   product of the public scheme carries the 1.5% charge.

8. The **funders' loss budget per cohort** (`development.funder_loss_budget_per_cohort`): the DFI and the guarantor agree what they can lose.
9. ~~The **all-in cap** and its legal treatment.~~ The author reports legal has confirmed it (batch 4). Keep the written advice on file.
10. The DFI's **cost of funds**, and what counts as "additional" (definition and the `gates.gate4_*` pass marks).

11. The **trip wire line**, the minimum number of loans with a known outcome before it can fire, and who is the named officer who can lift it. Set it above the loss rate you plan for, or it fires on normal days.
12. The **outcome lag** (how many loans are released before an earlier loan's outcome is known). It depends on the tenor and how fast loans are made, and the pilot will show it.

13. **Each party's own costs and hurdles:** the DFI's cost of funds, equity share and cost of equity; the guarantor's cost of capital, admin cost per bridge, and how long its capital is set aside per cohort. The demo values are placeholders and carry no meaning.

14. The reserve split is decided (the DFI funds all of it). Still open: the escrow terms (funded up front, ring-fenced, so the guarantor's cover does not rest on a promise), when unused reserve is released, and how recoveries after write-off are treated.

16. The cohort size and the controlled-account cash chance are answered as assumptions (100 loans, 5%). The reserve size is unclear (batch 6). Still open: the real stop-line minimums (50 is my suggestion) and the funders' loss budget.
15. The **real tenor** (the job plus the customer's payment cycle), and whether the damage, late and cash-payment chances rise with it; and the **real cash-payment chance** once a controlled account and split payments are in place.

## What the demo run shows (demo values, not findings)

- Above a 90% margin of advance nothing changes: every simulated deposit is at least 10% of materials,
  so the bridge never needs more. The deposit, not the margin, sets the bridge size.
- The demo fee (RM60) puts the borrower at about 2.2% a month, above the market's 0.8–1.5%, and above
  the fee-ceiling reference. The simulated break-even flat fee is about RM35 (about 1.3% a month), which
  is where "slightly better than market" becomes possible, if cost to serve holds.

## What the demo run shows (demo values, not findings)

- Above a 90% margin of advance nothing changes: every simulated deposit is at least 10% of materials,
  so the bridge never needs more. The deposit, not the margin, sets the bridge size.
- The demo fee (RM60) puts the borrower at about 2.2% a month, above the market's 0.8–1.5%, and above
  the fee-ceiling reference. The simulated break-even flat fee is about RM35 (about 1.3% a month), which
  is where "slightly better than market" becomes possible, if cost to serve holds.

## In the design, not built (out of the listed scope)

- Registration not required for the smallest first bridge, if the financier's rules allow.
- Live-bridge limit stepped up after clean repayments.
