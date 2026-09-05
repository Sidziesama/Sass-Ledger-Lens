import fs from "node:fs";
import vm from "node:vm";
import { demoData, runScenario, runSuite } from "../scenarios.mjs";
import { money, percent, signed } from "../engine.mjs";

const shouldSend = process.argv.includes("--send");
const source = fs.readFileSync(new URL("../data/story.js", import.meta.url), "utf8");
const sandbox = { window: {} };
vm.runInNewContext(source, sandbox);

const data = demoData(sandbox.window.LEDGERLENS_DATA);
const period = data.periods.at(-1);
const result = runScenario(data, period, "clean");
const suite = runSuite(data, period);
const topAccounts = result.order.filter(account => account.material).slice(0, 4);

const output = [
  `LedgerLens reviewed ${period.from} to ${period.to}.`,
  ...topAccounts.map(account => {
    const drivers = result.publishable.find(claim => claim.account === account.account && claim.type === "drivers");
    const context = result.publishable.find(claim => claim.account === account.account && claim.type === "cloud-context");
    return `${account.account}: ${signed(account.delta)} (${percent(account.percent)}). ${(context || drivers)?.text || "Driver details withheld."}`;
  }),
  `${result.rejected + result.blocked} weak claim(s) were withheld from the CFO brief.`
].join(" ");

const payload = {
  project_id: process.env.PRISMTRACE_PROJECT_ID,
  model: "ledgerlens-deterministic-courtroom-v1",
  input_messages: [
    {
      role: "user",
      content: `Explain material financial changes for ${period.from} to ${period.to} using monthly summaries and transaction-level CSV rows.`
    }
  ],
  output_message: output,
  latency_ms: 0,
  trace_id: `ledgerlens-${period.from}-to-${period.to}-courtroom-demo`,
  session_id: "ledgerlens-hackathon-demo",
  agent_id: "ledgerlens-financial-variance-courtroom",
  agent_name: "LedgerLens Financial Variance Courtroom",
  metadata: {
    track: "Maximor Money Operations",
    flow: "Detect -> Investigate -> Explain -> Prove -> Remember",
    prism_framework: "Observe -> Improve -> Prove",
    period_from: period.from,
    period_to: period.to,
    accepted_rows: result.rows.length,
    quarantined_rows: result.quarantine.length,
    issue_count: result.issues.length,
    publishable_claims: result.publishable.length,
    rejected_claims: result.rejected,
    blocked_claims: result.blocked,
    evidence_coverage_percent: result.coverage,
    top_account: topAccounts[0]?.account,
    top_account_delta: topAccounts[0] ? money(topAccounts[0].delta) : "N/A",
    edge_cases_passing: suite.filter(item => item.pass).length,
    edge_cases_total: suite.length,
    guarded_edge_cases: suite.map(item => item.name)
  }
};

if (!shouldSend) {
  fs.mkdirSync(new URL("../artifacts/", import.meta.url), { recursive: true });
  fs.writeFileSync(
    new URL("../artifacts/prism-trace-preview.json", import.meta.url),
    JSON.stringify(payload, null, 2)
  );
  console.log("Wrote artifacts/prism-trace-preview.json. Set PRISMTRACE_PROJECT_ID and PRISMTRACE_API_KEY before trace:send.");
  process.exit(0);
}

const host = process.env.PRISMTRACE_HOST || "https://prism.blockconvey.com";
const apiKey = process.env.PRISMTRACE_API_KEY;

if (!payload.project_id || !apiKey || payload.project_id.includes("00000000") || apiKey.includes("replace-me")) {
  console.error("Missing PRISM credentials. Fill PRISMTRACE_PROJECT_ID and PRISMTRACE_API_KEY before running trace:send.");
  process.exit(2);
}

const response = await fetch(`${host}/api/traces`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-PRISMtrace-Key": apiKey
  },
  body: JSON.stringify(payload)
});

const body = await response.text();
if (!response.ok) throw new Error(`PRISM ingest failed ${response.status}: ${body}`);

console.log("PRISM trace sent.");
console.log(body);
