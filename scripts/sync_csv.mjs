import fs from "node:fs";
import vm from "node:vm";
import Papa from "papaparse";

const source = fs.readFileSync(new URL("../data/story.js", import.meta.url), "utf8");
const sandbox = { window: {} };
vm.runInNewContext(source, sandbox);
const data = sandbox.window.LEDGERLENS_DATA;

const summaryColumns = ["month", "account", "amount"];
const transactionColumns = ["id", "duplicateOf", "date", "month", "account", "counterparty", "segment", "category", "amount", "status"];

fs.writeFileSync(
  new URL("../data/monthly_summary.csv", import.meta.url),
  `${Papa.unparse(data.summaries, { columns: summaryColumns, escapeFormulae: true })}\n`
);

fs.writeFileSync(
  new URL("../data/transactions.csv", import.meta.url),
  `${Papa.unparse(data.transactions, { columns: transactionColumns, escapeFormulae: true })}\n`
);

console.log("Synced data/monthly_summary.csv and data/transactions.csv from data/story.js");
