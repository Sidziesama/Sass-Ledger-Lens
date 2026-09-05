# Dataset answer key — Tallgrass Supply Co.

B2B commercial-kitchen equipment & supplies distributor. ~$26M revenue,
43 active accounts, 24 monthly periods (2024-09 .. 2026-08), 18.5k transactions.

`monthly_summary.csv` is exactly the sum of `transactions.csv` by period × GL
account. Every claim the agent makes must reconcile to those rows.

The data is built so a naive single-period variance tool is **confidently wrong**.
Each trap has a plausible false answer and a true answer that requires either
deterministic decomposition or a prior carried from an earlier run.

| # | Period | Naive (wrong) answer | True answer | What it takes to get it right |
|---|--------|---------------------|-------------|-------------------------------|
| **T2** | 2025-10 | "Revenue +32%, strong growth in restaurant groups" | Copper Fork's annual pre-season stocking order ($655k) slipped from Sep into Oct. Sep was correspondingly light. Pure timing, zero growth. | Look for an offsetting gap in the prior period, same counterparty |
| **T1** | 2025-11 | "Revenue -7%, momentum is stalling" | Oct was inflated by T2. Normalised for it, Nov grew and is in line with the seasonal index (Nov is structurally the strongest month). Nothing is wrong. | Requires the prior *learned in the T2 run* |
| **T5** | 2026-01 | "Gross margin collapsed 530bps — supplier costs are out of control" | Outbound freight was reclassified from Opex 6500 into COGS 5100. Same vendor, same amounts, different account. Net income unchanged. | Detect a GL reclass: vendor+amount continuity across accounts, NI-neutral |
| **T4** | 2026-03 | "Margin down because Northline raised refrigeration prices 4%" | The 4% cost increase is real but minor. ~3/4 of the margin decline is **mix**: a $470k Vaughn & Sons equipment buildout swung revenue toward low-margin equipment. | Rate-vs-mix decomposition; the decoy is findable and true-but-immaterial |
| **T3** | 2026-05 | "Revenue +24%, broad-based strength" | 3 of 43 accounts are ~76% of the increase. One of them (Ridgeline) has payment behaviour deteriorating from 6 to 31 days late. Growth is concentrated and low quality. | Concentration + join to AR ageing |
| **T6** | 2026-06 | "Opex up $95k, cost discipline slipping" | One-time legal settlement with Ridgeline. Non-recurring. Must not be extrapolated — and it connects back to the T3 customer. | One-time detection + cross-run linkage |
| **T7** | 2026-04..08 | *never flagged at all* | Seven accounts each ran a monthly refrigeration replacement program. One by one they went silent, lost to a competitor. Each month's incremental loss is ~1.4% of revenue — always below the reporting threshold — but the run-rate reaches **$92k/mo, $1.1M annualized**. | **Impossible single-period.** It is a pattern of *absence*: no transaction is created, so there is nothing to diff. Only priors about who normally buys what will surface it. |

T7 is the thesis of the product. Variance reports can only see things that happened.
The most expensive thing in this dataset is something that stopped happening.
