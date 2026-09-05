"""
Synthetic dataset generator for Tallgrass Supply Co.

A B2B commercial-kitchen equipment & supplies distributor, ~$18M revenue,
24 monthly periods (2024-09 .. 2026-08).

The data is engineered so that a naive single-period variance tool produces
CONFIDENTLY WRONG answers, and only an agent that (a) decomposes deterministically
and (b) carries learned priors across runs gets them right.

Planted structure -- see docs/DATASET_TRAPS.md for the full key.
  T1  Seasonality masks performance          (Nov-2025)
  T2  Timing artifact, not growth            (Sep/Oct-2025 Copper Fork stocking order)
  T3  Concentration inside healthy growth    (May-2026)
  T4  Margin: mix dominates, rate is a decoy (Mar-2026)
  T5  Accounting reclass, zero economics     (Jan-2026 freight Opex -> COGS)
  T6  Genuine one-time item                  (Jun-2026 legal settlement)
  T7  Slow persistent bleed, invisible/month (Mar..Aug-2026 refrigeration erosion)

Every figure in monthly_summary.csv is the exact sum of transactions.csv.
"""

import csv
import os
import random
from datetime import date, timedelta

SEED = 20260905
RNG = random.Random(SEED)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample")

# ----------------------------------------------------------------------------
# Calendar
# ----------------------------------------------------------------------------
PERIODS = []
_y, _m = 2024, 9
for _ in range(24):
    PERIODS.append(f"{_y:04d}-{_m:02d}")
    _m += 1
    if _m == 13:
        _m, _y = 1, _y + 1

P_INDEX = {p: i for i, p in enumerate(PERIODS)}

# Restaurants stock ahead of the holiday season and ahead of summer.
SEASON = {
    1: 0.82, 2: 0.86, 3: 0.96, 4: 1.05, 5: 1.12, 6: 1.08,
    7: 0.94, 8: 0.90, 9: 1.02, 10: 1.14, 11: 1.26, 12: 1.10,
}

BASE_MONTHLY_REVENUE = 1_430_000.0
ANNUAL_GROWTH = 1.09
MONTHLY_GROWTH = ANNUAL_GROWTH ** (1.0 / 12.0)

# ----------------------------------------------------------------------------
# Chart of accounts
# ----------------------------------------------------------------------------
ACCOUNTS = [
    ("4000", "Product Revenue", "Revenue"),
    ("4200", "Service & Installation Revenue", "Revenue"),
    ("4900", "Returns & Allowances", "Revenue"),
    ("5000", "Product COGS", "COGS"),
    ("5100", "Freight & Delivery (COGS)", "COGS"),
    ("5200", "Warehouse Labor", "COGS"),
    ("6000", "Salaries & Wages", "Opex"),
    ("6010", "Payroll Taxes & Benefits", "Opex"),
    ("6100", "Rent & Occupancy", "Opex"),
    ("6200", "Software & Subscriptions", "Opex"),
    ("6300", "Marketing & Advertising", "Opex"),
    ("6400", "Professional Fees", "Opex"),
    ("6500", "Outbound Freight", "Opex"),
    ("6600", "Insurance", "Opex"),
    ("6700", "Utilities", "Opex"),
    ("6800", "Travel & Entertainment", "Opex"),
    ("6900", "Other Operating Expense", "Opex"),
]
ACCT_NAME = {a: n for a, n, _ in ACCOUNTS}
ACCT_SECTION = {a: s for a, _, s in ACCOUNTS}

# ----------------------------------------------------------------------------
# Products. Equipment is LOW margin, consumables are HIGH margin -- so a mix
# shift toward big equipment orders quietly compresses blended gross margin.
# ----------------------------------------------------------------------------
CATEGORIES = {
    "Refrigeration":         dict(margin=0.24, lo=1200, hi=8200, qty=(1, 4)),
    "Cooking Equipment":     dict(margin=0.22, lo=900,  hi=6500, qty=(1, 4)),
    "Beverage Equipment":    dict(margin=0.26, lo=400,  hi=3500, qty=(1, 6)),
    "Smallwares":            dict(margin=0.41, lo=8,    hi=180,  qty=(6, 90)),
    "Disposables":           dict(margin=0.34, lo=15,   hi=90,   qty=(10, 140)),
    "Janitorial & Chemicals":dict(margin=0.38, lo=20,   hi=200,  qty=(5, 70)),
}

