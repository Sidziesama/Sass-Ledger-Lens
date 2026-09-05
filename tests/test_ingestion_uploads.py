from io import BytesIO, StringIO

import pytest
from pydantic import ValidationError

from src.ingestion import load_account_summaries, load_transactions, validate_dataset


def test_file_like_and_bytes_uploads_are_supported():
    summaries = load_account_summaries(
        BytesIO(b'[{"period":"2026-01-01","account":"Revenue","amount":"10"}]')
    )
    transactions = load_transactions(
        StringIO(
            '[{"transaction_id":"t1","period":"2026-01-01","account":"Revenue","amount":"10"}]'
        )
    )
    assert summaries[0].amount == transactions[0].amount
    assert validate_dataset(summaries, transactions) == []


def test_upload_rejects_unknown_fields():
    payload = b'[{"period":"2026-01-01","account":"Revenue","amount":"10","mystery":1}]'
    with pytest.raises(ValidationError, match="mystery"):
        load_account_summaries(payload)


def test_upload_rejects_duplicate_transaction_ids():
    summaries = load_account_summaries(
        b'[{"period":"2026-01-01","account":"Revenue","amount":"20"}]'
    )
    transactions = load_transactions(
        b'[{"transaction_id":"duplicate","period":"2026-01-01","account":"Revenue","amount":"10"},'
        b'{"transaction_id":"duplicate","period":"2026-01-01","account":"Revenue","amount":"10"}]'
    )
    with pytest.raises(ValueError, match="duplicate transaction IDs"):
        validate_dataset(summaries, transactions)


def test_upload_reports_reconciliation_warning():
    summaries = load_account_summaries(
        b'[{"period":"2026-01-01","account":"Revenue","amount":"20"}]'
    )
    transactions = load_transactions(
        b'[{"transaction_id":"t1","period":"2026-01-01","account":"Revenue","amount":"10"}]'
    )
    warnings = validate_dataset(summaries, transactions)
    assert "totals 10 USD" in warnings[0]
