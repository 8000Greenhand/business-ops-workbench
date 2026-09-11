"""Tests for additive arithmetic contribution analysis."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.diagnostics import (
    ContributionEngine,
    ContributionStatus,
    UnsupportedContributionComparison,
    UnsupportedContributionMetric,
)
from ops_workbench.diagnostics.models import ContributionDirection
from ops_workbench.metrics import MetricEngine
from ops_workbench.models.database import get_fact_row_count, replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report


def _metric_engine(tmp_path: Path, dataframe: pd.DataFrame) -> MetricEngine:
    standardized = standardize(dataframe)
    report = build_quality_report(standardized)
    assert report.is_valid
    database_path = tmp_path / "contribution.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    return MetricEngine(database_path=database_path)


def _membership_frame(metric: str = "gross_revenue") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [
                "2025-01-01",
                "2025-01-01",
                "2025-01-01",
                "2025-01-08",
                "2025-01-08",
                "2025-01-08",
            ],
            "channel": ["A", "B", "C", "A", "B", "D"],
            metric: [100, 200, 300, 120, 150, 80],
        }
    )


@pytest.fixture
def membership_engine(tmp_path: Path) -> MetricEngine:
    return _metric_engine(tmp_path, _membership_frame())


def test_eligibility_uses_metric_definition_semantics(
    membership_engine: MetricEngine,
) -> None:
    contribution = ContributionEngine(membership_engine)
    assert contribution.is_contribution_eligible("leads")
    assert contribution.is_contribution_eligible("net_revenue")
    assert not contribution.is_contribution_eligible("conversion_rate")
    with pytest.raises(UnsupportedContributionMetric, match="non-additive ratio"):
        contribution.analyze_contribution(
            "conversion_rate", "2025-01-08", "2025-01-08", "channel"
        )
    with pytest.raises(ValueError, match="Unknown metric id"):
        contribution.is_contribution_eligible("unknown_metric")


def test_basic_values_membership_shares_and_reconciliation(
    membership_engine: MetricEngine,
) -> None:
    result = ContributionEngine(membership_engine).analyze_contribution(
        "gross_revenue",
        "2025-01-08",
        "2025-01-08",
        "channel",
        comparison="previous_week",
    )
    segments = {item.dimension_value: item for item in result.segments}

    assert result.status == ContributionStatus.AVAILABLE
    assert result.overall_current == Decimal("350.00")
    assert result.overall_baseline == Decimal("600.00")
    assert result.overall_delta == Decimal("-250.00")
    assert segments["A"].current_value == Decimal("120.00")
    assert segments["A"].baseline_value == Decimal("100.00")
    assert segments["A"].delta == Decimal("20.00")
    assert segments["C"].current_value == 0
    assert segments["C"].delta == Decimal("-300.00")
    assert segments["D"].baseline_value == 0
    assert segments["D"].delta == Decimal("80.00")
    assert segments["C"].net_change_share == Decimal("1.2")
    assert segments["D"].net_change_share == Decimal("-0.32")
    assert sum(item.movement_share for item in result.segments) == Decimal(1)
    assert result.current_reconciliation_difference == 0
    assert result.baseline_reconciliation_difference == 0
    assert result.reconciliation_difference == 0


def test_direction_and_ranking_helpers(membership_engine: MetricEngine) -> None:
    result = ContributionEngine(membership_engine).analyze_contribution(
        "gross_revenue", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    segments = {item.dimension_value: item for item in result.segments}
    assert segments["D"].direction == ContributionDirection.INCREASE
    assert segments["C"].direction == ContributionDirection.DECREASE
    assert [item.dimension_value for item in result.top_increases()] == ["D", "A"]
    assert [item.dimension_value for item in result.top_decreases()] == ["C", "B"]
    assert [item.dimension_value for item in result.top_movements()] == ["C", "D", "B", "A"]
    assert [item.rank_by_absolute_change for item in result.segments] == [1, 2, 3, 4]


def test_offsetting_changes_allow_shares_over_100_percent(tmp_path: Path) -> None:
    engine = _metric_engine(
        tmp_path,
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025-01-01", "2025-01-08", "2025-01-08"],
                "channel": ["A", "B", "A", "B"],
                "leads": [150, 0, 0, 50],
            }
        ),
    )
    result = ContributionEngine(engine).analyze_contribution(
        "leads", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    segments = {item.dimension_value: item for item in result.segments}
    assert result.overall_delta == Decimal(-100)
    assert segments["A"].net_change_share == Decimal("1.5")
    assert segments["B"].net_change_share == Decimal("-0.5")
    assert segments["A"].movement_share == Decimal("0.75")
    assert segments["B"].movement_share == Decimal("0.25")


def test_zero_overall_delta_retains_internal_movement(tmp_path: Path) -> None:
    engine = _metric_engine(
        tmp_path,
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025-01-01", "2025-01-08", "2025-01-08"],
                "channel": ["A", "B", "A", "B"],
                "leads": [0, 100, 100, 0],
            }
        ),
    )
    result = ContributionEngine(engine).analyze_contribution(
        "leads", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    assert result.status == ContributionStatus.AVAILABLE
    assert result.overall_delta == 0
    assert not result.net_change_share_available
    assert all(item.net_change_share is None for item in result.segments)
    assert all(item.movement_share == Decimal("0.5") for item in result.segments)


def test_no_change_has_no_movement_share(tmp_path: Path) -> None:
    engine = _metric_engine(
        tmp_path,
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025-01-08"],
                "channel": ["A", "A"],
                "leads": [100, 100],
            }
        ),
    )
    result = ContributionEngine(engine).analyze_contribution(
        "leads", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    assert result.status == ContributionStatus.AVAILABLE_NO_CHANGE
    assert result.segments[0].direction == ContributionDirection.UNCHANGED
    assert result.segments[0].net_change_share is None
    assert result.segments[0].movement_share is None


def test_null_dimension_group_is_preserved(tmp_path: Path) -> None:
    engine = _metric_engine(
        tmp_path,
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025-01-01", "2025-01-08", "2025-01-08"],
                "channel": [None, "A", None, "A"],
                "leads": [20, 80, 30, 70],
            }
        ),
    )
    result = ContributionEngine(engine).analyze_contribution(
        "leads", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    segments = {item.dimension_value: item for item in result.segments}
    assert None in segments
    assert segments[None].delta == Decimal(10)
    assert result.reconciliation_difference == 0


def test_previous_period_and_previous_week_dates(membership_engine: MetricEngine) -> None:
    contribution = ContributionEngine(membership_engine)
    previous_period = contribution.analyze_contribution(
        "gross_revenue", "2025-01-08", "2025-01-08", "channel"
    )
    previous_week = contribution.analyze_contribution(
        "gross_revenue", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    assert previous_period.baseline_start == previous_period.baseline_end == date(2025, 1, 7)
    assert previous_week.baseline_start == previous_week.baseline_end == date(2025, 1, 1)
    with pytest.raises(UnsupportedContributionComparison, match="not supported"):
        contribution.analyze_contribution(
            "gross_revenue",
            "2025-01-08",
            "2025-01-08",
            "channel",
            comparison="rolling_7d_average",
        )


def test_filters_and_multi_value_filters(tmp_path: Path) -> None:
    dataframe = _membership_frame("leads")
    dataframe["business_line"] = ["L1", "L1", "L2", "L1", "L1", "L2"]
    engine = _metric_engine(tmp_path, dataframe)
    contribution = ContributionEngine(engine)
    filtered = contribution.analyze_contribution(
        "leads",
        "2025-01-08",
        "2025-01-08",
        "channel",
        comparison="previous_week",
        filters={"business_line": "L1"},
    )
    multi = contribution.analyze_contribution(
        "leads",
        "2025-01-08",
        "2025-01-08",
        "channel",
        comparison="previous_week",
        filters={"channel": ["A", "B"]},
    )
    assert {item.dimension_value for item in filtered.segments} == {"A", "B"}
    assert {item.dimension_value for item in multi.segments} == {"A", "B"}


def test_invalid_dimension_and_sql_injection_value(tmp_path: Path) -> None:
    engine = _metric_engine(tmp_path, _membership_frame("leads"))
    contribution = ContributionEngine(engine)
    with pytest.raises(ValueError, match="Invalid contribution dimension"):
        contribution.analyze_contribution(
            "leads", "2025-01-08", "2025-01-08", "date"
        )
    result = contribution.analyze_contribution(
        "leads",
        "2025-01-08",
        "2025-01-08",
        "team",
        comparison="previous_week",
        filters={"channel": "A' OR 1=1 --"},
    )
    assert result.status == ContributionStatus.AVAILABLE_NO_CHANGE
    assert get_fact_row_count(database_path=engine.database_path) == 6


def test_decimal_net_revenue_contribution_is_exact(tmp_path: Path) -> None:
    engine = _metric_engine(
        tmp_path,
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025-01-08"],
                "channel": ["A", "A"],
                "gross_revenue": ["0.10", "0.30"],
                "refund_amount": ["0.01", "0.02"],
            }
        ),
    )
    result = ContributionEngine(engine).analyze_contribution(
        "net_revenue", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    assert result.overall_baseline == Decimal("0.09")
    assert result.overall_current == Decimal("0.28")
    assert result.overall_delta == Decimal("0.19")
    assert result.reconciliation_difference == Decimal("0.00")


def test_reconciliation_failure_is_explicit(
    membership_engine: MetricEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = membership_engine.calculate_metric

    def inconsistent(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        if kwargs.get("start_date") == date(2025, 1, 8):
            return replace(result, value=Decimal(result.value) + Decimal("0.02"))
        return result

    monkeypatch.setattr(membership_engine, "calculate_metric", inconsistent)
    result = ContributionEngine(membership_engine).analyze_contribution(
        "gross_revenue", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    assert result.status == ContributionStatus.RECONCILIATION_FAILED
    assert result.current_reconciliation_difference == Decimal("-0.02")
    assert result.reason


def test_metric_unavailability_blocks_whole_analysis(tmp_path: Path) -> None:
    engine = _metric_engine(
        tmp_path,
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025-01-08"],
                "channel": ["A", "A"],
                "leads": [10, 20],
            }
        ),
    )
    result = ContributionEngine(engine).analyze_contribution(
        "refund_amount", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    assert result.status == ContributionStatus.UNAVAILABLE
    assert not result.segments
    assert "unavailable" in str(result.reason)


def test_query_count_does_not_grow_with_segments(
    membership_engine: MetricEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grouped_original = membership_engine.calculate_metric_by_dimension
    overall_original = membership_engine.calculate_metric
    grouped_calls = 0
    overall_calls = 0

    def grouped(*args: object, **kwargs: object) -> object:
        nonlocal grouped_calls
        grouped_calls += 1
        return grouped_original(*args, **kwargs)

    def overall(*args: object, **kwargs: object) -> object:
        nonlocal overall_calls
        overall_calls += 1
        return overall_original(*args, **kwargs)

    monkeypatch.setattr(membership_engine, "calculate_metric_by_dimension", grouped)
    monkeypatch.setattr(membership_engine, "calculate_metric", overall)
    ContributionEngine(membership_engine).analyze_contribution(
        "gross_revenue", "2025-01-08", "2025-01-08", "channel", comparison="previous_week"
    )
    assert grouped_calls == 2
    assert overall_calls == 2
