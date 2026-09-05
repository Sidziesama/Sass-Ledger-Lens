"""Load and validate the financial dataset. Pure stdlib: no install risk, runs offline."""

import csv
import os
from collections import defaultdict

NUM = ("quantity", "unit_price", "amount", "signed_amount")


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return v


class Dataset:
    def __init__(self, root):
        self.root = root
        self.transactions = self._csv("transactions.csv", NUM)
        self.summary = self._csv("monthly_summary.csv", ("amount", "signed_amount"))
        self.customers = self._csv("customers.csv", ())
        self.products = self._csv("products.csv", ("list_price",))
        self.invoices = self._csv("ar_invoices.csv", ("amount", "days_late"))
        self.accounts = self._csv("accounts.csv", ())
        self.periods = sorted({t["period"] for t in self.transactions})
        self._by_period = defaultdict(list)
        for t in self.transactions:
            self._by_period[t["period"]].append(t)

    def _csv(self, name, numeric):
        path = os.path.join(self.root, name)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            for k in numeric:
                if k in r:
                    r[k] = _num(r[k])
        return rows

    def txns(self, period):
        return self._by_period[period]

    def prior(self, period, n=1):
        """The period n steps before `period`, or None."""
        i = self.periods.index(period)
        return self.periods[i - n] if i - n >= 0 else None

    def history_before(self, period):
        return [p for p in self.periods if p < period]

    # -- validation ----------------------------------------------------------
    def validate(self):
        """Prove monthly_summary is exactly the sum of transactions. If this
        fails, every downstream number is untrustworthy and the agent must say so."""
        from_txn = defaultdict(float)
        for t in self.transactions:
            from_txn[(t["period"], t["gl_account"])] += t["amount"]
        issues = []
        for r in self.summary:
            k = (r["period"], r["gl_account"])
            diff = round(r["amount"] - from_txn.get(k, 0.0), 2)
            if abs(diff) > 0.05:
                issues.append({"period": r["period"], "gl_account": r["gl_account"],
                               "summary": r["amount"], "transactions": from_txn.get(k, 0.0),
                               "difference": diff})
        return {
            "reconciled": not issues,
            "periods": len(self.periods),
            "transactions": len(self.transactions),
            "summary_rows": len(self.summary),
            "issues": issues,
        }


def load(root=None):
    if root is None:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        root = os.path.join(here, "data", "synthetic")
    return Dataset(root)
