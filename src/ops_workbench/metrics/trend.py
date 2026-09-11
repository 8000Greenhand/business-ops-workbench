"""Daily metric series and seven-day rolling organization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import duckdb

from ops_workbench.metrics.engine import (
    FilterValue,
    MetricEngine,
    MetricResult,
    MetricStatus,
    MetricValue,
)
from ops_workbench.models.canonical_schema import (
    DIMENSION_FIELDS,
    FACT_BUSINESS_DAILY_TABLE,
)


@dataclass(frozen=True, slots=True)
class MetricSeriesPoint:
    """One calendar date and its structured metric result."""

    metric_id: str
    date: date
    value: MetricValue | None
    status: MetricStatus
    format: str
    numerator_value: MetricValue | None = None
    denominator_value: MetricValue | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MetricSeries:
    """A continuous daily metric series; absent dates are explicit no-data points."""

    metric_id: str
    start_date: date
    end_date: date
    grain: str
    points: tuple[MetricSeriesPoint, ...]


@dataclass(frozen=True, slots=True)
class MetricDimensionSeriesPoint:
    """One daily metric result for one canonical dimension member."""

    metric_id: str
    date: date
    dimension: str
    dimension_value: str | None
    value: MetricValue | None
    status: MetricStatus
    format: str
    numerator_value: MetricValue | None = None
    denominator_value: MetricValue | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MetricDimensionSeries:
    """A daily metric series grouped by one canonical dimension."""

    metric_id: str
    dimension: str
    start_date: date
    end_date: date
    grain: str
    points: tuple[MetricDimensionSeriesPoint, ...]


def get_metric_series(
    engine: MetricEngine,
    metric_id: str,
    start_date: date | str,
    end_date: date | str,
    *,
    grain: str = "day",
    filters: Mapping[str, FilterValue] | None = None,
) -> MetricSeries:
    """Return one point per calendar day using a single DuckDB group-by query."""
    start, end = _validate_dates(start_date, end_date, grain)
    grouped = engine._calculate_metric_grouped(
        metric_id,
        ("date",),
        start_date=start,
        end_date=end,
        filters=filters,
    )
    by_date = {group_values[0]: result for group_values, result in grouped}
    points = tuple(
        _series_point(
            metric_id,
            current_date,
            by_date.get(current_date) or _no_data_result(engine, metric_id),
        )
        for current_date in _date_range(start, end)
    )
    return MetricSeries(metric_id, start, end, grain, points)


def get_metric_series_by_dimension(
    engine: MetricEngine,
    metric_id: str,
    dimension: str,
    start_date: date | str,
    end_date: date | str,
    *,
    grain: str = "day",
    filters: Mapping[str, FilterValue] | None = None,
) -> MetricDimensionSeries:
    """Return daily results grouped by one whitelisted canonical dimension."""
    if dimension not in DIMENSION_FIELDS:
        raise ValueError(f"Invalid trend dimension: {dimension}")
    start, end = _validate_dates(start_date, end_date, grain)
    grouped = engine._calculate_metric_grouped(
        metric_id,
        ("date", dimension),
        start_date=start,
        end_date=end,
        filters=filters,
    )
    values = {
        (group_values[0], group_values[1]): result
        for group_values, result in grouped
    }
    members = tuple(dict.fromkeys(group_values[1] for group_values, _ in grouped))
    missing = _no_data_result(engine, metric_id)
    points = tuple(
        _dimension_point(
            metric_id,
            current_date,
            dimension,
            member,
            values.get((current_date, member), missing),
        )
        for current_date in _date_range(start, end)
        for member in members
    )
    return MetricDimensionSeries(metric_id, dimension, start, end, grain, points)


def get_rolling_series(
    engine: MetricEngine,
    metric_id: str,
    start_date: date | str,
    end_date: date | str,
    *,
    window_days: int = 7,
    filters: Mapping[str, FilterValue] | None = None,
) -> MetricSeries:
    """Return trailing seven-day metrics, never treating absent or NULL days as zero.

    Ratio metrics aggregate daily numerators and denominators before division.
    Atomic and difference metrics average the available daily metric values.
    """
    if window_days != 7:
        raise ValueError("M2B only supports window_days=7")
    start, end = _validate_dates(start_date, end_date, "day")
    extended_start = start - timedelta(days=window_days - 1)
    source = get_metric_series(
        engine,
        metric_id,
        extended_start,
        end,
        filters=filters,
    )
    source_by_date = {point.date: point for point in source.points}
    earliest_fact_date = _earliest_fact_date(engine)
    points: list[MetricSeriesPoint] = []
    for current_date in _date_range(start, end):
        window_start = current_date - timedelta(days=window_days - 1)
        if earliest_fact_date is None or window_start < earliest_fact_date:
            result = _no_data_result(
                engine,
                metric_id,
                "Seven calendar days of history are not available",
            )
        else:
            daily_results = tuple(
                _point_result(source_by_date[day], engine)
                for day in _date_range(window_start, current_date)
            )
            result = average_daily_metric(engine, metric_id, daily_results)
        points.append(_series_point(metric_id, current_date, result))
    return MetricSeries(metric_id, start, end, "day", tuple(points))


def average_daily_metric(
    engine: MetricEngine,
    metric_id: str,
    daily_results: Sequence[MetricResult],
) -> MetricResult:
    """Summarize available daily results using the registered metric type."""
    definition = engine.registry.get(metric_id)
    available = tuple(
        result for result in daily_results if result.status == MetricStatus.AVAILABLE
    )
    if not available:
        unavailable = next(
            (
                result
                for result in daily_results
                if result.status != MetricStatus.UNAVAILABLE_NO_DATA
            ),
            None,
        )
        return unavailable or _no_data_result(engine, metric_id)
    if definition.type == "ratio":
        ratio_days = tuple(
            result
            for result in daily_results
            if result.status
            in {MetricStatus.AVAILABLE, MetricStatus.UNAVAILABLE_ZERO_DENOMINATOR}
            and result.numerator_value is not None
            and result.denominator_value is not None
        )
        if not ratio_days:
            return available[0]
        numerator = sum(Decimal(result.numerator_value) for result in ratio_days)
        denominator = sum(Decimal(result.denominator_value) for result in ratio_days)
        if denominator == 0:
            return MetricResult(
                metric_id=metric_id,
                name=definition.name,
                value=None,
                status=MetricStatus.UNAVAILABLE_ZERO_DENOMINATOR,
                format=definition.format,
                numerator_value=numerator,
                denominator_value=denominator,
                reason="Rolling denominator aggregates to zero",
            )
        return MetricResult(
            metric_id=metric_id,
            name=definition.name,
            value=numerator / denominator,
            status=MetricStatus.AVAILABLE,
            format=definition.format,
            numerator_value=numerator,
            denominator_value=denominator,
        )
    value = sum(Decimal(result.value) for result in available) / len(available)
    return MetricResult(
        metric_id=metric_id,
        name=definition.name,
        value=value,
        status=MetricStatus.AVAILABLE,
        format=definition.format,
        reason=f"Average of {len(available)} available daily value(s)",
    )


def _validate_dates(
    start_date: date | str,
    end_date: date | str,
    grain: str,
) -> tuple[date, date]:
    if grain != "day":
        raise ValueError("M2B only supports grain='day'")
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    if start > end:
        raise ValueError("start_date must not be after end_date")
    return start, end


def _date_range(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset) for offset in range((end - start).days + 1)
    )


def _no_data_result(
    engine: MetricEngine,
    metric_id: str,
    reason: str = "No data exists for this calendar date",
) -> MetricResult:
    definition = engine.registry.get(metric_id)
    return MetricResult(
        metric_id=metric_id,
        name=definition.name,
        value=None,
        status=MetricStatus.UNAVAILABLE_NO_DATA,
        format=definition.format,
        reason=reason,
    )


def _series_point(
    metric_id: str,
    current_date: date,
    result: MetricResult,
) -> MetricSeriesPoint:
    return MetricSeriesPoint(
        metric_id=metric_id,
        date=current_date,
        value=result.value,
        status=result.status,
        format=result.format,
        numerator_value=result.numerator_value,
        denominator_value=result.denominator_value,
        reason=result.reason,
    )


def _dimension_point(
    metric_id: str,
    current_date: date,
    dimension: str,
    member: object,
    result: MetricResult,
) -> MetricDimensionSeriesPoint:
    return MetricDimensionSeriesPoint(
        metric_id=metric_id,
        date=current_date,
        dimension=dimension,
        dimension_value=None if member is None else str(member),
        value=result.value,
        status=result.status,
        format=result.format,
        numerator_value=result.numerator_value,
        denominator_value=result.denominator_value,
        reason=result.reason,
    )


def _point_result(point: MetricSeriesPoint, engine: MetricEngine) -> MetricResult:
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


def _earliest_fact_date(engine: MetricEngine) -> date | None:
    with duckdb.connect(str(engine.database_path), read_only=True) as connection:
        value = connection.execute(
            f'SELECT MIN("date") FROM "{FACT_BUSINESS_DAILY_TABLE}"'
        ).fetchone()[0]
    return value
