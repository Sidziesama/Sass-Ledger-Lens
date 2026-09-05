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

## Milestone 5: PRISM observability

The investigator emits an ordered trajectory covering materiality ranking, driver-decomposition tool calls, context retrieval, stopping decisions, final outcomes, and failures. Evidence construction adds claim-verification steps to the same trace. `PrismTraceObserver.from_env()` connects to `prismtrace-sdk` when the three values in `.env.example` are configured and otherwise degrades to a no-op observer, keeping financial calculations available offline.

## Milestone 6: Streamlit investigation workspace

The dashboard presents material period changes, evidence-backed summaries, ranked driver charts, transaction lineage, the complete PRISM-shaped investigation trace, remembered context, and reviewer feedback. Investigation runs are only persisted when a reviewer explicitly saves them.

Upload a monthly-summary JSON file and a transaction JSON file together from the sidebar to investigate another dataset. Both files are validated against strict Pydantic schemas; duplicate transaction IDs are rejected and summary-to-detail reconciliation differences are shown before investigation.

Saved investigations appear in the Run history tab with periods, account results, claim counts, and review status. Any two stored runs can be compared to show variance changes and newly appearing or disappearing drivers.

```bash
streamlit run app/app.py
```

## Command-line investigations

Run the same deterministic workflow without the UI and optionally save a portable JSON artifact containing variances, drivers, claims, transaction lineage, business context, and the investigation trace:

```bash
python -m src.cli \
  --prior 2026-01-01 \
  --current 2026-02-01 \
  --output data/runs/demo-investigation.json
```

Add `--prism` to submit the trajectory when the `PRISMTRACE_*` environment variables are configured.
Add `--llm` to use the configured OpenAI-compatible provider; otherwise the grounded offline template is used.

## Evidence-constrained explanations

`EvidenceBoundExplainer` sends a structured packet of deterministic results and verified claims to a pluggable provider. It rejects unknown claim citations and any numeric fact not present in the evidence packet. `TemplateExplanationProvider` works offline; `OpenAICompatibleProvider` can use a hosted provider or GIDE's local API through the `LEDGER_LENS_LLM_*` settings in `.env.example`.

## Deterministic benchmark

The multi-period benchmark proves exact variance results, correct top-driver selection, full decomposition reconciliation, and transaction-evidence completeness against known outcomes:

```bash
python -m src.evaluation.benchmark --output data/runs/benchmark-score.json
```

The command exits nonzero if any benchmark case fails, making it suitable for CI and PRISM's “Prove” stage.

## Development quality checks

Install development dependencies and run the same checks enforced by GitHub Actions:

```bash
python -m pip install -r requirements-dev.txt
ruff check .
ruff format --check .
pytest -q
python -m src.evaluation.benchmark
```

CI runs these checks for every pull request and every push to `main`.

## GIDE and PRISM setup

Copy `.env.example` to `.env` and fill in your own credentials. Both the CLI and dashboard load this file; it must remain untracked.

Use the official GIDE CLI to sign in, start the server, select a model that fits your hardware, and create an API key. Set `LEDGER_LENS_LLM_BASE_URL` to the server's actual address with `/v1`, and `LEDGER_LENS_LLM_MODEL` to an ID returned by its `/v1/models` endpoint. Set `LEDGER_LENS_LLM_JSON_MODE=false` only if your endpoint does not support JSON response mode. Model selection and authentication do not prove that inference can run: verify available memory and a real completion.

Set the three `PRISMTRACE_*` values from your PRISM project. Enable the dashboard checkboxes or run:

```bash
python -m src.cli --prior 2026-01-01 --current 2026-02-01 --llm --prism
```

PRISM receives an explicitly labeled workflow summary trace and ordered trajectory under the same run ID, including explanation validation and failures. It receives account and driver summaries, so enable it only for data you intend to share with your configured PRISM service. Delivery failure leaves local results available and is shown separately.

Explanations can select only approved, evidence-backed statements. Model failures or rejected output produce a visible warning and a validated template fallback. Summary/detail discrepancies or currency mismatches block explanations; insufficient coverage remains partial with a required caveat. The workflow owns the trace lifecycle so provider calls and validation appear before completion.

## Workflow edge-case regressions

Seven synthetic datasets from `reliability` commit `6288a94` are preserved under `tests/fixtures/reliability`. Run `pytest -q tests/test_reliability_cases.py` to check summary/detail gaps, absent detail, missing periods, duplicate transaction IDs, mixed currencies, accounts absent from summaries, and percentage display through the actual workflow.

Duplicate IDs now return a blocked, reviewable result before attribution. Accounts with transactions but no summary are reported at dataset level even if materiality would skip them. CLI and dashboard show these issues. Displayed percentages use two decimals; structured financial values retain their original precision. These seven checks do not replace the other branch's full 56-scenario benchmark.
