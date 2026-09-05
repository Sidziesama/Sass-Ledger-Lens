// Runs the main-branch "courtroom" engine on one prepared dataset and prints JSON.
//   node courtroom_runner.mjs <engine_dir> <data.json> <from> <to>
import { pathToFileURL } from "node:url";
import fs from "node:fs";
const [engineDir, dataPath, from, to] = process.argv.slice(2);
const { investigate } = await import(pathToFileURL(`${engineDir}/engine.mjs`).href);
const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));
try {
  const r = investigate(data, { from, to }, data.saved || []);
  const slim = {
    accounts: r.accounts.map(a => ({ account: a.account, previous: a.previous, current: a.current, delta: a.delta,
      percent: a.percent, valid: a.valid, material: a.material, score: a.score, reclass: a.reclass,
      ties: a.ties.map(t => ({ month: t.month, ok: t.ok, gap: t.gap, count: t.count, reason: t.reason })) })),
    issues: r.issues, quarantine: r.quarantine.map(q => ({ id: q.id, account: q.account, reason: q.reason })),
    memories: r.memories.map(m => ({ id: m.id, status: m.status, reason: m.reason, account: m.account })),
    claims: r.claims.map(c => ({ id: c.id, account: c.account, type: c.type, status: c.status, title: c.title, text: c.text,
      formula: c.formula, rowIds: (c.rows || []).map(x => x.id).slice(0, 40),
      drivers: (c.drivers || []).slice(0, 8).map(d => ({ name: d.name, previous: d.previous, current: d.current, delta: d.delta })),
      checks: (c.checks || []).map(k => ({ name: k.name, pass: k.pass })) })),
    coverage: r.coverage, rejected: r.rejected, blocked: r.blocked, order: r.order.map(a => a.account),
  };
  process.stdout.write(JSON.stringify(slim));
} catch (e) {
  process.stdout.write(JSON.stringify({ error: String(e && e.message || e) }));
}