PRODUCT_NAMES = {
    "Refrigeration": ["Reach-In Refrigerator", "Undercounter Freezer", "Walk-In Cooler Panel",
                      "Blast Chiller", "Prep Table Refrigerator", "Merchandiser Cooler",
                      "Ice Machine", "Back Bar Cooler"],
    "Cooking Equipment": ["Six-Burner Range", "Convection Oven", "Countertop Griddle",
                          "Deep Fryer", "Salamander Broiler", "Combi Oven", "Induction Range",
                          "Conveyor Toaster"],
    "Beverage Equipment": ["Espresso Machine", "Bulk Coffee Brewer", "Soda Fountain Tower",
                           "Juice Dispenser", "Water Filtration Unit", "Draft Beer Cooler"],
    "Smallwares": ["Sauce Pan", "Sheet Pan", "Chef Knife", "Mixing Bowl Set", "Tongs",
                   "Hotel Pan", "Cutting Board", "Whisk", "Ladle", "Storage Container"],
    "Disposables": ["Takeout Container", "Napkin Case", "Paper Cup Sleeve", "Foil Roll",
                    "Glove Case", "Deli Paper", "Straw Case", "Portion Cup"],
    "Janitorial & Chemicals": ["Degreaser Concentrate", "Sanitizer Tablets", "Floor Cleaner",
                               "Dish Detergent", "Mop Head", "Trash Liner Case"],
}

PRODUCTS = []
_sku = 1000
for cat, spec in CATEGORIES.items():
    for nm in PRODUCT_NAMES[cat]:
        _sku += 1
        price = round(RNG.uniform(spec["lo"], spec["hi"]), 2)
        PRODUCTS.append(dict(
            sku=f"SKU-{_sku}", name=nm, category=cat,
            list_price=price, margin=spec["margin"],
        ))

BY_CAT = {}
for p in PRODUCTS:
    BY_CAT.setdefault(p["category"], []).append(p)

# A refrigeration line is worth ~100x a disposables line, so weighting category
# choice by the raw mix would let equipment dominate revenue. Divide by the
# average line value so the mix weights control DOLLAR share as intended.
AVG_LINE_VALUE = {}
for cat, spec in CATEGORIES.items():
    avg_price = sum(x["list_price"] for x in BY_CAT[cat]) / len(BY_CAT[cat])
    avg_qty = (spec["qty"][0] + spec["qty"][1]) / 2
    AVG_LINE_VALUE[cat] = avg_price * avg_qty

# ----------------------------------------------------------------------------
# Customers
# ----------------------------------------------------------------------------
SEGMENT_MIX = {
    "Restaurant Group":       {"Refrigeration": 0.20, "Cooking Equipment": 0.20, "Beverage Equipment": 0.10,
                               "Smallwares": 0.22, "Disposables": 0.18, "Janitorial & Chemicals": 0.10},
    "Independent Restaurant": {"Refrigeration": 0.16, "Cooking Equipment": 0.14, "Beverage Equipment": 0.08,
                               "Smallwares": 0.28, "Disposables": 0.22, "Janitorial & Chemicals": 0.12},
    "Institutional":          {"Refrigeration": 0.18, "Cooking Equipment": 0.16, "Beverage Equipment": 0.06,
                               "Smallwares": 0.20, "Disposables": 0.28, "Janitorial & Chemicals": 0.12},
    "Hotel & Hospitality":    {"Refrigeration": 0.15, "Cooking Equipment": 0.15, "Beverage Equipment": 0.18,
                               "Smallwares": 0.22, "Disposables": 0.18, "Janitorial & Chemicals": 0.12},
    "Distributor Resale":     {"Refrigeration": 0.22, "Cooking Equipment": 0.18, "Beverage Equipment": 0.10,
                               "Smallwares": 0.24, "Disposables": 0.20, "Janitorial & Chemicals": 0.06},
}

