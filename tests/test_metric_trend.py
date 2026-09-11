"""Tests for daily and rolling metric series."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.metrics import MetricEngine, MetricStatus
from ops_workbench.metrics.trend import (
    get_metric_series,
    get_metric_series_by_dimension,
    get_rolling_series,
)
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report


@pytest.fixture
def trend_engine(tmp_path: Path) -> MetricEngine:
    dataframe = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-02", "2025-01-04", "2025-01-05", "2025-01-06", "2025-01-07"],
            "channel": ["渠道A", "渠道B", "渠道A", "渠道A", "渠道B", "渠道B"],
            "valid_leads": [2, 90, None, None, None, None],
            "paid_users": [1, 9, None, None, None, None],
            "gross_revenue": ["100.00", "900.00", None, None, None, None],
            "refund_amount": ["10.00", "90.00", None, None, None, None],
        }
    )
    standardized = standardize(dataframe)
    report = build_quality_report(standardized)
    assert report.is_valid
    database_path = tmp_path / "trend.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    return MetricEngine(database_path=database_path)


def test_single_and_multi_day_series(trend_engine: MetricEngine) -> None:
    single = get_metric_series(
        trend_engine, "conversion_rate", "2025-01-01", "2025-01-01"
    )
    multi = get_metric_series(
        trend_engine, "conversion_rate", "2025-01-01", "2025-01-03"
    )

    assert len(single.points) == 1
    assert single.points[0].value == Decimal("0.5")
    assert [point.value for point in multi.points[:2]] == [
        Decimal("0.5"),
        Decimal("0.1"),
    ]
    assert multi.points[2].date == date(2025, 1, 3)
    assert multi.points[2].value is None
    assert multi.points[2].status == MetricStatus.UNAVAILABLE_NO_DATA


def test_daily_derived_metric_uses_engine_semantics(trend_engine: MetricEngine) -> None:
    series = get_metric_series(
        trend_engine, "net_revenue", "2025-01-01", "2025-01-02"
    )
    assert [point.value for point in series.points] == [
        Decimal("90.00"),
        Decimal("810.00"),
    ]


def test_daily_ratio_aggregates_rows_before_division(tmp_path: Path) -> None:
    standardized = standardize(
        pd.DataFrame(
            {
                "date": ["2025-02-01", "2025-02-01"],
                "salesperson": ["销售A", "销售B"],
                "valid_leads": [2, 90],
                "paid_users": [1, 9],
            }
        )
    )
    report = build_quality_report(standardized)
    database_path = tmp_path / "daily-ratio.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    engine = MetricEngine(database_path=database_path)

    point = get_metric_series(
        engine, "conversion_rate", "2025-02-01", "2025-02-01"
    ).points[0]
    assert point.value == Decimal(10) / Decimal(92)
    assert point.value != Decimal("0.30")


def test_series_filter_and_date_range(trend_engine: MetricEngine) -> None:
    series = get_metric_series(
        trend_engine,
        "conversion_rate",
        "2025-01-01",
        "2025-01-02",
        filters={"channel": "渠道A"},
    )
    assert series.points[0].value == Decimal("0.5")
    assert series.points[1].status == MetricStatus.UNAVAILABLE_NO_DATA


def test_series_by_one_dimension_is_continuous(trend_engine: MetricEngine) -> None:
    series = get_metric_series_by_dimension(
        trend_engine,
        "net_revenue",
        "channel",
        "2025-01-01",
        "2025-01-02",
    )
    assert len(series.points) == 4
    by_key = {(point.date, point.dimension_value): point for point in series.points}
    assert by_key[(date(2025, 1, 1), "渠道A")].value == Decimal("90.00")
    assert by_key[(date(2025, 1, 1), "渠道B")].status == MetricStatus.UNAVAILABLE_NO_DATA
    assert by_key[(date(2025, 1, 2), "渠道B")].value == Decimal("810.00")


def test_invalid_grain_dimension_and_date_order_are_rejected(
    trend_engine: MetricEngine,
) -> None:
    with pytest.raises(ValueError, match="grain='day'"):
        get_metric_series(
            trend_engine, "net_revenue", "2025-01-01", "2025-01-02", grain="week"
        )
    with pytest.raises(ValueError, match="Invalid trend dimension"):
        get_metric_series_by_dimension(
            trend_engine, "net_revenue", "date", "2025-01-01", "2025-01-02"
        )
    with pytest.raises(ValueError, match="start_date"):
        get_metric_series(
            trend_engine, "net_revenue", "2025-01-02", "2025-01-01"
        )


def test_rolling_ratio_aggregates_numerator_and_denominator(
    trend_engine: MetricEngine,
) -> None:
    series = get_rolling_series(
        trend_engine, "conversion_rate", "2025-01-07", "2025-01-07"
    )
    point = series.points[0]

    assert point.status == MetricStatus.AVAILABLE
    assert point.numerator_value == Decimal(10)
    assert point.denominator_value == Decimal(92)
    assert point.value == Decimal(10) / Decimal(92)
    assert point.value != Decimal("0.30")


def test_additive_rolling_averages_only_available_daily_values(
    trend_engine: MetricEngine,
) -> None:
    series = get_rolling_series(
        trend_engine, "net_revenue", "2025-01-07", "2025-01-07"
    )
    assert series.points[0].value == Decimal("450.00")
    assert "2 available" in str(series.points[0].reason)


def test_rolling_requires_full_calendar_history_and_only_supports_7d(
    trend_engine: MetricEngine,
) -> None:
    early = get_rolling_series(
        trend_engine, "conversion_rate", "2025-01-01", "2025-01-01"
    )
    assert early.points[0].status == MetricStatus.UNAVAILABLE_NO_DATA
    with pytest.raises(ValueError, match="window_days=7"):
        get_rolling_series(
            trend_engine,
            "conversion_rate",
            "2025-01-07",
            "2025-01-07",
            window_days=2,
        )
