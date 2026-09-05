from datetime import date
from decimal import Decimal

from src.ingestion.models import BusinessContext, InvestigationRun, RunAccountSummary
from src.memory import JsonMemoryStore


def test_memory_reports_consistent_range_expired_and_rejected(tmp_path):
    store = JsonMemoryStore(tmp_path)
    for context in (
        BusinessContext(
            context_id="PR-0001",
            subject="Revenue",
            description="normal",
            valid_from=date(2026, 1, 1),
            learned_min_pct=Decimal("5"),
            learned_max_pct=Decimal("15"),
            source_type="user_verified",
            status="confirmed",
        ),
        BusinessContext(
            context_id="PR-0002",
            subject="Revenue",
            description="old",
            valid_until=date(2026, 1, 31),
        ),
        BusinessContext(
            context_id="PR-0003",
            subject="Revenue",
            description="wrong",
            status="rejected",
            reason="reviewer disproved it",
        ),
    ):
        store.save_business_context(context)
    notes = store.assess_business_context(
        subject="Revenue", as_of=date(2026, 2, 1), observed_variance_pct=Decimal("20")
    )
    assert "PR-0001 exceeds the learned range" in notes
    assert any("PR-0002 not applied: expired" in note for note in notes)
    assert "PR-0003 not applied: rejected (reviewer disproved it)" in notes


def test_saving_each_run_writes_a_prior_for_the_next_run(tmp_path):
    store = JsonMemoryStore(tmp_path)
    store.save_investigation_run(
        InvestigationRun(
            run_id="run-12345678",
            prior_period=date(2026, 1, 1),
            current_period=date(2026, 2, 1),
            accounts=[
                RunAccountSummary(
                    account="Revenue",
                    variance=Decimal("10"),
                    variance_pct=Decimal("10"),
                    coverage=Decimal("1"),
                    evidence_sufficient=True,
                )
            ],
        )
    )
    contexts = store.get_business_context(subject="Revenue", as_of=date(2026, 3, 1))
    assert contexts[0].context_id.startswith("PR-")
    assert contexts[0].source_type == "system_inferred"
    assert contexts[0].status == "proposed"
    assert (
        "consistent with PR-"
        in store.assess_business_context(
            subject="Revenue", as_of=date(2026, 3, 1), observed_variance_pct=Decimal("10")
        )[0]
    )
