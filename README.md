# Job-Linked Bridge

**Finance the materials of one confirmed job, pay the supplier directly, and get repaid from that job's payment.**

> **Pilot design tool, not a live product yet.** The rules are real and tested; the numbers are not.
> No Malaysian loss data exists, so every limit, rate and probability in `config/params.demo.yaml` is
> made up (`# DEMO ONLY, not a finding`) and every page built from it says **DEMO PARAMETERS**. The
> sample data is synthetic. Views are the author's own. Not financial advice.

## The problem, in one job

A painter wins a **RM12,000** job. The customer pays a **RM2,000** deposit. Paint and fittings cost
**RM5,000**, and the supplier wants paying before delivery. A bank asks for collateral or a track record
the painter does not have. So who funds the RM3,000 gap?

The **bridge** does. It uses the job itself as the security: it pays the **supplier** (never the
painter) the RM3,000, the customer pays the final bill into an **account the lender controls**, the
bridge is repaid first and the rest goes to the painter. If the customer never pays, the loss falls on
a **sponsor's reserve** first, then a **guarantor**, and only then on the **lender** (a DFI).

## How it works

```
 CUSTOMER confirms a job with a TRADESPERSON (painter, tiler, electrician, plumber)
        │  quote with a materials list, named payer, deposit paid
        ▼
┌──────────────────────────────────────────┐
│ 1. FOUR QUESTIONS (screen)               │  any 'no' stops here:
│    named payer, not the borrower?        │  refer to general micro-financing,
│    materials are the main cost?          │  refer to contract / invoice financing,
│    household / individual / small biz?   │  or 'no bridge needed'
│    deposit below the materials cost?     │
└─────────────────────┬────────────────────┘
                      │  passes all four
                      ▼
┌──────────────────────────────────────────┐
│ 2. CHECKS (decide)                       │  fail  → DECLINE or BLOCKED
│    eKYC, financial-crime screening,      │  small first bridge: registration
│    payer identity, credit record,        │  may be waived (A11)
│    business registration, trade record,  │  possible screening match → officer
│    PDPA consent, supplier on the panel,  │
│    one live bridge per job, no bypass    │
└─────────────────────┬────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────┐
│ 3. HOW MUCH (decide)                     │  painter: RM5,000 − RM2,000 = RM3,000
│    gap = materials − deposit             │  large job → two tranches
│    capped by: margin of advance,         │  small template job → automatic
│    per-bridge cap, supplier invoice,     │  otherwise → a named credit officer
│    borrower / supplier / cohort /        │
│    pilot caps (step up after clean       │
│    repayments)                           │
└─────────────────────┬────────────────────┘
                      │  RELEASE
                      ▼
┌──────────────────────────────────────────┐
│ 4. PAY THE SUPPLIER, never the borrower  │  variation signed by the payer?
│    bridge recorded on the staff page     │  → top up the same bridge (A5)
└─────────────────────┬────────────────────┘
                      │  job done
                      ▼
┌──────────────────────────────────────────┐
│ 5. CUSTOMER PAYS the controlled account  │  on time → clean repayment,
│    bridge repaid first, balance released │  counts toward a step-up
│    to the tradesperson                   │
└─────────────────────┬────────────────────┘
                      │  something goes wrong
                      ▼
┌──────────────────────────────────────────┐
│ 6. RECOVERY (collections) — tasks only   │  bypass repaid + officer approval
│    late: reminder → notice → escalate    │  → block lifts; second bypass → out
│    bypass: hold, block, recover          │  no home or workplace visits
│    dispute: hold part, mediate           │
│    abandoned: supplier takes stock back  │
│    stop chasing when it costs more       │
└─────────────────────┬────────────────────┘
                      │  written off
                      ▼
┌──────────────────────────────────────────┐
│ 7. WHO ABSORBS THE LOSS (waterfall)      │  claim file for the guarantor:
│    1st  sponsor's first-loss reserve     │  job record, invoice, receipts,
│         (one pool per cohort)            │  notices, recovery steps
│    2nd  guarantor, a share up to a cap   │
│    3rd  financier (DFI), the rest        │
└─────────────────────┬────────────────────┘
                      │  every month
                      ▼
┌──────────────────────────────────────────┐
│ 8. PILOT GATES (from the bridge log)     │  no pass mark set → NO_THRESHOLD_SET
│    0 size  1 mechanics                   │  (the engine never invents one)
│    2 performance  3 economics            │
│    cohort 2 only if 1 and 2 PASS         │
└──────────────────────────────────────────┘
```

