# Benchmark comparison — every branch vs the reference investigator

Same 56 cases, same evaluator, same ground truth. Each version is scored through an
adapter that feeds it the case files and renders a `RunResult` from **its own** output
(its claim text, its statuses, its flags). Nothing under any teammate branch is modified.

```bash
python -m reliability.benchmark.evaluate                                                                  # reference
git worktree add /tmp/rh origin/reliability-hardening
python -m reliability.benchmark.evaluate --src-root /tmp/rh --runner reliability.benchmark.adapters.main_v1:run
git worktree add /tmp/court origin/main
COURTROOM_ROOT=/tmp/court python -m reliability.benchmark.evaluate --runner reliability.benchmark.adapters.courtroom_v1:run_normalized
```

| | `main` @ d180870 (JS courtroom) | `python-grounded-prism` @ c22adba | `reliability-hardening` @ 9b0eed8 | old `main` @ 3d74433 | reference |
|---|---|---|---|---|---|
| **Overall** | **8 / 56** normalized · 0 / 56 raw | **2 / 56** live GIDE explainer · 1 / 56 template | 5 / 56 | 0 / 56 | **56 / 56** |
| normal | 4 / 11 | 0 / 11 | 3 / 11 | 0 / 11 | 11 / 11 |
| ambiguous | 0 / 10 | 0 / 10 | 0 / 10 | 0 / 10 | 10 / 10 |
| data quality | 2 / 11 | 0 / 11 | 0 / 11 | 0 / 11 | 11 / 11 |
| adversarial | 1 / 10 | 0 / 10 | 1 / 10 | 0 / 10 | 10 / 10 |
| memory (incl. 4 multi-run sequences) | 1 / 14 | 0 / 14 | 1 / 14 | 0 / 14 | 14 / 14 |

`python-grounded-prism` continues the Python lineage with a GIDE-backed grounded explainer
and PRISM tracing. Commit 8603b97 added a data-quality gate, memory validity windows and
reliability notes (zero base, concentration, inactivity, reversal, non-recurring, reclass,
"does not establish why"); premature-stopping fell from 37 to 31 cases.

Scored at c22adba (code unchanged from 8603b97):

