"""Cross-file validation for uploaded Ledger Lens datasets."""

from collections import Counter, defaultdict
from decimal import Decimal

from .models import AccountSummary, Transaction


def validate_dataset(summaries: list[AccountSummary], transactions: list[Transaction]) -> list[str]:
    if not summaries:
        raise ValueError("monthly summaries must contain at least one record")
    if not transactions:
        raise ValueError("transactions must contain at least one record")

    duplicate_ids = sorted(
        transaction_id
        for transaction_id, count in Counter(tx.transaction_id for tx in transactions).items()
        if count > 1
    )
    if duplicate_ids:
        raise ValueError(f"duplicate transaction IDs: {', '.join(duplicate_ids)}")

    summary_totals: dict[tuple, Decimal] = defaultdict(Decimal)
    transaction_totals: dict[tuple, Decimal] = defaultdict(Decimal)
    for row in summaries:
        summary_totals[(row.period, row.account, row.currency)] += row.amount
    for tx in transactions:
        transaction_totals[(tx.period, tx.account, tx.currency)] += tx.amount

    warnings = []
    for key, summary_total in sorted(summary_totals.items()):
        transaction_total = transaction_totals.get(key)
        if transaction_total is None:
            warnings.append(
                f"No transaction detail for {key[1]} in {key[0].isoformat()} ({key[2]})."
            )
        elif transaction_total != summary_total:
            warnings.append(
                f"Transaction detail for {key[1]} in {key[0].isoformat()} totals "
                f"{transaction_total} {key[2]}, but the summary is {summary_total} {key[2]}."
            )
    return warnings
