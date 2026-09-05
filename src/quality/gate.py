"""Pre-investigation quality gate with explicit, amount-bearing findings."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from pydantic import Field

from src.ingestion.models import AccountSummary, LedgerModel, Transaction


class QualityFlag(LedgerModel):
    code: str
    severity: str
    message: str
    account: str | None = None
    amount: Decimal | None = None
    transaction_ids: list[str] = Field(default_factory=list)


class QualityReport(LedgerModel):
    flags: list[QualityFlag] = Field(default_factory=list)

    def blockers_for(self, account: str) -> list[QualityFlag]:
        return [f for f in self.flags if f.account == account and f.severity == "blocker"]


def _counterparty(tx: Transaction) -> str | None:
    return tx.customer or tx.vendor


def _month_index(value: date) -> int:
    return value.year * 12 + value.month


def run_quality_gate(
    summaries: list[AccountSummary],
    transactions: list[Transaction],
    prior_period: date,
    current_period: date,
) -> QualityReport:
    flags: list[QualityFlag] = []

    periods = sorted({row.period for row in summaries})
    for left, right in zip(periods, periods[1:], strict=False):
        if _month_index(right) - _month_index(left) > 1:
            flags.append(
                QualityFlag(
                    code="period_gap",
                    severity="warning",
                    message=f"period gap between {left} and {right}",
                )
            )

    summary_totals: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    transaction_totals: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    for row in summaries:
        if row.period in (prior_period, current_period):
            summary_totals[(row.account, row.period)] += row.amount
    for tx in transactions:
        if tx.period in (prior_period, current_period):
            transaction_totals[(tx.account, tx.period)] += tx.amount
        if tx.transaction_date and (tx.transaction_date.year, tx.transaction_date.month) != (
            tx.period.year,
            tx.period.month,
        ):
            flags.append(
                QualityFlag(
                    code="cutoff",
                    severity="warning",
                    account=tx.account,
                    transaction_ids=[tx.transaction_id],
                    message=f"cutoff mismatch: {tx.transaction_id} is dated {tx.transaction_date} but posted to {tx.period}",
                )
            )

    for key, expected in summary_totals.items():
        actual = transaction_totals[key]
        gap = expected - actual
        if gap:
            account, period = key
            flags.append(
                QualityFlag(
                    code="reconciliation_gap",
                    severity="blocker",
                    account=account,
                    amount=abs(gap),
                    message=f"cannot reliably attribute {account}: gap of ${abs(gap):,.2f} in {period}",
                )
            )

    variants: dict[str, set[str]] = defaultdict(set)
    for tx in transactions:
        party = _counterparty(tx)
        if party:
            variants[party.casefold().strip()].add(party)
    for names in variants.values():
        if len(names) > 1:
            flags.append(
                QualityFlag(
                    code="naming_variant",
                    severity="warning",
                    message=f"naming variants treated as one counterparty: {' / '.join(sorted(names))}",
                )
            )

    dated = [tx for tx in transactions if tx.transaction_date and _counterparty(tx)]
    for index, left in enumerate(dated):
        for right in dated[index + 1 :]:
            if left.transaction_id == right.transaction_id:
                continue
            same = (
                left.account == right.account
                and left.amount == right.amount
                and _counterparty(left).casefold().strip()
                == _counterparty(right).casefold().strip()
            )
            if same and abs((left.transaction_date - right.transaction_date).days) <= 2:
                flags.append(
                    QualityFlag(
                        code="near_duplicate",
                        severity="warning",
                        account=left.account,
                        amount=abs(left.amount),
                        transaction_ids=[left.transaction_id, right.transaction_id],
                        message=f"possible near-duplicate: same payee and amount within 2 days ({left.transaction_id}, {right.transaction_id})",
                    )
                )

    for account in sorted({tx.account for tx in transactions}):
        amounts = [tx.amount for tx in transactions if tx.account == account]
        if amounts and any(value > 0 for value in amounts) and any(value < 0 for value in amounts):
            flags.append(
                QualityFlag(
                    code="sign_inconsistency",
                    severity="warning",
                    account=account,
                    message=f"sign check: {account} contains both positive and negative postings",
                )
            )

    return QualityReport(flags=flags)
