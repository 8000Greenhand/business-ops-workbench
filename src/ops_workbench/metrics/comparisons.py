"""Metric period comparison semantics built on the M2A engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from ops_workbench.metrics.engine import (
    FilterValue,
    MetricEngine,
    MetricResult,
    MetricStatus,
    MetricValue,
)
from ops_workbench.metrics.trend import (
    MetricSeriesPoint,
    average_daily_metric,
    get_metric_series,
)

ComparisonType = Literal["previous_period", "previous_week", "rolling_7d_average"]


class MetricComparisonStatus(StrEnum):
    """Overall availability of a current-versus-baseline comparison."""

    AVAILABLE = "available"
    UNAVAILABLE_CURRENT = "unavailable_current"
    UNAVAILABLE_BASELINE = "unavailable_baseline"


@dataclass(frozen=True, slots=True)
class MetricPeriodResult:
    """One current or baseline period value."""

    start_date: date
    end_date: date
    value: MetricValue | None
    status: MetricStatus
    format: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MetricComparisonResult:
    """A structured metric comparison with absolute and relative changes."""

    metric_id: str
    comparison_type: ComparisonType
    current: MetricPeriodResult
    baseline: MetricPeriodResult
    delta: Decimal | None
    relative_change: Decimal | None
    percentage_point_change: Decimal | None
    status: MetricComparisonStatus
    reason: str | None = None


def compare_metric(
    engine: MetricEngine,
    metric_id: str,
    start_date: date | str,
    end_date: date | str,
    *,
    comparison: ComparisonType = "previous_period",
    filters: Mapping[str, FilterValue] | None = None,
) -> MetricComparisonResult:
    """Compare one metric with an equal period, prior week, or prior 7-day mean."""
    start, end, baseline_start, baseline_end = resolve_comparison_period(
        start_date,
        end_date,
        comparison,
    )
    if comparison == "rolling_7d_average" and start != end:
        raise ValueError("rolling_7d_average comparison requires a single current day")

    current_result = engine.calculate_metric(
        metric_id,
        start_date=start,
        end_date=end,
        filters=filters,
    )
    if comparison == "rolling_7d_average":
        series = get_metric_series(
            engine,
            metric_id,
            baseline_start,
            baseline_end,
            filters=filters,
        )
        daily = tuple(_point_to_result(engine, point) for point in series.points)
        baseline_result = average_daily_metric(engine, metric_id, daily)
    else:
        baseline_result = engine.calculate_metric(
            metric_id,
            start_date=baseline_start,
            end_date=baseline_end,
            filters=filters,
        )

    return compare_metric_results(
        metric_id,
        comparison,
        current_result,
        start,
        end,
        baseline_result,
        baseline_start,
        baseline_end,
    )


def compare_metric_results(
    metric_id: str,
    comparison: ComparisonType,
    current_result: MetricResult,
    current_start: date,
    current_end: date,
    baseline_result: MetricResult,
    baseline_start: date,
    baseline_end: date,
) -> MetricComparisonResult:
    """Compare two precomputed metric results with the standard M2 semantics."""
    current = _period(current_start, current_end, current_result)
    baseline = _period(baseline_start, baseline_end, baseline_result)
    if current_result.status != MetricStatus.AVAILABLE:
        return MetricComparisonResult(
            metric_id,
            comparison,
            current,
            baseline,
            None,
            None,
            None,
            MetricComparisonStatus.UNAVAILABLE_CURRENT,
            f"Current metric is unavailable: {current_result.status}",
        )
    if baseline_result.status != MetricStatus.AVAILABLE:
        return MetricComparisonResult(
            metric_id,
            comparison,
            current,
            baseline,
            None,
            None,
            None,
            MetricComparisonStatus.UNAVAILABLE_BASELINE,
            f"Baseline metric is unavailable: {baseline_result.status}",
        )

    delta = Decimal(current_result.value) - Decimal(baseline_result.value)
    relative_change = (
        None
        if baseline_result.value == 0
        else delta / Decimal(baseline_result.value)
    )
    percentage_point_change = (
        delta if current_result.format == "percentage" else None
    )
    return MetricComparisonResult(
        metric_id,
        comparison,
        current,
        baseline,
        delta,
        relative_change,
        percentage_point_change,
        MetricComparisonStatus.AVAILABLE,
    )


def resolve_comparison_period(
    start_date: date | str,
    end_date: date | str,
    comparison: ComparisonType,
) -> tuple[date, date, date, date]:
    """Resolve current and baseline dates for one supported comparison."""
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    if start > end:
        raise ValueError("start_date must not be after end_date")
    if comparison not in {
        "previous_period",
        "previous_week",
        "rolling_7d_average",
    }:
        raise ValueError(f"Unsupported comparison type: {comparison}")
    if comparison == "previous_period":
        days = (end - start).days + 1
        baseline_end = start - timedelta(days=1)
        baseline_start = baseline_end - timedelta(days=days - 1)
    elif comparison == "previous_week":
        baseline_start, baseline_end = (
            start - timedelta(days=7),
            end - timedelta(days=7),
        )
    else:
        baseline_start, baseline_end = (
            start - timedelta(days=7),
            start - timedelta(days=1),
        )
    return start, end, baseline_start, baseline_end


def _period(start: date, end: date, result: MetricResult) -> MetricPeriodResult:
    return MetricPeriodResult(
        start_date=start,
        end_date=end,
        value=result.value,
        status=result.status,
        format=result.format,
        reason=result.reason,
    )


def _point_to_result(engine: MetricEngine, point: MetricSeriesPoint) -> MetricResult:
    definition = engine.registry.get(point.metric_id)
    return MetricResult(
        metric_id=point.metric_id,
        name=definition.name,
        value=point.value,
        status=point.status,
        format=point.format,
        numerator_value=point.numerator_value,
        denominator_value=point.denominator_value,
        reason=point.reason,
    )
