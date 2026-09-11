"""Tests for structured diagnosis orchestration and one-level drilldown."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.alerts.severity import BusinessSeverity
from ops_workbench.diagnostics import (
    ContributionEngine,
    DiagnosisEngine,
    DiagnosisStatus,
    EvidenceKind,
    render_diagnosis_summary,
)
from ops_workbench.diagnostics.models import AnomalyEvent, ContributionDirection
from ops_workbench.metrics import MetricEngine, MetricStatus
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report


def _metric_engine(tmp_path: Path, dataframe: pd.DataFrame) -> MetricEngine:
    standardized = standardize(dataframe)
    report = build_quality_report(standardized)
    assert report.is_valid
    database_path = tmp_path / "diagnosis.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    return MetricEngine(database_path=database_path)


def _diagnostic_frame(*, include_refund: bool = True) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for offset in range(8):
        current_date = date(2025, 1, 1) + timedelta(days=offset)
        current = offset == 7
        rows.extend(
            [
                {
                    "date": current_date,
                    "business_line": "L1",
                    "channel": "C1",
                    "product": "P1",
                    "team": "T1",
                    "salesperson": "S1",
                    "leads": 100,
                    "valid_leads": 30 if current else 80,
                    "paid_users": 5 if current else 20,
                    "gross_revenue": "800.00" if current else "1000.00",
                    **({"refund_amount": "200.00" if current else "100.00"} if include_refund else {}),
                },
                {
                    "date": current_date,
                    "business_line": "L1",
                    "channel": "C1",
                    "product": "P2",
                    "team": "T2",
                    "salesperson": "S2",
                    "leads": 100,
                    "valid_leads": 90 if current else 80,
                    "paid_users": 25 if current else 20,
                    "gross_revenue": "1000.00",
                    **({"refund_amount": "100.00"} if include_refund else {}),
                },
            ]
        )
    return pd.DataFrame(rows)


def _event(
    metric_id: str = "valid_lead_rate",
    *,
    event_date: date = date(2025, 1, 8),
    dimension: str | None = "channel",
    dimension_value: str | None = "C1",
    comparison_type: str = "rolling_7d_average",
) -> AnomalyEvent:
    return AnomalyEvent(
        rule_id="test_rule",
        rule_name="Test rule",
        metric_id=metric_id,
        metric_name=metric_id,
        date=event_date,
        dimension=dimension,
        dimension_value=dimension_value,
        current_value=Decimal("0.60"),
        baseline_value=Decimal("0.80"),
        delta=Decimal("-0.20"),
        relative_change=Decimal("-0.25"),
        percentage_point_change=Decimal("-0.20"),
        severity=BusinessSeverity.CRITICAL,
        comparison_type=comparison_type,
        current_status=MetricStatus.AVAILABLE,
        baseline_status=MetricStatus.AVAILABLE,
        evidence="channel=C1的指标当前为60%，过去7日基线为80%。",
    )


@pytest.fixture
def diagnosis_engine(tmp_path: Path) -> DiagnosisEngine:
    return DiagnosisEngine(_metric_engine(tmp_path, _diagnostic_frame()))


def test_scope_component_baselines_and_trigger_dimension(
    diagnosis_engine: DiagnosisEngine,
) -> None:
    result = diagnosis_engine.diagnose_event(
        _event(),
        filters={"business_line": "L1"},
    )
    observations = {item.metric_id: item for item in result.component_observations}

    assert result.status == DiagnosisStatus.COMPLETE
    assert result.scope_filters == {"business_line": "L1", "channel": "C1"}
    assert result.anomaly_comparison_type == "rolling_7d_average"
    assert result.diagnostic_comparison_type == "previous_week"
    assert observations["valid_leads"].current_value == 120
    assert observations["valid_leads"].baseline_value == 160
    assert observations["valid_leads"].delta == Decimal(-40)
    assert observations["valid_leads"].relative_change == Decimal("-0.25")
    assert observations["valid_leads"].direction == ContributionDirection.DECREASE
    assert observations["leads"].delta == 0
    assert all(finding.dimension != "channel" for finding in result.drilldown_findings)
    assert all(finding.dimension != "business_line" for finding in result.drilldown_findings)
    assert any(item.dimension == "business_line" for item in result.skipped_dimensions)


def test_drilldown_reuses_contribution_and_limits_top_segments(
    tmp_path: Path,
) -> None:
    metric_engine = _metric_engine(tmp_path, _diagnostic_frame())
    real_contribution = ContributionEngine(metric_engine)

    class RecordingContribution:
        def __init__(self) -> None:
            self.metric_ids: list[str] = []

        def analyze_contribution(self, metric_id: str, *args: object, **kwargs: object) -> object:
            self.metric_ids.append(metric_id)
            return real_contribution.analyze_contribution(metric_id, *args, **kwargs)

    recording = RecordingContribution()
    result = DiagnosisEngine(
        metric_engine,
        contribution_engine=recording,
    ).diagnose_event(_event())

    assert recording.metric_ids
    assert set(recording.metric_ids) == {"valid_leads", "leads"}
    assert "valid_lead_rate" not in recording.metric_ids
    assert all(len(item.top_increases) <= 3 for item in result.drilldown_findings)
    assert all(len(item.top_decreases) <= 3 for item in result.drilldown_findings)
    assert all(len(item.top_movements) <= 3 for item in result.drilldown_findings)
    product = next(
        item
        for item in result.drilldown_findings
        if item.metric_id == "valid_leads" and item.dimension == "product"
    )
    assert product.top_decreases[0].dimension_value == "P1"
    assert product.top_increases[0].dimension_value == "P2"
    assert product.top_movements[0].dimension_value == "P1"
    assert product.reconciliation_status.value == "available"


def test_invalid_filter_and_scope_conflict_are_explicit(
    diagnosis_engine: DiagnosisEngine,
) -> None:
    with pytest.raises(ValueError, match="Invalid filter field"):
        diagnosis_engine.diagnose_event(_event(), filters={"date": "2025-01-08"})
    conflict = diagnosis_engine.diagnose_event(
        _event(),
        filters={"channel": "other"},
    )
    assert conflict.status == DiagnosisStatus.INSUFFICIENT_DATA
    assert "conflicts" in str(conflict.reason)


def test_partial_diagnosis_preserves_missing_component(tmp_path: Path) -> None:
    engine = DiagnosisEngine(
        _metric_engine(tmp_path, _diagnostic_frame(include_refund=False))
    )
    result = engine.diagnose_event(
        _event(
            "refund_rate_amount",
            dimension="product",
            dimension_value="P1",
        )
    )
    observations = {item.metric_id: item for item in result.component_observations}

    assert result.status == DiagnosisStatus.PARTIAL
    assert observations["refund_amount"].current_value is None
    assert observations["refund_amount"].current_status == MetricStatus.UNAVAILABLE_MISSING_FIELD
    assert observations["gross_revenue"].current_status == MetricStatus.AVAILABLE
    assert any(item.metric_id == "gross_revenue" for item in result.drilldown_findings)
    assert any(item.metric_id == "refund_amount" for item in result.skipped_dimensions)


def test_no_data_is_insufficient_and_unsupported_recipe_is_structured(
    diagnosis_engine: DiagnosisEngine,
) -> None:
    no_data = diagnosis_engine.diagnose_event(
        _event(event_date=date(2026, 1, 1))
    )
    unsupported = diagnosis_engine.diagnose_event(_event("impressions"))

    assert no_data.status == DiagnosisStatus.INSUFFICIENT_DATA
    assert not no_data.drilldown_findings
    assert unsupported.status == DiagnosisStatus.UNSUPPORTED
    assert unsupported.diagnostic_comparison_type is None
    assert "No diagnostic recipe" in str(unsupported.reason)


def test_unavailable_candidate_dimension_is_skipped(tmp_path: Path) -> None:
    dataframe = _diagnostic_frame().drop(columns=["product"])
    result = DiagnosisEngine(_metric_engine(tmp_path, dataframe)).diagnose_event(_event())
    assert result.status == DiagnosisStatus.PARTIAL
    assert any(
        item.dimension == "product" and "no classified values" in item.reason
        for item in result.skipped_dimensions
    )
    assert all(item.dimension != "product" for item in result.drilldown_findings)


def test_additive_event_observes_components_and_direct_metric(
    diagnosis_engine: DiagnosisEngine,
) -> None:
    result = diagnosis_engine.diagnose_event(
        _event("net_revenue", dimension="channel", dimension_value="C1")
    )
    assert result.status == DiagnosisStatus.COMPLETE
    assert {item.metric_id for item in result.component_observations} == {
        "gross_revenue",
        "refund_amount",
    }
    finding_metrics = {item.metric_id for item in result.drilldown_findings}
    assert {"net_revenue", "gross_revenue", "refund_amount"} <= finding_metrics
    assert all(item.dimension != "channel" for item in result.drilldown_findings)
    assert any(
        item.metric_id == "net_revenue" and item.dimension == "channel"
        for item in result.skipped_dimensions
    )


def test_evidence_kinds_language_recommendations_and_limitations(
    diagnosis_engine: DiagnosisEngine,
) -> None:
    result = diagnosis_engine.diagnose_event(_event())
    kinds = {item.kind for item in result.evidence}
    assert {EvidenceKind.FACT, EvidenceKind.DIAGNOSTIC, EvidenceKind.RECOMMENDATION} <= kinds
    assert result.recommended_checks
    assert result.limitations
    rendered = render_diagnosis_summary(result)
    built_in_text = rendered + "\n" + "\n".join(item.message for item in result.evidence)
    for forbidden in ("导致", "造成", "证明", "根因是", "一定是"):
        assert forbidden not in built_in_text
