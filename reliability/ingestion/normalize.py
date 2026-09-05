"""Canonical input schema, and hardened parsing of it.

Ledger Lens accepts two files:

    monthly_summary.csv   period, account, amount            [+ section, currency]
    transactions.csv      transaction_id, date, period, account, amount,
                          counterparty, description
                          [+ segment, department, product, category, geography,
                             vendor, currency, section]

Everything the agent later reasons about comes through here. This module is
deliberately paranoid: amounts with currency symbols, thousands separators,
parentheses or unicode minus signs; four date formats; case and whitespace
variants of the same account or counterparty; unicode look-alike names. None of
that is allowed to silently become a financial fact. Anything that cannot be
parsed is recorded as a problem, never coerced.
"""

import csv
import re
import unicodedata
from collections import defaultdict
from datetime import datetime

REQUIRED_SUMMARY = ("period", "account", "amount")
REQUIRED_TXN = ("transaction_id", "date", "period", "account", "amount", "counterparty")
DIMENSIONS = ("counterparty", "segment", "department", "product", "category",
              "geography", "vendor", "customer")

_CURRENCY = re.compile(r"[$€£¥₹]|\b(USD|EUR|GBP|CAD|AUD|INR)\b", re.I)
_NUM = re.compile(r"^[+-]?\d+(\.\d+)?$")

SECTION_HINTS = (
    (re.compile(r"revenue|sales|income(?! tax)|subscription|fees? earned", re.I), "Revenue"),
    (re.compile(r"cogs|cost of (goods|sales|revenue)|direct cost", re.I), "COGS"),
)


def parse_amount(raw):
    """Return (value, problem). value is None when the field is unusable."""
    if raw is None:
        return None, "null amount"
    s = str(raw).strip()
    if s == "" or s.lower() in ("null", "none", "nan", "n/a", "-"):
        return None, "null amount"
    s = s.replace("−", "-").replace("–", "-")          # unicode minus / en dash
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.endswith("-"):
        neg, s = True, s[:-1]
    if s.endswith("CR") or s.endswith("cr"):
        neg, s = True, s[:-2]
    s = _CURRENCY.sub("", s).replace(",", "").replace(" ", "").strip()
    if s.startswith("-"):
        neg, s = (not neg), s[1:]
    if s.startswith("+"):
        s = s[1:]
    if not _NUM.match(s):
        return None, f"non-numeric amount {raw!r}"
    v = float(s)
    return (-v if neg else v), None


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y", "%d %b %Y",
                 "%B %d, %Y", "%Y%m%d", "%m-%d-%Y", "%d-%m-%Y")


def parse_date(raw):
    """Return (date, problem). Ambiguous day/month forms are flagged, not guessed."""
    if raw is None or str(raw).strip() == "":
        return None, "missing date"
    s = str(raw).strip()
    hits = []
    for fmt in _DATE_FORMATS:
        try:
            hits.append((fmt, datetime.strptime(s, fmt).date()))
        except ValueError:
            continue
    if not hits:
        return None, f"unparseable date {raw!r}"
    dates = {d for _, d in hits}
    if len(dates) > 1:
        # e.g. 03/04/2026 parses as both Mar 4 and Apr 3
        return min(dates), f"ambiguous date {raw!r} (day/month order)"
    return hits[0][1], None


_MONTHS = {m.lower(): i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def norm_period(raw):
    """Canonical YYYY-MM from '2026/08', '2026-8', '202608', 'Aug 2026', '08/2026'.

    Returns (period, problem). A period that cannot be read is a problem, not
    a guess -- a row booked to an unreadable period is excluded from every total.
    """
    if raw is None or str(raw).strip() == "":
        return None, "missing period"
    s = str(raw).strip()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{4})", s)
        if m:
            y, mo = int(m.group(2)), int(m.group(1))
        else:
            m = re.fullmatch(r"(\d{4})(\d{2})", s)
            if m:
                y, mo = int(m.group(1)), int(m.group(2))
            else:
                m = re.fullmatch(r"([A-Za-z]{3,9})\.?[ -]?(\d{4})", s) or re.fullmatch(r"(\d{4})[ -]([A-Za-z]{3,9})", s)
                if m:
                    a, b = m.group(1), m.group(2)
                    name, y = (a, int(b)) if a[0].isalpha() else (b, int(a))
                    mo = _MONTHS.get(name[:3].lower())
                    if not mo:
                        return None, f"unreadable period {raw!r}"
                else:
                    return None, f"unreadable period {raw!r}"
    if not 1 <= mo <= 12:
        return None, f"unreadable period {raw!r}"
    return f"{y:04d}-{mo:02d}", None


