import { breakdown, investigate, makeFinding, money, percent, signed } from "./engine.mjs";
import { demoData, runScenario, runSuite, scenarios } from "./scenarios.mjs";
import { parseCsv } from "./csv.mjs";

const root = document.querySelector("#root");
const summaryInput = document.querySelector("#summaryInput");
const transactionInput = document.querySelector("#transactionInput");
const sourceStory = window.LEDGERLENS_DATA;
const demoLedger = demoData(sourceStory);

const tabs = [
  ["review", "Review"],
  ["evidence", "Evidence"],
  ["memory", "Business memory"],
  ["lab", "Test lab"]
];

const state = {
  data: demoLedger,
  mode: "demo",
  periodIndex: Math.min(1, demoLedger.periods.length - 1),
  scenarioId: "clean",
  selectedAccount: null,
  selectedClaimId: null,
  selectedDriver: null,
  tab: "review",
  notice: "Synthetic close data loaded. Results are deterministic and recomputed on every run.",
  importError: "",
  pendingSummaries: null,
  pendingTransactions: null,
  suite: null
};

function clone(value) {
  return typeof structuredClone === "function" ? structuredClone(value) : JSON.parse(JSON.stringify(value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const attr = escapeHtml;
const cleanStatus = value => ["approved", "qualified", "rejected", "blocked", "active", "stale", "unapproved"].includes(value) ? value : "blocked";
const icon = name => `<i data-lucide="${attr(name)}" aria-hidden="true"></i>`;
const monthLabel = value => value || "Unknown";
const driverDimension = account => account === "Operating Cash Flow" ? "category" : "counterparty";
const abs = value => Math.abs(value || 0);

function memoryKey(scope) {
  return `ledgerlens.memory.${scope || "default"}`;
}

function loadSavedMemory(scope) {
  try {
    const value = localStorage.getItem(memoryKey(scope));
    const parsed = value ? JSON.parse(value) : [];
    return Array.isArray(parsed) ? parsed.filter(item => item && typeof item === "object") : [];
  } catch {
    return [];
  }
}

function writeSavedMemory(scope, entries) {
  localStorage.setItem(memoryKey(scope), JSON.stringify(entries));
}

function periodsFor(data) {
  if (Array.isArray(data.periods) && data.periods.length) return data.periods;
  const months = [...new Set((data.summaries || []).map(row => row.month))].sort();
  return months.slice(1).map((to, index) => ({
    from: months[index],
    to,
    label: `${months[index]} to ${to}`,
    context: "Imported close review"
  }));
}

function currentPeriod() {
  const periods = periodsFor(state.data);
  state.periodIndex = Math.max(0, Math.min(state.periodIndex, periods.length - 1));
  return periods[state.periodIndex];
}

function calculate() {
  const period = currentPeriod();
  if (!period) throw new Error("At least two accounting months are required.");
  const saved = loadSavedMemory(state.data.scope);
  if (state.mode === "demo") return runScenario(state.data, period, state.scenarioId, saved);
  return investigate(state.data, period, saved);
}

function normalizeSelection(result) {
  const ordered = result.order?.length ? result.order : result.accounts;
  if (!ordered.some(account => account.account === state.selectedAccount)) {
    state.selectedAccount = ordered[0]?.account || result.accounts[0]?.account || null;
  }
  const accountClaims = result.claims.filter(claim => claim.account === state.selectedAccount);
  if (!accountClaims.some(claim => claim.id === state.selectedClaimId)) {
    state.selectedClaimId = (accountClaims.find(claim => claim.type === "drivers") || accountClaims[0])?.id || null;
  }
  const claim = accountClaims.find(item => item.id === state.selectedClaimId);
  const drivers = claim?.drivers || [];
  if (state.selectedDriver && !drivers.some(driver => driver.name === state.selectedDriver)) state.selectedDriver = null;
}

function selectedAccount(result) {
  return result.accounts.find(account => account.account === state.selectedAccount) || result.accounts[0];
}

function selectedClaim(result) {
  return result.claims.find(claim => claim.id === state.selectedClaimId) || result.claims.find(claim => claim.account === state.selectedAccount);
}

function verdictCounts(result) {
  return {
    publishable: result.publishable.length,
    rejected: result.rejected,
    blocked: result.blocked
  };
}

function statusCopy(status) {
  return {
    approved: "Approved",
    qualified: "Qualified",
    rejected: "Rejected",
    blocked: "Blocked",
    active: "Active",
    stale: "Stale",
    unapproved: "Needs approval"
  }[status] || "Review";
}

function render() {
  let result;
  let error = null;
  try {
    result = calculate();
    normalizeSelection(result);
  } catch (caught) {
    error = caught;
  }

  root.innerHTML = `
    ${renderHeader(result, error)}
    ${state.notice ? `<div class="notice">${icon("circle-check")}<span>${escapeHtml(state.notice)}</span></div>` : ""}
    ${state.importError ? `<div class="notice danger">${icon("triangle-alert")}<span>${escapeHtml(state.importError)}</span></div>` : ""}
    ${renderTabs()}
    ${error ? renderFatal(error) : renderTab(result)}
  `;

  window.lucide?.createIcons({
    attrs: {
      "stroke-width": 2,
      width: 18,
      height: 18
    }
  });
}

function renderHeader(result, error) {
  const periods = periodsFor(state.data);
  const period = currentPeriod();
  const counts = result && !error ? verdictCounts(result) : { publishable: 0, rejected: 0, blocked: 0 };
  return `
    <header class="masthead">
      <div class="brand-block">
        <span class="eyebrow">Maximor Money Operations</span>
        <h1>LedgerLens</h1>
        <p>GIDE/Ornith proposes finance narratives; LedgerLens verifies material movement, source rows, and reviewer-approved memory before anything reaches the CFO brief.</p>
      </div>
      <div class="status-stack" aria-label="Demo status">
        <span class="badge strong">${state.mode === "demo" ? "Synthetic ledger" : "Imported ledger"}</span>
        <span class="badge">GIDE/Ornith AI proposer</span>
        <span class="badge">Deterministic checks</span>
        <span class="badge muted">PRISM trace-ready</span>
      </div>
    </header>

    <section class="toolbar" aria-label="Review controls">
      <label>
        <span>Review period</span>
        <select id="periodSelect">
          ${periods.map((item, index) => `<option value="${index}" ${index === state.periodIndex ? "selected" : ""}>${escapeHtml(item.label || `${item.from} to ${item.to}`)}</option>`).join("")}
        </select>
      </label>
      <label>
        <span>Failure case</span>
        <select id="scenarioSelect" ${state.mode !== "demo" ? "disabled" : ""}>
          ${scenarios.map(item => `<option value="${attr(item.id)}" ${item.id === state.scenarioId ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}
        </select>
      </label>
      <div class="button-row" role="group" aria-label="Actions">
        <button class="button primary" type="button" data-action="run">${icon("gavel")}<span>Run review</span></button>
        <button class="button" type="button" data-action="import-summary" title="Import monthly summary CSV">${icon("file-spreadsheet")}<span>Summary CSV</span></button>
        <button class="button" type="button" data-action="import-transactions" title="Import transaction CSV">${icon("upload")}<span>Transactions CSV</span></button>
        <button class="button icon-only" type="button" data-action="export" title="Export evidence package" aria-label="Export evidence package">${icon("download")}</button>
        <button class="button icon-only" type="button" data-action="reset" title="Reset demo data" aria-label="Reset demo data">${icon("rotate-ccw")}</button>
      </div>
      <div class="toolbar-stats">
        <strong>${escapeHtml(monthLabel(period?.to))}</strong>
        <span>${counts.publishable} publishable / ${counts.rejected} rejected / ${counts.blocked} blocked</span>
      </div>
    </section>
  `;
}

function renderTabs() {
  return `
    <nav class="tabs" role="tablist" aria-label="LedgerLens views">
      ${tabs.map(([id, label]) => `
        <button type="button" role="tab" data-tab="${id}" aria-selected="${state.tab === id}" class="${state.tab === id ? "active" : ""}">
          ${escapeHtml(label)}
        </button>
      `).join("")}
    </nav>
  `;
}

function renderTab(result) {
  if (state.tab === "evidence") return renderEvidence(result);
  if (state.tab === "memory") return renderMemory(result);
  if (state.tab === "lab") return renderLab(result);
  return renderReview(result);
}

function renderFatal(error) {
  return `
    <section class="empty-state">
      <div>${icon("octagon-alert")}</div>
      <h2>Review blocked</h2>
      <p>${escapeHtml(error.message)}</p>
    </section>
  `;
}

function renderReview(result) {
  const account = selectedAccount(result);
  const counts = verdictCounts(result);
  const scenario = result.scenario || scenarios.find(item => item.id === state.scenarioId);
  const invalidAccounts = result.accounts.filter(item => !item.valid).length;
  const unresolved = result.issues.length + invalidAccounts;
  return `
    <section class="metric-strip" aria-label="Review summary">
      ${renderMetric("Top movement", account?.account || "-", account ? signed(account.delta) : "-", account ? percent(account.percent) : "N/A")}
      ${renderMetric("Evidence", `${result.coverage ?? 0}%`, `${result.rows.length} rows accepted`, `${result.quarantine.length} quarantined`)}
      ${renderMetric("Courtroom", `${counts.publishable} publishable`, `${counts.rejected} rejected`, `${counts.blocked} blocked`)}
      ${renderMetric("Edge case", escapeHtml(scenario?.name || "Live data"), state.mode === "demo" ? "Scenario lab active" : "Imported data", unresolved ? `${unresolved} unresolved issue(s)` : "No unresolved issues")}
    </section>

    <section class="review-grid">
      <div class="surface ledger-surface">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Detect</span>
            <h2>Material changes</h2>
          </div>
          <span class="mini-badge">${result.accounts.filter(item => item.material).length} material</span>
        </div>
        ${renderAccountTable(result)}
      </div>

      <div class="surface courtroom-surface">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Challenge</span>
            <h2>${escapeHtml(account?.account || "Account")} courtroom</h2>
          </div>
          <span class="mini-badge">GIDE claims start untrusted</span>
        </div>
        ${renderDriverBars(result, account)}
        ${renderCourtroom(result)}
      </div>

      <aside class="side-column">
        ${renderWeakClaims(result)}
        ${renderBrief(result)}
        ${renderTrace(result)}
      </aside>
    </section>
  `;
}

function renderMetric(label, value, detail, footnote) {
  return `
    <article class="metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail || "")}${footnote ? `<em>${escapeHtml(footnote)}</em>` : ""}</small>
    </article>
  `;
}

function renderAccountTable(result) {
  const rows = (result.order?.length ? result.order : result.accounts).map(account => {
    const active = account.account === state.selectedAccount;
    const signClass = account.delta > 0 ? "positive" : account.delta < 0 ? "negative" : "neutral";
    return `
      <tr class="${active ? "active" : ""}">
        <td>
          <button class="link-button" type="button" data-account="${attr(account.account)}">
            ${escapeHtml(account.account)}
          </button>
        </td>
        <td class="${signClass}">${escapeHtml(signed(account.delta))}</td>
        <td>${escapeHtml(percent(account.percent))}</td>
        <td><span class="status ${account.valid ? "approved" : "blocked"}">${account.valid ? "Tied" : "Blocked"}</span></td>
        <td>${account.score}</td>
      </tr>
    `;
  }).join("");

  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Account</th>
            <th>Change</th>
            <th>Percent</th>
            <th>Reconcile</th>
            <th>Score</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderDriverBars(result, account) {
  if (!account) return "";
  const drivers = breakdown(result, account.account, driverDimension(account.account)).slice(0, 6);
  const max = Math.max(...drivers.map(driver => abs(driver.delta)), 1);
  return `
    <div class="driver-panel">
      <div class="driver-head">
        <span>${escapeHtml(driverDimension(account.account))} breakdown</span>
        <strong>${escapeHtml(account.valid ? "reconciled" : "withheld")}</strong>
      </div>
      ${drivers.map(driver => {
        const width = Math.max(6, abs(driver.delta) / max * 100);
        const tone = driver.delta >= 0 ? "increase" : "decrease";
        return `
          <button class="driver-row ${state.selectedDriver === driver.name ? "selected" : ""}" type="button" data-driver="${attr(driver.name)}">
            <span>${escapeHtml(driver.name)}</span>
            <span class="bar-track"><span class="bar ${tone}" style="width:${width}%"></span></span>
            <strong>${escapeHtml(signed(driver.delta))}</strong>
          </button>
        `;
      }).join("")}
    </div>
  `;
}

function renderCourtroom(result) {
  const claims = result.claims.filter(claim => claim.account === state.selectedAccount);
  return `
    <div class="claim-stack">
      ${claims.map(claim => {
        const expanded = claim.id === state.selectedClaimId;
        return `
          <article class="claim-card ${cleanStatus(claim.status)} ${expanded ? "expanded" : ""}">
            <button class="claim-top" type="button" data-claim="${attr(claim.id)}">
              <span class="role">${escapeHtml(claim.type || "claim")}</span>
              <strong>${escapeHtml(claim.title || "Untitled claim")}</strong>
              <span class="status ${cleanStatus(claim.status)}">${statusCopy(claim.status)}</span>
            </button>
            <p>${escapeHtml(claim.text)}</p>
            ${expanded ? `
              <div class="formula">${escapeHtml(claim.formula || "")}</div>
              <ul class="check-list">
                ${(claim.checks || []).map(check => `
                  <li class="${check.pass ? "pass" : "fail"}">
                    ${icon(check.pass ? "check" : "x")}
                    <span><b>${escapeHtml(check.name)}</b>${escapeHtml(check.detail)}</span>
                  </li>
                `).join("")}
              </ul>
            ` : ""}
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderWeakClaims(result) {
  const rejected = result.claims.filter(claim => claim.status === "rejected" || claim.status === "blocked").slice(0, 4);
  return `
    <section class="surface compact">
      <div class="section-heading">
        <div>
          <span class="eyebrow">Courtroom filter</span>
          <h2>Claims withheld</h2>
        </div>
        <span class="mini-badge">${rejected.length}</span>
      </div>
      <div class="mini-list">
        ${rejected.map(claim => `
          <button class="mini-item" type="button" data-account="${attr(claim.account)}" data-claim="${attr(claim.id)}">
            <span class="status ${cleanStatus(claim.status)}">${statusCopy(claim.status)}</span>
            <strong>${escapeHtml(claim.title)}</strong>
            <small>${escapeHtml(claim.account)}</small>
          </button>
        `).join("") || `<p class="muted-copy">No claims withheld for this run.</p>`}
      </div>
    </section>
  `;
}

function renderBrief(result) {
  const facts = [];
  for (const account of result.order.filter(item => item.material).slice(0, 4)) {
    const movement = result.publishable.find(claim => claim.account === account.account && claim.type === "movement");
    const drivers = result.publishable.find(claim => claim.account === account.account && claim.type === "drivers");
    const context = result.publishable.find(claim => claim.account === account.account && claim.type === "cloud-context");
    if (movement) facts.push(movement.text);
    if (context) facts.push(context.text);
    else if (drivers) facts.push(drivers.text);
  }
  return `
    <section class="surface compact">
      <div class="section-heading">
        <div>
          <span class="eyebrow">Explain</span>
          <h2>CFO brief</h2>
        </div>
        <span class="mini-badge">verified only</span>
      </div>
      <ol class="brief-list">
        ${facts.slice(0, 7).map(item => `<li>${escapeHtml(item)}</li>`).join("") || `<li>No publishable explanation until evidence reconciles.</li>`}
      </ol>
      <p class="withheld">${escapeHtml(result.rejected + result.blocked)} weak claim(s) were withheld from this brief.</p>
    </section>
  `;
}

function renderTrace(result) {
  return `
    <section class="surface compact">
      <div class="section-heading">
        <div>
          <span class="eyebrow">Observe</span>
          <h2>Trace preview</h2>
        </div>
      </div>
      <div class="trace">
        ${result.trace.map(item => `
          <div>
            <b>${escapeHtml(item.stage)}</b>
            <span>${escapeHtml(item.detail)}</span>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderEvidence(result) {
  const account = selectedAccount(result);
  const claim = selectedClaim(result);
  const rows = rowsForClaim(account, claim);
  return `
    <section class="evidence-layout">
      <div class="surface">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Prove</span>
            <h2>Evidence graph</h2>
          </div>
          <span class="mini-badge">${escapeHtml(account?.account || "")}</span>
        </div>
        ${renderClaimSwitch(result)}
        ${renderGraph(result, account, claim)}
      </div>
      <div class="surface">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Source rows</span>
            <h2>${rows.length} transaction rows</h2>
          </div>
          <button class="button slim" type="button" data-action="export">${icon("download")}<span>Evidence JSON</span></button>
        </div>
        ${renderTransactionTable(rows)}
        ${renderExceptions(result)}
      </div>
    </section>
  `;
}

function renderClaimSwitch(result) {
  return `
    <div class="claim-switch" role="group" aria-label="Claim selector">
      ${result.claims.filter(claim => claim.account === state.selectedAccount).map(claim => `
        <button type="button" data-claim="${attr(claim.id)}" class="${claim.id === state.selectedClaimId ? "active" : ""}">
          <span class="status ${cleanStatus(claim.status)}">${statusCopy(claim.status)}</span>
          ${escapeHtml(claim.type)}
        </button>
      `).join("")}
    </div>
  `;
}

function renderGraph(result, account, claim) {
  if (!account || !claim) return `<p class="muted-copy">Select a reconciled account and claim.</p>`;
  const drivers = (claim.drivers?.length ? claim.drivers : breakdown(result, account.account, driverDimension(account.account))).slice(0, 6);
  return `
    <div class="graph-grid">
      <div class="graph-column">
        <span class="graph-label">Claim</span>
        <div class="graph-node ${cleanStatus(claim.status)}">
          <strong>${escapeHtml(claim.title)}</strong>
          <span>${escapeHtml(claim.text)}</span>
        </div>
      </div>
      <div class="graph-column">
        <span class="graph-label">Tie-out</span>
        ${account.ties.map(tie => `
          <div class="graph-node ${tie.ok ? "approved" : "blocked"}">
            <strong>${escapeHtml(tie.month)}</strong>
            <span>${escapeHtml(`${money(tie.total)} ledger / ${money(tie.expected)} summary`)}</span>
          </div>
        `).join("")}
      </div>
      <div class="graph-column">
        <span class="graph-label">Drivers</span>
        ${drivers.map(driver => `
          <button class="graph-node button-node ${state.selectedDriver === driver.name ? "selected" : ""}" type="button" data-driver="${attr(driver.name)}">
            <strong>${escapeHtml(driver.name)}</strong>
            <span>${escapeHtml(`${signed(driver.delta)} across ${driver.rows.length} row(s)`)}</span>
          </button>
        `).join("")}
      </div>
      <div class="graph-column">
        <span class="graph-label">Transactions</span>
        <div class="graph-node">
          <strong>${claim.rows?.length || 0} cited row(s)</strong>
          <span>${escapeHtml((claim.rows || []).slice(0, 8).map(row => row.id).join(", "))}${(claim.rows || []).length > 8 ? "..." : ""}</span>
        </div>
      </div>
    </div>
  `;
}

function rowsForClaim(account, claim) {
  if (!claim) return [];
  const dimension = driverDimension(account?.account);
  const rows = claim.rows || [];
  if (!state.selectedDriver) return rows;
  return rows.filter(row => row[dimension] === state.selectedDriver);
}

function renderTransactionTable(rows) {
  return `
    <div class="table-wrap tall">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Date</th>
            <th>Month</th>
            <th>Account</th>
            <th>Counterparty</th>
            <th>Category</th>
            <th>Amount</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(row => `
            <tr>
              <td>${escapeHtml(row.id)}</td>
              <td>${escapeHtml(row.date)}</td>
              <td>${escapeHtml(row.month)}</td>
              <td>${escapeHtml(row.account)}</td>
              <td>${escapeHtml(row.counterparty)}${row.originalCounterparty ? `<small>alias: ${escapeHtml(row.originalCounterparty)}</small>` : ""}</td>
              <td>${escapeHtml(row.category)}</td>
              <td>${escapeHtml(money(row.cents ?? row.amount * 100))}</td>
            </tr>
          `).join("") || `<tr><td colspan="7">No cited rows for this selection.</td></tr>`}
        </tbody>
      </table>
    </div>
  `;
}

function renderExceptions(result) {
  const issues = result.issues.map(item => ({ title: item.code, detail: `${item.month || ""} ${item.account || ""} ${item.id || ""}: ${item.message}` }));
  const quarantined = result.quarantine.map(item => ({ title: "quarantined", detail: `${item.id}: ${item.reason}` }));
  const rows = [...issues, ...quarantined];
  return `
    <div class="exceptions">
      <h3>Exceptions</h3>
      ${rows.length ? rows.map(item => `
        <div>
          <span>${escapeHtml(item.title)}</span>
          <p>${escapeHtml(item.detail)}</p>
        </div>
      `).join("") : `<p class="muted-copy">No unresolved exceptions. Duplicate rows are counted once when confirmed.</p>`}
    </div>
  `;
}

function renderMemory(result) {
  const account = selectedAccount(result);
  const saved = loadSavedMemory(state.data.scope);
  const canApprove = result.claims.some(claim => claim.account === account?.account && claim.type === "drivers" && claim.status === "approved");
  const reusableMemory = result.memories.filter(memory => memory.kind !== "finding" || memory.reviewedPeriod < result.period.to);
  return `
    <section class="memory-layout">
      <div class="surface">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Remember</span>
            <h2>Reviewer-approved business memory</h2>
          </div>
          <div class="button-row">
            <button class="button primary slim" type="button" data-action="approve-memory" ${canApprove ? "" : "disabled"}>${icon("save")}<span>Approve finding</span></button>
            <button class="button slim" type="button" data-action="clear-memory" ${saved.length ? "" : "disabled"}>${icon("trash-2")}<span>Clear saved</span></button>
          </div>
        </div>
        <div class="memory-grid">
          ${reusableMemory.map(memory => `
            <article class="memory-card ${cleanStatus(memory.status)}">
              <span class="status ${cleanStatus(memory.status)}">${statusCopy(memory.status)}</span>
              <h3>${escapeHtml(memory.title || memory.id)}</h3>
              <p>${escapeHtml(memory.detail || memory.reason)}</p>
              <small>${escapeHtml(memory.source || "No source")} / ${escapeHtml(memory.validFrom || "?")} to ${escapeHtml(memory.validThrough || "?")}</small>
            </article>
          `).join("") || `<p class="muted-copy">No reusable business memory attached to this ledger.</p>`}
        </div>
      </div>

      <div class="surface">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Local findings</span>
            <h2>Saved from courtroom</h2>
          </div>
          <span class="mini-badge">${saved.length}</span>
        </div>
        <div class="memory-grid single">
          ${saved.map(memory => `
            <article class="memory-card">
              <h3>${escapeHtml(memory.title)}</h3>
              <p>${escapeHtml(memory.detail)}</p>
              <small>${escapeHtml(memory.source)} / fingerprint ${escapeHtml(memory.fingerprint)}</small>
              <button class="button slim" type="button" data-action="delete-memory" data-memory-id="${attr(memory.id)}">${icon("x")}<span>Remove</span></button>
            </article>
          `).join("") || `<p class="muted-copy">Approve a verified account finding to carry it into later close reviews.</p>`}
        </div>
      </div>
    </section>
  `;
}

function renderLab(result) {
  const scenario = scenarios.find(item => item.id === state.scenarioId);
  const currentPass = state.mode === "demo" && scenario ? !!scenario.expect(result) : null;
  const suite = state.suite || (state.mode === "demo" ? runSuite(state.data, currentPeriod()) : []);
  const passed = suite.filter(item => item.pass).length;
  return `
    <section class="lab-layout">
      <div class="surface">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Edge cases</span>
            <h2>Failure lab</h2>
          </div>
          <button class="button primary slim" type="button" data-action="run-suite" ${state.mode === "demo" ? "" : "disabled"}>${icon("test-tube-2")}<span>Run all</span></button>
        </div>
        ${state.mode !== "demo" ? `
          <div class="empty-state small">
            <h2>Scenario lab uses the synthetic ledger</h2>
            <p>Imported data stays untouched. Switch back to the demo ledger to test controlled failures.</p>
            <button class="button primary" type="button" data-action="use-demo">${icon("database")}<span>Use demo ledger</span></button>
          </div>
        ` : `
          <div class="lab-hero ${currentPass ? "pass" : "fail"}">
            <strong>${currentPass ? "Current case passes" : "Current case fails"}</strong>
            <span>${escapeHtml(scenario?.description || "")}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Expected behavior</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                ${suite.map(item => `
                  <tr>
                    <td>${escapeHtml(item.name)}</td>
                    <td>${escapeHtml(item.detail)}</td>
                    <td><span class="status ${item.pass ? "approved" : "blocked"}">${item.pass ? "Pass" : "Fail"}</span></td>
                    <td><button class="link-button" type="button" data-scenario="${attr(item.id)}">Open</button></td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
          <p class="suite-count">${passed}/${suite.length} edge cases passing for ${escapeHtml(currentPeriod().to)}.</p>
        `}
      </div>
      <div class="surface">
        <div class="section-heading">
          <div>
            <span class="eyebrow">Guardrails</span>
            <h2>What is checked</h2>
          </div>
        </div>
        <div class="guard-grid">
          ${[
            ["calculator", "Cent-exact arithmetic", "No floating-point rounding for money."],
            ["scale", "Summary tie-out", "Each account must reconcile in both periods."],
            ["fingerprint", "Complete citations", "Claims must cite the exact source set."],
            ["badge-check", "Memory provenance", "Only approved, current context can support a claim."],
            ["clock-alert", "Stale memory defense", "Saved findings expire if prior evidence changes."],
            ["shield-alert", "Bad input handling", "FX, dates, schema gaps, duplicates, conflicts, and injections fail closed."]
          ].map(([name, title, detail]) => `
            <article>
              ${icon(name)}
              <h3>${escapeHtml(title)}</h3>
              <p>${escapeHtml(detail)}</p>
            </article>
          `).join("")}
        </div>
      </div>
    </section>
  `;
}

function exportEvidence() {
  let result;
  try {
    result = calculate();
    normalizeSelection(result);
  } catch (error) {
    state.importError = error.message;
    render();
    return;
  }
  const account = selectedAccount(result);
  const claim = selectedClaim(result);
  const payload = {
    product: "LedgerLens Financial Variance Courtroom",
    generatedAt: new Date().toISOString(),
    dataset: state.data.name || state.data.scope,
    period: result.period,
    selectedAccount: account?.account,
    selectedClaim: claim ? {
      id: claim.id,
      type: claim.type,
      status: claim.status,
      title: claim.title,
      text: claim.text,
      formula: claim.formula,
      checks: claim.checks
    } : null,
    tieOuts: account?.ties,
    rows: rowsForClaim(account, claim).map(row => ({
      id: row.id,
      date: row.date,
      month: row.month,
      account: row.account,
      counterparty: row.counterparty,
      segment: row.segment,
      category: row.category,
      amount: money(row.cents)
    })),
    issues: result.issues,
    quarantine: result.quarantine,
    trace: result.trace
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `ledgerlens-evidence-${result.period.to}-${(account?.account || "account").replaceAll(" ", "-").toLowerCase()}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  state.notice = "Evidence package exported from the current courtroom result.";
  render();
}

function approveMemory() {
  try {
    const result = calculate();
    normalizeSelection(result);
    const finding = makeFinding(result, state.selectedAccount);
    const saved = loadSavedMemory(state.data.scope);
    const next = [finding, ...saved.filter(item => item.id !== finding.id)];
    writeSavedMemory(state.data.scope, next);
    state.notice = `${finding.title} saved as reviewer-approved memory.`;
    state.tab = "memory";
  } catch (error) {
    state.importError = error.message;
  }
  render();
}

function deleteMemory(id) {
  const saved = loadSavedMemory(state.data.scope).filter(item => item.id !== id);
  writeSavedMemory(state.data.scope, saved);
  state.notice = "Saved finding removed.";
  render();
}

function clearMemory() {
  writeSavedMemory(state.data.scope, []);
  state.notice = "Saved reviewer findings cleared for this ledger.";
  render();
}

function rowsToPeriods(summaries) {
  const months = [...new Set(summaries.map(row => row.month))].sort();
  if (months.length < 2) throw new Error("Imported summaries need at least two accounting months.");
  return months.slice(1).map((to, index) => ({
    from: months[index],
    to,
    label: `${months[index]} to ${to}`,
    context: "Imported close review"
  }));
}

async function parseFile(input, kind) {
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  try {
    const rows = parseCsv(await file.text(), kind, window.Papa);
    if (kind === "summary") state.pendingSummaries = rows;
    else state.pendingTransactions = rows;
    state.importError = "";
    state.notice = `${file.name} parsed. ${state.pendingSummaries && state.pendingTransactions ? "Both files loaded." : "Load the matching CSV to complete import."}`;
    if (state.pendingSummaries && state.pendingTransactions) {
      const periods = rowsToPeriods(state.pendingSummaries);
      const imported = {
        name: "Imported CSV ledger",
        scope: `imported-${Date.now()}`,
        summaries: state.pendingSummaries,
        transactions: state.pendingTransactions,
        periods,
        context: [],
        aliases: {}
      };
      state.data = imported;
      state.mode = "import";
      state.periodIndex = periods.length - 1;
      state.scenarioId = "clean";
      state.selectedAccount = null;
      state.selectedClaimId = null;
      state.selectedDriver = null;
      state.suite = null;
      state.pendingSummaries = null;
      state.pendingTransactions = null;
      state.notice = `Imported ${imported.summaries.length} summaries and ${imported.transactions.length} transactions.`;
    }
  } catch (error) {
    state.importError = error.message;
  }
  render();
}

root.addEventListener("click", event => {
  const target = event.target.closest("button");
  if (!target) return;
  const tab = target.dataset.tab;
  const account = target.dataset.account;
  const claim = target.dataset.claim;
  const driver = target.dataset.driver;
  const scenario = target.dataset.scenario;
  const action = target.dataset.action;

  if (tab) {
    state.tab = tab;
    render();
    return;
  }
  if (account) {
    state.selectedAccount = account;
    state.selectedClaimId = claim || null;
    state.selectedDriver = null;
    if (claim) state.tab = "evidence";
    render();
    return;
  }
  if (claim) {
    state.selectedClaimId = claim;
    state.selectedDriver = null;
    render();
    return;
  }
  if (driver) {
    state.selectedDriver = state.selectedDriver === driver ? null : driver;
    if (state.tab !== "evidence") state.tab = "evidence";
    render();
    return;
  }
  if (scenario) {
    state.mode = "demo";
    state.data = demoLedger;
    state.scenarioId = scenario;
    state.selectedAccount = null;
    state.selectedClaimId = null;
    state.selectedDriver = null;
    state.tab = "review";
    state.notice = `${scenarios.find(item => item.id === scenario)?.name || "Scenario"} loaded.`;
    render();
    return;
  }
  if (!action) return;
  if (action === "run") {
    state.notice = `Courtroom recomputed for ${currentPeriod().to}.`;
    state.importError = "";
    render();
  } else if (action === "import-summary") {
    summaryInput.click();
  } else if (action === "import-transactions") {
    transactionInput.click();
  } else if (action === "export") {
    exportEvidence();
  } else if (action === "reset" || action === "use-demo") {
    state.data = demoLedger;
    state.mode = "demo";
    state.periodIndex = Math.min(1, demoLedger.periods.length - 1);
    state.scenarioId = "clean";
    state.selectedAccount = null;
    state.selectedClaimId = null;
    state.selectedDriver = null;
    state.importError = "";
    state.notice = "Demo ledger restored.";
    render();
  } else if (action === "approve-memory") {
    approveMemory();
  } else if (action === "delete-memory") {
    deleteMemory(target.dataset.memoryId);
  } else if (action === "clear-memory") {
    clearMemory();
  } else if (action === "run-suite") {
    state.suite = runSuite(state.data, currentPeriod());
    const passed = state.suite.filter(item => item.pass).length;
    state.notice = `${passed}/${state.suite.length} edge cases passed for ${currentPeriod().to}.`;
    render();
  }
});

root.addEventListener("change", event => {
  if (event.target.id === "periodSelect") {
    state.periodIndex = Number(event.target.value);
    state.selectedAccount = null;
    state.selectedClaimId = null;
    state.selectedDriver = null;
    state.suite = null;
    state.notice = `Review period changed to ${currentPeriod().to}.`;
    render();
  }
  if (event.target.id === "scenarioSelect") {
    state.scenarioId = event.target.value;
    state.selectedAccount = null;
    state.selectedClaimId = null;
    state.selectedDriver = null;
    state.suite = null;
    state.notice = `${scenarios.find(item => item.id === state.scenarioId)?.name || "Scenario"} loaded.`;
    render();
  }
});

summaryInput.addEventListener("change", () => parseFile(summaryInput, "summary"));
transactionInput.addEventListener("change", () => parseFile(transactionInput, "transaction"));

render();
