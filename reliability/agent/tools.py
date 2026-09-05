"""The tool surface. The model may only learn financial facts through these.

Every tool is deterministic and returns evidence. The model cannot compute a
number; it can only ask for one and then explain it. This is the whole
anti-hallucination design: there is no path by which a figure in the narrative
was invented, because the model never had arithmetic to do.
"""

import json

from ..finance import detectors as D
from ..finance.metrics import expectation, expected_mom_pct, seasonal_index
from ..finance.variance import decompose, margin_bridge, margin_rate_bridge, pnl, variance

SPECS = [
    {"name": "get_pnl", "description": "Summary P&L for one period.",
     "input_schema": {"type": "object", "properties": {"period": {"type": "string"}},
                      "required": ["period"], "additionalProperties": False}},
    {"name": "get_variance", "description": "Headline movement between two periods.",
     "input_schema": {"type": "object",
                      "properties": {"from_period": {"type": "string"},
                                     "to_period": {"type": "string"}},
                      "required": ["from_period", "to_period"], "additionalProperties": False}},
    {"name": "decompose_change",
     "description": ("Exhaustively attribute a section's movement along one dimension. "
                     "Returns every member, the top movers, and concentration stats."),
     "input_schema": {"type": "object",
                      "properties": {"from_period": {"type": "string"},
                                     "to_period": {"type": "string"},
                                     "dimension": {"type": "string",
                                                   "enum": ["customer", "category", "segment",
                                                            "gl_account", "vendor", "sku"]},
                                     "section": {"type": "string",
                                                 "enum": ["Revenue", "COGS", "Opex"]}},
                      "required": ["from_period", "to_period", "dimension"],
                      "additionalProperties": False}},
    {"name": "get_margin_bridge",
     "description": ("Split the gross-margin PERCENT movement into mix and rate effects, "
                     "in basis points. Use this before blaming a supplier price increase."),
     "input_schema": {"type": "object",
                      "properties": {"from_period": {"type": "string"},
                                     "to_period": {"type": "string"}},
                      "required": ["from_period", "to_period"], "additionalProperties": False}},
    {"name": "get_expectation",
     "description": ("What this period SHOULD have been, from seasonality and trend in prior "
                     "periods only. Converts a delta into a surprise. Always call this before "
                     "calling a movement good or bad."),
     "input_schema": {"type": "object",
                      "properties": {"period": {"type": "string"},
                                     "metric": {"type": "string",
                                                "enum": ["revenue", "gross_profit", "opex",
                                                         "net_income"]}},
                      "required": ["period"], "additionalProperties": False}},
    {"name": "check_reclassification",
     "description": ("Test whether a cost movement is an accounting reclass rather than an "
                     "economic change: same counterparty, offsetting accounts, net-income neutral."),
     "input_schema": {"type": "object",
                      "properties": {"from_period": {"type": "string"},
                                     "to_period": {"type": "string"}},
                      "required": ["from_period", "to_period"], "additionalProperties": False}},
    {"name": "check_timing_shift",
     "description": ("Test whether growth is really the same order landing in a different month, "
                     "by comparing year-on-year in both periods and looking for an offset."),
     "input_schema": {"type": "object",
                      "properties": {"from_period": {"type": "string"},
                                     "to_period": {"type": "string"}},
                      "required": ["from_period", "to_period"], "additionalProperties": False}},
    {"name": "check_one_time_items",
     "description": "Find line items far outside their own account's history. Do not extrapolate these.",
     "input_schema": {"type": "object", "properties": {"period": {"type": "string"}},
                      "required": ["period"], "additionalProperties": False}},
    {"name": "check_silent_churn",
     "description": ("Find recurring revenue that STOPPED arriving. No transaction is created "
                     "when a customer stops buying, so this cannot be found by differencing "
                     "two periods. Always call this."),
     "input_schema": {"type": "object",
                      "properties": {"period": {"type": "string"},
                                     "lookback_months": {"type": "integer"}},
                      "required": ["period"], "additionalProperties": False}},
    {"name": "check_revenue_quality",
     "description": "Check whether customers whose revenue grew are actually paying on time.",
     "input_schema": {"type": "object", "properties": {"period": {"type": "string"}},
                      "required": ["period"], "additionalProperties": False}},
    {"name": "get_transactions",
     "description": ("Raw transaction rows, for citing evidence. Filter by period and optionally "
                     "counterparty, category, or GL account."),
     "input_schema": {"type": "object",
                      "properties": {"period": {"type": "string"},
                                     "counterparty": {"type": "string"},
                                     "category": {"type": "string"},
                                     "gl_account": {"type": "string"},
                                     "limit": {"type": "integer"}},
                      "required": ["period"], "additionalProperties": False}},
]


