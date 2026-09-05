# Benchmark comparison — `main` (latest) vs reference investigator

Same 52 cases, same evaluator, same ground truth. `main` is scored through
`benchmark/adapters/main_v1.py`, which feeds the case files to `src/` unchanged
and, from `main@33fea51`, uses the product's own `EvidenceBoundExplainer` with
its offline `TemplateExplanationProvider` for the memo text — so the language
checks measure their words, not the adapter's.

```bash
python -m reliability.benchmark.evaluate                                                     # reference
python -m reliability.benchmark.evaluate --runner reliability.benchmark.adapters.main_v1:run  # main
```

| | `main` @ 33fea51 | reference |
|---|---|---|
| **Overall** | **0 / 52** (5 / 52 before the false-precision rule, see below) | **52 / 52** |
| normal | 0 / 11 | 11 / 11 |
| ambiguous | 0 / 10 | 10 / 10 |
| data quality | 0 / 11 | 11 / 11 |
| adversarial | 0 / 10 | 10 / 10 |
| memory | 0 / 10 | 10 / 10 |

## The one-line fix that unlocks 47 checks

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
| `number_lint` | 47 | Unrounded Decimals in the memo (above). | round to 0–1 decimals; `_money()` / `_signed()` |
| `required_pattern` | 37 | The memo does not say what the evidence requires: "not meaningful" on a zero base, "reversal", "reclassification", "distributed across", "no activity in … (new)", "cannot reliably attribute", "does not establish why", "consistent with PR-…", "was not applied: expired". `main` reports drivers and stops. | `agent/reference.py` claim templates; `finance/detectors.py` |
| `data_quality_flags` | 19 | No gate. Reconciliation gaps, duplicates, reversals, conflicting summaries, missing columns/periods, cutoff, mixed currency, look-alike names all pass through silently. | `quality/gate.py` (23 checks, blocker/warning/info) |
| `confidence` | 7 | One coverage number → "high" even when the summary conflicts or memory is contested. | `policy/uncertainty.py` |
| `abstention` / `abstention_scope` | 6 + 5 | `main` never abstains. On a $90K reconciliation gap it still attributes. | gate blockers → refuse attribution on scope |
| `memory_used` / `memory_rejected` | 6 + 3 | `BusinessContext` has no validity window, source type, expectation, or contested state; stale, future, rejected and contradicted context are indistinguishable from valid context. | `memory/store.py` §12 schema; `retrieve()` returns rejects with reasons |
| `top_drivers` | 1 | Picks the best-covering dimension and stops there ("Enterprise"), never drills to the customer inside it. | hierarchical drill in `reference.py` |

## Failure classes

| Class | `main` | reference |
|---|---|---|
| HALLUCINATED_CLAIM (false precision) | 47 | 0 |
| PREMATURE_STOPPING | 33 | 0 |
| DATA_QUALITY_FAILURE | 19 | 0 |
| CONFIDENCE_CALIBRATION_FAILURE | 7 | 0 |
| ABSTENTION_FAILURE | 6 | 0 |
| MEMORY_RETRIEVAL_FAILURE | 6 | 0 |
| STALE_MEMORY_FAILURE | 3 | 0 |
| DRIVER_ATTRIBUTION_FAILURE | 1 | 0 |

The reference started at 2 / 33 on the first version of this benchmark.
`docs/IMPROVEMENT_LOG.md` records every pass.
