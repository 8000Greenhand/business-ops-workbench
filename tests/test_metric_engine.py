"""Tests for DuckDB-backed metric calculation and availability semantics."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.metrics import MetricEngine, MetricStatus
from ops_workbench.models.database import get_fact_row_count, replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report


def _persist(database_path: Path, dataframe: pd.DataFrame) -> MetricEngine:
    standardized = standardize(dataframe)
    report = build_quality_report(standardized)
    assert report.is_valid
    replace_fact_business_daily(standardized, report, database_path=database_path)
    return MetricEngine(database_path=database_path)


@pytest.fixture
def engine(tmp_path: Path) -> MetricEngine:
    return _persist(
        tmp_path / "metrics.duckdb",
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025-01-02", "2025-01-03"],
                "business_line": ["业务线A", "业务线A", "业务线B"],
                "product": ["产品A", "产品B", "产品C"],
                "channel": ["渠道01", "渠道03", "渠道03"],
                "region": ["北区", "南区", "南区"],
                "team": ["团队01", "团队02", "团队02"],
                "salesperson": ["销售A", "销售B", "销售C"],
                "impressions": [20, 900, 50],
                "leads": [2, 90, None],
                "valid_leads": [2, 90, None],
                "contacted_leads": [2, 80, None],
                "followed_leads": [1, 70, None],
                "paid_users": [1, 9, None],
                "paid_orders": [1, 10, None],
                "gross_revenue": ["0.10", "0.20", None],
                "refund_users": [0, 1, None],
                "refund_orders": [0, 1, None],
                "refund_amount": ["0.00", "0.10", None],
            }
        ),
    )


def test_atomic_sums_and_decimal_precision(engine: MetricEngine) -> None:
    leads, gross = engine.calculate_metrics(("leads", "gross_revenue"))

    assert leads.status == MetricStatus.AVAILABLE
    assert leads.value == 92
    assert gross.value == Decimal("0.30")
    assert isinstance(gross.value, Decimal)


def test_ratios_use_aggregated_dependencies_not_average_of_row_rates(
    engine: MetricEngine,
) -> None:
    valid_rate, conversion, refund_rate = engine.calculate_metrics(
        ("valid_lead_rate", "conversion_rate", "refund_rate_amount")
    )

    assert valid_rate.value == Decimal(92) / Decimal(92)
    assert conversion.value == Decimal(10) / Decimal(92)
    assert conversion.value != Decimal("0.30")
    assert conversion.numerator_value == 10
    assert conversion.denominator_value == 92
    assert refund_rate.value == Decimal("0.10") / Decimal("0.30")


def test_derived_metrics_use_aggregated_atomic_dependencies(
    engine: MetricEngine,
) -> None:
    net, per_lead = engine.calculate_metrics(("net_revenue", "revenue_per_lead"))

    assert net.value == Decimal("0.20")
    assert net.numerator_value == Decimal("0.30")
    assert net.denominator_value == Decimal("0.10")
    assert per_lead.value == Decimal("0.20") / Decimal(92)
    assert per_lead.numerator_value == Decimal("0.20")


def test_single_multi_and_combined_filters(engine: MetricEngine) -> None:
    assert engine.calculate_metric("leads", filters={"channel": "渠道03"}).value == 90
    assert engine.calculate_metric(
        "leads", filters={"channel": ["渠道01", "渠道03"]}
    ).value == 92
    assert engine.calculate_metric(
        "leads",
        filters={"business_line": "业务线A", "team": ["团队02"]},
    ).value == 90


def test_invalid_filter_field_and_value_are_rejected(engine: MetricEngine) -> None:
    with pytest.raises(ValueError, match="Invalid filter field"):
        engine.calculate_metric("leads", filters={"leads": "2"})
    with pytest.raises(ValueError, match="one or more string values"):
        engine.calculate_metric("leads", filters={"channel": []})


def test_filter_values_are_parameterized_against_sql_injection(
    engine: MetricEngine,
) -> None:
    result = engine.calculate_metric(
        "leads",
        filters={"channel": "渠道03' OR 1=1 --"},
    )

    assert result.status == MetricStatus.UNAVAILABLE_NO_DATA
    assert get_fact_row_count(database_path=engine.database_path) == 3


def test_date_boundaries_and_empty_date_range(engine: MetricEngine) -> None:
    assert engine.calculate_metric("leads", start_date="2025-01-02").value == 90
    assert engine.calculate_metric("leads", end_date=date(2025, 1, 1)).value == 2
    assert engine.calculate_metric(
        "leads", start_date="2025-01-01", end_date="2025-01-02"
    ).value == 92
    empty = engine.calculate_metric(
        "leads", start_date="2026-01-01", end_date="2026-01-31"
    )
    assert empty.status == MetricStatus.UNAVAILABLE_NO_DATA
    assert empty.value is None


def test_group_by_channel_and_team(engine: MetricEngine) -> None:
    channels = engine.calculate_metric_by_dimension("net_revenue", "channel")
    teams = engine.calculate_metric_by_dimension("conversion_rate", "team")

    assert [(row.dimension_value, row.value) for row in channels] == [
        ("渠道01", Decimal("0.10")),
        ("渠道03", Decimal("0.10")),
    ]
    assert [(row.dimension_value, row.value) for row in teams] == [
        ("团队01", Decimal("0.5")),
        ("团队02", Decimal("0.1")),
    ]
    assert all(row.status == MetricStatus.AVAILABLE for row in teams)


def test_unknown_metric_and_group_dimension_are_rejected(engine: MetricEngine) -> None:
    with pytest.raises(ValueError, match="Unknown metric id"):
        engine.calculate_metric("drop_table")
    with pytest.raises(ValueError, match="Invalid group-by dimension"):
        engine.calculate_metric_by_dimension("leads", "date")


def test_missing_field_propagates_to_direct_derived_metric(tmp_path: Path) -> None:
    engine = _persist(
        tmp_path / "missing.duckdb",
        pd.DataFrame(
            {
                "date": ["2025-01-01"],
                "leads": [10],
                "gross_revenue": ["100.00"],
            }
        ),
    )

    atomic = engine.calculate_metric("refund_amount")
    direct = engine.calculate_metric("refund_rate_amount")
    nested = engine.calculate_metric("revenue_per_lead")
    assert atomic.status == MetricStatus.UNAVAILABLE_MISSING_FIELD
    assert direct.status == MetricStatus.UNAVAILABLE_MISSING_FIELD
    assert direct.value is None
    assert nested.status == MetricStatus.UNAVAILABLE_DEPENDENCY


def test_available_all_null_is_no_data_not_zero(tmp_path: Path) -> None:
    engine = _persist(
        tmp_path / "null.duckdb",
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025-01-02"],
                "gross_revenue": [None, None],
            }
        ),
    )

    result = engine.calculate_metric("gross_revenue")
    assert result.status == MetricStatus.UNAVAILABLE_NO_DATA
    assert result.value is None


def test_partial_null_sum_uses_only_valid_values(engine: MetricEngine) -> None:
    result = engine.calculate_metric("gross_revenue")
    assert result.status == MetricStatus.AVAILABLE
    assert result.value == Decimal("0.30")


def test_zero_denominator_has_distinct_status(tmp_path: Path) -> None:
    engine = _persist(
        tmp_path / "zero.duckdb",
        pd.DataFrame(
            {
                "date": ["2025-01-01"],
                "leads": [0],
                "valid_leads": [0],
            }
        ),
    )

    result = engine.calculate_metric("valid_lead_rate")
    assert result.status == MetricStatus.UNAVAILABLE_ZERO_DENOMINATOR
    assert result.value is None
    assert result.numerator_value == 0
    assert result.denominator_value == 0
