# Ledger Lens demo guide

This is a 60–90 second judge-facing walkthrough for the Maximor Money Operations “Explain the
Change” track.

## Before recording

```bash
cd Sass-Ledger-Lens
source .venv/bin/activate
./scripts/preflight.sh
gide server restart
python -m streamlit run app/app.py
```

Wait for GIDE to finish loading before clicking **Run investigation**. Do not run the CLI and UI
generation simultaneously; a busy local model can return HTTP 429 and trigger the safe fallback.

## 75-second script

**0–10 seconds — Problem and rule**

> Finance teams know that Revenue changed, but proving what drove it still takes manual drill-down.
> Ledger Lens automates that investigation. Python calculates, the agent investigates, and the LLM
> only explains verified evidence.

Show the Ledger Lens header and the selected January–February periods.

**10–25 seconds — What changed**

Click **Run investigation** and show the Overview.

> Revenue increased from one million to 1.18 million: a $180,000 or 18% material variance. The
> investigator selected customer as the most informative dimension and stopped at 87.8% coverage.

**25–42 seconds — Why and evidence**

Open **Drivers**, then **Evidence** and expand one claim.

> Other, Acme, and Globex are the three largest verified movements. Every claim maps to the exact
> calculation and underlying transaction IDs. The model cannot invent a number because unsupported
> numbers and citations are rejected.

**42–55 seconds — Reliability**

Return to **Overview** and point to the final disclosure.

> Ledger Lens separates contribution from causation. It always says when the available data cannot
> establish why the business changed, and it blocks attribution when transaction detail does not
> reconcile to the ledger.

**55–67 seconds — Learning**

Open **Memory & review**.

> A reviewer can save the run, approve or correct a finding, and create a dated prior. Future runs
> report whether that prior is consistent, outside its learned range, expired, contested, or
> rejected.

**67–80 seconds — PRISM proof**

Open **Investigation trace** and, if available, the PRISM project in another tab.

> PRISM records the complete trajectory: financial tools, stopping decisions, evidence checks,
> model generation, latency, and safe fallbacks. The benchmark independently proves exact variance,
> driver, reconciliation, and evidence accuracy.

Finish on the Overview with the grounded memo visible.

## Recording checklist

- Use the `python-grounded-prism` branch and bundled sample data.
- Keep the browser at a readable zoom with the sidebar visible.
- Preload GIDE; confirm the explanation provider is `openai-compatible`.
- Avoid showing `.env`, API keys, terminal history, or private dashboard credentials.
- Show at least one transaction-backed claim and one PRISM trajectory.
- Keep the final recording under 90 seconds.
