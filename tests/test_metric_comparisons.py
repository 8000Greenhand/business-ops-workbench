"""Tests for equal-period, prior-week, and rolling comparisons."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.metrics import MetricEngine, MetricStatus
from ops_workbench.metrics.comparisons import (
    MetricComparisonStatus,
    compare_metric,
)
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report


@pytest.fixture
def comparison_engine(tmp_path: Path) -> MetricEngine:
    dataframe = pd.DataFrame(
        {
            "date": [
                "2025-01-01",
                "2025-01-02",
                "2025-01-03",
                "2025-01-04",
                "2025-01-08",
                "2025-01-09",
            ],
            "channel": ["渠道A"] * 6,
            "leads": [10, 20, 0, 40, 100, 200],
            "valid_leads": [4, 10, 0, 20, 50, 100],
            "paid_users": [1, 2, 0, 8, 10, 20],
            "gross_revenue": [
                "100.00",
                "200.00",
                "0.00",
                "400.00",
                "800.00",
                "1600.00",
            ],
        }
    )
    standardized = standardize(dataframe)
    report = build_quality_report(standardized)
    assert report.is_valid
    database_path = tmp_path / "comparisons.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    return MetricEngine(database_path=database_path)


def test_previous_period_single_day_and_zero_baseline(
    comparison_engine: MetricEngine,
) -> None:
    result = compare_metric(
        comparison_engine, "leads", "2025-01-04", "2025-01-04"
    )
    assert result.current.value == 40
    assert result.baseline.start_date == result.baseline.end_date == date(2025, 1, 3)
    assert result.baseline.value == 0
    assert result.delta == Decimal(40)
    assert result.relative_change is None
    assert result.percentage_point_change is None


def test_previous_period_is_equal_length_and_non_overlapping(
    comparison_engine: MetricEngine,
) -> None:
    result = compare_metric(
        comparison_engine, "leads", "2025-01-03", "2025-01-04"
    )
    assert (result.current.start_date, result.current.end_date) == (
        date(2025, 1, 3),
        date(2025, 1, 4),
    )
    assert (result.baseline.start_date, result.baseline.end_date) == (
        date(2025, 1, 1),
        date(2025, 1, 2),
    )
    assert result.current.value == 40
    assert result.baseline.value == 30
    assert result.delta == Decimal(10)
    assert result.relative_change == Decimal(1) / Decimal(3)


def test_previous_week_shifts_the_exact_range_by_seven_days(
    comparison_engine: MetricEngine,
) -> None:
    result = compare_metric(
        comparison_engine,
        "leads",
        "2025-01-08",
        "2025-01-09",
        comparison="previous_week",
    )
    assert (result.baseline.start_date, result.baseline.end_date) == (
        date(2025, 1, 1),
        date(2025, 1, 2),
    )
    assert result.current.value == 300
    assert result.baseline.value == 30
    assert result.relative_change == Decimal(9)


def test_percentage_comparison_separates_points_and_relative_change(
    comparison_engine: MetricEngine,
) -> None:
    result = compare_metric(
        comparison_engine,
        "valid_lead_rate",
        "2025-01-08",
        "2025-01-08",
        comparison="previous_week",
    )
    assert result.current.value == Decimal("0.5")
    assert result.baseline.value == Decimal("0.4")
    assert result.percentage_point_change == Decimal("0.1")
    assert result.relative_change == Decimal("0.25")


def test_baseline_no_data_does_not_become_zero(comparison_engine: MetricEngine) -> None:
    result = compare_metric(
        comparison_engine, "leads", "2025-01-01", "2025-01-01"
    )
    assert result.status == MetricComparisonStatus.UNAVAILABLE_BASELINE
    assert result.baseline.status == MetricStatus.UNAVAILABLE_NO_DATA
    assert result.delta is result.relative_change is None


def test_current_and_dependency_unavailable_are_explicit(
    comparison_engine: MetricEngine,
) -> None:
    current = compare_metric(
        comparison_engine, "refund_amount", "2025-01-08", "2025-01-08"
    )
    dependency = compare_metric(
        comparison_engine, "revenue_per_lead", "2025-01-08", "2025-01-08"
    )
    assert current.status == MetricComparisonStatus.UNAVAILABLE_CURRENT
    assert current.current.status == MetricStatus.UNAVAILABLE_MISSING_FIELD
    assert dependency.status == MetricComparisonStatus.UNAVAILABLE_CURRENT
    assert dependency.current.status == MetricStatus.UNAVAILABLE_DEPENDENCY


def test_rolling_comparison_uses_prior_daily_average_for_additive_metric(
    comparison_engine: MetricEngine,
) -> None:
    result = compare_metric(
        comparison_engine,
        "leads",
        "2025-01-08",
        "2025-01-08",
        comparison="rolling_7d_average",
    )
    assert result.baseline.start_date == date(2025, 1, 1)
    assert result.baseline.end_date == date(2025, 1, 7)
    assert result.baseline.value == Decimal("17.5")
    assert result.current.value == 100


def test_rolling_ratio_comparison_aggregates_dependencies(
    comparison_engine: MetricEngine,
) -> None:
    result = compare_metric(
        comparison_engine,
        "conversion_rate",
        "2025-01-08",
        "2025-01-08",
        comparison="rolling_7d_average",
    )
    assert result.baseline.value == Decimal(11) / Decimal(34)
    assert result.baseline.value != (
        Decimal("0.25") + Decimal("0.2") + Decimal("0.4")
    ) / 3


def test_invalid_comparison_and_multi_day_rolling_are_rejected(
    comparison_engine: MetricEngine,
) -> None:
    with pytest.raises(ValueError, match="Unsupported comparison"):
        compare_metric(
            comparison_engine,
            "leads",
            "2025-01-01",
            "2025-01-01",
            comparison="year_over_year",
        )
    with pytest.raises(ValueError, match="single current day"):
        compare_metric(
            comparison_engine,
            "leads",
            "2025-01-07",
            "2025-01-08",
            comparison="rolling_7d_average",
        )
