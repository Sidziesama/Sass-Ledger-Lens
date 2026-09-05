import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import Papa from "papaparse";
import { breakdown, cents, investigate, makeFinding, money, sum } from "../engine.mjs";
import { parseCsv } from "../csv.mjs";
import { demoData, runScenario, runSuite } from "../scenarios.mjs";

function loadStory() {
  const source = fs.readFileSync(new URL("../data/story.js", import.meta.url), "utf8");
  const sandbox = { window: {} };
  vm.runInNewContext(source, sandbox);
  return demoData(sandbox.window.LEDGERLENS_DATA);
}

const data = loadStory();

function account(result, name) {
  return result.accounts.find(item => item.account === name);
}

function claim(result, id) {
  return result.claims.find(item => item.id === id);
}

test("clean demo periods reconcile and produce verified courtroom output", () => {
  for (const period of data.periods) {
    const result = runScenario(data, period, "clean");
    assert.equal(result.accounts.every(item => item.valid), true);
    assert.equal(result.issues.length, 0);
    assert.equal(result.publishable.every(item => item.status === "approved" || item.status === "qualified"), true);
    assert.equal(result.claims.some(item => item.status === "rejected"), true);
    assert.equal(result.coverage, 100);
  }
});

test("known August revenue math and concentration are recomputed from source rows", () => {
  const result = runScenario(data, data.periods[0], "clean");
  const revenue = account(result, "Revenue");
  const drivers = breakdown(result, "Revenue", "counterparty");
  assert.equal(revenue.delta, cents(180000));
  assert.equal(drivers.find(item => item.name === "Acme Corp").delta, cents(52000));
  assert.equal(drivers.find(item => item.name === "Globex").delta, cents(41000));
  assert.equal(claim(result, "broad-growth").status, "rejected");
});

test("all curated edge scenarios pass for every available period", () => {
  for (const period of data.periods) {
    const suite = runSuite(data, period);
    const failures = suite.filter(item => !item.pass);
    assert.deepEqual(failures, []);
  }
});

test("bad inputs fail closed instead of rounding or inventing evidence", () => {
  const mismatch = runScenario(data, data.periods[1], "mismatch");
  assert.equal(account(mismatch, "Revenue").valid, false);
  assert.equal(mismatch.claims.filter(item => item.account === "Revenue").every(item => item.status === "blocked"), true);

  const currency = runScenario(data, data.periods[0], "currency");
  assert.equal(account(currency, "Revenue").valid, false);
  assert.equal(currency.issues.some(item => item.code === "currency"), true);

  const wrongClaim = runScenario(data, data.periods[0], "wrong-claim");
  assert.equal(claim(wrongClaim, "tampered").status, "rejected");

  const missingCitations = runScenario(data, data.periods[0], "missing-citations");
  assert.equal(claim(missingCitations, "no-citations").status, "rejected");
  assert.equal(missingCitations.publishable.some(item => item.id === "no-citations"), false);

  const badCitation = runScenario(data, data.periods[0], "bad-citation");
  assert.equal(claim(badCitation, "fake-evidence").status, "rejected");
});

test("money math uses cent-exact parsing", () => {
  assert.equal(sum([cents("0.10"), cents("0.20")]), 30);
  assert.equal(money(sum([cents("0.10"), cents("0.20")])), "$0.30");
  assert.throws(() => cents("12.345"), /Invalid USD amount/);
  assert.throws(() => cents("1e6"), /Invalid USD amount/);
  assert.throws(() => cents("$1.00"), /Invalid USD amount/);
});

test("reviewer-approved memory persists only when prior evidence is unchanged", () => {
  const august = runScenario(data, data.periods[0], "clean");
  const finding = makeFinding(august, "Cloud Costs");
  const september = investigate(data, data.periods[1], [finding]);
  const active = september.memories.find(item => item.id === finding.id);
  assert.equal(active.status, "active");
  assert.equal(september.order[0].account, "Cloud Costs");

  const changed = structuredClone(data);
  changed.transactions.find(item => item.id === "CLD-0801").amount = 75000;
  const stale = investigate(changed, data.periods[1], [finding]);
  assert.equal(stale.memories.find(item => item.id === finding.id).status, "stale");
});

test("CSV parser accepts practical finance files and rejects ambiguous ones", () => {
  const summaryCsv = "month,account,amount\r\n2026-08,Revenue,10.00\r\n2026-09,Revenue,12.50\r\n";
  const rows = parseCsv(summaryCsv, "summary", Papa);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].amount, "10.00");

  const txCsv = [
    "id,date,month,account,counterparty,segment,category,amount,status",
    "T1,2026-09-01,2026-09,Revenue,\"ACME, Inc.\",Enterprise,Subscription,12.50,posted"
  ].join("\n");
  assert.equal(parseCsv(txCsv, "transaction", Papa)[0].counterparty, "ACME, Inc.");

  assert.throws(() => parseCsv("month,account,amount,amount\n2026-09,Revenue,1,1", "summary", Papa), /Duplicate CSV headers/);
  assert.throws(() => parseCsv("month,account,amount\n2026-09,Revenue,12.345", "summary", Papa), /at most two decimal places/);
});

test("random reconciled ledgers conserve account and driver deltas", () => {
  let seed = 7;
  const next = () => {
    seed = seed * 48271 % 0x7fffffff;
    return seed / 0x7fffffff;
  };
  for (let n = 0; n < 60; n += 1) {
    const summaries = [];
    const transactions = [];
    for (const month of ["2026-01", "2026-02"]) {
      for (const accountName of ["Revenue", "Cloud Costs", "Payroll"]) {
        const values = Array.from({ length: 4 }, () => Math.round((next() * 200000 - 60000) * 100) / 100);
        const total = values.reduce((acc, value) => acc + cents(value), 0);
        summaries.push({ month, account: accountName, amount: String(total / 100) });
        values.forEach((value, index) => {
          transactions.push({
            id: `${n}-${month}-${accountName}-${index}`,
            date: `${month}-15`,
            month,
            account: accountName,
            counterparty: `Counterparty ${index}`,
            segment: "Synthetic",
            category: "Generated",
            amount: String(value),
            status: "posted"
          });
        });
      }
    }
    const synthetic = {
      name: "Generated ledger",
      scope: `generated-${n}`,
      summaries,
      transactions,
      periods: [{ from: "2026-01", to: "2026-02", label: "Generated close" }],
      context: []
    };
    const result = investigate(synthetic, synthetic.periods[0]);
    assert.equal(result.issues.length, 0);
    for (const item of result.accounts) {
      assert.equal(item.valid, true);
      assert.equal(sum(breakdown(result, item.account).map(driver => driver.delta)), item.delta);
    }
  }
});