# Named accounts carry the planted narrative.
NAMED = [
    ("CUST-001", "Copper Fork Group",        "Restaurant Group",       0.062, "Net 45"),
    ("CUST-002", "Harborline Hospitality",   "Hotel & Hospitality",    0.048, "Net 30"),
    ("CUST-003", "Vaughn & Sons Restaurant Co", "Restaurant Group",    0.044, "Net 45"),
    ("CUST-004", "Meridian Public Schools",  "Institutional",          0.039, "Net 60"),
    ("CUST-005", "Bright Harbor Hotels",     "Hotel & Hospitality",    0.035, "Net 30"),
    ("CUST-006", "Ridgeline Kitchens Group", "Restaurant Group",       0.031, "Net 30"),
    ("CUST-007", "Ashgrove Dining Partners", "Restaurant Group",       0.028, "Net 45"),
    ("CUST-008", "Northfield Medical Center","Institutional",          0.026, "Net 60"),
    ("CUST-009", "Stonecrest Resale Supply", "Distributor Resale",     0.025, "Net 30"),
    ("CUST-010", "Lakeside Catering Co",     "Independent Restaurant", 0.022, "Net 30"),
]

_first = ["Old", "Birch", "Cedar", "Rowan", "Alder", "Quarry", "Hollow", "Pine", "Marlow",
          "Bramble", "Kestrel", "Foxglove", "Dunmore", "Selby", "Ashford", "Wexley",
          "Thornbury", "Calder", "Marbury", "Ellery", "Ravensworth", "Gilman", "Hartwell",
          "Ivybridge", "Pelham", "Sutton", "Weldon", "Camberly", "Fairhaven", "Ludlow",
          "Brackley", "Norwood", "Ockham", "Pendry", "Rushmoor", "Tarleton"]
_last = ["Kitchen", "Tavern", "Grill", "Bistro", "Provisions", "Hospitality Group",
         "Dining Co", "Public House", "Eatery", "Food Hall"]

CUSTOMERS = []
for cid, nm, seg, share, terms in NAMED:
    CUSTOMERS.append(dict(id=cid, name=nm, segment=seg, share=share, terms=terms))

_n = 10
_remaining = 1.0 - sum(c["share"] for c in CUSTOMERS)
_others = []
for i in range(36):
    _n += 1
    seg = RNG.choices(
        ["Independent Restaurant", "Restaurant Group", "Institutional",
         "Hotel & Hospitality", "Distributor Resale"],
        weights=[0.46, 0.16, 0.14, 0.14, 0.10])[0]
    _others.append(dict(
        id=f"CUST-{_n:03d}",
        name=f"{RNG.choice(_first)} {RNG.choice(_last)}",
        segment=seg,
        share=RNG.uniform(0.4, 1.6),
        terms=RNG.choice(["Net 30", "Net 30", "Net 45", "Net 15"]),
    ))
_tot = sum(c["share"] for c in _others)
for c in _others:
    c["share"] = c["share"] / _tot * _remaining
CUSTOMERS.extend(_others)
CUST_BY_ID = {c["id"]: c for c in CUSTOMERS}

# Baseline payment behaviour (days late vs terms). T3 makes Ridgeline deteriorate.
for c in CUSTOMERS:
    c["base_late"] = RNG.uniform(-2, 9) if c["segment"] != "Institutional" else RNG.uniform(4, 18)