- **Live path (`MAIN_V1_LLM=1`, its provider on GIDE's 1.5B): 2 / 56.** Its gate now
  rejects 31 of 56 drafts (was 53) — more memos ship. Of the 39 `number_lint` failures,
  **all 39 are the unrounded Decimal `percentage_display`** ("66.66666666666666666666666667%")
  reaching accepted memos; the model itself leaked **1** ungrounded number and **4** causal
  phrasings ("This decrease is due to…") that the gate has no rule for. Numbers from the
  product's own evidence packet (coverage, notes) are counted as grounded.
- **Template path: 1 / 56** — same Decimal defect, first.

Two one-line fixes (round the packet's percentages; add a causal-verb check) would remove
43 of the failures; what remains is the shared worklist (38 limitation phrasings, 19
data-quality flags, 10 memory).

## The JavaScript courtroom (`main` @ d180870)

Its engine requires `segment` and `category` on every transaction, so on the canonical
CSVs it blocks every account (**0 / 56 raw**, 46 abstention failures). With those columns
filled and dates normalized it runs cleanly: **8 / 56**, the best of the three teammate
versions. It passes the duplicate-id, mixed-currency, tiny-denominator, huge-account and
alias cases, and it correctly rejects its own "broad-based" and "pricing caused" candidates.

What it still misses, in order of cases unlocked:

| Failed check | Cases | What it means |
|---|---|---|
| `required_pattern` | 48 | The brief states movement and top drivers, never a limitation: no "not meaningful" on a zero base, no "reversal", no "reclassification" unless a row is literally categorised `Reclass`, no "does not establish why", no seasonal norm, no memory reasons. |
| `data_quality_flags` | 12 | No reconciliation-gap wording beyond "blocked"; no reversal pairs, no near-duplicates (only exact ids), no naming variants, no sign checks. |
| `confidence` / `abstention` | 6 + 5 | One rule: tie-out ok → approved. No partial confidence, no per-account abstention wording. |
| `forbidden_pattern` | 5 | "Acme / acme / ACME" listed as three customers; the near-duplicate counted twice ("Fieldmark +$160,000"); "increased" on a no-change month. |
| `material_variances` | 5 | Flat $10,000 threshold; a $2,300 move on a $500 base is immaterial, but so is a $9,000 move on a $10,000 account. |
| `top_drivers` / `memory_used` | 3 + 3 | Drivers are top-3 by counterparty only, no drill within a segment. Memory only ever attaches to an account literally named `Cloud Costs`. |

## The old Python `main` (3d74433): the one-line fix that unlocks 47 checks

`TemplateExplanationProvider` prints raw `Decimal`s into the memo:

> Revenue increased by 203518.96 (40.90037309924180988050104740%).

That is spec CASE 34 (false precision) verbatim, so the linter now rejects any
percentage with more than two decimals. Every `main` memo trips it. Rounding in
the template restores the earlier **5 / 52**, and the rest of this document
describes that state.

## What `main` already does right

- Finds the right customer when the movement is concentrated (C02, C03, C12 name Acme / NewCo at the correct share).
- Never invents a causal explanation: 0 causal-lint failures.
- Its explainer already has a number-grounding check of its own (`_number_tokens`) — the same idea as `policy/language.py`.
- Stops on coverage rather than drilling forever: tool budget never exceeded.
- Raw and normalized input score identically: ingestion is not the bottleneck.

## What `main` needs to clear the benchmark — in order of cases unlocked

| Failed check | Cases | What it means | Where the reference does it |
|---|---|---|---|
| `number_lint` | 51 | Unrounded Decimals in the memo (above). | round to 0–1 decimals; `_money()` / `_signed()` |
| `required_pattern` | 41 | The memo does not say what the evidence requires: "not meaningful" on a zero base, "reversal", "reclassification", "distributed across", "no activity in … (new)", "cannot reliably attribute", "does not establish why", "consistent with PR-…", "was not applied: expired". `main` reports drivers and stops. | `agent/reference.py` claim templates; `finance/detectors.py` |
| `data_quality_flags` | 19 | No gate. Reconciliation gaps, duplicates, reversals, conflicting summaries, missing columns/periods, cutoff, mixed currency, look-alike names all pass through silently. | `quality/gate.py` (23 checks, blocker/warning/info) |
| `confidence` | 7 | One coverage number → "high" even when the summary conflicts or memory is contested. | `policy/uncertainty.py` |
| `abstention` / `abstention_scope` | 6 + 5 | `main` never abstains. On a $90K reconciliation gap it still attributes. | gate blockers → refuse attribution on scope |
| `memory_used` / `memory_rejected` | 6 + 3 | `BusinessContext` has no validity window, source type, expectation, or contested state; stale, future, rejected and contradicted context are indistinguishable from valid context. | `memory/store.py` §12 schema; `retrieve()` returns rejects with reasons |
| `top_drivers` | 1 | Picks the best-covering dimension and stops there ("Enterprise"), never drills to the customer inside it. | hierarchical drill in `reference.py` |

## Failure classes

| Class | `main` | `reliability-hardening` | reference |
|---|---|---|---|
| HALLUCINATED_CLAIM (false precision) | 51 | 0 | 0 |
| PREMATURE_STOPPING | 37 | 37 | 0 |
| DATA_QUALITY_FAILURE | 19 | 19 | 0 |
| CONFIDENCE_CALIBRATION_FAILURE | 7 | 8 | 0 |
| ABSTENTION_FAILURE | 6 | 6 | 0 |
| MEMORY_RETRIEVAL_FAILURE | 6 | 10 | 0 |
| STALE_MEMORY_FAILURE | 3 | 4 | 0 |
| DRIVER_ATTRIBUTION_FAILURE | 1 | 1 | 0 |

The reference started at 2 / 33 on the first version of this benchmark.
`docs/IMPROVEMENT_LOG.md` records every pass.
