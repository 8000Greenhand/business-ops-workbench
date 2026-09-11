"""Full Demo integration for M2B trends, comparisons, rolling, and funnel."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from ops_workbench.ingestion.file_loader import load_source
from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.metrics import (
    MetricComparisonStatus,
    MetricEngine,
    MetricStatus,
    calculate_funnel,
    compare_metric,
    get_metric_series,
    get_rolling_series,
)
from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report
from scripts.generate_demo_data import ANOMALY_CHANNEL, generate_demo_data


def test_full_demo_m2b_outputs_are_finite_and_day_200_is_lower(
    tmp_path: Path,
) -> None:
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

    day_200 = date(2025, 7, 19)
    filters = {"channel": ANOMALY_CHANNEL}
    previous_week = compare_metric(
        engine,
        "valid_lead_rate",
        day_200,
        day_200,
        comparison="previous_week",
        filters=filters,
    )
    rolling_average = compare_metric(
        engine,
        "valid_lead_rate",
        day_200,
        day_200,
        comparison="rolling_7d_average",
        filters=filters,
    )
    assert previous_week.status == MetricComparisonStatus.AVAILABLE
    assert rolling_average.status == MetricComparisonStatus.AVAILABLE
    assert previous_week.current.value < previous_week.baseline.value
    assert rolling_average.current.value < rolling_average.baseline.value

    conversion = get_metric_series(
        engine, "conversion_rate", "2025-01-01", "2025-12-31"
    )
    assert len(conversion.points) == 365
    assert all(point.status == MetricStatus.AVAILABLE for point in conversion.points)
    assert all(
        isinstance(point.value, Decimal) and point.value.is_finite()
        for point in conversion.points
    )

    revenue = get_metric_series(
        engine, "net_revenue", "2025-06-01", "2025-06-30"
    )
    rolling_revenue = get_rolling_series(
        engine, "net_revenue", "2025-06-01", "2025-06-30"
    )
    assert len(revenue.points) == len(rolling_revenue.points) == 30
    assert all(point.status == MetricStatus.AVAILABLE for point in revenue.points)
    assert all(point.status == MetricStatus.AVAILABLE for point in rolling_revenue.points)

    full_funnel = calculate_funnel(engine)
    channel_funnel = calculate_funnel(engine, filters=filters)
    for funnel in (full_funnel, channel_funnel):
        assert all(stage.status == MetricStatus.AVAILABLE for stage in funnel.stages)
        assert all(step.status == MetricStatus.AVAILABLE for step in funnel.step_rates)
        assert all(outcome.status == MetricStatus.AVAILABLE for outcome in funnel.outcomes)
