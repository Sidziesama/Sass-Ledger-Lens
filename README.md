# Ledger Lens

Ledger Lens is a JSON-first financial variance investigation system for the Maximor Money Operations “Explain the Change” track.

**Submission branch:** `python-grounded-prism`

The governing rule is: **Python calculates. The agent investigates. The LLM explains.**

## Quick start

Ledger Lens requires Python 3.11 or newer. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

The application works offline with its deterministic explanation provider. To use GIDE, create a
local API key, put it in the private `.env` file, and start its server:

```bash
gide apikey create ledger-lens
gide server start
```

Run the dashboard:

```bash
python -m streamlit run app/app.py
```

Or run the investigation directly, adding `--llm` when GIDE is available:

```bash
python -m src.cli \
  --prior 2026-01-01 \
  --current 2026-02-01 \
  --llm \
  --llm-debug
```

Local secrets, model history, virtual environments, caches, and generated run artifacts are
excluded from Git. Never commit `.env`.

## Problem

Finance teams can calculate period variances quickly, but explaining those changes reliably still
requires manual account drill-down, transaction review, and institutional context. Generic LLM
summaries make this riskier because they can invent amounts or overstate causes that the ledger
does not prove.

## Solution

Ledger Lens autonomously identifies material changes, selects informative dimensions, ranks the
drivers, traces every claim to transactions, and produces a concise explanation. Deterministic
Python remains the source of financial truth; GIDE only narrates the verified evidence packet.
Structured reviewer feedback and learned priors improve subsequent investigations without changing
the underlying calculations.

## Key features

- Exact `Decimal` variance, materiality, contribution, and reconciliation calculations.
- Autonomous dimension selection with explicit coverage and evidence stopping rules.
- Claim → calculation → driver → transaction lineage for every supported financial statement.
- Reliability disclosures for zero bases, inactivity, reversals, reclassifications, one-time
  items, concentration, distributed movement, outlier masking, and unresolved causality.
- A data-quality gate covering tie-outs, near-duplicates, naming variants, signs, period gaps, and
  cutoff mismatches; reconciliation gaps block attribution.
- Lifecycle-aware memory with provenance, validity windows, learned ranges, and reviewer decisions.
- Evidence-constrained local explanations through GIDE with a deterministic offline fallback.
- PRISM traces for tool calls, decisions, model generation, evidence verification, errors, and
  latency, plus a repeatable benchmark and CI quality gate.

## Architecture and workflow

```text
JSON summaries + transactions
          │
          ▼
Pydantic validation → data-quality gate
          │
          ▼
Decimal variance + materiality ranking
          │
          ▼
Investigator → dimension decomposition → stopping rule
          │
          ├── transaction lineage + grounded claims
          ├── structured priors + reviewer feedback
          └── PRISM trajectory
          │
          ▼
Verified evidence packet → GIDE narration / deterministic fallback
          │
          ▼
Streamlit workspace + portable JSON artifact
```

The main workflow is:

1. Validate JSON contracts and reconcile summary values to transaction detail.
2. Rank account changes against absolute and percentage materiality thresholds.
3. Decompose each material account across customer, vendor, segment, and category dimensions.
4. Stop when selected drivers achieve the requested explanatory coverage with valid evidence.
5. Build transaction-backed claims and retrieve applicable, auditable memory.
6. Generate and validate the explanation; reject unsupported citations or numbers.
7. Present the result, investigation trace, memory, and review workflow in Streamlit.

## Technology

- Python 3.11+, Pydantic, pandas, and exact `Decimal` arithmetic
- Streamlit investigation workspace
- GIDE local OpenAI-compatible model endpoint
- PRISM Trace SDK and GitHub Actions
- pytest and Ruff

## Example investigation

Using the bundled January–February sample, Ledger Lens identifies Revenue as material:

```text
Revenue: 1,000,000 → 1,180,000, variance +180,000 (18.00%)
Top drivers: Other +65,000; Acme +52,000; Globex +41,000
Explanatory coverage: 87.8%; evidence sufficient
```

The generated memo cites the verified drivers, applies relevant memory, and explicitly states:
“The available data does not establish why Revenue changed.” The Evidence tab exposes the exact
transactions behind each claim.

## Demo

See [`DEMO.md`](DEMO.md) for the timed 60–90 second walkthrough. Before recording or submitting,
run the complete local gate:

```bash
./scripts/preflight.sh
```

## Milestone 1: financial foundation

The current implementation validates account summaries and transactions with Pydantic, compares periods with exact `Decimal` arithmetic, ranks material variances, decomposes changes across business dimensions, and preserves transaction IDs as evidence lineage.

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

The reliability gate runs before attribution. It reports reconciliation gaps with exact amounts,
near-duplicates, counterparty naming variants, sign inconsistencies, missing periods, and cutoff
mismatches. A reconciliation gap blocks an evidence-sufficient conclusion. The memo also carries
deterministic disclosures for zero bases, reversals, data-detected reclassifications, one-time
items, distributed or concentrated movement, inactive counterparties, and outlier masking. Every
memo states that the available data does not establish the underlying business cause.

Saved runs write proposed, system-inferred priors for the next investigation. Priors retain a
source type, status, validity window, learned range, and reviewer reason. The memo identifies
applied prior IDs and explicitly reports expired, rejected, or contested priors as not applied.

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

CI runs these checks for every pull request and every push to `main` or
`python-grounded-prism`.

## PRISM evaluation pipeline

Ledger Lens follows **Observe → Improve → Prove**:

- **Observe:** capture ordered investigator, tool, evidence, LLM, latency, fallback, and error steps.
- **Improve:** use failed grounding, quality-gate findings, reviewer feedback, and learned priors to
  strengthen the next run.
- **Prove:** run deterministic benchmark cases and submit a complete trajectory through the manual
  PRISM Evaluation workflow.

The manually triggered `PRISM Evaluation` GitHub Actions workflow proves the deterministic benchmark, submits one complete investigation trajectory, and retains the benchmark and investigation JSON as workflow artifacts. Configure a GitHub environment named `prism` with the secret `PRISMTRACE_API_KEY` and these variables:

```text
PRISMTRACE_HOST=https://prism-api-prod.up.railway.app
PRISMTRACE_PROJECT_ID=ae23818e-ed92-4975-9646-7b19cc142939
```

The submitted trajectory includes deterministic tool calls, investigation decisions, evidence verification, and explanation success or fallback. GIDE remains a local runtime integration; the hosted workflow uses the deterministic evidence-bound explanation because GitHub runners cannot access the local GIDE endpoint.
