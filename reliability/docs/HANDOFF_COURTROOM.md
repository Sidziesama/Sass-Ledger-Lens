# Handoff: what the JS courtroom on `main` needs to pass the benchmark

Scored at `main` @ d180870 with the 56-case reliability benchmark: **8/56** with normalized
input, **0/56** on the raw canonical CSVs. Reference implementation of every item below lives
under `reliability/` on the `reliability` branch (file named per item). Reproduce:

```bash
git checkout reliability && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
git worktree add /tmp/court origin/main
COURTROOM_ROOT=/tmp/court .venv/bin/python -m reliability.benchmark.evaluate \
  --runner reliability.benchmark.adapters.courtroom_v1:run_normalized -v
```

`-v` prints, per failing case, the exact check and what the engine said.

## 1. Input contract (0/56 raw → everything blocks)
`prepare()` requires `id, date, month, account, counterparty, segment, category, status` on
every row; a missing `segment` or `category` is a schema issue that removes the row, so no
account ties out and every claim is blocked. The sponsor's inputs are "simple CSVs".
**Fix:** accept `transaction_id`/`period` as synonyms, default missing `segment`/`category`
to `Unspecified`, derive `date` from `period` when absent, parse `$1,234`, `(500)`, `1,000-`,
four date and six period formats. Ref: `ingestion/normalize.py`.

## 2. The brief never states a limitation (48 cases — the big one)
`judge()` produces "movement" and "top-3 drivers" and stops. The benchmark expects the
memo to say, when true:
- zero prior base → "percentage change is not meaningful" (it prints `no percentage`, close — say it in words)
- reversal pair (+X then −X, same counterparty) → "is the reversal of …"
- reclassification detected from the data (same vendor moves accounts, net-income neutral),
  not only when a row is literally tagged `category = Reclass`
- one-time item (n-sigma above the account's own history) → "non-recurring, do not extrapolate"
- distributed movement (top-3 < 35% across 20+ counterparties) → say so, stop drilling
- new / inactive counterparty → "had no activity in <period>"; never "churned", never −100%
- concentration → "not broad-based"; outlier masking → "excluding X, revenue declined by …"
- **always**: "The available data does not establish why …" when only attribution exists
- seasonal norm when ≥13 months of history (same month in prior years)
- blocked account → "cannot reliably attribute <account>: <reason with the gap amount>"
- memory: "consistent with PR-…", "exceeds the learned range", "was not applied: expired / rejected"
Ref: claim templates in `agent/reference.py`; detectors in `finance/detectors.py`.

## 3. Data-quality flags (12)
Tie-out failure is the only signal. Add: reconciliation gap **with the amount**; near-duplicate
(same account + counterparty + amount within 2 days, different ids, ≥ $5K; a run of 3+ is a
series, not a duplicate); duplicate id; conflicting summary rows vs missing summary;
naming variants; sign inconsistency; period gaps; cutoff (date outside period);
look-alike unicode names. Severity blocker / warning / info decides what may be said.
Ref: `quality/gate.py`.

## 4. Counterparty normalization (A07)
"Acme", "acme ", "ACME" are three customers today. Group on a normalized key
(NFKC, casefold, collapse whitespace); display the first spelling.

## 5. Materiality (5 cases)
Flat `|delta| ≥ $10,000`. A $9,000 move on a $10,000 account is material; a $2,300 move on
$500 must not out-rank a $300K revenue move. Score = absolute (relative to the section's size)
+ percentage (capped) + historical abnormality + contribution to the section's movement,
with policy overrides (critical accounts, first activity in an account, data-quality flag).
Ref: `finance/materiality.py`, `_rank()` in `agent/reference.py`.

## 6. Confidence and abstention (11)
One rule (tie-out ok → approved) gives "high" even when a material account is blocked or a
memory is contested. Track data / attribution / context / evidence-coverage separately and
derive high / medium / low from explicit rules; abstain **per account** with wording.
Ref: `policy/uncertainty.py`.

## 7. Drivers (3)
Top-3 by counterparty only. Add: drill inside the winning segment to the customer
("Within Enterprise, Acme +$52K"), single-transaction concentration measured on the
transaction's *incremental* amount, offsetting movements that net out, unexplained residual
stated in dollars and %.

## 8. Memory (13 of 14 memory cases fail)
`propose()` only creates memory claims for an account literally named `Cloud Costs`, and only
for kind `cloud-baseline`. Generalize to any account; add `source_type`
(user_verified / system_inferred / hypothesis), `contested` and `rejected` statuses reported
with a reason; **write** memory from each run's verified findings (reclass, one-off, silent
churn) so the next run uses it — the sponsor's "learn across runs". Ref: `memory/store.py`,
`memory/learn.py`, the four `S0x_*` sequence cases.

## 9. Small ones
- No-change month: a $3K wobble below materiality must not yield "Revenue increased …";
  say "No financially material or historically unusual movements were identified."
- Near-duplicate counted twice ("Fieldmark +$160,000") — item 3.
- `scripts/verify.mjs` needs `npm install` (papaparse) before it runs.
- Percentages: keep ≤ 1 decimal; any figure with ≥ 3 decimals is "false precision".

## 10. If a model writes the brief (GIDE is mandatory)
Give it verified claims only; lint the draft — every number must trace to a claim, every
sentence must cite a claim id, no "caused / because of / due to" without a causal claim —
and ship the template when it fails. Measured on the 1.5B: 50/56 drafts accepted, 0
invented figures shipped. Ref: `agent/memo.py`, `policy/language.py`, `agent/llm.py`.
