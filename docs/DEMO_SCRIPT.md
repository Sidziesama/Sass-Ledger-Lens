# LedgerLens 90-Second Demo Script

## 0-10 seconds

Finance teams do not need another chatbot that says numbers changed. They need an analyst that proves why the numbers changed and refuses to publish weak explanations.

## 10-22 seconds

This is LedgerLens for the Maximor Money Operations track. It compares monthly summaries with transaction-level CSV evidence, ranks material movements, and runs each explanation through a courtroom.

## 22-38 seconds

On the September close, Revenue, COGS, Operating Cash Flow, and Cloud Costs are material. The CFO brief is already evidence-gated: only approved and qualified claims are shown.

## 38-52 seconds

Click Revenue. The movement and driver math are approved, but two common AI answers are rejected: "growth was broad-based" and "pricing caused the increase." Those sound plausible, but the evidence does not prove them.

## 52-66 seconds

Open Evidence. The claim links to tie-outs, driver decomposition, and exact transaction rows. The duplicate VectorDB cloud row is quarantined and counted once.

## 66-78 seconds

Open Test lab. LedgerLens runs 21 edge cases: summary mismatch, missing invoice, duplicate ID, conflicting ID, refund, reclass, customer alias, stale memory, zero baseline, wrong claim, missing citations, fabricated citation, and more.

## 78-88 seconds

Open Summary mismatch. Revenue is now blocked because the summary does not reconcile to transactions. Notice that Revenue disappears from the CFO brief instead of being guessed.

## 88-90 seconds

Closing line:

> LedgerLens does not ask you to trust AI. It makes every financial claim prove itself before it reaches the CFO.

## Optional PRISM Line

The repo can generate and send a PRISM trace from the same courtroom engine. After credentials are added, run `npm run trace:handshake`, `npm run trace:send`, then `npm run trace:doctor`.
