"""Adapter: score the `main`-branch investigator (src/) with the reliability benchmark.

    python -m reliability.benchmark.evaluate --runner reliability.benchmark.adapters.main_v1:run
    python -m reliability.benchmark.evaluate --runner reliability.benchmark.adapters.main_v1:run_normalized

Two modes, deliberately:

  run             feeds the case files to src/ exactly as written. Hostile number
                  formats reach their pydantic loader untouched. If the loader
                  rejects the input, that is recorded as an abstention with a
                  LOADER_REJECTED flag -- an honest measurement of ingestion
                  robustness, not a crash.
  run_normalized  runs the reliability normalizer first, so the benchmark
                  measures the investigator's reasoning separately from parsing.

Nothing under src/ is modified. The prose in the RunResult is rendered by this
adapter from their structured output (AccountVariance, DriverContribution,
ClaimLineage), one sentence per structure, so the language checks measure what
their result actually contains and never invent behaviour on their behalf.
"""

import csv
import os
from datetime import date
from decimal import Decimal, InvalidOperation

from src.agent.investigator import Investigator
from src.agent.tools import FinancialTools
from src.evidence.lineage import EvidenceError, build_claim_lineage
from src.ingestion.models import AccountSummary, Transaction

try:                                   # present from main@33fea51 onwards
    from src.explanation.explainer import EvidenceBoundExplainer, UngroundedExplanationError
    from src.explanation.providers import TemplateExplanationProvider
    _provider = None
    if os.environ.get("MAIN_V1_LLM") == "1":
        # Score the product's REAL explainer path: its own OpenAI-compatible provider
        # pointed at GIDE (LEDGER_LENS_LLM_* in .env), with its own grounding checks.
        from reliability.agent.llm import _load_dotenv
        _load_dotenv()
        from src.explanation.providers import OpenAICompatibleProvider
        _provider = OpenAICompatibleProvider.from_env()
    _EXPLAINER = EvidenceBoundExplainer(_provider or TemplateExplanationProvider())
except Exception:                      # noqa: BLE001
    _EXPLAINER, UngroundedExplanationError = None, Exception

REVENUE_HINTS = ("revenue", "sales", "income")
ABS_THRESHOLD = Decimal("1000")
PCT_THRESHOLD = Decimal("0")


def _pdate(period):
    return date(int(period[:4]), int(period[5:7]), 1)


def _money(v):
    v = Decimal(v)
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _to_models(case_dir, normalized):
    """Case CSVs -> their pydantic models. Returns (summaries, txns, problems)."""
    problems = []
    if normalized:
        from reliability.ingestion.normalize import SimpleDataset
        ds = SimpleDataset(case_dir)
        s_rows = [{"period": s["period"], "account": s["account"], "amount": str(s["amount"])}
                  for s in ds.summary]
        t_rows = [{"transaction_id": t["txn_id"], "period": t["period"], "account": t["gl_account"],
                   "amount": str(t["amount"]), "counterparty": t["counterparty_name"],
                   "segment": t.get("segment") or None, "category": t.get("category") or None,
                   "department": t.get("department") or None, "product": t.get("product") or None,
                   "geography": t.get("geography") or None, "description": t.get("description") or None,
                   "section": t["statement_section"]}
                  for t in ds.transactions]
    else:
        s_rows = _read_csv(os.path.join(case_dir, "monthly_summary.csv"))
        t_rows = _read_csv(os.path.join(case_dir, "transactions.csv"))

    summaries, txns = [], []
    for r in s_rows:
        try:
            summaries.append(AccountSummary(period=_pdate(r["period"]), account=r["account"],
                                            amount=Decimal(str(r["amount"]))))
        except Exception as e:                            # noqa: BLE001
            problems.append(f"summary row rejected ({r.get('account')}, {r.get('period')}): {type(e).__name__}")
    for r in t_rows:
        acct = (r.get("account") or "").strip()
        is_rev = (r.get("section") == "Revenue") if r.get("section") else \
            any(h in acct.lower() for h in REVENUE_HINTS)
        cp = (r.get("counterparty") or "").strip() or None
        try:
            per = r.get("period") or (r.get("date") or "")[:7]
            txns.append(Transaction(
                transaction_id=r.get("transaction_id") or "",
                period=_pdate(per), account=acct, amount=Decimal(str(r.get("amount"))),
                customer=cp if is_rev else None, vendor=None if is_rev else cp,
                segment=(r.get("segment") or None), category=(r.get("category") or None),
                department=(r.get("department") or None), product=(r.get("product") or None),
                geography=(r.get("geography") or None), description=(r.get("description") or None)))
        except Exception as e:                            # noqa: BLE001
            problems.append(f"transaction {r.get('transaction_id')} rejected: {type(e).__name__}")
    return summaries, txns, problems


