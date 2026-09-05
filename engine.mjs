// Money is parsed as decimal cents. Unsafe values fail closed before aggregation.
export function cents(value) {
  const raw = String(value).trim();
  if (!/^-?\d+(\.\d{1,2})?$/.test(raw)) throw new Error(`Invalid USD amount: ${raw}`);
  const [whole, fraction = ""] = raw.replace("-", "").split(".");
  const amount = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (amount > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("Amount exceeds safe precision");
  return Number(amount) * (raw.startsWith("-") ? -1 : 1);
}
export function sum(values) {
  const total = values.reduce((a, b) => a + BigInt(b), 0n);
  if (total > BigInt(Number.MAX_SAFE_INTEGER) || total < -BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("Total exceeds safe precision");
  return Number(total);
}
export const money = value => value == null ? "Unavailable" : new Intl.NumberFormat("en-US", {style:"currency", currency:"USD", minimumFractionDigits: value % 100 ? 2 : 0, maximumFractionDigits:2}).format(value / 100);
export const signed = value => value == null ? "Unavailable" : `${value > 0 ? "+" : ""}${money(value)}`;
export const percent = value => value == null ? "N/A" : `${new Intl.NumberFormat("en-US", {maximumFractionDigits:1}).format(value)}%`;
const periodValid = value => /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
const txt = value => typeof value === "string" && value.trim().length > 0;
const pairRows = (data, period) => data.transactions.filter(r => r.month === period.from || r.month === period.to);
const financialKey = r => JSON.stringify([r.date,r.month,r.account,r.counterparty,r.segment,r.category,String(r.amount),r.currency || "USD"]);
export function fingerprint(data, through) {
  // This is a reproducibility key, not a security signature.
  const source = JSON.stringify({summaries:data.summaries.filter(r=>r.month<=through),transactions:data.transactions.filter(r=>r.month<=through),aliases:data.aliases || {}});
  let hash = 2166136261;
  for (let i=0;i<source.length;i++) hash = Math.imul(hash ^ source.charCodeAt(i),16777619);
  return (hash>>>0).toString(16);
}
export function prepare(data, period) {
  if (!periodValid(period.from) || !periodValid(period.to) || period.from >= period.to) throw new Error("Choose two distinct periods in chronological order");
  if (!Array.isArray(data.summaries) || !Array.isArray(data.transactions) || !data.summaries.length || !data.transactions.length) throw new Error("Both summaries and transaction evidence are required");
  const issues = [], quarantine = [], rows = [], summaries = [];
  const problem = (r, code, message) => issues.push({account:r.account || "*", month:r.month, id:r.id || "summary",code,message});
  // Malformed dates must not disappear simply because they cannot match the selected period.
  for (const r of [...data.summaries,...data.transactions]) {
    if (!periodValid(r.month) || !txt(r.account)) throw new Error("Every row needs a valid YYYY-MM period and account");
  }
  const source = pairRows(data,period);
  const conflicting = new Set();
  const byId = new Map();
  for (const r of source) {
    if (byId.has(r.id) && financialKey(byId.get(r.id)) !== financialKey(r)) conflicting.add(r.id);
    else byId.set(r.id,r);
  }
  const seen = new Set();
  for (const original of source) {
    const r = {...original};
    if (!txt(r.id) || !txt(r.counterparty) || !txt(r.category) || !txt(r.segment)) {problem(r,"schema","Required transaction fields are missing");continue;}
    const date = new Date(`${r.date}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(r.date) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0,10)!==r.date || r.date.slice(0,7)!==r.month) {problem(r,"date","Transaction date does not match its period");continue;}
    if ((r.currency || "USD") !== "USD") {problem(r,"currency","Non-USD evidence needs an explicit FX conversion");continue;}
    try { r.cents = cents(r.amount); } catch(error) {problem(r,"amount",error.message);continue;}
    if (conflicting.has(r.id)) {problem(r,"conflict","Conflicting versions of the same transaction ID");quarantine.push({...r,reason:"Conflicting ID"});continue;}
    if (r.status === "duplicate") {
      const originalRow = byId.get(r.duplicateOf);
      if (originalRow && originalRow.status === "posted" && financialKey(originalRow)===financialKey(r)) quarantine.push({...r,reason:`Confirmed duplicate of ${r.duplicateOf}`});
      else problem(r,"duplicate","Duplicate marker has no matching posted source");
      continue;
    }
    if (r.status !== "posted") {problem(r,"status","Unsupported posting status needs review");continue;}
    if (seen.has(r.id)) {quarantine.push({...r,reason:"Repeated identical transaction ID"});continue;}
    seen.add(r.id);
    const alias = data.aliases?.[r.counterparty];
    if (alias?.approved === true && txt(alias.canonical) && txt(alias.source)) {r.originalCounterparty=r.counterparty;r.counterparty=alias.canonical;}
    rows.push(r);
  }
  for (const r of data.summaries.filter(r=>r.month===period.from || r.month===period.to)) {
    if ((r.currency || "USD")!=="USD") {problem(r,"currency","Summary currency is not USD");continue;}
    try { summaries.push({...r,cents:cents(r.amount)}); } catch(error) {problem(r,"amount",error.message);}
  }
  const names = [...new Set([...summaries,...source].map(r=>r.account))];
  const accounts = names.map(account => {
    const evidence = rows.filter(r=>r.account===account);
    const ties = [period.from,period.to].map(month=>{
      const cells=summaries.filter(r=>r.account===account && r.month===month);
      const tx=evidence.filter(r=>r.month===month);
      const total=sum(tx.map(r=>r.cents));
      const expected=cells.length===1 ? cells[0].cents : null;
      const ok=cells.length===1 && tx.length>0 && total===expected;
      return {month,total,expected,ok,count:tx.length,gap:expected===null ? null : expected-total,reason:cells.length!==1?"Exactly one summary required":!tx.length?"No source rows":total!==expected?"Summary does not reconcile":"Reconciled"};
    });
    const previous=ties[0].expected,current=ties[1].expected;
    const delta=previous==null || current==null ? null : sum([current,-previous]);
    const percentage=previous===null || previous===0 || delta===null ? null : delta/Math.abs(previous)*100;
    const valid=ties.every(t=>t.ok) && !issues.some(i=>i.account===account || i.account==="*");
    const reclass=sum(evidence.filter(r=>r.category==="Reclass").map(r=>r.cents*(r.month===period.to?1:-1)));
    // Percentage swings cannot elevate a trivial dollar movement above a material one.
    const material=delta!==null && Math.abs(delta)>=1000000;
    const score=delta===null?0:Math.round(Math.min(Math.abs(delta)/20000000,1)*70 + (material ? Math.min(Math.abs(percentage || 0)/100,1)*30 : 0));
    return {account,previous,current,delta,percent:percentage,valid,ties,rows:evidence,reclass,material,score};
  }).sort((a,b)=>Number(b.material)-Number(a.material) || b.score-a.score || (a.account<b.account?-1:1));
  return {data,period,rows,accounts,issues,quarantine};
}
export function breakdown(state, account, dimension="counterparty") {
  const rows=state.rows.filter(r=>r.account===account);
  return [...new Set(rows.map(r=>r[dimension]))].map(name=>{
    const sources=rows.filter(r=>r[dimension]===name);
    const previous=sum(sources.filter(r=>r.month===state.period.from).map(r=>r.cents));
    const current=sum(sources.filter(r=>r.month===state.period.to).map(r=>r.cents));
    return {name,previous,current,delta:sum([current,-previous]),rows:sources};
  }).sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta) || a.name.localeCompare(b.name));
}
export function memoryState(data, period, saved=[]) {
  return [...(data.context || []),...saved].map(memory=>{
    let status="active", reason="Reviewer-approved context";
    if (!memory.approved || !txt(memory.source)) {status="unapproved";reason="Needs reviewer approval and source";}
    else if (!periodValid(memory.validFrom) || !periodValid(memory.validThrough) || memory.validFrom>period.to || memory.validThrough<period.to) {status="stale";reason="Outside its effective period";}
    else if (memory.kind==="finding" && (memory.reviewedPeriod>=period.to || memory.fingerprint!==fingerprint(data,memory.reviewedPeriod))) {status="stale";reason="Prior-period evidence changed, or finding is not from an earlier review";}
    return {...memory,status,reason};
  });
}
function baselineFor(memories,period) {
  const matches=memories.filter(m=>m.status==="active" && m.kind==="cloud-baseline" && m.expected?.[period.to]!==undefined);
  if (matches.length!==1) return null;
  try {return {...matches[0],cents:cents(matches[0].expected[period.to])};}catch{return null;}
}
export function propose(state) {
  const claims=[];
  for (const a of state.accounts) {
    claims.push({id:`${a.account}:movement`,account:a.account,type:"movement",asserted:a.delta,evidenceIds:a.rows.map(r=>r.id)});
    claims.push({id:`${a.account}:drivers`,account:a.account,type:"drivers",evidenceIds:a.rows.map(r=>r.id)});
  }
  const revenue=state.accounts.find(a=>a.account==="Revenue");
  if(revenue) claims.push(
    {id:"broad-growth",account:"Revenue",type:"broad-growth",evidenceIds:revenue.rows.map(r=>r.id)},
    {id:"pricing-cause",account:"Revenue",type:"causal",statement:"The new pricing caused the revenue increase.",evidenceIds:revenue.rows.map(r=>r.id)}
  );
  const cloud=state.accounts.find(a=>a.account==="Cloud Costs");
  if(cloud) claims.push(
    {id:"cloud-memory",account:"Cloud Costs",type:"cloud-context",evidenceIds:cloud.rows.map(r=>r.id)},
    {id:"cloud-exclusive",account:"Cloud Costs",type:"cloud-exclusive",evidenceIds:cloud.rows.map(r=>r.id)}
  );
  return claims;
}
export function judge(state, candidate, memories=[]) {
  const a=state.accounts.find(a=>a.account===candidate.account);
  const checks=[];
  const check=(name,pass,detail)=>checks.push({name,pass,detail});
  if(!a) return {...candidate,status:"blocked",title:"Unknown account",text:"No account evidence available.",checks:[],rows:[]};
  for(const tie of a.ties) check(`${tie.month} tie-out`,tie.ok,`${tie.reason}: ledger ${money(tie.total)}, summary ${money(tie.expected)}`);
  check("Input integrity",a.valid,a.valid?"Valid source rows and both summaries reconcile":"Unresolved input or reconciliation errors");
  const drivers=breakdown(state,a.account,a.account==="Operating Cash Flow"?"category":"counterparty");
  const decomposition=sum(drivers.map(d=>d.delta));
  check("Driver reconciliation",decomposition===a.delta,`${signed(decomposition)} in driver changes; ${signed(a.delta)} reported change`);
  const result={...candidate,title:"",text:"",status:"approved",checks,rows:a.rows,drivers,formula:`${money(a.current)} - ${money(a.previous)} = ${signed(a.delta)}`,account:a.account};
  if(!checks.every(c=>c.pass)) return {...result,status:"blocked",title:"Evidence incomplete",text:`${a.account}: explanation withheld until the source data reconciles.`};
  const evidenceIds=Array.isArray(candidate.evidenceIds)?candidate.evidenceIds:[];
  const exact=evidenceIds.length===a.rows.length && new Set(evidenceIds).size===a.rows.length && a.rows.every(r=>evidenceIds.includes(r.id));
  check("Complete citations",exact,exact?"Both periods are represented by the complete source set":"Missing, extra, or repeated source citations");
  if(!exact) return {...result,status:"rejected",title:"Citation check failed",text:"The proposed evidence does not support the full comparison."};
  const direction=a.delta>0?"increased":a.delta<0?"decreased":"was unchanged";
  if(candidate.type==="movement") {
    check("Claim arithmetic",candidate.asserted===a.delta,`Proposed ${signed(candidate.asserted)}; recomputed ${signed(a.delta)}`);
    result.status=candidate.asserted===a.delta?"approved":"rejected";
    result.title=result.status==="approved"?"Account movement verified":"Incorrect amount rejected";
    result.text=`${a.account} ${direction}${a.delta===0?"":` by ${money(Math.abs(a.delta))}`} (${a.previous===0?"no percentage: zero baseline":percent(a.percent)}) from ${money(a.previous)} to ${money(a.current)}.`;
    if(result.status==="rejected") result.text=`Proposed ${signed(candidate.asserted)}; source-supported movement is ${signed(a.delta)}.`;
  } else if(candidate.type==="drivers") {
    result.title="Driver decomposition verified";
    const top=drivers.filter(d=>d.delta!==0).slice(0,3);
    const remainder=sum([a.delta,-sum(top.map(d=>d.delta))]);
    result.text=top.length?`${top.map(d=>`${d.name} ${signed(d.delta)}`).join("; ")}. Remaining drivers: ${signed(remainder)}.`:"No net movement in any grouped driver.";
    if(a.reclass!==0) result.text+=` Includes ${signed(a.reclass)} of reclassification; movement excluding reclassification is ${signed(sum([a.delta,-a.reclass]))}.`;
    result.formula=`${drivers.map(d=>`(${signed(d.delta)})`).join(" + ")} = ${signed(a.delta)}`;
  } else if(candidate.type==="broad-growth") {
    const positives=drivers.filter(d=>d.delta>0).sort((a,b)=>b.delta-a.delta);
    const positiveTotal=sum(positives.map(d=>d.delta));
    const top=sum(positives.slice(0,3).map(d=>d.delta));
    const concentration=positiveTotal>0?top/positiveTotal*100:null;
    const passes=a.delta>0 && concentration!==null && concentration<40 && a.reclass===0;
    check("Growth concentration",passes,`Top three observed counterparties represent ${percent(concentration)} of gross positive movement; demo policy requires below 40%, positive net growth, and no reclassification.`);
    result.status=passes?"approved":"rejected";result.title=passes?"Growth breadth passes policy":"Broad-growth claim rejected";
    result.text=`Proposed: growth was broad-based. Top three observed counterparties contributed ${signed(top)} of ${signed(positiveTotal)} gross positive movement (${percent(concentration)}). Portfolio rows are aggregates, not individual customers.`;
    result.formula=`${money(top)} / ${money(positiveTotal)} = ${percent(concentration)} of positive movement`;
  } else if(candidate.type==="cloud-context" || candidate.type==="cloud-exclusive") {
    const baseline=baselineFor(memories,state.period);
    check("Memory provenance",!!baseline,baseline?`${baseline.source}; valid ${baseline.validFrom} through ${baseline.validThrough}`:"No unique, current, approved baseline is available");
    if(!baseline) return {...result,status:"blocked",title:"Memory cannot support this claim",text:"Cloud movement is measurable, but the baseline explanation is withheld."};
    const residual=sum([a.delta,-baseline.cents]);
    result.baseline=baseline;result.residual=residual;
    result.formula=`${signed(a.delta)} actual change - ${money(baseline.cents)} expected = ${signed(residual)} residual`;
    if(candidate.type==="cloud-exclusive") {
      check("Causal evidence",false,"Budget expectations cannot establish a cause, even if the residual is zero");
      result.status="rejected";result.title="Single-cause explanation rejected";result.text=`Proposed: migration explains all cloud growth. Residual versus the approved expectation is ${signed(residual)}; transactions alone do not establish the cause.`;
    } else {result.status="qualified";result.title="Expected cost separated from residual";result.text=`Cloud change is ${signed(a.delta)} against a reviewer-approved expectation of ${money(baseline.cents)}. The residual is ${signed(residual)}. The migration remains business context, not proven causation.`;}
  } else {
    check("Supported claim type",false,"Free-form causal assertions require additional evidence and human review");
    result.status="rejected";result.title="Unsupported causal claim rejected";result.text=candidate.statement || "Unrecognized claim withheld.";
  }
  return result;
}
export function investigate(data, period, saved=[], extraCandidates=[]) {
  const state=prepare(data,period);
  const memories=memoryState(data,period,saved);
  const claims=[...propose(state),...extraCandidates].map(c=>judge(state,c,memories));
  const publishable=claims.filter(c=>c.status==="approved" || c.status==="qualified");
  const recurring=memories.filter(m=>m.status==="active" && m.kind==="finding");
  const order=[...state.accounts].sort((a,b)=>Number(recurring.some(m=>m.account===b.account))-Number(recurring.some(m=>m.account===a.account)) || b.score-a.score);
  return {...state,memories,claims,publishable,coverage:publishable.length?100:null,rejected:claims.filter(c=>c.status==="rejected").length,blocked:claims.filter(c=>c.status==="blocked").length,order,
    trace:[{stage:"Normalize",detail:`${state.rows.length} posted rows accepted; ${state.quarantine.length} duplicates quarantined.`},{stage:"Reconcile",detail:`${state.accounts.filter(a=>a.valid).length}/${state.accounts.length} accounts tie in both periods.`},{stage:"Remember",detail:`${recurring.length} approved prior findings reused; ${memories.filter(m=>m.status!=="active").length} memory items withheld.`},{stage:"Investigate",detail:`Priority: ${order.map(a=>a.account).join(", ")}.`},{stage:"Judge",detail:`${publishable.length} publishable; ${claims.filter(c=>c.status==="rejected").length} rejected; ${claims.filter(c=>c.status==="blocked").length} blocked.`}]};
}
export function makeFinding(result,account) {
  const claim=result.claims.find(c=>c.account===account && c.type==="drivers" && c.status==="approved");
  if(!claim) throw new Error("Only verified driver findings can be saved");
  const year=Number(result.period.to.slice(0,4));
  return {id:`finding:${result.period.to}:${account}`,kind:"finding",account,title:`${account}: ${result.period.to} review`,detail:claim.text,source:`Reviewer-approved close ${result.period.to}`,approved:true,reviewedPeriod:result.period.to,validFrom:result.period.to,validThrough:`${year+1}-12`,fingerprint:fingerprint(result.data,result.period.to)};
}
