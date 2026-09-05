"""Exercise the product workflow using adversarial fixtures from reliability."""

import csv
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.cli import print_report
from src.ingestion.models import AccountSummary, Transaction
from src.workflow import run_workflow

FIXTURES = Path(__file__).parent / "fixtures/reliability"


def read_case(code):
    folder = next(FIXTURES.glob(code + "_*"))
    case = json.loads((folder / "case.json").read_text())

    def rows(name):
        with (folder / name).open() as handle:
            return list(csv.DictReader(handle))

    def period(value):
        return date.fromisoformat(value + "-01")

    summaries = [
        AccountSummary(
            period=period(r["period"]),
            account=r["account"],
            amount=r["amount"],
            currency=r.get("currency") or "USD",
        )
        for r in rows("monthly_summary.csv")
    ]
    transactions = [
        Transaction(
            transaction_id=r["transaction_id"],
            period=period(r["period"]),
            account=r["account"],
            amount=r["amount"],
            currency=r.get("currency") or "USD",
            customer=r.get("counterparty") if r["account"] == "Revenue" else None,
            vendor=r.get("counterparty") if r["account"] != "Revenue" else None,
            segment=r.get("segment") or None,
        )
        for r in rows("transactions.csv")
    ]
    return summaries, transactions, period(case["prior_period"]), period(case["period"])


def execute(code):
    return run_workflow(*read_case(code), Decimal("1000"), Decimal("0"))


@pytest.mark.parametrize(
    "code,account,issue",
    [
        ("C04", "Revenue", "unreconciled:"),
        ("C05", "Cloud Expense", "missing_transactions:"),
        ("D02", "Revenue", "missing_summary:"),
        ("D05", "Revenue", "currency_mismatch:"),
    ],
)
def test_unreliable_account_cannot_publish_explanation(code, account, issue):
    artifact = execute(code).artifact
    output = next(a for a in artifact["accounts"] if a["account"] == account)
    assert output["status"] == "blocked"
    assert any(i.startswith(issue) for i in output["reliability_issues"])
    assert output["claims"] == []
    assert output["explanation"] is None
    assert not output["evidence_sufficient"]


def test_duplicate_ids_produce_reviewable_blocked_run(capsys):
    execution = execute("D04")
    artifact = execution.artifact
    assert artifact["status"] == "blocked"
    assert artifact["accounts"] == []
    assert any(i["code"] == "DUPLICATE_TRANSACTION_ID" for i in artifact["data_quality_issues"])
    assert not any(e["step_type"] == "llm_call" for e in artifact["trace"])
    assert artifact["trace"][-1]["label"] == "Workflow completed"
    print_report(artifact)
    report = capsys.readouterr().out
    assert "DUPLICATE_TRANSACTION_ID" in report
    assert "No material variances" not in report


def test_unmapped_account_is_visible_even_if_materiality_skips_it(capsys):
    artifact = execute("D06").artifact
    assert artifact["status"] == "partial"
    assert any(
        i["code"] == "MISSING_ACCOUNT_MAPPING" and i["account"] == "Consulting"
        for i in artifact["data_quality_issues"]
    )
    print_report(artifact)
    assert "Consulting" in capsys.readouterr().out


def test_percentage_display_is_rounded_without_changing_financial_values(capsys):
    artifact = execute("C02").artifact
    explanations = [a for a in artifact["accounts"] if a["explanation"]]
    assert explanations
    for account in explanations:
        exact = Decimal(account["variance"]) / abs(Decimal(account["prior_amount"])) * 100
        assert Decimal(account["variance_pct"]) == exact
        assert f"{abs(exact):.2f}%" in account["explanation"]["summary"]
        assert not re.search(r"\d+\.\d{3,}%", account["explanation"]["summary"])
    print_report(artifact)
    assert not re.search(r"\d+\.\d{3,}%", capsys.readouterr().out)
