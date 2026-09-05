"""Generate the benchmark cases. Each case is a small CSV pair plus ground truth.

    python -m reliability.benchmark.make_cases

The cases are built to BREAK a variance agent in specific, named ways. Every
one has a plausible wrong answer. See the spec's §7, §8, §13.
"""

import csv
import json
import os
import random
import shutil

from .schema import new_case, new_sequence
from ..memory.store import PriorStore

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cases")
RNG = random.Random(7)
JUL, AUG = "2026-07", "2026-08"


def T(i, date, account, amount, cp, **d):
    row = {"transaction_id": i, "date": date, "period": d.pop("period", date[:7]), "account": account,
           "amount": amount, "counterparty": cp, "description": d.pop("description", "")}
    row.update(d)
    return row


def write(case, txns, summary=None, memory=None, policy=None, raw_txn_rows=None, drop_cols=()):
    d = os.path.join(OUT, case["id"])
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    cols = ["transaction_id", "date", "period", "account", "amount", "counterparty", "description"]
    for t in txns:
        for k in t:
            if k not in cols:
                cols.append(k)
    cols = [c for c in cols if c not in drop_cols]
    with open(os.path.join(d, "transactions.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for t in txns:
            w.writerow({k: t.get(k, "") for k in cols})
        if raw_txn_rows:
            f.write("\n".join(raw_txn_rows) + "\n")
    if summary is None:
        agg = {}
        for t in txns:
            if isinstance(t["amount"], (int, float)):
                agg[(t["period"], t["account"])] = agg.get((t["period"], t["account"]), 0) + t["amount"]
        summary = [{"period": p, "account": a, "amount": round(v, 2)} for (p, a), v in sorted(agg.items())]
    with open(os.path.join(d, "monthly_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["period", "account", "amount"]); w.writeheader(); w.writerows(summary)
    seq = case.pop("sequence", None)
    with open(os.path.join(d, "case.json"), "w") as f:
        json.dump(case, f, indent=2)
    if seq:
        with open(os.path.join(d, "sequence.json"), "w") as f:
            json.dump(seq, f, indent=2)
    if memory:
        memory.path = os.path.join(d, "memory.json"); memory.save()
    if policy:
        json.dump(policy, open(os.path.join(d, "policy.json"), "w"))
    return d


def base_month(period, rev_custs, rev_total, opex, seq):
    """A boring month: revenue over customers, fixed opex lines."""
    rows = []
    n = len(rev_custs)
    for i, c in enumerate(rev_custs):
        amt = round(rev_total / n * RNG.uniform(0.98, 1.02), 2)
        rows.append(T(f"R{period[-2:]}{seq}{i:03d}", f"{period}-{RNG.randint(2, 27):02d}", "Revenue", amt, c,
                      segment="Enterprise" if i < n // 2 else "SMB", description="subscription"))
    for j, (acct, amt, vend) in enumerate(opex):
        rows.append(T(f"O{period[-2:]}{seq}{j:03d}", f"{period}-15", acct, amt, vend))
    return rows


OPEX = [("Payroll", 260_000, "Payroll (internal)"), ("Marketing", 90_000, "Fieldmark"),
        ("Cloud Expense", 82_000, "AWS"), ("Rent", 40_000, "Granby Properties")]
CUSTS = ["Acme", "Globex", "Stark", "Initech", "Umbrella", "Hooli", "Vandelay", "Wonka"]


def build():
    cases = []

    # ---------------------------------------------------------------- normal / edge
    # C01 zero prior
    tx = base_month(JUL, [], 0, OPEX, "a") + base_month(AUG, ["Acme"], 100_000, OPEX, "b")
    cases.append((new_case("C01_zero_prior_base", "normal", "Revenue from $0 to $100K", AUG, JUL,
                           expected_material_variances=["Revenue"],
                           forbidden_patterns=[r"infinit", r"\bnan\b", r"undefined%", r"Revenue.*\(\+?\d+\.?\d*%\)"],
                           required_patterns=[r"prior-period base was zero|not meaningful"]), tx))

    # C02 tiny denominator vs real move
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX + [("Office Snacks", 100, "Snackco")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, OPEX + [("Office Snacks", 1000, "Snackco")], "b")
    tx.append(T("X1", f"{AUG}-20", "Revenue", 50_000, "Acme", segment="Enterprise"))
    cases.append((new_case("C02_tiny_denominator", "normal", "+900% on $900 vs +5% on $1M", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_immaterial=["Office Snacks"],
                           expected_top_drivers={"Revenue": ["Acme"]}), tx))

    # C03 huge account small pct
    tx = base_month(JUL, CUSTS, 100_000_000, OPEX, "a") + base_month(AUG, CUSTS, 100_000_000, OPEX, "b")
    tx.append(T("X1", f"{AUG}-20", "Revenue", 2_400_000, "Acme", segment="Enterprise"))
    tx.append(T("X2", f"{AUG}-21", "Revenue", 600_000, "Globex", segment="Enterprise"))
    cases.append((new_case("C03_huge_account_small_pct", "normal", "$100M -> $103M is +3% but +$3M", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_top_drivers={"Revenue": ["Acme"]},
                           notes="dollar impact must win over percentage"), tx))

    # C04 summary does not reconcile (data_quality)
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_090_000, OPEX, "b")
    summ = [{"period": JUL, "account": "Revenue", "amount": round(sum(t["amount"] for t in tx if t["period"] == JUL and t["account"] == "Revenue"), 2)},
            {"period": AUG, "account": "Revenue", "amount": 1_180_000}]
    for acct, amt, _ in OPEX:
        summ += [{"period": JUL, "account": acct, "amount": amt}, {"period": AUG, "account": acct, "amount": amt}]
    cases.append((new_case("C04_reconciliation_gap", "data_quality", "Summary $1.18M vs transactions $1.09M", AUG, JUL,
                           expected_data_quality_flags=["RECONCILIATION_GAP"], expected_material_variances=["Revenue"],
                           expected_abstention=True, expected_abstention_scope=["Revenue"],
                           required_patterns=[r"cannot reliably attribute"], acceptable_confidence=["low"],
                           forbidden_patterns=[r"together \$[\d,]+, or \d+% of the movement in Revenue"]), tx, summ))

    # C05 material account with no transactions
    tx = base_month(JUL, CUSTS, 1_000_000, [o for o in OPEX if o[0] != "Cloud Expense"], "a") \
       + base_month(AUG, CUSTS, 1_000_000, [o for o in OPEX if o[0] != "Cloud Expense"], "b")
    summ = None
    agg = {}
    for t in tx:
        agg[(t["period"], t["account"])] = agg.get((t["period"], t["account"]), 0) + t["amount"]
    summ = [{"period": p, "account": a, "amount": round(v, 2)} for (p, a), v in sorted(agg.items())]
    summ += [{"period": JUL, "account": "Cloud Expense", "amount": 82_000}, {"period": AUG, "account": "Cloud Expense", "amount": 121_000}]
    cases.append((new_case("C05_missing_transactions", "data_quality", "Cloud +$39K in summary, zero transaction rows", AUG, JUL,
                           expected_data_quality_flags=["NO_TRANSACTIONS_FOR_ACCOUNT"], expected_material_variances=["Cloud Expense"],
                           expected_abstention=True, expected_abstention_scope=["Cloud Expense"],
                           required_patterns=[r"no transaction records"]), tx, summ))

    # C06 duplicate transactions
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    tx.append(T("D1", f"{AUG}-09", "Marketing", 80_000, "Fieldmark", description="Q3 campaign"))
    tx.append(T("D2", f"{AUG}-10", "Marketing", 80_000, "Fieldmark", description="Q3 campaign"))
    cases.append((new_case("C06_duplicate_transactions", "data_quality", "$80K campaign booked twice under different ids", AUG, JUL,
                           expected_data_quality_flags=["PROBABLE_DUPLICATE"], expected_material_variances=["Marketing"],
                           expected_abstention=True, expected_abstention_scope=["Marketing"],
                           forbidden_patterns=[r"Fieldmark \+\$160,000"]), tx))

    # C07 reversal
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX + [("Consulting", 50_000, "Bellweather")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, OPEX + [("Consulting", 50_000, "Bellweather")], "b")
    tx.append(T("V1", f"{JUL}-28", "Consulting", 100_000, "Veridian", description="project fee"))
    tx.append(T("V2", f"{AUG}-02", "Consulting", -100_000, "Veridian", description="reversal of V1"))
    cases.append((new_case("C07_reversal", "normal", "+$100K then -$100K reversal reads as a $200K swing", AUG, JUL,
                           expected_data_quality_flags=["REVERSAL_PAIR"], expected_material_variances=["Consulting"],
                           required_patterns=[r"reversal"], forbidden_patterns=[r"deteriorat", r"cost (saving|discipline)"]), tx))

    # C08 reclassification
    tx = base_month(JUL, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Rent", 40_000, "Granby")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Rent", 40_000, "Granby")], "b")
    tx += [T("M1", f"{JUL}-10", "Marketing", 100_000, "Fieldmark"), T("M2", f"{JUL}-11", "Marketing", 100_000, "Brandhaus"),
           T("P1", f"{JUL}-12", "Professional Services", 50_000, "Bellweather"),
           T("M3", f"{AUG}-10", "Marketing", 100_000, "Brandhaus"),
           T("P2", f"{AUG}-11", "Professional Services", 100_000, "Fieldmark", description="reclassified from Marketing"),
           T("P3", f"{AUG}-12", "Professional Services", 50_000, "Bellweather")]
    cases.append((new_case("C08_reclassification", "ambiguous", "Marketing -$100K, Professional Services +$100K, same vendor", AUG, JUL,
                           expected_material_variances=["Marketing", "Professional Services"],
                           required_patterns=[r"reclassification"], forbidden_patterns=[r"cost (saving|discipline)", r"savings"]), tx))

    # C10 one giant transaction
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX + [("Equipment", 50_000, "Various")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, OPEX + [("Equipment", 50_000, "Various")], "b")
    tx.append(T("G1", f"{AUG}-18", "Equipment", 470_000, "Northline Systems", description="walk-in freezer install"))
    for i in range(6):
        tx.append(T(f"G{i + 2}", f"{AUG}-{10 + i:02d}", "Equipment", 5_000, f"Vendor {i}"))
    cases.append((new_case("C10_single_giant_transaction", "normal", "$470K of a $500K increase is one transaction", AUG, JUL,
                           expected_material_variances=["Equipment"], expected_top_drivers={"Equipment": ["Northline Systems"]},
                           required_patterns=[r"single transaction"], forbidden_patterns=[r"broadly", r"(?<!not )broad-based"]), tx))

    # C11 many tiny transactions, no dominant driver
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    vendors = [f"Travel Vendor {i:02d}" for i in range(40)]
    for i in range(800):
        tx.append(T(f"TJ{i:04d}", f"{JUL}-{RNG.randint(1, 28):02d}", "Travel", round(RNG.uniform(60, 190), 2), RNG.choice(vendors)))
    for i in range(1600):
        tx.append(T(f"TA{i:04d}", f"{AUG}-{RNG.randint(1, 28):02d}", "Travel", round(RNG.uniform(60, 190), 2), RNG.choice(vendors)))
    cases.append((new_case("C11_distributed_movement", "normal", "+$100K across 1,600 small transactions, 40 vendors", AUG, JUL,
                           expected_material_variances=["Travel"], required_patterns=[r"distributed across"],
                           forbidden_patterns=[r"single transaction"], max_tool_calls=14), tx))

    # C12 new customer
    tx = base_month(JUL, CUSTS[:5], 500_000, OPEX, "a") + base_month(AUG, CUSTS[:5], 500_000, OPEX, "b")
    tx.append(T("N1", f"{AUG}-05", "Revenue", 200_000, "NewCo", segment="Enterprise"))
    cases.append((new_case("C12_new_customer", "normal", "$0 -> $200K customer is new, not +inf%", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_top_drivers={"Revenue": ["NewCo"]},
                           required_patterns=[r"NewCo had no activity in 2026-07"],
                           forbidden_patterns=[r"NewCo \+\d+%", r"NewCo grew", r"infinit"]), tx))

    # C13 inactive customer (do not say churn)
    tx = base_month(JUL, CUSTS[:5], 500_000, OPEX, "a") + base_month(AUG, CUSTS[:5], 500_000, OPEX, "b")
    tx.append(T("L1", f"{JUL}-05", "Revenue", 150_000, "OldCo", segment="Enterprise"))
    cases.append((new_case("C13_inactive_customer", "ambiguous", "$150K -> $0 customer; data does not prove churn", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_top_drivers={"Revenue": ["OldCo"]},
                           required_patterns=[r"no activity in 2026-08", r"does not establish whether the relationship ended"],
                           forbidden_patterns=[r"\bchurn", r"-100%", r"\blost the customer"]), tx))

    # C14 offsetting movements
    tx = []
    for i in range(10):
        tx.append(T(f"E7{i}", f"{JUL}-10", "Revenue", 30_000, f"Ent {i}", segment="Enterprise"))
        tx.append(T(f"S7{i}", f"{JUL}-10", "Revenue", 40_000, f"SMB {i}", segment="SMB"))
        tx.append(T(f"E8{i}", f"{AUG}-10", "Revenue", 60_000, f"Ent {i}", segment="Enterprise"))
        tx.append(T(f"S8{i}", f"{AUG}-10", "Revenue", 12_000, f"SMB {i}", segment="SMB"))
    tx += base_month(JUL, [], 0, OPEX, "a") + base_month(AUG, [], 0, OPEX, "b")
    cases.append((new_case("C14_offsetting_movements", "ambiguous", "Enterprise +$300K, SMB -$280K, net +$20K", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_top_drivers={"Revenue": ["Enterprise", "SMB"]},
                           required_patterns=[r"opposing|hides"], forbidden_patterns=[r"broadly stable", r"\bstable\b"],
                           notes="net hides gross; policy must treat Revenue as critical to force investigation"), tx,
                  None, None, {"critical_accounts": ["Revenue"]}))

    # C16 seasonality with 25 months of history
    tx = []
    y, m = 2023, 12
    periods = []
    for _ in range(25):
        periods.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    for k, p in enumerate(periods):
        mult = 1.4 if p.endswith("-12") else 1.0
        tx += base_month(p, CUSTS, 1_000_000 * mult * (1 + 0.004 * k), OPEX, f"s{k}")
    cases.append((new_case("C16_seasonality_normal", "ambiguous", "December +40%, as every December", "2025-12", "2025-11",
                           expected_material_variances=["Revenue"], required_patterns=[r"historically normal"],
                           forbidden_patterns=[r"outside its seasonal norm"]), tx))

    # C25 statistical anomaly, no economic importance
    tx = base_month(JUL, CUSTS, 2_000_000, OPEX + [("Office Snacks", 500, "Snackco")], "a") \
       + base_month(AUG, CUSTS, 2_000_000, OPEX + [("Office Snacks", 2_800, "Snackco")], "b")
    tx.append(T("X1", f"{AUG}-20", "Revenue", 300_000, "Acme", segment="Enterprise"))
    cases.append((new_case("C25_anomaly_without_importance", "normal", "Snacks +460% ($2.3K) vs Revenue +$300K", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_immaterial=["Office Snacks"]), tx))

    # C26 economically important, statistically normal (quarterly payroll step)
    tx = []
    y, m = 2025, 1
    periods = []
    for _ in range(20):
        periods.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    pay = 2_000_000
    for k, p in enumerate(periods):
        if k and k % 3 == 0:
            pay += 300_000
        tx += base_month(p, CUSTS, 5_000_000, [("Payroll", pay, "Payroll (internal)"), ("Rent", 40_000, "Granby")], f"q{k}")
    cases.append((new_case("C26_important_but_normal", "normal", "Payroll +$300K, as every quarter", periods[18], periods[17],
                           expected_material_variances=["Payroll"], notes="material by dollars even if historically regular"), tx))

    # C27 negative values / refunds
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    for i in range(6):
        tx.append(T(f"RF7{i}", f"{JUL}-2{i}", "Revenue", -8_000, f"Refund {i}", description="refund", segment="SMB"))
        tx.append(T(f"RF8{i}", f"{AUG}-2{i}", "Revenue", -25_000, f"Refund {i}", description="refund", segment="SMB"))
    tx.append(T("X1", f"{AUG}-20", "Revenue", 250_000, "Acme", segment="Enterprise"))
    cases.append((new_case("C27_negative_values", "normal", "Refund credits inside Revenue; gross vs net", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_top_drivers={"Revenue": ["Acme"]},
                           required_patterns=[r"Excluding Acme"], notes="+$250K masked by -$102K of refunds"), tx))

    # C29 outlier masking underlying decline
    tx = base_month(JUL, CUSTS, 2_000_000, OPEX, "a")
    aug = base_month(AUG, CUSTS, 1_800_000, OPEX, "b")
    tx += aug
    tx.append(T("B1", f"{AUG}-05", "Revenue", 1_200_000, "BigCo", segment="Enterprise"))
    cases.append((new_case("C29_outlier_masks_decline", "ambiguous", "+$1M total; BigCo +$1.2M, everyone else -$200K", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_top_drivers={"Revenue": ["BigCo"]},
                           required_patterns=[r"Excluding BigCo, Revenue declined"]), tx))

    # C30 concentration
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_010_000, OPEX, "b")
    tx.append(T("K1", f"{AUG}-05", "Revenue", 190_000, "Acme", segment="Enterprise"))
    cases.append((new_case("C30_concentration_risk", "ambiguous", "+20% with 95% of it from one customer", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_top_drivers={"Revenue": ["Acme"]},
                           required_patterns=[r"concentrated|not broad-based"], forbidden_patterns=[r"broad-based growth"]), tx))

    # C31 insufficient history for seasonality claims
    tx = base_month("2025-11", CUSTS, 1_000_000, OPEX, "a") + base_month("2025-12", CUSTS, 1_400_000, OPEX, "b")
    cases.append((new_case("C31_insufficient_history", "ambiguous", "Two periods only; December +40%", "2025-12", "2025-11",
                           expected_data_quality_flags=["INSUFFICIENT_HISTORY"], expected_material_variances=["Revenue"],
                           forbidden_patterns=[r"seasonal", r"historically normal", r"\btrend\b"]), tx))

    # C32 conflicting summary rows
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_100_000, OPEX, "b")
    agg = {}
    for t in tx:
        agg[(t["period"], t["account"])] = agg.get((t["period"], t["account"]), 0) + t["amount"]
    summ = [{"period": p, "account": a, "amount": round(v, 2)} for (p, a), v in sorted(agg.items())]
    summ.append({"period": AUG, "account": "Revenue", "amount": 1_250_000})
    cases.append((new_case("C32_conflicting_files", "data_quality", "Two August revenue totals in the summary", AUG, JUL,
                           expected_data_quality_flags=["CONFLICTING_SUMMARY"], expected_abstention=True,
                           expected_abstention_scope=["Revenue"], acceptable_confidence=["low"]), tx, summ))

    # C33 correlation is not causation
    tx = base_month(JUL, CUSTS, 1_000_000, [("Marketing", 90_000, "Fieldmark"), ("Rent", 40_000, "Granby")], "a") \
       + base_month(AUG, CUSTS, 1_200_000, [("Marketing", 135_000, "Fieldmark"), ("Rent", 40_000, "Granby")], "b")
    cases.append((new_case("C33_unsupported_causality", "ambiguous", "Marketing +50%, Revenue +20%: no causal claim", AUG, JUL,
                           expected_material_variances=["Revenue", "Marketing"],
                           forbidden_patterns=[r"\bcaused\b", r"because of", r"as a result of", r"led to", r"drove revenue",
                                               r"marketing (spend|investment|campaign)[^.]*revenue"],
                           required_patterns=[r"does not establish why"]), tx, None, None, {"critical_accounts": ["Revenue", "Marketing"]}))

    # C35 nothing happened
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_003_000, OPEX, "b")
    cases.append((new_case("C35_no_meaningful_change", "normal", "Everything within noise", AUG, JUL,
                           expected_material_variances=[], required_patterns=[r"No financially material"],
                           forbidden_patterns=[r"increased|decreased|driven"]), tx))

    # ---------------------------------------------------------------- adversarial
    # A01 hostile number and date formats, account-name variants
    tx = [T("F1", "2026-07-05", "Revenue", "$400,000.00", "Acme", segment="Enterprise"),
          T("F2", "07/09/2026", "Revenue", "300,000", "Globex", segment="Enterprise"),
          T("F3", "Jul 12, 2026", "revenue ", 300000, "Stark", segment="SMB"),
          T("F4", "2026-08-05", "REVENUE", "$650,000", "Acme", segment="Enterprise"),
          T("F5", "2026/08/09", "Revenue", "300,000", "Globex", segment="Enterprise"),
          T("F6", "Aug 12, 2026", "Revenue", "300000", "Stark", segment="SMB"),
          T("F7", "2026-08-13", "Revenue", "(20,000)", "Stark", description="credit"),
          T("F8", "2026-07-15", "Rent", "40,000", "Granby"), T("F9", "2026-08-15", "Rent", "40000-", "Granby")]
    for t in tx:
        t["period"] = t["date"][:7] if t["date"][:4].isdigit() else ("2026-07" if "07" in t["date"] or "Jul" in t["date"] else "2026-08")
    summ = [{"period": JUL, "account": "Revenue", "amount": 1_000_000}, {"period": AUG, "account": "Revenue", "amount": 1_230_000},
            {"period": JUL, "account": "Rent", "amount": 40_000}, {"period": AUG, "account": "Rent", "amount": -40_000}]
    cases.append((new_case("A01_hostile_formats", "adversarial", "Currency symbols, commas, parentheses, trailing minus, 4 date formats", AUG, JUL,
                           expected_data_quality_flags=["INCONSISTENT_ACCOUNT_NAME"], expected_no_data_quality_flags=["UNPARSEABLE_AMOUNT"],
                           expected_material_variances=["Revenue"], expected_top_drivers={"Revenue": ["Acme"]}), tx, summ))

    # A02 unicode look-alike vendor
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    tx.append(T("U1", f"{AUG}-14", "Marketing", 60_000, "Fieldmаrk", description="campaign"))   # Cyrillic a
    cases.append((new_case("A02_lookalike_vendor", "adversarial", "'Fieldmаrk' with a Cyrillic а", AUG, JUL,
                           expected_data_quality_flags=["LOOKALIKE_NAME"], expected_material_variances=["Marketing"]), tx))

    # A03 alias soup: do not infer that "Amazon" is AWS
    tx = base_month(JUL, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)")], "b")
    tx += [T("C1", f"{JUL}-03", "Cloud Expense", 50_000, "AWS"), T("C2", f"{JUL}-04", "Cloud Expense", 20_000, "Amazon Web Services"),
           T("C3", f"{JUL}-05", "Cloud Expense", 12_000, "Amazon"),
           T("C4", f"{AUG}-03", "Cloud Expense", 58_000, "AWS"), T("C5", f"{AUG}-04", "Cloud Expense", 31_000, "AMZN AWS"),
           T("C6", f"{AUG}-05", "Cloud Expense", 40_000, "Amazon", description="marketplace order")]
    cases.append((new_case("A03_alias_soup", "adversarial", "AWS / Amazon Web Services / AMZN AWS / Amazon", AUG, JUL,
                           expected_material_variances=["Cloud Expense"],
                           forbidden_patterns=[r"AWS migration", r"Amazon (is|=) AWS", r"all Amazon"],
                           notes="must not merge 'Amazon' (marketplace) into AWS without evidence"), tx))

    # A04 misleading description
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    tx.append(T("R1", f"{AUG}-14", "Revenue", 90_000, "Acme", description="refund", segment="Enterprise"))
    cases.append((new_case("A04_misleading_description", "adversarial", "Positive revenue row described as 'refund'", AUG, JUL,
                           expected_data_quality_flags=["DESCRIPTION_SIGN_MISMATCH"], expected_material_variances=["Revenue"],
                           forbidden_patterns=[r"refunds? (increased|drove|reduced)"]), tx))

    # A05 cutoff / timing: dated Sep 1 but booked to Aug
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    tx.append(T("CUT1", "2026-09-01", "Revenue", 500_000, "Acme", period=AUG, segment="Enterprise", description="invoice"))
    cases.append((new_case("A05_cutoff_timing", "adversarial", "$500K dated Sep 1 booked to August", AUG, JUL,
                           expected_data_quality_flags=["TXN_OUTSIDE_PERIOD"], expected_material_variances=["Revenue"],
                           expected_top_drivers={"Revenue": ["Acme"]}), tx))

    # A06 corrupt rows and null amounts
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    tx.append(T("Z1", f"{AUG}-14", "Marketing", "", "Fieldmark"))
    tx.append(T("Z2", f"{AUG}-15", "Marketing", "abc", "Fieldmark"))
    cases.append((new_case("A06_corrupt_rows", "adversarial", "Null amount, non-numeric amount, short row", AUG, JUL,
                           expected_data_quality_flags=["UNPARSEABLE_AMOUNT", "CORRUPT_ROW"]), tx, None, None, None,
                  ["Z3,2026-08-16,2026-08,Marketing"]))

    # ---------------------------------------------------------------- memory sequences
    def cloud_case(cid, title, period, prior, jul_cloud, aug_cloud, prior_kwargs, **gt):
        tx = base_month(prior, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", jul_cloud, "AWS")], "a") \
           + base_month(period, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", aug_cloud, "AWS")], "b")
        st = PriorStore(os.path.join(HERE, "_tmp_memory.json"))
        st.priors = []
        st.add("counterparty", {"account": "Cloud Expense", "vendor": "AWS"},
               "AWS migration of the analytics workload began in July and is expected to elevate cloud spend through September",
               "expect month-on-month increases of up to +30% through 2026-09; investigate anything beyond that",
               {"run_id": "run_2026_07", "period": "2026-07"}, 0.95, source_type="user_verified",
               source="finance_reviewer", valid_from="2026-07", valid_until="2026-09", **prior_kwargs)
        return (new_case(cid, "memory", title, period, prior, expected_material_variances=["Cloud Expense"], **gt), tx, None, st)

    cases.append(cloud_case("M01_memory_consistent", "Cloud +12% inside the learned migration range", AUG, JUL, 82_000, 92_000,
                            {"expectation": {"max_increase_pct": 30}}, expected_memory_usage=["PR-0001"],
                            required_patterns=[r"consistent with the reviewer-provided context"],
                            forbidden_patterns=[r"exceeds that range"]))
    cases.append(cloud_case("M02_memory_exceeded", "Cloud +34% beyond the learned range", AUG, JUL, 82_000, 110_000,
                            {"expectation": {"max_increase_pct": 30}}, expected_memory_usage=["PR-0001"],
                            required_patterns=[r"exceeds that range"], acceptable_confidence=["medium", "low"],
                            forbidden_patterns=[r"is consistent with the reviewer"]))
    cases.append(cloud_case("M03_stale_memory", "Cloud +30% in December; migration context expired in September", "2026-12", "2026-11",
                            82_000, 107_000, {"expectation": {"max_increase_pct": 30}}, expected_memory_rejected=["PR-0001"],
                            required_patterns=[r"was not applied.*expired"], forbidden_patterns=[r"consistent with the reviewer"]))
    # M04 contradicted memory
    tx = base_month(JUL, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", 82_000, "AWS")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", 120_000, "AWS")], "b")
    st = PriorStore(os.path.join(HERE, "_tmp_memory.json")); st.priors = []
    st.add("counterparty", {"account": "Cloud Expense", "vendor": "AWS"},
           "cloud spend will fall from August because the migration completed and duplicate environments were shut down",
           "expect Cloud Expense to decline", {"run_id": "run_2026_07"}, 0.9, source_type="user_verified",
           source="finance_reviewer", valid_from="2026-08", expectation={"direction": "down"})
    cases.append((new_case("M04_contradicted_memory", "memory", "Reviewer said cloud would fall; it rose 46%", AUG, JUL,
                           expected_material_variances=["Cloud Expense"], expected_memory_usage=["PR-0001"],
                           required_patterns=[r"sources conflict"], acceptable_confidence=["medium", "low"],
                           forbidden_patterns=[r"consistent with PR-0001"]), tx, None, st))

    # ================================================================ batch 2
    JUN = "2026-06"
    def _agg_summary(tx):
        agg = {}
        for t in tx:
            if isinstance(t["amount"], (int, float)):
                agg[(t["period"], t["account"])] = agg.get((t["period"], t["account"]), 0) + t["amount"]
        return [{"period": p, "account": a, "amount": round(v, 2)} for (p, a), v in sorted(agg.items())]

    # ---- ambiguous (+2)
    # B01 Simpson's paradox: blended margin up, every segment's margin down
    tx = []
    for p, ent, smb, m_ent, m_smb, tag in ((JUL, 400_000, 600_000, 0.60, 0.30, "a"), (AUG, 800_000, 300_000, 0.58, 0.28, "b")):
        shares = (0.4, 0.3, 0.2, 0.1)
        for i, sh in enumerate(shares):
            tx.append(T(f"E{tag}{i}", f"{p}-1{i}", "Revenue", round(ent * sh, 2), f"Ent {i}", segment="Enterprise"))
            tx.append(T(f"EC{tag}{i}", f"{p}-1{i}", "COGS", round(ent * sh * (1 - m_ent), 2), "Supplier A", segment="Enterprise"))
            tx.append(T(f"S{tag}{i}", f"{p}-2{i}", "Revenue", round(smb * sh, 2), f"SMB {i}", segment="SMB"))
            tx.append(T(f"SC{tag}{i}", f"{p}-2{i}", "COGS", round(smb * sh * (1 - m_smb), 2), "Supplier B", segment="SMB"))
    tx += base_month(JUL, [], 0, OPEX, "a") + base_month(AUG, [], 0, OPEX, "b")
    cases.append((new_case("B01_simpsons_paradox", "ambiguous", "Blended margin +7.8pts while both segments fell 2pts", AUG, JUL,
                           expected_material_variances=["Revenue"], required_patterns=[r"mix", r"Every segment earned a lower margin"],
                           forbidden_patterns=[r"operational (margin )?improvement", r"margin improved because"]), tx,
                  None, None, {"critical_accounts": ["Revenue", "COGS"]}))

    # B02 multiple plausible explanations: state the driver, never the cause
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    for i in range(8):
        tx.append(T(f"TV7{i}", f"{JUL}-1{i}", "Travel", 2_100 + 130 * i, "Delta" if i % 2 else "Marriott"))
        tx.append(T(f"TV8{i}", f"{AUG}-1{i}", "Travel", 8_600 + 260 * i, "Delta" if i % 2 else "Marriott"))
    cases.append((new_case("B02_multiple_plausible_causes", "ambiguous", "Travel +280%: Delta and Marriott up; no cause in the data", AUG, JUL,
                           expected_material_variances=["Travel"], expected_top_drivers={"Travel": ["Delta", "Marriott"]},
                           required_patterns=[r"does not establish why"],
                           forbidden_patterns=[r"conference", r"headcount", r"more employees", r"price increase", r"more trips"]), tx))

    # ---- data quality (+7)
    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_100_000, OPEX, "b")
    cases.append((new_case("D01_missing_amount_column", "data_quality", "transactions.csv has no amount column", AUG, JUL,
                           expected_data_quality_flags=["MISSING_COLUMNS"], expected_abstention=True,
                           acceptable_confidence=["low"], required_patterns=[r"cannot analyse this period"]),
                  tx, _agg_summary(tx), None, None, None, ("amount",)))

    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_100_000, OPEX, "b")
    cases.append((new_case("D02_missing_period", "data_quality", "Asked for September; only July and August exist", "2026-09", AUG,
                           expected_data_quality_flags=["MISSING_PERIOD"], expected_abstention=True,
                           acceptable_confidence=["low"], required_patterns=[r"cannot analyse this period"]), tx))

    tx = base_month(JUN, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_150_000, OPEX, "b")
    tx.append(T("X1", f"{AUG}-20", "Revenue", 120_000, "Acme", segment="Enterprise"))
    cases.append((new_case("D03_period_gap", "data_quality", "July is missing between June and August", AUG, JUN,
                           expected_data_quality_flags=["PERIOD_GAP"], expected_material_variances=["Revenue"],
                           expected_top_drivers={"Revenue": ["Acme"]}), tx))

    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    tx.append(T("DUPID", f"{AUG}-09", "Marketing", 60_000, "Fieldmark", description="Q3 campaign"))
    tx.append(T("DUPID", f"{AUG}-09", "Marketing", 60_000, "Fieldmark", description="Q3 campaign"))
    cases.append((new_case("D04_duplicate_id_identical", "data_quality", "Same transaction_id twice, identical content, $60K", AUG, JUL,
                           expected_data_quality_flags=["DUPLICATE_TXN_ID"], expected_material_variances=["Marketing"],
                           expected_abstention=True, expected_abstention_scope=["Marketing"]), tx))

    tx = base_month(JUL, CUSTS[:6], 900_000, OPEX, "a") + base_month(AUG, CUSTS[:6], 900_000, OPEX, "b")
    for t in tx:
        if t["account"] == "Revenue":
            t["currency"] = "USD"
    tx.append(T("EU7", f"{JUL}-05", "Revenue", 108_000, "Berlin Bistro GmbH", currency="EUR", segment="SMB", description="EUR 100,000 translated"))
    tx.append(T("EU8", f"{AUG}-05", "Revenue", 118_000, "Berlin Bistro GmbH", currency="EUR", segment="SMB", description="EUR 100,000 translated"))
    cases.append((new_case("D05_mixed_currency", "data_quality", "EUR customer unchanged in EUR, up 9% in USD translation", AUG, JUL,
                           expected_data_quality_flags=["MIXED_CURRENCY"],
                           forbidden_patterns=[r"broad-based growth", r"Berlin Bistro GmbH grew"]), tx,
                  None, None, {"critical_accounts": ["Revenue"]}))

    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    tx += [T("CN7", f"{JUL}-12", "Consulting", 30_000, "Bellweather"), T("CN8", f"{AUG}-12", "Consulting", 75_000, "Bellweather")]
    summ = [r for r in _agg_summary(tx) if r["account"] != "Consulting"]
    cases.append((new_case("D06_account_missing_from_summary", "data_quality", "Consulting has transactions but no summary line", AUG, JUL,
                           expected_data_quality_flags=["MISSING_ACCOUNT_MAPPING"]), tx, summ))

    tx = base_month(JUL, CUSTS, 1_000_000, OPEX, "a") + base_month(AUG, CUSTS, 1_000_000, OPEX, "b")
    for i in range(7):
        tx.append(T(f"NEG{i}", f"{AUG}-1{i}", "Revenue", -15_000, f"Credit {i}", segment="SMB", description="credit memo"))
    cases.append((new_case("D07_sign_inconsistent", "data_quality", "Revenue with ~45% negative rows", AUG, JUL,
                           expected_data_quality_flags=["SIGN_INCONSISTENT"]), tx,
                  None, None, {"critical_accounts": ["Revenue"]}))

    # ---- adversarial (+4)
    tx = base_month(JUL, CUSTS[1:], 1_000_000, OPEX, "a") + base_month(AUG, CUSTS[1:], 1_000_000, OPEX, "b")
    tx += [T("V7", f"{JUL}-05", "Revenue", 120_000, "Acme", segment="Enterprise"),
           T("V8a", f"{AUG}-05", "Revenue", 60_000, "Acme", segment="Enterprise"),
           T("V8b", f"{AUG}-06", "Revenue", 52_000, "acme ", segment="Enterprise"),
           T("V8c", f"{AUG}-07", "Revenue", 44_000, "ACME", segment="Enterprise"),
           T("G8", f"{AUG}-08", "Revenue", 20_000, "Globex", segment="Enterprise")]
    cases.append((new_case("A07_counterparty_variants", "adversarial", "'Acme' / 'acme ' / 'ACME' are one customer (+$36K), Globex +$20K", AUG, JUL,
                           expected_material_variances=["Revenue"], expected_top_drivers={"Revenue": ["Acme"]},
                           required_patterns=[r"Acme \+\$36,000"], forbidden_patterns=[r"Acme \+\$52,000", r"Acme \+\$44,000", r"Acme -\$60,000"]), tx))

    tx = base_month(JUL, CUSTS, 1_000_000, [o for o in OPEX if o[0] != "Marketing"], "a") \
       + base_month(AUG, CUSTS, 1_000_000, [o for o in OPEX if o[0] != "Marketing"], "b")
    tx += [T("MK7", f"{JUL}-10", "Marketing", 90_000, "Fieldmark"), T("MK8", f"{AUG}-10", "Marketing", 95_000, "Fieldmark Marketing LLC")]
    cases.append((new_case("A08_renamed_vendor", "adversarial", "Fieldmark became 'Fieldmark Marketing LLC'; data cannot prove they are the same", AUG, JUL,
                           expected_material_variances=["Marketing"],
                           required_patterns=[r"no activity in 2026-07", r"does not establish whether the relationship ended"],
                           forbidden_patterns=[r"\bchurn", r"renamed", r"same vendor"]), tx, None, None, {"critical_accounts": ["Marketing"]}))

    tx = base_month(JUL, CUSTS, 1_000_000, OPEX + [("Consulting", 40_000, "Bellweather")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, OPEX + [("Consulting", 40_000, "Bellweather")], "b")
    tx += [T("OF1", f"{AUG}-08", "Consulting", 50_000, "Veridian", description="project fee"),
           T("OF2", f"{AUG}-22", "Consulting", -50_000, "Veridian", description="project fee reversal")]
    cases.append((new_case("A09_intra_period_offset", "adversarial", "+$50K and -$50K in the same month, net zero", AUG, JUL,
                           expected_data_quality_flags=["REVERSAL_PAIR"], expected_material_variances=[],
                           required_patterns=[r"No financially material"]), tx))

    tx = base_month(JUL, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Rent", 40_000, "Granby")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Rent", 40_000, "Granby")], "b")
    tx += [T("CL7", f"{JUL}-05", "Cloud Expense", 82_000, "AWS"), T("CL8", f"{AUG}-05", "Cloud & Infrastructure", 88_000, "AWS")]
    cases.append((new_case("A10_account_renamed", "adversarial", "'Cloud Expense' became 'Cloud & Infrastructure' between periods", AUG, JUL,
                           expected_material_variances=["Cloud Expense", "Cloud & Infrastructure"],
                           required_patterns=[r"reclassification"], forbidden_patterns=[r"cost (saving|discipline)", r"eliminated"]), tx))

    # ---- memory (+6)
    def mem_store():
        st = PriorStore(os.path.join(HERE, "_tmp_memory.json")); st.priors = []; return st

    tx = base_month(JUL, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", 82_000, "AWS")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", 96_000, "AWS")], "b")
    st = mem_store()
    st.add("counterparty", {"account": "Cloud Expense", "vendor": "AWS"},
           "cloud spend growth is probably the analytics migration", "treat cloud increases as expected",
           {"run_id": "run_2026_07"}, 0.4, source_type="hypothesis", source="system",
           valid_from="2026-07", valid_until="2026-10", expectation={"max_increase_pct": 30})
    cases.append((new_case("M05_hypothesis_not_fact", "memory", "A system hypothesis must not be presented as established context", AUG, JUL,
                           expected_material_variances=["Cloud Expense"], expected_memory_usage=["PR-0001"],
                           required_patterns=[r"unverified system hypothesis", r"not treated as an established fact"],
                           forbidden_patterns=[r"reviewer-provided context"], acceptable_confidence=["medium", "low"]), tx, None, st))

    tx = base_month(JUN, CUSTS, 1_000_000, OPEX + [("Professional Fees", 12_000, "Bellweather")], "a") \
       + base_month(JUL, CUSTS, 1_000_000, OPEX + [("Professional Fees", 12_000, "Bellweather")], "b")
    tx.append(T("SETTLE", f"{JUN}-18", "Professional Fees", 95_000, "Bellweather", description="Settlement - Ridgeline contract dispute"))
    st = mem_store()
    st.add("one_time", {"account": "Professional Fees", "period": "2026-06"},
           "June contained a one-time $95,000 legal settlement (Ridgeline dispute)",
           "expect Professional Fees to fall back in July; the decrease is not a saving",
           {"run_id": "run_2026_06"}, 0.95, source_type="user_verified", source="finance_reviewer",
           valid_from="2026-07", valid_until="2026-07", expectation={"direction": "down"})
    cases.append((new_case("M06_one_time_carried_forward", "memory", "July -$95K in fees is the June settlement not recurring, not discipline", JUL, JUN,
                           expected_material_variances=["Professional Fees"], expected_memory_usage=["PR-0001"],
                           required_patterns=[r"consistent with PR-0001"], forbidden_patterns=[r"cost (saving|discipline)", r"savings"]), tx, None, st))

    tx = base_month(JUL, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", 82_000, "AWS"), ("Marketing", 90_000, "Fieldmark")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", 82_500, "AWS"), ("Marketing", 130_000, "Fieldmark")], "b")
    st = mem_store()
    st.add("counterparty", {"account": "Cloud Expense", "vendor": "AWS"},
           "AWS migration elevates cloud spend through September", "expect up to +30%",
           {"run_id": "run_2026_07"}, 0.95, source_type="user_verified", source="finance_reviewer",
           valid_from="2026-07", valid_until="2026-09", expectation={"max_increase_pct": 30})
    cases.append((new_case("M07_scope_mismatch", "memory", "Cloud prior must not be applied to a Marketing movement", AUG, JUL,
                           expected_material_variances=["Marketing"], forbidden_patterns=[r"PR-0001", r"AWS migration"]), tx, None, st))

    tx = base_month(JUL, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", 82_000, "AWS")], "a") \
       + base_month(AUG, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", 100_000, "AWS")], "b")
    st = mem_store()
    st.add("counterparty", {"account": "Cloud Expense", "vendor": "AWS"},
           "a data-warehouse migration starting in October will raise cloud spend", "expect up to +40% from October",
           {"run_id": "run_2026_07"}, 0.9, source_type="user_verified", source="finance_reviewer",
           valid_from="2026-10", valid_until="2026-12", expectation={"max_increase_pct": 40})
    cases.append((new_case("M08_future_prior", "memory", "A prior valid from October must not explain August", AUG, JUL,
                           expected_material_variances=["Cloud Expense"], expected_memory_rejected=["PR-0001"],
                           required_patterns=[r"was not applied.*not valid before"], forbidden_patterns=[r"consistent with"]), tx, None, st))

    st = mem_store()
    pid = st.add("counterparty", {"account": "Cloud Expense", "vendor": "AWS"},
                 "cloud spend will fall from August", "expect Cloud Expense to decline",
                 {"run_id": "run_2026_07"}, 0.9, source_type="user_verified", source="finance_reviewer",
                 valid_from="2026-08", expectation={"direction": "down"})
    st.set_status(pid, "contested", note="contradicted in a prior run", by="system")
    cases.append((new_case("M09_contested_prior", "memory", "A contested prior is cited with reduced weight, not as fact", AUG, JUL,
                           expected_material_variances=["Cloud Expense"], expected_memory_usage=["PR-0001"],
                           required_patterns=[r"contested prior"], acceptable_confidence=["medium", "low"]), tx, None, st))

    st = mem_store()
    pid = st.add("counterparty", {"account": "Cloud Expense", "vendor": "AWS"},
                 "AWS migration elevates cloud spend", "expect up to +30%",
                 {"run_id": "run_2026_07"}, 0.9, source_type="user_verified", source="finance_reviewer",
                 valid_from="2026-07", valid_until="2026-09", expectation={"max_increase_pct": 30})
    st.set_status(pid, "rejected", note="reviewer: migration was cancelled", by="finance_reviewer")
    cases.append((new_case("M10_rejected_prior", "memory", "A reviewer-rejected prior is never applied", AUG, JUL,
                           expected_material_variances=["Cloud Expense"], expected_memory_rejected=["PR-0001"],
                           required_patterns=[r"was not applied.*rejected"], forbidden_patterns=[r"consistent with"]), tx, None, st))

    # ================================================================ sequences (§13)
    def months(start, n):
        y, m = int(start[:4]), int(start[5:]); out = []
        for _ in range(n):
            out.append(f"{y:04d}-{m:02d}"); m += 1
            if m == 13:
                m, y = 1, y + 1
        return out

    # S01 the cloud story: learn from the reviewer, verify against it, retire it
    ps = months("2026-06", 7)
    cloud = {"2026-06": 82_000, "2026-07": 102_500, "2026-08": 110_700, "2026-09": 148_300,
             "2026-10": 150_000, "2026-11": 150_000, "2026-12": 195_000}
    tx = []
    for k, p in enumerate(ps):
        tx += base_month(p, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Cloud Expense", cloud[p], "AWS"),
                                                  ("Rent", 40_000, "Granby")], f"s{k}")
    aws_prior = {"op": "add", "type": "counterparty", "scope": {"account": "Cloud Expense", "vendor": "AWS"},
                 "statement": "AWS migration of the analytics workload began in July and is expected to elevate cloud spend through September",
                 "implication": "expect month-on-month increases of up to +30% through 2026-09",
                 "confidence": 0.95, "source_type": "user_verified", "valid_from": "2026-07", "valid_until": "2026-09",
                 "expectation": {"max_increase_pct": 30}}
    cases.append((new_sequence("S01_cloud_story", "memory", "Cloud: +25% learn, +8% consistent, +34% exceeds, +30% in Dec after expiry", [
        {"period": "2026-07", "prior_period": "2026-06",
         "ground_truth": {"expected_material_variances": ["Cloud Expense"], "required_patterns": [r"does not establish why"]}},
        {"period": "2026-08", "prior_period": "2026-07", "feedback": [aws_prior],
         "ground_truth": {"expected_material_variances": ["Cloud Expense"], "expected_memory_usage": ["PR-0001"],
                          "required_patterns": [r"consistent with the reviewer-provided context"], "forbidden_patterns": [r"exceeds that range"]}},
        {"period": "2026-09", "prior_period": "2026-08",
         "ground_truth": {"expected_material_variances": ["Cloud Expense"], "expected_memory_usage": ["PR-0001"],
                          "required_patterns": [r"exceeds that range"], "acceptable_confidence": ["medium", "low"]}},
        {"period": "2026-12", "prior_period": "2026-11",
         "ground_truth": {"expected_material_variances": ["Cloud Expense"], "expected_memory_rejected": ["PR-0001"],
                          "required_patterns": [r"was not applied.*expired"], "forbidden_patterns": [r"consistent with the reviewer"]}},
    ]), tx))

    # S02 a one-off the system learns by itself, then explains the following month
    ps = months("2026-01", 10)
    tx = []
    for k, p in enumerate(ps):
        tx += base_month(p, CUSTS, 1_000_000, OPEX + [("Professional Fees", 12_000 + 300 * (k % 3), "Bellweather")], f"o{k}")
    tx.append(T("SETTLE", "2026-08-18", "Professional Fees", 95_000, "Bellweather", description="Settlement - Ridgeline contract dispute"))
    cases.append((new_sequence("S02_one_time_learned", "memory", "Aug settlement detected; Sep decrease explained by memory, not as a saving", [
        {"period": "2026-08", "prior_period": "2026-07",
         "ground_truth": {"expected_material_variances": ["Professional Fees"], "required_patterns": [r"non-recurring item"]}},
        {"period": "2026-09", "prior_period": "2026-08",
         "ground_truth": {"expected_material_variances": ["Professional Fees"], "expected_memory_usage": ["PR-0001"],
                          "required_patterns": [r"consistent with PR-0001"], "forbidden_patterns": [r"cost (saving|discipline)", r"savings"]}},
    ]), tx))

    # S03 a reclass learned in July is still known in August, when nothing moves
    ps = months("2026-01", 10)
    tx = []
    for k, p in enumerate(ps):
        tx += base_month(p, CUSTS, 1_000_000, [("Payroll", 260_000, "Payroll (internal)"), ("Rent", 40_000, "Granby")], f"r{k}")
        acct = "Outbound Freight" if p < "2026-07" else "Freight (COGS)"
        tx.append(T(f"FR{k}", f"{p}-28", acct, 60_000, "Pacific Freight Partners", description="freight"))
    cases.append((new_sequence("S03_reclass_carried_forward", "memory", "Freight reclass learned in July; cited in August without a movement", [
        {"period": "2026-07", "prior_period": "2026-06",
         "ground_truth": {"expected_material_variances": ["Outbound Freight", "Freight (COGS)"], "required_patterns": [r"reclassification"]}},
        {"period": "2026-08", "prior_period": "2026-07",
         "ground_truth": {"required_patterns": [r"(Carried from earlier runs, |Context from memory )PR-000\d"], "expected_memory_usage": ["PR-0001"]}},
    ]), tx))

    # S04 silent churn across six consecutive runs: nothing is ever booked
    ps = months("2025-01", 20)
    standing = {f"Program {i}": (22_000 + 1_500 * i, ps[13 + i]) for i in range(7)}   # stop 2026-02 .. 2026-08
    tx = []
    for k, p in enumerate(ps):
        tx += base_month(p, CUSTS, 1_200_000 * (1 + 0.01 * k), OPEX, f"c{k}")
        for name, (amt, stop) in standing.items():
            if p < stop:
                tx.append(T(f"EQ{k}{name[-1]}", f"{p}-{8 + int(name[-1]):02d}", "Revenue",
                            round(amt * RNG.uniform(0.92, 1.08), 2), name, segment="SMB", category="Equipment",
                            description="monthly equipment program"))
    steps = [{"period": ps[i], "prior_period": ps[i - 1], "score": False} for i in range(14, 19)]
    steps.append({"period": ps[19], "prior_period": ps[18],
                  "ground_truth": {"required_patterns": [r"has bought none since", r"annualised Revenue at risk",
                                                         r"(Carried from earlier runs, |Context from memory )PR-000\d"],
                                   "forbidden_patterns": [r"\bchurn", r"lost the customer"]}})
    cases.append((new_sequence("S04_silent_churn_sequence", "memory",
                               "Seven monthly programs stop one by one; by the sixth run memory names them", steps), tx))

    return cases


if __name__ == "__main__":
    shutil.rmtree(OUT, ignore_errors=True)
    n = 0
    for entry in build():
        case, tx = entry[0], entry[1]
        summ = entry[2] if len(entry) > 2 else None
        mem = entry[3] if len(entry) > 3 else None
        pol = entry[4] if len(entry) > 4 else None
        raw = entry[5] if len(entry) > 5 else None
        drop = entry[6] if len(entry) > 6 else ()
        write(case, tx, summ, mem, pol, raw, drop); n += 1
    tmp = os.path.join(HERE, "_tmp_memory.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    print(f"wrote {n} cases to {OUT}")
