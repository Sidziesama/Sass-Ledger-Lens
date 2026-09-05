# LedgerLens Architecture

LedgerLens implements the sponsor prompt as a deterministic financial review desk:

```text
Monthly Summary CSV
        +
Transaction CSV
        |
        v
Input Normalizer
        |
        v
Reconciliation Engine
        |
        v
Materiality Ranking
        |
        v
GIDE/Ornith AI Candidate Proposer
        |
        v
Financial Courtroom
        |
        v
Evidence Graph + CFO Brief
        |
        v
Reviewer-Approved Business Memory
```

## Product Loop

```text
Detect -> Investigate -> Explain -> Prove -> Remember
```

## Core Boundary

The LLM is not the source of financial truth.

GIDE/Ornith is used as the AI proposal layer. It can suggest finance narratives such as "revenue growth looks concentrated" or "cloud spend may relate to migration context." Those proposals then enter the deterministic courtroom.

Deterministic code handles:

- cent-exact money parsing
- period comparison
- summary-to-transaction tie-out
- materiality ranking
- customer/vendor/category drilldown
- duplicate and conflicting ID handling
- claim arithmetic
- complete citation checks
- memory validity
- CFO brief filtering

An LLM can be added later for:

- proposing candidate explanations
- drafting CFO wording
- deciding which tool to call next
- suggesting memory updates

In this demo, GIDE/Ornith fills the proposal role. The courtroom judge remains deterministic.

## Courtroom Roles

- Detective: GIDE/Ornith proposes movement, driver, business-memory, and causal claims.
- Prosecutor: attacks broad, unsupported, or over-causal explanations.
- Judge: approves, qualifies, rejects, or blocks each claim using calculations and evidence.

## Evidence Model

Every approved claim must connect to:

- the selected account
- both period summary totals
- all accepted source rows for that account
- driver decomposition
- the exact arithmetic formula
- courtroom checks

If any required source data fails reconciliation, account claims are blocked.

## Business Memory

Business memory is reviewer-approved context, not blind model memory.

Two memory types are used:

- `context`: known events such as migration budgets or pricing changes
- `finding`: a reviewed conclusion saved from a prior close

Findings include a source fingerprint. If prior evidence changes, the finding becomes stale and cannot guide the next close.

## Edge Defense

The scenario suite covers failures that a normal AI summary can miss:

- mismatched summaries
- missing rows
- duplicate rows
- conflicting IDs
- refunds
- reclasses
- aliases
- stale memory
- zero baselines
- flat periods
- declines
- tiny high-percent changes
- mixed currency rows
- wrong dates
- missing summaries
- invalid cents
- instruction text inside ledger data
- invented amounts
- missing source-row citations
- fabricated citations

## PRISM

`npm run trace:preview` writes a PRISM-style trace payload using the same courtroom result. `npm run trace:handshake`, `npm run trace:send`, and `npm run trace:doctor` verify live PRISM ingestion when local credentials are present. No credentials are committed.

## Demo Thesis

Naive AI:

```text
Revenue increased. Cloud costs increased.
```

LedgerLens:

```text
Revenue increased, but broad-growth and pricing-cause claims were rejected.
Cloud costs increased, but migration memory only supports a qualified explanation.
Unsupported claims are withheld from the CFO brief.
Every approved number links back to source rows.
```