# ----------------------------------------------------------------------------
# Vendors
# ----------------------------------------------------------------------------
VENDORS = [
    ("VEND-001", "Northline Cold Systems",   "Refrigeration"),
    ("VEND-002", "Kettleworks Manufacturing","Cooking Equipment"),
    ("VEND-003", "Aurelio Beverage Systems", "Beverage Equipment"),
    ("VEND-004", "Halverson Smallwares",     "Smallwares"),
    ("VEND-005", "Pinepoint Paper & Pack",   "Disposables"),
    ("VEND-006", "Clearline Chemical Co",    "Janitorial & Chemicals"),
    ("VEND-014", "Pacific Freight Partners", "Freight"),
]
VENDOR_FOR_CAT = {c: v[0] for v in VENDORS for c in [v[2]]}
VENDOR_NAME = {v[0]: v[1] for v in VENDORS}

OPEX_VENDORS = {
    "6000": ("VEND-020", "Payroll (internal)"),
    "6010": ("VEND-020", "Payroll (internal)"),
    "6100": ("VEND-021", "Granby Industrial Properties"),
    "6200": ("VEND-022", "Assorted SaaS Vendors"),
    "6300": ("VEND-023", "Fieldmark Marketing"),
    "6400": ("VEND-024", "Bellweather Legal LLP"),
    "6500": ("VEND-014", "Pacific Freight Partners"),
    "5100": ("VEND-014", "Pacific Freight Partners"),
    "6600": ("VEND-025", "Corvus Insurance Group"),
    "6700": ("VEND-026", "Regional Utilities Authority"),
    "6800": ("VEND-027", "Corporate Travel Desk"),
    "6900": ("VEND-028", "Miscellaneous Vendors"),
}

# ----------------------------------------------------------------------------
# PLANTED EFFECTS
# ----------------------------------------------------------------------------

# T5 -- outbound freight reclassified from Opex 6500 into COGS 5100 in Jan-2026.
FREIGHT_RECLASS_PERIOD = "2026-01"

# T7 -- SILENT CHURN. Seven steady refrigeration accounts quietly stop buying
#       refrigeration, one per month from Mar-2026, lost to a competitor.
#       Each month's incremental loss is ~1% of revenue -- far too small to ever
#       top a variance report -- but it compounds to a six-figure run-rate.
#       Critically this is a pattern of ABSENCE: no transaction is created, so
#       no single-period diff can see it. Only an agent holding a prior about
#       who normally buys what will notice the silence.
#       Each of these accounts runs a monthly refrigeration replacement program
#       -- a steady, boring, every-single-month line item -- until it silently
#       stops. The absence of a recurring order is the entire signal.
REFRIG_CHURN = {}
REFRIG_STANDING = {}
_churn_pool = sorted(c["id"] for c in CUSTOMERS
                     if c["segment"] in ("Independent Restaurant", "Hotel & Hospitality",
                                         "Distributor Resale")
                     and c["id"] not in ("CUST-002", "CUST-005"))
RNG.shuffle(_churn_pool)
for _i, _cid in enumerate(_churn_pool[:7]):
    REFRIG_CHURN[_cid] = PERIODS[17 + _i]        # 2026-02 .. 2026-08, one per month
    REFRIG_STANDING[_cid] = RNG.uniform(17_000, 26_000)

# T4 -- Northline raises refrigeration cost 4% effective Feb-2026 (the decoy).
COST_INFLATION = {p: (1.04 if p >= "2026-02" else 1.0) for p in PERIODS}

# T2 -- Copper Fork annual pre-season stocking order. Landed Sep in FY24,
#       slipped to Oct in FY25. Pure timing, reads as growth.
STOCKING_ORDER = {"2024-09": 620_000.0, "2025-10": 655_000.0}

# T4 -- Vaughn & Sons equipment buildout in Mar-2026 swings mix to low margin.
BUILDOUT = {"2026-03": ("CUST-003", 470_000.0)}

# T3 -- May-2026 growth concentrated in three accounts.
CONCENTRATION = {"2026-05": {"CUST-006": 152_000.0, "CUST-002": 106_000.0, "CUST-007": 79_000.0}}

