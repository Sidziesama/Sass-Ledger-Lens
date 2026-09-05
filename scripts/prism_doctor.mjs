import fs from "node:fs";

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

const host = process.env.PRISMTRACE_HOST || "https://prism-api-prod.up.railway.app";
const projectId = process.env.PRISMTRACE_PROJECT_ID;
const apiKey = process.env.PRISMTRACE_API_KEY;
const handshake = process.argv.includes("--handshake");

if (!projectId || !apiKey || projectId.includes("00000000") || apiKey.includes("replace-me")) {
  console.error("Missing PRISM credentials. Fill PRISMTRACE_PROJECT_ID and PRISMTRACE_API_KEY in .env.");
  process.exit(2);
}

const response = handshake
  ? await fetch(`${host}/api/setup-doctor/handshake`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-PRISMtrace-Key": apiKey
      },
      body: JSON.stringify({
        project_id: projectId,
        send_test_trace: true,
        client: "codex"
      })
    })
  : await fetch(`${host}/api/setup-doctor?project_id=${encodeURIComponent(projectId)}`, {
      headers: {
        "X-PRISMtrace-Key": apiKey
      }
    });

const body = await response.text();
console.log(`PRISM ${handshake ? "handshake" : "doctor"}: HTTP ${response.status}`);
console.log(body);
if (!response.ok) process.exit(1);