class Toolbox:
    """Executes tools and records every call, so a run is fully replayable."""

    def __init__(self, ds):
        self.ds = ds
        self.log = []

    def specs(self):
        return SPECS

    def call(self, name, args):
        fn = getattr(self, f"_{name}", None)
        if fn is None:
            result = {"error": f"unknown tool {name}"}
        else:
            try:
                result = fn(**args)
            except Exception as e:                        # noqa: BLE001
                result = {"error": f"{type(e).__name__}: {e}"}
        self.log.append({"tool": name, "args": args,
                         "result_bytes": len(json.dumps(result, default=str))})
        return result

    # -- implementations -----------------------------------------------------
    def _get_pnl(self, period):
        return pnl(self.ds, period)

    def _get_variance(self, from_period, to_period):
        return variance(self.ds, from_period, to_period)

    def _decompose_change(self, from_period, to_period, dimension, section="Revenue"):
        return decompose(self.ds, from_period, to_period, dimension, section)

    def _get_margin_bridge(self, from_period, to_period):
        return {"rate_bridge": margin_rate_bridge(self.ds, from_period, to_period),
                "profit_bridge": margin_bridge(self.ds, from_period, to_period)}

    def _get_expectation(self, period, metric="revenue"):
        e = expectation(self.ds, period, metric)
        if e.get("available"):
            e["seasonality_alone_implies_mom_pct"] = expected_mom_pct(self.ds, period, metric)
        return e

    def _check_reclassification(self, from_period, to_period):
        return {"findings": D.detect_reclass(self.ds, from_period, to_period)}

    def _check_timing_shift(self, from_period, to_period):
        return {"findings": D.detect_timing_shift(self.ds, from_period, to_period)}

    def _check_one_time_items(self, period):
        return {"findings": D.detect_one_time(self.ds, period)}

    def _check_silent_churn(self, period, lookback_months=3):
        f = D.detect_silent_churn(self.ds, period, lookback=lookback_months)
        return {"findings": f,
                "total_monthly_revenue_silent": round(
                    sum(x["avg_monthly_revenue"] for x in f), 2),
                "total_annualised": round(sum(x["annualised_run_rate_lost"] for x in f), 2)}

    def _check_revenue_quality(self, period):
        return {"findings": D.detect_ar_deterioration(self.ds, period)}

    def _get_transactions(self, period, counterparty=None, category=None,
                          gl_account=None, limit=25):
        rows = self.ds.txns(period)
        if counterparty:
            rows = [t for t in rows if counterparty.lower() in t["counterparty_name"].lower()]
        if category:
            rows = [t for t in rows if t["category"] == category]
        if gl_account:
            rows = [t for t in rows if t["gl_account"] == gl_account]
        rows = sorted(rows, key=lambda t: -abs(t["amount"]))[:min(limit, 60)]
        return {"count": len(rows),
                "rows": [{k: t[k] for k in ("txn_id", "date", "doc_id", "gl_account_name",
                                            "counterparty_name", "category", "description",
                                            "quantity", "amount", "memo")} for t in rows]}