**In one sentence:** the engine decides whether a job qualifies and how much to lend against it, sends
the money to the supplier, tells staff what to do when the customer does not pay, splits any loss
between sponsor, guarantor and lender, and scores whether the pilot is working.

| Box | What it is in the code |
|---|---|
| 1 Four questions | `screen.py` |
| 2–3 Checks and how much | `decide.py` (`decide`, `advance_limit`, `borrower_limits`) |
| 4 Pay the supplier, variation top-ups | `decide.py` (`decide_variation`), staff page `app.py` |
| 5–6 Repayment and recovery | `collections.py` |
| 7 Who absorbs the loss | `waterfall.py` |
| 8 Pilot gates | `gates.py` |
| Price and compliance checks | `pricing.py`, `compliance.py` |
| What-if dashboard | `simulate.py`, `report.py` |
| Staff page and its record | `app.py`, `ledger.py`, `store.py` (SQLite) |

## Who uses it

| Who | When | Where |
|---|---|---|
| Job source staff | a customer confirms a job | **Staff page → New job** |
| Credit officer | deposit paid, supplier invoice in | **Staff page**: decision, then *Record release* once the supplier is paid |
| Credit officer | the customer signs a variation | **Staff page → bridge → Variation signed: top up** |
| Collections owner | daily, for late bridges | **Staff page → Bridges and tasks**: set days past due; tasks appear on their day |
| Pilot steering group | monthly | **Staff page → Pilot gates**, or `bridge gates` on a log |
| Management, DFI, guarantor, sponsor | before and during the pilot | **What-if dashboard**: `bridge simulate` (see [`docs/demo_report.html`](docs/demo_report.html)) |

## Try it

Windows PowerShell, one line at a time. Use Python 3.11 to 3.13: on a newer pre-release Python, PyYAML has
no ready-made package yet and the install asks for a C++ compiler.

```powershell
git clone https://github.com/dewatagiri/self_employed_bridge.git
cd self_employed_bridge
py -3.13 -m pip install -e ".[dev]"
py -3.13 -m pytest -q
```