# T6 -- one-time legal settlement.
ONE_TIME_OPEX = {("2026-06", "6400"): (95_000.0, "Settlement - Ridgeline contract dispute")}

# T3 -- Ridgeline payment behaviour deteriorates alongside its growth.
RIDGELINE_LATE = {"2026-02": 6, "2026-03": 13, "2026-04": 21, "2026-05": 31,
                  "2026-06": 38, "2026-07": 44, "2026-08": 49}


def month_days(period):
    y, m = int(period[:4]), int(period[5:])
    nm_y, nm_m = (y + 1, 1) if m == 12 else (y, m + 1)
    return (date(nm_y, nm_m, 1) - date(y, m, 1)).days


def rand_day(period):
    return date(int(period[:4]), int(period[5:]), RNG.randint(1, month_days(period)))


txns = []
invoices = []
_tid = 0
_doc = 0


def add(period, dt, doc_type, doc_id, acct, cp_id, cp_name, cp_type, segment,
        category, sku, desc, qty, unit_price, amount, memo=""):
    global _tid
    _tid += 1
    section = ACCT_SECTION[acct]
    sign = 1.0 if section == "Revenue" else -1.0
    txns.append(dict(
        txn_id=f"TXN-{_tid:07d}",
        date=dt.isoformat(),
        period=period,
        doc_type=doc_type,
        doc_id=doc_id,
        gl_account=acct,
        gl_account_name=ACCT_NAME[acct],
        statement_section=section,
        counterparty_id=cp_id,
        counterparty_name=cp_name,
        counterparty_type=cp_type,
        segment=segment,
        category=category,
        sku=sku,
        description=desc,
        quantity=qty,
        unit_price=round(unit_price, 4) if unit_price else "",
        amount=round(amount, 2),
        signed_amount=round(sign * amount, 2),
        memo=memo,
    ))


def make_order(period, cust, budget, force_category=None, memo=""):
    """Emit one sales order: revenue lines + matched COGS lines + an AR invoice."""
    global _doc
    _doc += 1
    doc_id = f"SO-{period.replace('-', '')}-{_doc:05d}"
    dt = rand_day(period)
    mix = SEGMENT_MIX[cust["segment"]]
    spent = 0.0
    lines = 0
    guard = 0
    while spent < budget and guard < 60:
        guard += 1
        if force_category:
            cat = force_category
        else:
            cats = list(mix.keys())
            w = []
            for c in cats:
                weight = mix[c] / AVG_LINE_VALUE[c]
                if c == "Refrigeration":
                    stop = REFRIG_CHURN.get(cust["id"])
                    if stop and period >= stop:
                        weight = 0.0          # T7: this account went silent
                w.append(weight)
            if sum(w) == 0:
                continue
            cat = RNG.choices(cats, weights=w)[0]
        prod = RNG.choice(BY_CAT[cat])
        qlo, qhi = CATEGORIES[cat]["qty"]
        qty = RNG.randint(qlo, qhi)
        price = prod["list_price"] * RNG.uniform(0.93, 1.06)
        amt = qty * price
        if amt > budget * 1.9 and lines > 0:
            continue
        cost_mult = COST_INFLATION[period] if cat == "Refrigeration" else 1.0
        cost = amt * (1 - prod["margin"]) * cost_mult * RNG.uniform(0.985, 1.015)

        add(period, dt, "INVOICE", doc_id, "4000", cust["id"], cust["name"], "customer",
            cust["segment"], cat, prod["sku"], prod["name"], qty, price, amt, memo)
        vid = VENDOR_FOR_CAT[cat]
        add(period, dt, "INVOICE", doc_id, "5000", vid, VENDOR_NAME[vid], "vendor",
            cust["segment"], cat, prod["sku"], f"COGS - {prod['name']}", qty,
            cost / qty, cost, memo)
        spent += amt
        lines += 1

    if lines == 0:
        return 0.0

    terms_days = int(cust["terms"].split()[1])
    due = dt + timedelta(days=terms_days)
    if cust["id"] == "CUST-006" and period in RIDGELINE_LATE:
        late = RIDGELINE_LATE[period] + RNG.randint(-3, 3)
    else:
        late = cust["base_late"] + RNG.uniform(-4, 6)
    paid = due + timedelta(days=int(round(late)))
    invoices.append(dict(
        invoice_id=doc_id, customer_id=cust["id"], customer_name=cust["name"],
        segment=cust["segment"], issue_date=dt.isoformat(), terms=cust["terms"],
        due_date=due.isoformat(), amount=round(spent, 2),
        paid_date=paid.isoformat() if paid <= date(2026, 9, 30) else "",
        days_late=int(round(late)),
    ))
    return spent


