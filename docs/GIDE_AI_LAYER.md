# GIDE AI Layer

## Role

LedgerLens uses AI for candidate narrative generation, not for financial truth.

The intended split is:

```text
GIDE / Ornith 9B local model
        |
        v
Candidate variance narratives
        |
        v
Deterministic LedgerLens courtroom
        |
        v
Approved, qualified, rejected, or blocked CFO claims
```

## Installed Model

- Tool: GIDE `2.3.56`
- Local model family: `ornith`
- Model file: `Ornith-1.5-9B-Q5_K_M.gguf`
- Approximate model size on disk: `6.2 GB`
- Hardware profile: Apple Silicon GPU mode, 16K context

## GIDE Prompt Used For The Hackathon Story

```text
You are the AI proposer for LedgerLens. Read this repository and produce a concise audit of the product idea: what financial narratives an AI would propose, which ones the deterministic courtroom should approve/reject/block, and the top edge cases judges will care about. Do not edit files.
```

## Why This Is Stronger Than A Normal AI Summary

A normal finance chatbot writes a plausible explanation.

LedgerLens lets AI propose the explanation, then forces it through:

- summary-to-ledger reconciliation
- cent-exact arithmetic
- complete source-row citations
- driver decomposition
- memory provenance checks
- causal-language rejection
- blocked output when the data is incomplete

## Demo Language

Say this:

> GIDE/Ornith proposes the candidate explanations. LedgerLens does not trust those explanations until deterministic finance checks prove every number and citation.

Do not say the model computed the close. The model proposes wording; the courtroom verifies the finance.
