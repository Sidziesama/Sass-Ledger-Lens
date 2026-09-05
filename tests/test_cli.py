import json

import pytest

from src.agent import FinancialTools, Investigator
from src.cli import build_artifact, main, parser, print_report
from src.ingestion import load_account_summaries, load_transactions


def test_cli_prints_report_and_exports_evidence(tmp_path, capsys):
    output = tmp_path / "investigation.json"
    exit_code = main(
        [
            "--prior",
            "2026-01-01",
            "--current",
            "2026-02-01",
            "--output",
            str(output),
        ]
    )
    report = capsys.readouterr().out
    artifact = json.loads(output.read_text())
    assert exit_code == 0
    assert "Revenue" in report
    assert "coverage=" in report
    assert artifact["accounts"][0]["claims"][0]["transactions"]
    assert artifact["accounts"][0]["explanation"]["grounded"] is True
    assert artifact["trace"]


def test_cli_rejects_reversed_periods():
    with pytest.raises(SystemExit):
        main(["--prior", "2026-02-01", "--current", "2026-01-01"])


def test_cli_reports_no_material_variances(tmp_path, capsys):
    main(
        [
            "--prior",
            "2026-01-01",
            "--current",
            "2026-02-01",
            "--absolute-threshold",
            "9999999",
            "--memory",
            str(tmp_path),
        ]
    )
    assert "No material variances found." in capsys.readouterr().out


def test_cli_llm_flag_requires_configuration(monkeypatch):
    for name in (
        "LEDGER_LENS_LLM_BASE_URL",
        "LEDGER_LENS_LLM_API_KEY",
        "LEDGER_LENS_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="--llm requires"):
        main(["--prior", "2026-01-01", "--current", "2026-02-01", "--llm"])


def test_cli_falls_back_when_configured_provider_fails(capsys):
    class FailingProvider:
        name = "failing-provider"

        def generate(self, *, system, prompt):
            raise TimeoutError("local model exceeded its budget")

    args = parser().parse_args(["--prior", "2026-01-01", "--current", "2026-02-01"])
    summaries = load_account_summaries(args.summaries)
    transactions = load_transactions(args.transactions)
    result = Investigator(FinancialTools(summaries, transactions)).investigate(
        args.prior, args.current, args.absolute_threshold, args.percentage_threshold
    )
    artifact = build_artifact(result, transactions, [], FailingProvider())
    print_report(artifact)
    assert artifact["accounts"][0]["explanation"]["provider"] == "deterministic-template"
    assert "TimeoutError" in artifact["accounts"][0]["explanation_error"]
    assert "used deterministic fallback" in capsys.readouterr().out


def test_cli_debug_prints_safe_fallback_reason(capsys):
    artifact = {
        "prior_period": "2026-01-01",
        "current_period": "2026-02-01",
        "accounts": [
            {
                "account": "Revenue",
                "prior_amount": "100",
                "current_amount": "150",
                "variance": "50",
                "variance_pct": "50",
                "evidence_sufficient": True,
                "investigated_dimension": "customer",
                "coverage": "1",
                "drivers": [],
                "explanation": None,
                "explanation_error": "LLMResponseError: finish_reason=length",
            }
        ],
    }
    print_report(artifact, llm_debug=True)
    assert "LLM diagnostic: LLMResponseError: finish_reason=length" in capsys.readouterr().out