def _run(case_dir, period, prior_period, memory_path=None, normalized=False):
    summaries, txns, problems = _to_models(case_dir, normalized)
    flags = [{"code": "LOADER_REJECTED", "severity": "warning", "detail": p, "scope": {}} for p in problems]
    tool_calls = {"n": 0}

    if not summaries and not txns:
        return _abstain(period, prior_period, flags, "loader rejected every row")

    tools = FinancialTools(summaries, txns)
    _orig = tools.breakdown_by_dimension

    def counted(*a, **k):
        tool_calls["n"] += 1
        return _orig(*a, **k)
    tools.breakdown_by_dimension = counted

    inv = Investigator(tools)
    try:
        res = inv.investigate(_pdate(prior_period), _pdate(period), ABS_THRESHOLD, PCT_THRESHOLD)
    except Exception as e:                                # noqa: BLE001
        flags.append({"code": "INVESTIGATOR_ERROR", "severity": "blocker",
                      "detail": f"{type(e).__name__}: {e}", "scope": {}})
        return _abstain(period, prior_period, flags, f"investigator raised {type(e).__name__}")

    claims, sentences, material, unexplained = [], [], [], {}
    n = 0
    total_var = total_attr = Decimal(0)
    for ai in res.accounts:
        v = ai.variance
        n += 1
        pct = f" ({float(v.variance_pct):+.1f}%)" if v.variance_pct is not None else ""
        obs = (f"{v.account} moved from {_money(v.prior_amount)} to {_money(v.current_amount)}, "
               f"a change of {_money(v.variance)}{pct}.")
        cid = f"claim_{n:03d}"
        claims.append({"claim_id": cid, "claim": obs, "kind": "observation", "account": v.account,
                       "variance": float(v.variance), "driver_amount": None, "contribution_pct": None,
                       "drivers": [], "transaction_ids": ["summary"], "calculation":
                       f"{v.current_amount} - {v.prior_amount} = {v.variance}", "detector": None,
                       "confidence": 1.0, "supporting_priors": [], "verified": True,
                       "verification_note": "adapter-rendered from AccountVariance",
                       "numbers": [float(v.prior_amount), float(v.current_amount), float(v.variance)]
                       + ([float(v.variance_pct)] if v.variance_pct is not None else [])})
        sentences.append(f"{obs} [{cid}]")
        material.append({"account": v.account, "prior": float(v.prior_amount), "current": float(v.current_amount),
                         "variance": float(v.variance),
                         "variance_pct": float(v.variance_pct) if v.variance_pct is not None else None,
                         "materiality": "high", "score": None, "reason": ai.stop_decision.reason,
                         "historical_z": None, "components": None})
        total_var += abs(v.variance)

        try:
            lineage = build_claim_lineage(ai, txns)
        except EvidenceError as e:
            lineage = []
            flags.append({"code": "LINEAGE_ERROR", "severity": "warning", "detail": str(e),
                          "scope": {"account": v.account}})
        for cl in lineage:
            n += 1
            cid = f"claim_{n:03d}"
            calc = cl.calculation
            share = f", or {float(calc.contribution_pct):.0f}% of the movement" if calc.contribution_pct is not None else ""
            txt = f"By {cl.dimension}, {cl.driver} contributed {_money(calc.variance)} to {cl.account}{share}."
            claims.append({"claim_id": cid, "claim": txt, "kind": "attribution", "account": cl.account,
                           "variance": float(v.variance), "driver_amount": float(calc.variance),
                           "contribution_pct": float(calc.contribution_pct) if calc.contribution_pct is not None else None,
                           "drivers": [cl.driver], "transaction_ids": [t.transaction_id for t in cl.transactions],
                           "calculation": f"{calc.current_amount} - {calc.prior_amount} = {calc.variance}",
                           "detector": None, "confidence": 1.0, "supporting_priors": [], "verified": True,
                           "verification_note": "adapter-rendered from ClaimLineage",
                           "numbers": [float(calc.variance), float(calc.prior_amount), float(calc.current_amount)]
                           + ([float(calc.contribution_pct)] if calc.contribution_pct is not None else [])})
            sentences.append(f"{txt} [{cid}]")
        # Their memo, their words: prefer the product's own explainer when it runs.
        if _EXPLAINER is not None and lineage:
            try:
                ex = _EXPLAINER.explain(ai, lineage)
                n += 1
                cid = f"claim_{n:03d}"
                prose = f"{ex.headline} {ex.summary}".strip()
                claims.append({"claim_id": cid, "claim": prose, "kind": "explanation", "account": v.account,
                               "variance": float(v.variance), "driver_amount": None, "contribution_pct": None,
                               "drivers": [cl.driver for cl in lineage], "transaction_ids": ["summary"],
                               "calculation": None, "detector": f"explainer:{ex.provider}", "confidence": 1.0,
                               "supporting_priors": [], "verified": bool(ex.grounded),
                               "verification_note": "product explainer (grounded=%s)" % ex.grounded,
                               "numbers": []})
                sentences.append(f"{prose} [{cid}]")
            except UngroundedExplanationError as e:
                flags.append({"code": "EXPLAINER_REJECTED", "severity": "warning", "detail": str(e)[:200],
                              "scope": {"account": v.account}})
            except Exception as e:                        # noqa: BLE001
                flags.append({"code": "EXPLAINER_ERROR", "severity": "warning",
                              "detail": f"{type(e).__name__}: {e}"[:200], "scope": {"account": v.account}})
        cov = ai.stop_decision.coverage
        attributed = abs(v.variance) * cov
        total_attr += attributed
        unexplained[v.account] = float(abs(v.variance) - attributed)

    if not res.accounts:
        sentences.append("No accounts met the materiality thresholds.")

    attr_conf = float(total_attr / total_var) if total_var else 0.0
    overall = "high" if attr_conf >= 0.8 and not any(f["severity"] == "blocker" for f in flags) \
        else "medium" if attr_conf >= 0.5 else "low"
    return {
        "period": period, "prior_period": prior_period,
        "data_quality": {"passed": not any(f["severity"] == "blocker" for f in flags),
                         "data_confidence": 1.0 if not flags else 0.8, "flags": flags, "blocked_accounts": []},
        "material_variances": material, "not_investigated": [],
        "claims": claims, "narrative": " ".join(sentences),
        "confidence": {"data": 1.0, "attribution": round(attr_conf, 3), "context": 0.35,
                       "evidence_coverage_pct": 100.0 if claims else None,
                       "unexplained_amount": float(total_var - total_attr),
                       "unexplained_share": round(1 - attr_conf, 3) if total_var else None,
                       "contradictions": 0, "overall": overall,
                       "reasons": [f"{attr_conf:.0%} attributed (stop rule coverage)"]},
        "unexplained": unexplained, "memory_used": [], "memory_rejected": [], "contradictions": [],
        "abstained": False, "abstained_scope": [],
        "trace": {"tool_calls": tool_calls["n"], "runner": "src/ main v1"},
    }


