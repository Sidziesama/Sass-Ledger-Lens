# Ledger Lens

Ledger Lens is a JSON-first financial variance investigation system for the Maximor Money Operations “Explain the Change” track.

## Milestone 1: financial foundation

The current implementation validates account summaries and transactions with Pydantic, compares periods with exact `Decimal` arithmetic, ranks material variances, decomposes changes across business dimensions, and preserves transaction IDs as evidence lineage.

The governing rule is: **Python calculates. The agent investigates. The LLM explains.**

```bash
source .venv/bin/activate
pytest
```

Core functions are `compare_periods`, `rank_material_variances`, `breakdown_by_dimension`, and `get_top_drivers`.

## Milestone 2: investigator

`FinancialTools` exposes deterministic comparison, ranking, decomposition, transaction retrieval, counterparty-history, and contribution functions. `Investigator` walks material account variances and only stops when the configured explanatory-coverage target is met and every selected driver has transaction evidence. Accounts without evidence are explicitly marked incomplete.

## Milestone 3: evidence lineage

`build_claim_lineage` converts investigated drivers into validated claim records containing the exact calculation, driver identity, and source transactions. Missing or mismatched transaction IDs invalidate the claim instead of allowing an unsupported explanation.

## Milestone 4: structured memory

`JsonMemoryStore` atomically persists business context, immutable investigation runs, and appended reviewer feedback as validated JSON. Context retrieval filters by account subject, tags, and effective date. When configured with this store, the investigator attaches relevant prior context to each account investigation so repeated runs benefit from finance-team knowledge without changing deterministic financial truth.