def norm_key(s):
    """Matching key for names: unicode-folded, case-folded, whitespace-collapsed."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s&]", " ", s)
    return re.sub(r"\s+", " ", s).strip().casefold()


def has_lookalike_chars(s):
    """Detect Cyrillic/Greek letters inside otherwise-Latin text -- a classic spoof."""
    if not s:
        return False
    scripts = set()
    for ch in s:
        if ch.isalpha():
            name = unicodedata.name(ch, "")
            scripts.add(name.split(" ")[0])
    return len(scripts & {"CYRILLIC", "GREEK"}) > 0 and "LATIN" in scripts


def infer_section(account, explicit=None):
    if explicit:
        e = explicit.strip().lower()
        if e.startswith("rev"):
            return "Revenue", False
        if e in ("cogs", "cost of sales", "cost of goods sold"):
            return "COGS", False
        if e.startswith("op") or e in ("expense", "expenses", "sg&a"):
            return "Opex", False
    for rx, sec in SECTION_HINTS:
        if rx.search(account or ""):
            return sec, True
    return "Opex", True


def read_csv(path):
    """Read rows, keeping malformed ones as problems instead of dropping them."""
    rows, problems = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return [], [{"row": 0, "problem": "empty file"}], []
        header = [h.strip().lower().replace(" ", "_") for h in header]
        for i, r in enumerate(reader, start=2):
            if not any(c.strip() for c in r):
                continue
            if len(r) != len(header):
                problems.append({"row": i, "problem": f"expected {len(header)} columns, got {len(r)}"})
                continue
            rows.append(dict(zip(header, (c.strip() for c in r))))
    return rows, problems, header


def load_simple(root):
    """Load the canonical schema into the internal transaction model.

    Returns (dataset_dict, parse_report). The report is consumed by the
    data-quality gate; nothing here decides whether the data is usable.
    """
    import os
    report = {"summary_rows_malformed": [], "txn_rows_malformed": [],
              "amount_problems": [], "date_problems": [], "missing_columns": {},
              "section_inferred_accounts": set(), "lookalike_names": [],
              "period_from_date": 0, "period_problems": []}

    s_rows, s_bad, s_hdr = read_csv(os.path.join(root, "monthly_summary.csv"))
    t_rows, t_bad, t_hdr = read_csv(os.path.join(root, "transactions.csv"))
    report["summary_rows_malformed"] = s_bad
    report["txn_rows_malformed"] = t_bad
    miss_s = [c for c in REQUIRED_SUMMARY if c not in s_hdr]
    miss_t = [c for c in REQUIRED_TXN if c not in t_hdr]
    if miss_s:
        report["missing_columns"]["monthly_summary.csv"] = miss_s
    if miss_t:
        report["missing_columns"]["transactions.csv"] = miss_t
    report["dimensions_available"] = [d for d in DIMENSIONS if d in t_hdr]

    acct_map = {}
    if os.path.exists(os.path.join(root, "accounts.csv")):
        for r in read_csv(os.path.join(root, "accounts.csv"))[0]:
            acct_map[norm_key(r.get("account") or r.get("gl_account_name"))] = \
                r.get("section") or r.get("statement_section")

    summary = []
    for r in s_rows:
        v, prob = parse_amount(r.get("amount"))
        if prob:
            report["amount_problems"].append({"file": "monthly_summary.csv", "row": r, "problem": prob})
            continue
        sec, inferred = infer_section(r.get("account"),
                                      r.get("section") or acct_map.get(norm_key(r.get("account"))))
        if inferred:
            report["section_inferred_accounts"].add(r.get("account"))
        per, pprob = norm_period(r.get("period"))
        if pprob:
            report["period_problems"].append({"file": "monthly_summary.csv", "row": r, "problem": pprob})
            continue
        summary.append({"period": per, "account": r.get("account", "").strip(),
                        "account_key": norm_key(r.get("account")), "statement_section": sec,
                        "amount": v, "currency": (r.get("currency") or "").strip().upper()})

    txns = []
    for r in t_rows:
        v, prob = parse_amount(r.get("amount"))
        if prob:
            report["amount_problems"].append({"file": "transactions.csv", "row": r, "problem": prob})
        d, dprob = parse_date(r.get("date"))
        if dprob:
            report["date_problems"].append({"row": r, "problem": dprob})
        period, pprob = norm_period(r.get("period"))
        if not period and d:
            period = d.strftime("%Y-%m")
            report["period_from_date"] += 1
        elif pprob:
            report["period_problems"].append({"file": "transactions.csv", "row": r, "problem": pprob})
        sec, inferred = infer_section(r.get("account"),
                                      r.get("section") or acct_map.get(norm_key(r.get("account"))))
        if inferred:
            report["section_inferred_accounts"].add(r.get("account"))
        cp = (r.get("counterparty") or r.get("customer") or r.get("vendor") or "").strip()
        if has_lookalike_chars(cp) or has_lookalike_chars(r.get("account", "")):
            report["lookalike_names"].append({"transaction_id": r.get("transaction_id"),
                                              "counterparty": cp, "account": r.get("account")})
        txns.append({
            "txn_id": (r.get("transaction_id") or "").strip(),
            "date": d.isoformat() if d else (r.get("date") or ""),
            "date_ok": d is not None,
            "period": period or "",
            "gl_account": (r.get("account") or "").strip(),
            "gl_account_name": (r.get("account") or "").strip(),
            "account_key": norm_key(r.get("account")),
            "statement_section": sec,
            "counterparty_id": norm_key(cp),
            "counterparty_name": cp,
            "counterparty_type": "customer" if sec == "Revenue" else "vendor",
            "segment": (r.get("segment") or "").strip(),
            "department": (r.get("department") or "").strip(),
            "category": (r.get("category") or "").strip(),
            "product": (r.get("product") or "").strip(),
            "geography": (r.get("geography") or "").strip(),
            "currency": (r.get("currency") or "").strip().upper(),
            "description": (r.get("description") or "").strip(),
            "memo": (r.get("memo") or "").strip(),
            "sku": "", "quantity": "", "unit_price": "",
            "amount": v,
            "amount_ok": v is not None,
            "signed_amount": (v if sec == "Revenue" else -v) if v is not None else None,
        })
    report["section_inferred_accounts"] = sorted(report["section_inferred_accounts"])
    return {"summary": summary, "transactions": txns}, report


class SimpleDataset:
    """Same interface the engine expects, built from the canonical schema."""

    def __init__(self, root):
        data, self.parse_report = load_simple(root)
        self.root = root
        self.summary = data["summary"]
        self.transactions = [t for t in data["transactions"] if t["amount_ok"]]
        self.rejected_transactions = [t for t in data["transactions"] if not t["amount_ok"]]
        self.periods = sorted({t["period"] for t in self.transactions if t["period"]}
                              | {s["period"] for s in self.summary if s["period"]})
        self._by_period = defaultdict(list)
        for t in self.transactions:
            self._by_period[t["period"]].append(t)
        self.invoices = []
        self.dimensions = self.parse_report["dimensions_available"]

    def txns(self, period):
        return self._by_period.get(period, [])

    def prior(self, period, n=1):
        if period not in self.periods:
            return None
        i = self.periods.index(period)
        return self.periods[i - n] if i - n >= 0 else None

    def history_before(self, period):
        return [p for p in self.periods if p < period]