def _abstain(period, prior_period, flags, why):
    txt = f"Ledger Lens (main v1) could not analyse this period: {why}."
    return {
        "period": period, "prior_period": prior_period,
        "data_quality": {"passed": False, "data_confidence": 0.0, "flags": flags, "blocked_accounts": []},
        "material_variances": [], "not_investigated": [],
        "claims": [{"claim_id": "claim_001", "claim": txt, "kind": "abstention", "account": None, "variance": None,
                    "driver_amount": None, "contribution_pct": None, "drivers": [], "transaction_ids": ["n/a"],
                    "calculation": None, "detector": "loader", "confidence": 1.0, "supporting_priors": [],
                    "verified": True, "verification_note": "", "numbers": []}],
        "narrative": f"{txt} [claim_001]",
        "confidence": {"data": 0.0, "attribution": 0.0, "context": 0.0, "evidence_coverage_pct": None,
                       "unexplained_amount": None, "unexplained_share": None, "contradictions": 0,
                       "overall": "low", "reasons": [why]},
        "unexplained": {}, "memory_used": [], "memory_rejected": [], "contradictions": [],
        "abstained": True, "abstained_scope": [], "trace": {"tool_calls": 0, "runner": "src/ main v1"},
    }


def run(case_dir, period, prior_period, memory_path=None):
    return _run(case_dir, period, prior_period, memory_path, normalized=False)


def run_normalized(case_dir, period, prior_period, memory_path=None):
    return _run(case_dir, period, prior_period, memory_path, normalized=True)
