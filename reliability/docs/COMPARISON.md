# Benchmark comparison — `main` v1 vs reference investigator

Same 33 cases, same evaluator, same ground truth. Run with:

```bash
python -m reliability.benchmark.evaluate                                                     # reference
python -m reliability.benchmark.evaluate --runner reliability.benchmark.adapters.main_v1:run  # main v1
```

| | `main` v1 (`src/`) | reference (`reliability/`) |
|---|---|---|
| **Overall** | **4 / 33** | **33 / 33** |
| normal | 3 / 11 | 11 / 11 |
| ambiguous | 0 / 8 | 8 / 8 |
| data quality | 0 / 4 | 4 / 4 |
| adversarial | 1 / 6 | 6 / 6 |
| memory | 0 / 4 | 4 / 4 |

Raw and normalized input give v1 the **same** score — ingestion is not the bottleneck; investigation policy is.

## What v1 already does right

- Finds the right customer when the movement is concentrated (C02, C03, C12 all name Acme / NewCo at the correct share).
- Never invents a causal explanation (0 causal-lint failures, 0 hallucinated numbers).
- Stops on coverage rather than drilling forever (tool budget never exceeded).

## What v1 needs to clear the benchmark — in order of cases unlocked

| Failed check | Cases | What it means | Where the reference does it |
|---|---|---|---|
| `required_pattern` | 21 | The memo does not say what the evidence requires: "not meaningful" on a zero base, "reversal", "reclassification", "distributed across", "no activity in … (new)", "cannot reliably attribute", "does not establish why". v1 reports drivers and stops. | `agent/reference.py` claim templates; `finance/detectors.py` |
| `data_quality_flags` | 11 | No gate. Reconciliation gaps, duplicates, reversals, conflicting summaries, cutoff, look-alike names all pass through silently. | `quality/gate.py` (22 checks, blocker/warning/info) |
| `abstention` + `abstention_scope` | 4 + 4 | v1 never abstains. On a $90K reconciliation gap it still attributes. | gate blockers → refuse attribution on scope |
| `confidence` | 4 | Single coverage number → "high" even when the summary conflicts or memory contradicts. | `policy/uncertainty.py` four dimensions + rules |
| `memory_used` / `memory_rejected` | 3 + 1 | v1's `BusinessContext` has no validity window, source type, or expectation; stale and contradicted context are not distinguished from valid context. | `memory/store.py` §12 schema |
| `top_drivers` | 3 | Picks the best-covering dimension and stops there ("Enterprise"), never drills to the customer inside it (C14 offset, C10 giant txn). | hierarchical drill in `reference.py` |
| `immaterial_ignored` | 1 | `is_material = abs >= T_abs and pct >= T_pct` — one hard threshold. A $2,300 snacks move is investigated beside a $300K revenue move. | `materiality`: A + P + H + C with a section-relative anchor |
| `arithmetic` | 1 | Conflicting summary rows are summed into one "truth". | refuse conflicting rows, fall back to transactions |

## Failure classes

| Class | v1 | reference |
|---|---|---|
| PREMATURE_STOPPING | 20 | 0 |
| DATA_QUALITY_FAILURE | 11 | 0 |
| ABSTENTION_FAILURE | 4 | 0 |
| CONFIDENCE_CALIBRATION_FAILURE | 4 | 0 |
| MEMORY_RETRIEVAL_FAILURE | 3 | 0 |
| DRIVER_ATTRIBUTION_FAILURE | 3 | 0 |
| STALE_MEMORY_FAILURE | 1 | 0 |
| MATERIALITY_FAILURE | 1 | 0 |
| ARITHMETIC_FAILURE | 1 | 0 |
| RECONCILIATION_FAILURE | 1 | 0 |

The reference started at 2 / 33 on the same benchmark. `docs/IMPROVEMENT_LOG.md` records the four passes that got it to 33.
