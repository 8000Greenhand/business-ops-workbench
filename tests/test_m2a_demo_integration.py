"""Full Demo integration for the configurable M2A metric engine."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from ops_workbench.ingestion.file_loader import load_source
from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.metrics import MetricEngine, MetricStatus
from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report
from scripts.generate_demo_data import ANOMALY_CHANNEL, generate_demo_data


def test_full_demo_metrics_grouping_and_day_200_signal(tmp_path: Path) -> None:
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
    engine = MetricEngine(database_path=database_path)

    metrics = engine.calculate_metrics(
        (
            "leads",
            "valid_lead_rate",
            "conversion_rate",
            "gross_revenue",
            "refund_rate_amount",
            "net_revenue",
            "avg_order_value",
            "revenue_per_lead",
        )
    )
    assert all(result.status == MetricStatus.AVAILABLE for result in metrics)
    assert all(
        result.value is not None
        and (not isinstance(result.value, Decimal) or result.value.is_finite())
        for result in metrics
    )

    for dimension, expected_count in (("business_line", 5), ("channel", 8), ("team", 6)):
        for metric_id in ("net_revenue", "conversion_rate"):
            grouped = engine.calculate_metric_by_dimension(metric_id, dimension)
            assert len(grouped) == expected_count
            assert all(row.status == MetricStatus.AVAILABLE for row in grouped)
            assert all(
                row.value is not None
                and (not isinstance(row.value, Decimal) or row.value.is_finite())
                for row in grouped
            )

    anomaly_date = demo.metadata["injected_anomalies"][0]["date"]
    anomaly_day = engine.calculate_metric(
        "valid_lead_rate",
        start_date=anomaly_date,
        end_date=anomaly_date,
        filters={"channel": ANOMALY_CHANNEL},
    )
    prior_end = date.fromisoformat(str(anomaly_date)) - timedelta(days=1)
    prior_start = prior_end - timedelta(days=6)
    normal = engine.calculate_metric(
        "valid_lead_rate",
        start_date=prior_start,
        end_date=prior_end,
        filters={"channel": ANOMALY_CHANNEL},
    )
    assert anomaly_day.status == normal.status == MetricStatus.AVAILABLE
    assert anomaly_day.value < normal.value * Decimal("0.90")
