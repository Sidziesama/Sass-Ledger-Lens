# Ledger Lens — Reliability Package

This directory is the reliability layer for Ledger Lens: the parts of the system whose job is to make the agent **hard to fool, hard to make hallucinate, and explicit about what it cannot prove.** It is self-contained and does not modify anything under `src/`.

Its policy, in one line:

> Calculate. Reconcile. Investigate. Challenge the apparent explanation. Quantify the residual. Cite. Abstain.

## What is here

| Module | Responsibility |
|---|---|
| `ingestion/normalize.py` | Canonical CSV schema. Parses `$1,234`, `(500)`, `−250`, `1,000-`, four date formats (ambiguous ones flagged, never guessed), six period formats, unicode look-alike names. Nothing unparseable is coerced. |
| `quality/gate.py` | 23 data-quality checks with `blocker / warning / info` severity. Reconciliation, exact and near duplicates (with a materiality floor), reversals, naming variants, sign consistency, conflicting summary rows, cutoff. A blocker refuses attribution on its scope. |
| `finance/` | Deterministic engine: exact MECE decomposition, margin bridges (volume / mix / rate), seasonal baselines, detectors (reclass, timing, one-time, silent churn, AR deterioration). |
| `evidence/claims.py` | Every factual statement is a `Claim` with its calculation, its transaction ids, and the `numbers` it states. Claims are verified before they can be shown. |
| `policy/uncertainty.py` | Four measured dimensions — data, attribution, context, evidence coverage — and a categorical `high / medium / low` verdict from explicit rules. No single "93.7% confident" number exists anywhere. |
| `policy/language.py` | Deterministic linter over the final memo: causal verbs without a causal claim, false precision, nonsense figures, and **any number that does not trace to a verified claim**. |
| `memory/store.py` | Priors with `source_type` (user-verified / system-inferred / hypothesis), validity windows, `contested` status, versioned reviewer corrections. `retrieve()` returns what it rejected and why. |
| `agent/reference.py` | The deterministic reference investigator — the floor any shipped investigator must clear. |
| `benchmark/` | 52 machine-evaluable cases with ground truth, an evaluator, and an 18-class failure taxonomy. |

## Run it

```bash
# one period, deterministic
python -m reliability.agent.run reliability/benchmark/cases/C29_outlier_masks_decline 2026-08 --prior 2026-07

# same, with memory that persists across runs, and GIDE's model writing the memo
python -m reliability.agent.run <case_dir> 2026-08 --memory runs/memory.json --llm

# reviewer feedback between runs (every action is versioned)
python -m reliability.memory.feedback --memory runs/memory.json list
python -m reliability.memory.feedback --memory runs/memory.json confirm PR-0003
python -m reliability.memory.feedback --memory runs/memory.json add --account "Cloud Expense" \
    --statement "AWS migration elevates cloud spend through September" --implication "expect up to +30%" \
    --valid-from 2026-07 --valid-until 2026-09 --max-increase-pct 30
```

The model is GIDE's local server (`gide apikey create`, discovered from `~/.gide/server-port.json`;
`GIDE_BASE_URL` / `GIDE_API_KEY` in `.env`). The model only writes the memo, from verified claims;
its draft is linted and replaced by the templated memo if it fails. `python -m reliability.benchmark.evaluate --llm`
reports how many of the 56 drafts the linter rejected, and why.

## Contracts

Any Ledger Lens implementation can be scored by producing a `RunResult` (see `benchmark/schema.py`) from `run(case_dir, period, prior_period, memory_path)`. The evaluator does not care which implementation it is talking to:

```bash
python -m reliability.benchmark.make_cases              # generate cases
python -m reliability.benchmark.evaluate                 # reference investigator
python -m reliability.benchmark.evaluate --runner pkg.mod:fn   # your investigator
```

A case directory may also carry a `sequence.json`: several periods run in order against one memory
file, with reviewer feedback ops applied between runs, and ground truth checked at each step. Four
such sequences cover the cloud-migration story, a one-off the system learns by itself, a reclass
carried forward, and silent churn across six consecutive months.

Each case checks: data-quality flags raised, material variances investigated, immaterial ones ignored, expected drivers found, forbidden phrases absent, required phrases present, confidence in the acceptable set, abstention correct, memory used or rejected as expected, every cited transaction id exists, every observation's arithmetic reproduces from the records, and the memo passes the language linter.

## Observe → Improve → Prove

The benchmark was built to break the agent, and it did. Every failure was classified and fixed; the record is in `docs/IMPROVEMENT_LOG.md`.

| Pass | Score | What the traces showed |
|---|---|---|
| 1 | 2 / 33 | Memo figures not traceable to structured claims (contract gap); one shadowed variable crashing seven cases |
| 2 | 20 / 33 | Agent stopped at segment level and never named the customer; a $102 accidental duplicate blocked a whole account; linter regex backtracking at sentence ends |
| 3 | 31 / 33 | Seasonality judged by sigma alone (any deviation on clean history looked abnormal); conflicting summary rows were being summed |
| 4 | **33 / 33** | — |
| 5 | 46 → **52 / 52** | Benchmark extended to 52 cases; a run of identical charges was being treated as a duplicate pair; renamed vendors, hypothesis priors, date tokens in the linter |
| 6 | 52 / 52 | False-precision rule widened after scoring the `main` explainer (26-decimal percentages) |

Final: adversarial 10/10, data-quality 11/11, memory 10/10, ambiguous 10/10, normal 11/11.
Comparison with the `main` investigator: `docs/COMPARISON.md`.

## What the agent will say when it cannot prove something

- "Revenue moved from $0 to $100,000; percentage change is not meaningful because the prior-period base was zero."
- "Ledger Lens cannot reliably attribute Revenue: summary 1,180,000.00 vs transactions 1,090,000.00 — gap +90,000.00."
- "OldCo had $150,000 in 2026-07 and no activity in 2026-08; the data does not establish whether the relationship ended."
- "The available data does not establish why Acme activity changed."
- "PR-0001 (AWS migration …) was not applied: expired after 2026-09."
- "The available sources conflict: PR-0001 states that cloud spend will fall … but Cloud Expense moved +$38,000 in the opposite direction. The prior is marked contested and confidence is reduced."
- "No financially material or historically unusual movements were identified for this period."

That last one is a successful run.