def build():
    for period in PERIODS:
        t = P_INDEX[period]
        m = int(period[5:])
        target = (BASE_MONTHLY_REVENUE * (MONTHLY_GROWTH ** t)
                  * SEASON[m] * RNG.uniform(0.975, 1.025))

        revenue = 0.0
        for cust in CUSTOMERS:
            budget = target * cust["share"] * RNG.uniform(0.80, 1.24)
            # Institutions buy ahead of the school year.
            if cust["segment"] == "Institutional" and m in (7, 8):
                budget *= 1.9
            if cust["id"] == "CUST-001" and period == "2025-09":
                budget *= 0.35          # T2: the stocking order did not land
            if period in CONCENTRATION and cust["id"] in CONCENTRATION[period]:
                budget += CONCENTRATION[period][cust["id"]]   # T3
            if budget > 500:
                revenue += make_order(period, cust, budget)

        # T7 -- monthly refrigeration replacement programs, until each goes silent
        for cid, standing in REFRIG_STANDING.items():
            if period < REFRIG_CHURN[cid]:
                revenue += make_order(period, CUST_BY_ID[cid],
                                      standing * RNG.uniform(0.92, 1.08),
                                      "Refrigeration",
                                      memo="Refrigeration replacement program")

        # T2 -- annual pre-season stocking order
        if period in STOCKING_ORDER:
            revenue += make_order(period, CUST_BY_ID["CUST-001"], STOCKING_ORDER[period],
                                  memo="Annual pre-season stocking order")
        # T4 -- equipment buildout swings mix toward low-margin categories
        if period in BUILDOUT:
            cid, amt = BUILDOUT[period]
            half = amt / 2
            revenue += make_order(period, CUST_BY_ID[cid], half, "Refrigeration",
                                  memo="Buildout - 4 new locations")
            revenue += make_order(period, CUST_BY_ID[cid], half, "Cooking Equipment",
                                  memo="Buildout - 4 new locations")

        dt_end = date(int(period[:4]), m, month_days(period))

        # Service & installation revenue tracks equipment volume
        equip = sum(x["amount"] for x in txns
                    if x["period"] == period and x["gl_account"] == "4000"
                    and x["category"] in ("Refrigeration", "Cooking Equipment", "Beverage Equipment"))
        add(period, dt_end, "JOURNAL", f"JE-{period}-SVC", "4200", "", "Various", "customer",
            "", "Service", "", "Installation & service revenue", "", "",
            equip * RNG.uniform(0.055, 0.075))

        # Returns & allowances (contra revenue, stored negative)
        add(period, dt_end, "JOURNAL", f"JE-{period}-RET", "4900", "", "Various", "customer",
            "", "Returns", "", "Returns & allowances", "", "",
            -revenue * RNG.uniform(0.008, 0.016))

        # ---- Freight: T5 reclass from Opex 6500 to COGS 5100 in Jan-2026 ----
        freight = revenue * RNG.uniform(0.052, 0.058)
        f_acct = "5100" if period >= FREIGHT_RECLASS_PERIOD else "6500"
        f_memo = ("Reclassified from 6500 Outbound Freight per Jan-2026 accounting policy change"
                  if period >= FREIGHT_RECLASS_PERIOD else "")
        vid, vname = OPEX_VENDORS[f_acct]
        add(period, dt_end, "BILL", f"BILL-{period}-FRT", f_acct, vid, vname, "vendor",
            "", "Freight", "", "Freight & delivery", "", "", freight, f_memo)

        # Warehouse labor
        add(period, dt_end, "JOURNAL", f"JE-{period}-WHL", "5200", "VEND-020", "Payroll (internal)",
            "vendor", "", "Labor", "", "Warehouse labor", "", "",
            revenue * RNG.uniform(0.028, 0.033))

        # ---- Opex ----
        headcount_step = 1.0 + 0.05 * (t // 8)          # two hiring waves over 24 months
        salaries = 158_000 * headcount_step * RNG.uniform(0.99, 1.01)
        opex = {
            "6000": salaries,
            "6010": salaries * RNG.uniform(0.25, 0.28),
            "6100": 42_500 * (1.03 if period >= "2026-01" else 1.0),
            "6200": 15_800 * (1 + 0.012 * t) * RNG.uniform(0.97, 1.03),
            "6300": revenue * RNG.uniform(0.018, 0.027),
            "6400": RNG.uniform(8_500, 14_000),
            "6600": 11_200,
            "6700": RNG.uniform(6_100, 9_400) * (1.15 if m in (7, 8, 12, 1) else 1.0),
            "6800": RNG.uniform(7_000, 19_000),
            "6900": RNG.uniform(3_000, 8_000),
        }
        for acct, amt in opex.items():
            memo = ""
            key = (period, acct)
            if key in ONE_TIME_OPEX:                    # T6
                extra, memo = ONE_TIME_OPEX[key]
                amt += extra
            vid, vname = OPEX_VENDORS[acct]
            add(period, dt_end, "BILL", f"BILL-{period}-{acct}", acct, vid, vname, "vendor",
                "", "Operating", "", ACCT_NAME[acct], "", "", amt, memo)


def write():
    os.makedirs(OUT, exist_ok=True)

    with open(f"{OUT}/transactions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(txns[0].keys()))
        w.writeheader()
        w.writerows(txns)

    summary = {}
    for x in txns:
        k = (x["period"], x["gl_account"])
        summary[k] = summary.get(k, 0.0) + x["amount"]
    with open(f"{OUT}/monthly_summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period", "gl_account", "gl_account_name", "statement_section",
                    "amount", "signed_amount"])
        for p in PERIODS:
            for acct, name, sec in ACCOUNTS:
                if (p, acct) in summary:
                    amt = round(summary[(p, acct)], 2)
                    sign = 1.0 if sec == "Revenue" else -1.0
                    w.writerow([p, acct, name, sec, amt, round(sign * amt, 2)])

    with open(f"{OUT}/customers.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "customer_name", "segment", "payment_terms"])
        for c in CUSTOMERS:
            w.writerow([c["id"], c["name"], c["segment"], c["terms"]])

    with open(f"{OUT}/products.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku", "product_name", "category", "list_price"])
        for p in PRODUCTS:
            w.writerow([p["sku"], p["name"], p["category"], p["list_price"]])

    with open(f"{OUT}/ar_invoices.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(invoices[0].keys()))
        w.writeheader()
        w.writerows(invoices)

    with open(f"{OUT}/accounts.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gl_account", "gl_account_name", "statement_section"])
        for a, n, s in ACCOUNTS:
            w.writerow([a, n, s])


if __name__ == "__main__":
    build()
    write()
    rev = {}
    for x in txns:
        if x["statement_section"] == "Revenue":
            rev[x["period"]] = rev.get(x["period"], 0) + x["amount"]
    print(f"transactions : {len(txns):,}")
    print(f"ar invoices  : {len(invoices):,}")
    print(f"periods      : {PERIODS[0]} .. {PERIODS[-1]}")
    print(f"revenue FY26 : ${sum(v for k, v in rev.items() if k >= '2025-09'):,.0f}")
    print(f"written to   : {OUT}")