**Staff page** (then open <http://127.0.0.1:8000> and press *Fill the example job*):

```powershell
py -3.13 -m self_employed_bridge.cli serve --config config/params.demo.yaml
```

**What-if dashboard** (charts, market comparison, sliders):

```powershell
py -3.13 -m self_employed_bridge.cli simulate --config config/params.demo.yaml --out report.html
start report.html
```

On Mac or Linux use `pip install -e ".[dev]"` and the `bridge` command, e.g. `bridge serve --config config/params.demo.yaml`.

Other commands: `screen`, `decide` (add `--top-up-after RM` for a variation), `waterfall --loss RM`,
`gates`, `check-config`. Add `--json` for machine-readable output.

## The rules as built

The author's decisions are numbered **A1–A12** in [`docs/DECISIONS.md`](docs/DECISIONS.md).

- **Who is in it** (A1): a development financial institution funds the bridges; a guarantee provider
  covers part of the loss; a sponsor funds the first-loss reserve; a job source holds the quote and deposit.
- **Who qualifies:** all four questions must be yes. Companies, agencies and GLCs with a purchase order go to
  contract or invoice financing instead.
- **Identity:** eKYC verified, financial-crime screening clear (a possible match or politically exposed person
  goes to an officer for enhanced checks; a true match is declined), payer identity confirmed, PDPA consent.
  The engine reads the provider's results; it never verifies identity itself.
- **Registration** (A11): business registration is required, except for a borrower's first bridge at or below
  a set amount, if the financier's rules allow.
- **How much** (A2): the whole deposit counts first, so the bridge covers only the gap. Never above the materials
  cost; capped by the margin of advance, the per-bridge cap, the invoice, and the borrower, supplier, cohort and
  pilot caps. Borrower limits **step up** after clean repayments (A11).
- **Who is paid:** the supplier, always. Larger jobs release in two steps.
- **Review:** automatic only for a small job that passes everything and matches the trade template; otherwise a
  named credit officer. A template mismatch goes to the officer, not a block (A6).
- **Variations** (A5): a variation signed by the payer can top up the same bridge, within every limit, always
  reviewed by an officer.
- **When it goes wrong:** the engine produces tasks with an owner (job source, financier, collections owner,
  supplier); it contacts nobody, and no task asks for a home or workplace visit. A **bypass** (customer pays the
  borrower) blocks the borrower until it is repaid in full and an officer approves; a second bypass is final (A7).
- **Losses** (A3): one first-loss reserve per sponsor cohort, then the guarantor up to its cap, then the DFI.
  Every write-off gets a claim file for the guarantor.
- **Price** (A4): one flat fee per bridge, set from measured cost to serve plus expected loss, never from a rate.
  The borrower also pays a guarantee fee on the amount drawn, which goes to the guarantor. A fee above 1.5% a
  month on the bridge triggers a "needs a stated reason" warning (A10).
- **Pilot gates:** size, mechanics, performance, economics. A gate with no pass mark says
  `NO_THRESHOLD_SET`; cohort 2 may start only when cohort 1 passes gates 1 and 2.

## Nothing is hard-coded

| File | What it holds |
|---|---|
| `config/params.template.yaml` | the real settings. Pilot numbers are `null` until agreed; the engine refuses to decide while one it needs is `null`, and names it |
| `config/params.demo.yaml` | made-up numbers so everything runs |

`bridge check-config config/params.template.yaml` lists every setting still missing and what it blocks.
[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) says who sets each one, in what order, with real outputs from
one job, one cohort and one pilot.

**Margin of advance and the market.** Market contract and invoice products advance 80–100% of contract or
invoice value, often against collateral. This bridge advances against the quoted materials cost, with no
collateral. The market figures sit in `market_reference`, marked pending until the author's team checks
each source (A9); they are shown for comparison and never drive a decision.

## Developmental pricing

If the borrower's all-in charge is capped (for example 1.5% a month, 18% a year, guarantee fee included), the
product may sit **below cost**. That is a choice, not a mistake: the DFI and guarantor knowingly accept a
planned loss in return for **additionality**, reaching borrowers the market does not serve (decision A13).

- The simulation report has a **Developmental pricing** section with sliders for the guarantor's cover, the
  all-in cap, the guarantee fee and the cost to serve. It shows each party's result and the **planned programme
  cost** per loan and per RM1,000 lent, counting the sponsor's reserve too. It claims no return.
- The cost buys something only if the bridge reaches the right people, so that is **measured, not assumed**.
  Gate 4 uses two answers recorded at release (on the staff page): is the borrower new to formal credit, and
  does the borrower say the job would not have gone ahead without the bridge.
- `pricing.all_in_rate_cap_pa` and `development.funder_loss_budget_per_cohort` are settings, empty in the
  template until the DFI and guarantor agree them. The financier's return is before its cost of funds.

## Risk and return: the DFI and the guarantor

One section of the simulation report compares the two parties that carry credit risk above the sponsor's reserve, each
with **its own costs** (decision A15). The DFI pays interest on the debt that funds the loans, holds equity against them and
bears the cost to serve. The guarantor sets its guarantee cap aside as capital and pays an admin cost per bridge.

For each it shows the result per group, the **return on capital against its own hurdle (the spread it earns)**, economic profit,
and risk: a bad group, the average of the worst 5% of groups, and the chance of a loss-making group. It also shows each party's
**break-even fee**, the all-in rate that covers every cost, and the gap to the borrower's cap. All costs are settings:
placeholders in the demo, empty in the real template.

### The reserve: the DFI and the guarantor are the sponsors

There is no outside funder (decision A17). The DFI and the guarantor **fund the first-loss reserve between them, up front, into a
ring-fenced account** (a promise is not enough: the guarantor's cover sits on top of it), and every rand of credit loss lands on the
two of them. What the cohort does not spend goes back (A16). The report shows each party's result **after funding its share**,
with its money tied up charged at its own required return, a table of what each reserve size costs and does for each, and the
**joint result**: what the two of them lose or earn together.

## The author's base case

`config/params.base_case.yaml` is the demo with the author's own answers on top (a 60-day tenor, 3% damage, 70% lost on each damaged loan,
70% cover, a 3.5% guarantee fee, an 18% a year all-in cap), each marked `AUTHOR ASSUMPTION`. They are assumptions, not findings, and the
rest is still placeholder, so its reports still say DEMO PARAMETERS. Open it with
`bridge simulate --config config/params.base_case.yaml --out report.html` ([`docs/base_case_report.html`](docs/base_case_report.html)).
On this case the product is priced below cost whatever the cost to serve; the cash-payment chance and the recovery rates are the unknowns that matter most.

## Path to viability

Low-ticket loans are usually not profitable, and serving them is the mandate (decision A18). A loan earns **by time** (the cap ×
days ÷ 365 of its size) but loses **by the loan**, so a short tenor, cash payments to the painter, damaged projects and a high cost to
serve all work against it. The report's *Path to viability* section has five sliders (the chance the customer pays the painter in cash,
the damage rate, how much is lost on bad loans, the tenor, and the cost to serve) and ends in a **verdict**:

