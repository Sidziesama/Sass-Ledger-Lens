# LedgerLens: Financial Variance Courtroom

LedgerLens is a Maximor Money Operations hackathon project for the "Explain the Change" prompt. It ingests monthly account summaries and transaction-level CSVs, ranks meaningful period-over-period changes, drills into source rows, and produces a CFO brief only after each claim survives verification.

The core idea: GIDE/Ornith can propose an explanation, but deterministic finance checks decide whether it is allowed into the brief.

## Problem Statement

Finance teams do not just need "Revenue increased 18%." They need to know:

- what changed across periods
- which changes are material
- which transactions drove the movement
- which explanations are evidence-backed
- what the system learned from previous reviewed closes

LedgerLens turns that into a repeatable review workflow.

## Differentiation

Most hackathon builds can become:

```text
CSV upload -> variance table -> AI summary
```

LedgerLens is built around a courtroom:

```text
CSV input -> data quality checks -> materiality ranking -> GIDE/Ornith AI proposals -> claim courtroom -> evidence graph -> local business memory -> CFO brief
```

Every proposed explanation is marked:

- `approved`: math ties and citations cover the complete source set
- `qualified`: numbers are proven, but the wording must preserve a caveat
- `rejected`: the claim is misleading, causal without evidence, or cites bad rows
- `blocked`: source data does not reconcile, so the explanation is withheld

That is the edge: the product does not ask judges to trust AI. It proves or withholds each financial claim.

## Key Features

- CSV import for monthly summaries and transaction-level evidence.
- GIDE/Ornith AI proposal layer for draft finance narratives.
- Deterministic cent-exact money arithmetic.
- Period comparison and materiality ranking.
- Driver decomposition by customer, vendor, segment, or category.
- Source-row evidence graph for every selected claim.
- CFO brief generated only from approved or qualified claims.
- Reviewer-approved business memory stored locally and reused only when still valid.
- Stale-memory defense using a reproducibility fingerprint.
- Edge-case lab with 21 controlled scenarios.
- PRISM trace preview generated from the same courtroom engine.

## Edge Cases Covered

The verification suite and browser UI cover:

- summary totals that do not tie to transactions
- missing transaction evidence
- duplicate and conflicting transaction IDs
- refunds and negative revenue credits
- reclassifications between accounts
- approved customer aliases
- expired business memory
- zero prior-period balances
- no-movement periods
- revenue declines
- tiny balances with huge percentages
- mixed currencies
- wrong accounting periods
- missing summaries
- invalid decimal precision
- instruction text embedded inside ledger data
- wrong proposed amounts
- missing source-row citations
- fabricated citations
- generated reconciled ledgers for conservation checks

## Tech Stack

- Static HTML, CSS, and JavaScript.
- `engine.mjs` for deterministic finance logic and claim verification.
- `scenarios.mjs` for controlled edge-case mutations.
- Papa Parse for CSV ingestion.
- Lucide icons for UI controls.
- Node test runner for verification.

No model is trained in this demo. GIDE/Ornith is the local AI proposal layer; the finance decisions stay inside the deterministic courtroom engine. The model may draft candidate narratives, but it must not replace tie-outs, arithmetic, citations, or memory checks.

## How It Works

1. Load monthly summary rows and transaction rows.
2. Validate schema, dates, USD amounts, duplicate IDs, and posting status.
3. Reconcile every account to both period summaries.
4. Rank material movements.
5. Generate candidate claims.
6. Judge each claim against tie-outs, driver math, citations, and memory provenance.
7. Publish only approved or qualified explanations into the CFO brief.
8. Let the reviewer approve a finding as local business memory for future periods.

Detailed architecture: `docs/ARCHITECTURE.md`

Demo script: `docs/DEMO_SCRIPT.md`

Judge checklist: `docs/JUDGE_DEMO.md`

GIDE AI layer: `docs/GIDE_AI_LAYER.md`

## How To Run

From this folder:

```bash
npm install
npm run dev
```

Open:

```text
http://localhost:8000
```

Run verification:

```bash
npm test
```

Refresh sample CSVs from the embedded demo dataset:

```bash
npm run sync:data
```

## PRISM

The current repo includes a preview trace generated from the same courtroom result:

```bash
npm run trace:preview
```

That writes:

```text
artifacts/prism-trace-preview.json
```

To send a real trace later, set:

- `PRISMTRACE_HOST`
- `PRISMTRACE_PROJECT_ID`
- `PRISMTRACE_API_KEY`

Then verify and send:

```bash
npm run trace:handshake
npm run trace:send
npm run trace:doctor
```

Do not commit `.env`.

## GIDE

GIDE is installed separately and should be used before submission if the hackathon requires it. Suggested command after sign-in/model setup:

```bash
gide -p "Analyze this repo and identify bugs in the financial variance analysis and claim-verification pipeline"
```

Position GIDE as the AI proposer. Position LedgerLens as the verifier that accepts, rejects, qualifies, or blocks proposed claims.

## Demo Flow

1. Start on the September close review.
2. Show the materiality table and the CFO brief.
3. Click Revenue: broad-growth and pricing-cause claims are rejected.
4. Open Evidence: show the graph, tie-outs, cited rows, and duplicate quarantine.
5. Open Test lab: show 21/21 edge cases passing.
6. Open Summary mismatch: Revenue is blocked and disappears from the CFO brief.
7. Open Business memory: approve a verified finding and explain that memory is reused only when source evidence stays unchanged.

Closing line:

> LedgerLens does not ask you to trust AI. It makes every financial claim prove itself before it reaches the CFO.
