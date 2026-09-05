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

## Pass 5 — benchmark extended to 52 cases

19 new cases (2 ambiguous, 7 data-quality, 4 adversarial, 6 memory). First run: **46/52**.

| Class | Count | Root cause | Fix |
|---|---|---|---|
| ABSTENTION_FAILURE (A07, B01, B02) | 3 | Three new cases used identical consecutive-day amounts, which tripped PROBABLE_DUPLICATE as a blocker. Legitimate as a pair; not as a run of four. | Gate: 3+ identical charges are a **series** (per-diems, instalments) → `RECURRING_SERIES` info, never a blocker. Cases also given realistic varied amounts. |
| PREMATURE_STOPPING (A08) | 1 | A renamed vendor appears as one counterparty going inactive and a new one appearing; the offsetting claim named both but never said "no activity … does not establish whether the relationship ended". | Inactive counterparties on the opposing side of an offset get the explicit inactive sentence. |
| PREMATURE_STOPPING (B02) | 1 | Same duplicate artifact as above. | — |
| HALLUCINATED_CLAIM (M05) | 1 | Hypothesis-source prior was wrapped in "unverified hypothesis" language but the inner text still said "reviewer-provided". | Neutralise source wording before wrapping. |
| HALLUCINATED_CLAIM (M08) | 1 | Linter read the "10" in "not valid before 2026-10" as an ungrounded figure. | Periods and dates are stripped before the number scan. |
| Ground truth (A07) | 1 | Forbidden pattern `ACME \+` matched the correct merged output under case-insensitive matching. | Ground truth distinguishes merged vs unmerged by amount. |

New reference capabilities forced by this batch: counterparty grouping on the
normalized key ("Acme" / "acme " / "ACME" are one customer); hypothesis and
contested priors get distinct, weaker language and cap confidence at medium;
gross-margin mix-vs-rate bridge by any shared dimension (Simpson's paradox is
named as a composition effect, not an operational improvement).

Result: **52/52**.

## Pass 6 — false precision

Scoring `main`'s own explainer exposed memos like "40.90037309924180988050104740%".
The linter's false-precision rule only caught "NN.NN% confident". Widened to any
percentage with more than two decimals and any bare figure with three or more.
Reference unaffected (52/52); `main` 5/52 → 0/52 until the template rounds.