- **Priced below cost**: the DFI and the guarantor lose money together, by so much per loan.
- **Costs covered, but no split of the cap gives both their required return.**
- **A split of the cap exists where both earn their required return**, and the section says what each party's fee would have to be.

Where a gap remains it is priced **per additional borrower**, which is what to ask a party that values additionality to pay. The cap
is a rate a year and losses come per loan, so the tenor and the loss rate matter more than the ticket size.

## Loss trip wire

`stop_lines.pause_if_loss_rate_over` is the line (for example 4%): when the loss so far, after recoveries, passes it as
a share of the money lent on loans with a known outcome, **new loans and top-ups stop** (decision A14).

- **Live:** `decide` returns `BLOCKED` with `TRIP_WIRE_LOSS`, and the staff page shows a banner. A named officer lifts it
  by changing the line in the config.
- **Simulation:** the report's *Damage rate and the loss trip wire* section has sliders for the damage rate, the loss on each
  damaged loan and the trip wire, and shows the loss avoided against the loans given up, on the same random draws.
- It trades **reach for loss**, and it cannot stop loans already out (outcomes arrive late). Set the line above the loss
  rate you plan for, or it fires on normal days.

## Honest limitations

- **No loss data.** The dashboard is a what-if tool. It shows which settings matter, not what will happen.
  It assumes pricing and margin of advance do not change how people behave, and bridges are independent.
- **No money moves here.** The engine and the staff page do not pay suppliers, connect to banks, run eKYC or
  contact anyone. Staff do those things and record them.
- **The staff page is for one PC and a small first cohort.** It has no user logins, so the record shows what
  was done but not who did it. A live product needs logins, a shared database and backups.
- **Legal points are flags, not answers:** whether the controlled account needs central-bank approval, and how
  the fee is treated under the DFI's rules, are for legal to confirm.
- **Market references are unverified** until the author's team opens each source.

## More

[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (design and data flow) ·
[`docs/DECISIONS.md`](docs/DECISIONS.md) (every decision and interpretation, open items) ·
[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) (real outputs, go-live order) ·
[`docs/demo_report.html`](docs/demo_report.html) and [`docs/demo_gates.html`](docs/demo_gates.html)
(open in a browser) · 221 tests (`pytest`).

## Licence

MIT. See [`LICENSE`](LICENSE). The demo numbers are made up and the code is a pilot design tool, so
use it at your own risk. Not financial, investment or legal advice.
