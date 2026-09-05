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
