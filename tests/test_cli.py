import json

import pytest

from src.cli import main


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
    monkeypatch.setattr("src.cli.load_settings", lambda: None)
    for name in (
        "LEDGER_LENS_LLM_BASE_URL",
        "LEDGER_LENS_LLM_API_KEY",
        "LEDGER_LENS_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="--llm requires"):
        main(["--prior", "2026-01-01", "--current", "2026-02-01", "--llm"])
