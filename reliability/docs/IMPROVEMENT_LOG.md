# Improvement log — benchmark passes

Machine-evaluated. Each pass ran all 33 cases against the reference investigator; failures were classified with the taxonomy in `benchmark/taxonomy.py`, fixed, and re-run.

## Pass 1 — 2/33

| Class | Count | Root cause | Fix |
|---|---|---|---|
| HALLUCINATED_CLAIM | 26 | Memo printed `prior`/`current`/`pct` but claims only carried `variance`; the linter correctly refused to accept untraceable numbers | Every `Claim` now declares `numbers=[...]` for every figure it states. This is the contract any implementation must meet. |
| TOOL_FAILURE | 7 | Inner loop `for r in top:` shadowed the account row; later `r["section"]` / `r["variance_pct"]` raised | Renamed. Seven cases restored. |
| DRIVER_ATTRIBUTION_FAILURE | 3 | Per-customer noise ±10% on a $100M base swamped a $2.4M planted driver | Case design tightened to ±2%; a genuine signal-to-noise question, not an agent bug |
| ABSTENTION_FAILURE | 2 | see pass 2 | |

## Pass 2 — 20/33

| Class | Count | Root cause | Fix |
|---|---|---|---|
| DRIVER_ATTRIBUTION_FAILURE (C02, C03) | 2 | Agent chose the best-covering dimension (segment), reported "Enterprise", and stopped. Exactly the failure the brief names. | Hierarchical drill: after any coarse dimension wins, decompose the leading member by counterparty and emit a depth-2 claim ("Within Enterprise, Acme +$52K …"). |
| ABSTENTION_FAILURE (C11) | 1 | Two random $102.02 travel charges from one vendor, two days apart, tripped PROBABLE_DUPLICATE as a *blocker* on the whole account | Duplicate checks get a materiality floor ($5K). Below it the flag is informational. |
| HALLUCINATED_CLAIM | 10 | Linter regex backtracked at sentence end (`+84,000.` → `+84`); signs compared literally while the memo prints magnitudes with direction words | Lookahead allows a terminal period; magnitudes compared, direction carried by words. |
| TOOL_FAILURE (C10) | 1 | Ground truth forbade the substring "broad" while the correct memo says "not broad-based" | Ground truth uses `(?<!not )broad-based`. |
| Case bug (A01) | 1 | Period string `2026/08` never canonicalized — a real adversarial gap | `norm_period()` accepts six formats; unreadable periods are flagged, not guessed. |

## Pass 3 — 31/33

| Class | Count | Root cause | Fix |
|---|---|---|---|
| Seasonality (C16) | 1 | Normality judged by sigma of residuals; on clean history sigma is tiny, so a +5% surprise read as abnormal | Same-month-prior-years rule: "December moved +40% against +41% and +39% in the two prior years." |
| ARITHMETIC_FAILURE (C32) | 1 | The *evaluator* summed two conflicting summary rows to compute "truth" — the same bug fixed in the agent one pass earlier | Truth is undefined when the summary conflicts; the check falls back to transaction totals. |

## Pass 4 — 33/33
