import fs from "node:fs";
import vm from "node:vm";
import { demoData, runScenario, runSuite } from "../scenarios.mjs";
import { money, percent, signed } from "../engine.mjs";

function loadEnvFile() {
  const file = new URL("../.env", import.meta.url);
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...value] = trimmed.split("=");
    if (!process.env[key]) process.env[key] = value.join("=").replace(/^["']|["']$/g, "");
  }
}

loadEnvFile();

const shouldSend = process.argv.includes("--send");
const source = fs.readFileSync(new URL("../data/story.js", import.meta.url), "utf8");
const sandbox = { window: {} };
vm.runInNewContext(source, sandbox);

const data = demoData(sandbox.window.LEDGERLENS_DATA);
const period = data.periods.at(-1);
const result = runScenario(data, period, "clean");
const suite = runSuite(data, period);
const topAccounts = result.order.filter(account => account.material).slice(0, 4);
const sessionId = `ledgerlens-production-close-${period.from}-to-${period.to}`;

const output = [
  `LedgerLens reviewed ${period.from} to ${period.to}.`,
  ...topAccounts.map(account => {
    const drivers = result.publishable.find(claim => claim.account === account.account && claim.type === "drivers");
    const context = result.publishable.find(claim => claim.account === account.account && claim.type === "cloud-context");
    return `${account.account}: ${signed(account.delta)} (${percent(account.percent)}). ${(context || drivers)?.text || "Driver details withheld."}`;
  }),
  `${result.rejected + result.blocked} weak claim(s) were withheld from the CFO brief.`
].join(" ");

const baseMetadata = {
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
};

function payload(traceId, input, message, step, latencyMs = 0) {
  return {
    project_id: process.env.PRISMTRACE_PROJECT_ID,
    model: "ledgerlens-deterministic-courtroom-v1",
    input_messages: [
      {
        role: "user",
        content: input
      }
    ],
    output_message: message,
    latency_ms: latencyMs,
    trace_id: traceId,
    session_id: sessionId,
    agent_id: "ledgerlens-financial-variance-courtroom",
    agent_name: "LedgerLens Financial Variance Courtroom",
    metadata: {
      ...baseMetadata,
      session_id: sessionId,
      agent_id: "ledgerlens-financial-variance-courtroom",
      agent_name: "LedgerLens Financial Variance Courtroom",
      step
    }
  };
}

const withheld = result.claims
  .filter(claim => claim.status === "rejected" || claim.status === "blocked")
  .map(claim => `${claim.id}: ${claim.status}`)
  .join("; ");

const payloads = [
  payload(
    `ledgerlens-live-review-${period.to}`,
    `Explain material financial changes for ${period.from} to ${period.to} using monthly summaries and transaction-level CSV rows.`,
    output,
    "close_review",
    420
  ),
  payload(
    `ledgerlens-live-courtroom-${period.to}`,
    "Verify whether any unsupported, causal, or uncited claim can enter the CFO brief.",
    `Courtroom result: ${result.publishable.length} claims publishable, ${result.rejected} rejected, ${result.blocked} blocked. Withheld claims: ${withheld}. Complete citations are required before approval or qualification.`,
    "courtroom_verification",
    180
  ),
  payload(
    `ledgerlens-live-edge-lab-${period.to}`,
    "Run the LedgerLens failure lab against controlled finance edge cases.",
    `${suite.filter(item => item.pass).length}/${suite.length} edge cases passed, including missing citations, fabricated citations, mixed currencies, wrong periods, invalid cents, stale memory, and hidden instructions in ledger text.`,
    "edge_lab",
    610
  )
];

const preview = {
  agent_id: "ledgerlens-financial-variance-courtroom",
  agent_name: "LedgerLens Financial Variance Courtroom",
  session_id: sessionId,
  traces: payloads
};

if (!shouldSend) {
  fs.mkdirSync(new URL("../artifacts/", import.meta.url), { recursive: true });
  fs.writeFileSync(
    new URL("../artifacts/prism-trace-preview.json", import.meta.url),
    JSON.stringify(preview, null, 2)
  );
  console.log("Wrote artifacts/prism-trace-preview.json. Set PRISMTRACE_PROJECT_ID and PRISMTRACE_API_KEY before trace:send.");
  process.exit(0);
}

const host = process.env.PRISMTRACE_HOST || "https://prism-api-prod.up.railway.app";
const apiKey = process.env.PRISMTRACE_API_KEY;

if (!process.env.PRISMTRACE_PROJECT_ID || !apiKey || process.env.PRISMTRACE_PROJECT_ID.includes("00000000") || apiKey.includes("replace-me")) {
  console.error("Missing PRISM credentials. Fill PRISMTRACE_PROJECT_ID and PRISMTRACE_API_KEY before running trace:send.");
  process.exit(2);
}

for (const item of payloads) {
  const response = await fetch(`${host}/api/traces`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-PRISMtrace-Key": apiKey
    },
    body: JSON.stringify(item)
  });

  const body = await response.text();
  if (!response.ok) throw new Error(`PRISM ingest failed ${response.status}: ${body}`);
  const saved = JSON.parse(body);
  console.log(`PRISM trace sent: ${saved.trace_id} (${saved.id}) session=${saved.session_id}`);
}
