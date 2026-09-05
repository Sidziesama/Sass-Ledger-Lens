"""Compare persisted investigation outcomes across repeated runs."""

from decimal import Decimal

from pydantic import Field

from src.ingestion.models import InvestigationRun, LedgerModel


class AccountHistoryChange(LedgerModel):
    account: str
    prior_run_variance: Decimal | None
    current_run_variance: Decimal | None
    change_between_runs: Decimal | None
    prior_evidence_sufficient: bool | None
    current_evidence_sufficient: bool | None


class RunComparison(LedgerModel):
    previous_run_id: str
    current_run_id: str
    account_changes: list[AccountHistoryChange]
    added_drivers: list[str] = Field(default_factory=list)
    removed_drivers: list[str] = Field(default_factory=list)
    current_review_statuses: list[str] = Field(default_factory=list)


def compare_investigation_runs(
    previous: InvestigationRun, current: InvestigationRun
) -> RunComparison:
    previous_accounts = {item.account: item for item in previous.accounts}
    current_accounts = {item.account: item for item in current.accounts}
    changes = []
    for account in sorted(previous_accounts.keys() | current_accounts.keys()):
        prior = previous_accounts.get(account)
        latest = current_accounts.get(account)
        changes.append(
            AccountHistoryChange(
                account=account,
                prior_run_variance=prior.variance if prior else None,
                current_run_variance=latest.variance if latest else None,
                change_between_runs=(
                    latest.variance - prior.variance if prior and latest else None
                ),
                prior_evidence_sufficient=prior.evidence_sufficient if prior else None,
                current_evidence_sufficient=(latest.evidence_sufficient if latest else None),
            )
        )

    def driver_keys(run: InvestigationRun) -> set[str]:
        return {f"{claim.driver_dimension}: {claim.driver_value}" for claim in run.claims}

    previous_drivers = driver_keys(previous)
    current_drivers = driver_keys(current)
    return RunComparison(
        previous_run_id=previous.run_id,
        current_run_id=current.run_id,
        account_changes=changes,
        added_drivers=sorted(current_drivers - previous_drivers),
        removed_drivers=sorted(previous_drivers - current_drivers),
        current_review_statuses=[feedback.status for feedback in current.feedback],
    )
