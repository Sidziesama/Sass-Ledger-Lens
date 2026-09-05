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

Reviewers can attach a structured correction to their feedback. Corrections are promoted into business context with reviewer and run provenance, then retrieved automatically for later investigations of the same account. Corrections inform explanations but never alter deterministic financial calculations.

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

### Use GIDE's local model

Create a local GIDE API key and place it in a private `.env` file; never commit the key:

```bash
gide server start
gide apikey create ledger-lens
cp .env.example .env
```

Set `LEDGER_LENS_LLM_API_KEY` in `.env` to the one-time value printed by GIDE. Keep the default local base URL and `model=local`, then run Streamlit normally. Ledger Lens sends only the deterministic evidence packet to GIDE. If GIDE is unavailable or its response fails grounding, the UI visibly falls back to the deterministic explanation.
The provider honors GIDE's `429` busy response and bounded `Retry-After` delay while the local model starts or finishes another request.
Local inference defaults to a 180-second timeout and a 768-token response budget. `LEDGER_LENS_LLM_DISABLE_REASONING=true` adds GIDE's `/no_think` directive so short financial explanations reach final content instead of exhausting the response budget in private reasoning. These settings can be changed with the corresponding `LEDGER_LENS_LLM_*` variables. If the configured model times out, is busy, returns malformed JSON, or fails grounding, both the CLI and UI identify the failure and use the deterministic grounded fallback instead of losing the investigation.
In this concise mode GIDE returns plain prose rather than constructing JSON. Ledger Lens deterministically attaches the verified claim IDs and applies the same unsupported-number validation before the explanation is accepted.
Because GIDE's raw local API does not support enforced response formats, the provider accepts either JSON or final-answer prose. Prose is conservatively attached to every verified claim in the supplied evidence packet and must still pass Ledger Lens's unsupported-number validation. Use `--llm-debug` to print a credential-safe fallback reason during local diagnosis.
Ledger Lens requests GIDE responses as a stream, collects the final-answer tokens, and validates the completed explanation before displaying it. This keeps long local generations active while discarding the model's private reasoning stream.

## Deterministic benchmark

The multi-period benchmark proves exact variance results, correct top-driver selection, full decomposition reconciliation, and transaction-evidence completeness against known outcomes:

```bash
python -m src.evaluation.benchmark --output data/runs/benchmark-score.json
```

The command exits nonzero if any benchmark case fails, making it suitable for CI and PRISM's “Prove” stage.
It also requires the exact expected set of material accounts, preventing false positives from passing unnoticed. Financial edge-case tests cover zero baselines, disappearing accounts, negative balances, offsetting drivers, and mixed currencies.

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

## PRISM evaluation pipeline

The manually triggered `PRISM Evaluation` GitHub Actions workflow proves the deterministic benchmark, submits one complete investigation trajectory, and retains the benchmark and investigation JSON as workflow artifacts. Configure a GitHub environment named `prism` with the secret `PRISMTRACE_API_KEY` and these variables:

```text
PRISMTRACE_HOST=https://prism-api-prod.up.railway.app
PRISMTRACE_PROJECT_ID=ae23818e-ed92-4975-9646-7b19cc142939
```

The submitted trajectory includes deterministic tool calls, investigation decisions, evidence verification, and explanation success or fallback. GIDE remains a local runtime integration; the hosted workflow uses the deterministic evidence-bound explanation because GitHub runners cannot access the local GIDE endpoint.
