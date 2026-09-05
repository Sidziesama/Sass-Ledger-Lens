"""Ledger Lens Streamlit dashboard."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from src.agent import FinancialTools, Investigator
from src.evidence import build_claim_lineage
from src.explanation import EvidenceBoundExplainer, TemplateExplanationProvider
from src.ingestion.loaders import load_account_summaries, load_transactions
from src.ingestion.models import (
    EvidenceClaim,
    InvestigationRun,
    ReviewerFeedback,
    RunAccountSummary,
)
from src.ingestion.validation import validate_dataset
from src.memory import JsonMemoryStore, compare_investigation_runs
from src.observability import InMemoryTraceObserver

ROOT = Path(__file__).parents[1]
SAMPLE = ROOT / "data" / "sample"
MEMORY = ROOT / "data" / "memory"


def money(value: Decimal) -> str:
    return f"${value:,.0f}"


def signed_money(value: Decimal) -> str:
    return f"{value:+,.0f} USD"


def evidence_summary(account) -> str:
    variance = account.variance
    direction = "increased" if variance.variance >= 0 else "decreased"
    percent = (
        "new from zero" if variance.variance_pct is None else f"{abs(variance.variance_pct):.1f}%"
    )
    if not account.drivers:
        return (
            f"{variance.account} {direction} by {money(abs(variance.variance))} ({percent}), "
            "but no transaction-backed driver explanation is available."
        )
    lead = account.drivers[0]
    return (
        f"{variance.account} {direction} by {money(abs(variance.variance))} ({percent}). "
        f"The largest {account.dimension} driver was {lead.driver} at "
        f"{signed_money(lead.variance)}, contributing {abs(lead.contribution_pct or 0):.1f}% "
        f"of the net change. The selected drivers explain "
        f"{account.stop_decision.coverage * 100:.1f}% of absolute driver movement."
    )


def claim_models(account, transactions) -> list[EvidenceClaim]:
    return [
        EvidenceClaim(
            claim_id=claim.claim_id,
            statement=(
                f"{claim.driver} contributed {signed_money(claim.calculation.variance)} "
                f"to {claim.account}."
            ),
            calculation=(
                f"{claim.calculation.current_amount} - {claim.calculation.prior_amount} "
                f"= {claim.calculation.variance}"
            ),
            driver_dimension=claim.dimension,
            driver_value=claim.driver,
            transaction_ids=[tx.transaction_id for tx in claim.transactions],
        )
        for claim in build_claim_lineage(account, transactions)
    ]


def run_dashboard(
    summaries, transactions, prior: date, current: date, absolute: Decimal, percentage: Decimal
):
    memory = JsonMemoryStore(MEMORY)
    observer = InMemoryTraceObserver()
    result = Investigator(
        FinancialTools(summaries, transactions), memory=memory, observer=observer
    ).investigate(prior, current, absolute, percentage)
    return result, transactions, observer, memory


st.set_page_config(page_title="Ledger Lens", page_icon="◉", layout="wide")
st.markdown(
    """
    <style>
    .stApp {background: linear-gradient(145deg, #07131d 0%, #0d2230 55%, #102b32 100%);}
    [data-testid="stMetric"] {background: rgba(255,255,255,.055); border: 1px solid rgba(126,231,206,.16); padding: 1rem; border-radius: 14px;}
    .eyebrow {color:#7ee7ce; letter-spacing:.14em; text-transform:uppercase; font-size:.75rem; font-weight:700;}
    .hero {font-size:2.8rem; line-height:1.05; font-weight:760; margin:.2rem 0 .7rem;}
    .subtle {color:#a9bac4; max-width:780px;}
    </style>
    <div class="eyebrow">Maximor Money Operations · Explain the Change</div>
    <div class="hero">Ledger Lens</div>
    <div class="subtle">A transaction-backed variance investigation workspace. Python calculates; the agent investigates; every explanation carries evidence.</div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Investigation controls")
    st.subheader("Data source")
    summary_upload = st.file_uploader(
        "Monthly summaries JSON", type=["json"], help="Upload together with transaction detail."
    )
    transaction_upload = st.file_uploader(
        "Transactions JSON", type=["json"], help="Upload together with monthly summaries."
    )

if bool(summary_upload) != bool(transaction_upload):
    st.error("Upload both JSON files together, or remove the uploaded file to use sample data.")
    st.stop()

try:
    if summary_upload and transaction_upload:
        summaries_for_periods = load_account_summaries(summary_upload.getvalue())
        selected_transactions = load_transactions(transaction_upload.getvalue())
        dataset_label = f"Uploaded: {summary_upload.name} + {transaction_upload.name}"
        dataset_signature = (
            summary_upload.file_id,
            transaction_upload.file_id,
        )
    else:
        summaries_for_periods = load_account_summaries(SAMPLE / "monthly_summary.json")
        selected_transactions = load_transactions(SAMPLE / "transactions.json")
        dataset_label = "Bundled sample data"
        dataset_signature = ("sample", "sample")
    dataset_warnings = validate_dataset(summaries_for_periods, selected_transactions)
except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError) as exc:
    st.error("The selected dataset could not be validated.")
    st.code(str(exc), language=None)
    st.stop()

periods = sorted({row.period for row in summaries_for_periods})
if len(periods) < 2:
    st.error("Monthly summaries must contain at least two distinct periods.")
    st.stop()

with st.sidebar:
    st.caption(dataset_label)
    prior_period = st.selectbox("Prior period", periods, index=0)
    current_period = st.selectbox("Current period", periods, index=len(periods) - 1)
    absolute_threshold = Decimal(
        str(st.number_input("Absolute materiality (USD)", min_value=0, value=50000, step=10000))
    )
    percentage_threshold = Decimal(
        str(st.number_input("Percentage materiality", min_value=0.0, value=10.0, step=1.0))
    )
    investigate = st.button("Run investigation", type="primary", width="stretch")

if (
    investigate
    or "investigation" not in st.session_state
    or st.session_state.get("dataset_signature") != dataset_signature
):
    if current_period <= prior_period:
        st.error("Current period must be after the prior period.")
        st.stop()
    with st.spinner("Tracing changes to transaction evidence…"):
        st.session_state.investigation = run_dashboard(
            summaries_for_periods,
            selected_transactions,
            prior_period,
            current_period,
            absolute_threshold,
            percentage_threshold,
        )
        st.session_state.dataset_signature = dataset_signature

result, transactions, observer, memory = st.session_state.investigation

for warning in dataset_warnings:
    st.warning(warning)

if not result.accounts:
    st.info("No account variances meet the selected materiality thresholds.")
    st.stop()

total_change = sum((item.variance.variance for item in result.accounts), Decimal("0"))
supported = sum(item.stop_decision.should_stop for item in result.accounts)
metric_columns = st.columns(4)
metric_columns[0].metric("Material accounts", len(result.accounts))
metric_columns[1].metric("Net material change", signed_money(total_change))
metric_columns[2].metric("Evidence sufficient", f"{supported}/{len(result.accounts)}")
metric_columns[3].metric("Trace steps", len(observer.events))

overview, drivers_tab, evidence_tab, trace_tab, memory_tab, history_tab = st.tabs(
    [
        "Overview",
        "Drivers",
        "Evidence",
        "Investigation trace",
        "Memory & review",
        "Run history",
    ]
)

with overview:
    st.subheader("Material variances")
    st.dataframe(
        [
            {
                "Account": item.variance.account,
                "Prior": float(item.variance.prior_amount),
                "Current": float(item.variance.current_amount),
                "Variance": float(item.variance.variance),
                "Variance %": float(item.variance.variance_pct)
                if item.variance.variance_pct is not None
                else None,
                "Coverage %": float(item.stop_decision.coverage * 100),
                "Evidence": "Sufficient" if item.stop_decision.should_stop else "Needs review",
            }
            for item in result.accounts
        ],
        width="stretch",
        hide_index=True,
    )
    for item in result.accounts:
        st.markdown(f"#### {item.variance.account}")
        claims = build_claim_lineage(item, transactions)
        if claims:
            explanation = EvidenceBoundExplainer(TemplateExplanationProvider()).explain(
                item, claims
            )
            st.write(explanation.summary)
            st.caption(
                f"Grounded · {len(explanation.claim_ids)} verified claims · {explanation.provider}"
            )
        else:
            st.write(evidence_summary(item))

with drivers_tab:
    selected_account = st.selectbox(
        "Account", [item.variance.account for item in result.accounts], key="driver_account"
    )
    account = next(item for item in result.accounts if item.variance.account == selected_account)
    st.caption(f"Ranked by absolute contribution · dimension: {account.dimension}")
    driver_rows = [
        {
            "Driver": row.driver,
            "Prior": float(row.prior_amount),
            "Current": float(row.current_amount),
            "Variance": float(row.variance),
            "Contribution %": float(row.contribution_pct)
            if row.contribution_pct is not None
            else None,
        }
        for row in account.drivers
    ]
    if driver_rows:
        st.bar_chart(driver_rows, x="Driver", y="Variance", horizontal=True)
        st.dataframe(driver_rows, width="stretch", hide_index=True)
    else:
        st.warning("No transaction-backed drivers are available for this account.")

with evidence_tab:
    for account in result.accounts:
        st.subheader(account.variance.account)
        claims = build_claim_lineage(account, transactions)
        if not claims:
            st.warning("No supported claims available.")
        for claim in claims:
            with st.expander(f"{claim.driver} · {signed_money(claim.calculation.variance)}"):
                st.code(
                    f"{claim.calculation.current_amount} - {claim.calculation.prior_amount} = {claim.calculation.variance}",
                    language=None,
                )
                st.dataframe(
                    [tx.model_dump(mode="json") for tx in claim.transactions],
                    width="stretch",
                    hide_index=True,
                )

with trace_tab:
    st.dataframe(
        [event.as_prism_step() for event in observer.events],
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "This local trace uses the same trajectory shape submitted to PRISM when credentials are configured."
    )

with memory_tab:
    st.subheader("Remembered business context")
    contexts = [context for account in result.accounts for context in account.business_context]
    if contexts:
        for context in contexts:
            st.info(
                f"**{context.subject}** — {context.description}  \nSource: {context.source or 'unspecified'}"
            )
    else:
        st.caption("No relevant context was retrieved for this investigation.")

    all_claims = [
        claim for account in result.accounts for claim in claim_models(account, transactions)
    ]
    existing_ids = {run.run_id for run in memory.list_investigation_runs()}
    if result.run_id not in existing_ids:
        if st.button("Save investigation run"):
            memory.save_investigation_run(
                InvestigationRun(
                    run_id=result.run_id,
                    prior_period=result.prior_period,
                    current_period=result.current_period,
                    claims=all_claims,
                    accounts=[
                        RunAccountSummary(
                            account=account.variance.account,
                            variance=account.variance.variance,
                            variance_pct=account.variance.variance_pct,
                            coverage=account.stop_decision.coverage,
                            evidence_sufficient=account.stop_decision.evidence_sufficient,
                        )
                        for account in result.accounts
                    ],
                )
            )
            st.success("Investigation saved to structured memory.")
            st.rerun()
    else:
        st.success("Investigation is saved.")
        with st.form("review_form", clear_on_submit=True):
            reviewer = st.text_input("Reviewer", value="Finance team")
            status = st.selectbox("Decision", ["approved", "needs_revision", "rejected"])
            comment = st.text_area("Comment")
            submitted = st.form_submit_button("Save feedback")
        if submitted:
            memory.add_reviewer_feedback(
                result.run_id,
                ReviewerFeedback(reviewer=reviewer, status=status, comment=comment or None),
            )
            st.success("Reviewer feedback saved.")

with history_tab:
    st.subheader("Saved investigation history")
    saved_runs = memory.list_investigation_runs()
    if not saved_runs:
        st.caption("Save an investigation to begin building run history.")
    else:
        st.dataframe(
            [
                {
                    "Run": run.run_id,
                    "Prior period": run.prior_period.isoformat(),
                    "Current period": run.current_period.isoformat(),
                    "Accounts": len(run.accounts),
                    "Claims": len(run.claims),
                    "Latest review": run.feedback[-1].status if run.feedback else "unreviewed",
                }
                for run in reversed(saved_runs)
            ],
            width="stretch",
            hide_index=True,
        )

        selected_run_id = st.selectbox("Inspect run", [run.run_id for run in reversed(saved_runs)])
        selected_run = next(run for run in saved_runs if run.run_id == selected_run_id)
        if selected_run.accounts:
            st.dataframe(
                [account.model_dump(mode="json") for account in selected_run.accounts],
                width="stretch",
                hide_index=True,
            )

        if len(saved_runs) >= 2:
            st.markdown("#### Compare two runs")
            previous_id = st.selectbox(
                "Previous run", [run.run_id for run in saved_runs[:-1]], key="previous_run"
            )
            current_id = st.selectbox(
                "Current run", [run.run_id for run in saved_runs[1:]], key="current_run"
            )
            previous_run = next(run for run in saved_runs if run.run_id == previous_id)
            current_run = next(run for run in saved_runs if run.run_id == current_id)
            comparison = compare_investigation_runs(previous_run, current_run)
            st.dataframe(
                [change.model_dump(mode="json") for change in comparison.account_changes],
                width="stretch",
                hide_index=True,
            )
            left, right = st.columns(2)
            left.write("**New drivers**")
            left.write(comparison.added_drivers or ["None"])
            right.write("**Drivers no longer present**")
            right.write(comparison.removed_drivers or ["None"])
