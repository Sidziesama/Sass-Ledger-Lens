# Handoff: `python-grounded-prism` — what to change to pass the benchmark

Scored at 6319d12: **5 / 56** on its live GIDE explainer path (0 / 56 with the offline
template). Reproduce (worktree, nothing of yours modified):

```bash
git checkout reliability && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
git worktree add /tmp/pgp origin/python-grounded-prism
MAIN_V1_LLM=1 .venv/bin/python -m reliability.benchmark.evaluate --src-root /tmp/pgp \
  --runner reliability.benchmark.adapters.main_v1:run -v
```

## Three fixes specific to this branch

1. **Round in `TemplateExplanationProvider`.** It prints raw `Decimal`s
   ("40.90037309924180988050104740%"). One decimal for percentages, none for dollars.
   This alone moves the template path from 0 / 56 to the live-path profile.

2. **Your grounding gate rejects 53 of 56 drafts on the 1.5B — and then says nothing.**
   The gate is right to reject; the problem is the empty fallback. When a draft fails,
   emit the deterministic sentences instead (movement, drivers, and every limitation the
   evidence supports), so a rejected draft never costs the reader information.
   Ref: `reliability/agent/memo.py` (template fallback, rejection recorded and counted).

3. **Change what you ask the model to do.** "Write a memo from these claims" gets 23 / 56
   accepted on this model; "choose 4–6 of these claims and copy them verbatim, each followed
   by its claim id, most important first" gets 50 / 56, with zero invented figures. Small
   models paraphrase and drop citations; asking them to select instead of rewrite fixes
   most of it. Ref: `reliability/agent/prompts.py` (v3), `docs/IMPROVEMENT_LOG.md` passes 7–9.

## The shared worklist (same as every branch)

The remaining 48 `required_pattern` misses are the memo never stating a limitation:
zero-base "percentage not meaningful", reversal, reclassification detected from data (vendor
moves accounts, net-income neutral), one-time items, distributed movement, new / inactive
counterparty wording (never "churn"), concentration, "excluding X, revenue declined",
seasonal norm, "cannot reliably attribute <account>: gap of $X", memory reasons
("consistent with PR-…", "exceeds the learned range", "not applied: expired / rejected"),
and always "the available data does not establish why". Then the data-quality gate (19):
reconciliation gap with amount, near-duplicates, naming variants, sign checks, period gaps,
cutoff. Then memory (10): validity windows, source type, contested / rejected with reasons,
and writing memory from each run. Reference for each: `reliability/docs/HANDOFF_COURTROOM.md`
items 2–8 (the file names there point at the reference implementation).

## Update — scored again at c22adba (after 8603b97's gate + reliability notes)

Good: reliability notes landed (zero base, concentration, inactivity, reversal, non-recurring,
reclass, "does not establish why"); premature-stopping 37 → 31. Live path still **2 / 56**,
and the reason is now precise:

| Failure | Cases | Fix |
|---|---|---|
| Unrounded Decimal in accepted memos (`percentage_display` = `str(Decimal)`, e.g. `66.66666666666666666666666667%`) | **39** | Round in `build_evidence_packet` (1 decimal for %, 0 for $) — the model quotes whatever the packet says |
| Causal phrasing the gate does not check ("This decrease is **due to** …", "**suggesting that** the variance is …") | 4 | Add a causal-verb rule to the grounding gate: reject `caused / because of / due to / resulted from / led to / as a result of` unless a causal claim exists |
| Genuinely ungrounded model number | 1 | Already caught by the number-token check on most cases; keep it |
| Limitation phrasings still missing on the live path | 38 | The notes exist — make sure the explainer's summary carries them verbatim (or the fallback ships them when a draft is rejected) |
| Data-quality flags never reach the memo | 19 | Reconciliation gap with amount, near-duplicates, naming variants, sign checks, period gaps, cutoff |
| Memory language | 10 | "consistent with PR-…", "exceeds the learned range", "not applied: expired / rejected" |

Gate now rejects 31 / 56 drafts (was 53). A rejected draft should still ship the deterministic
sentences — see item 2 above.
