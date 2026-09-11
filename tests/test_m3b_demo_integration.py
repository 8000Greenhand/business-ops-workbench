"""Demo integration for additive contribution ground-truth relationships."""

from pathlib import Path

from ops_workbench.diagnostics import ContributionEngine, ContributionStatus
from ops_workbench.diagnostics.models import ContributionDirection
from ops_workbench.ingestion.file_loader import load_source
from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.metrics import MetricEngine
from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report
from scripts.generate_demo_data import generate_demo_data


def test_demo_ground_truth_segments_and_net_revenue_reconcile(tmp_path: Path) -> None:
    demo = generate_demo_data(tmp_path / "demo", seed=42)
    loaded = load_source(demo.csv_path)
    identity = {field: field for field in CANONICAL_COLUMN_NAMES}
    standardized = standardize(
        apply_mapping(loaded.dataframe, identity),
        source_columns=loaded.metadata.source_columns,
        source_field_mapping=identity,
    )
    report = build_quality_report(standardized)
    database_path = tmp_path / "demo.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    contribution = ContributionEngine(MetricEngine(database_path=database_path))

    additive_metric = {
        "valid_lead_rate": ("valid_leads", ContributionDirection.DECREASE),
        "conversion_rate": ("paid_users", ContributionDirection.DECREASE),
        "refund_rate_amount": ("refund_amount", ContributionDirection.INCREASE),
    }
    for expected in demo.metadata["injected_anomalies"]:
        metric_id, direction = additive_metric[str(expected["metric"])]
        result = contribution.analyze_contribution(
            metric_id,
            str(expected["date"]),
            str(expected["date"]),
            str(expected["dimension"]),
            comparison="previous_week",
        )
        segment = next(
            item
            for item in result.segments
            if item.dimension_value == expected["value"]
        )
        assert result.status == ContributionStatus.AVAILABLE
        assert segment.direction == direction
        assert segment.rank_by_absolute_change == 1
        assert result.reconciliation_difference == 0

    for dimension in ("business_line", "channel", "team"):
        result = contribution.analyze_contribution(
            "net_revenue",
            "2025-08-01",
            "2025-08-30",
            dimension,
            comparison="previous_period",
        )
        assert result.status == ContributionStatus.AVAILABLE
        assert result.current_reconciliation_difference == 0
        assert result.baseline_reconciliation_difference == 0
        assert result.reconciliation_difference == 0
