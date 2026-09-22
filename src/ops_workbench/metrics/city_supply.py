"""Aggregations and derived metrics for simulated city supply operations."""

from __future__ import annotations

from collections.abc import Sequence
import math

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype


DIMENSION_COLUMNS = ("date", "city", "zone", "time_bucket")
TIME_BUCKETS = (
    "morning_peak",
    "daytime_offpeak",
    "evening_peak",
    "night",
)
ADDITIVE_METRIC_COLUMNS = (
    "demand_orders",
    "completed_orders",
    "gmv",
    "online_hours",
    "platform_revenue",
    "driver_subsidy",
    "other_variable_cost",
)
DERIVED_METRIC_COLUMNS = (
    "completion_rate",
    "avg_order_value",
    "gmv_per_online_hour",
    "orders_per_online_hour",
    "gross_profit",
    "gross_margin",
    "subsidy_rate",
)


def validate_city_supply_facts(frame: pd.DataFrame) -> None:
    """Validate the V0.1 fact schema without silently repairing source data."""
    required = set(DIMENSION_COLUMNS + ADDITIVE_METRIC_COLUMNS)
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"City supply facts missing columns: {sorted(missing)}")
    if frame.empty:
        return
    if frame[list(DIMENSION_COLUMNS)].isna().any().any():
        raise ValueError("City supply dimensions cannot be null")
    invalid_buckets = set(frame["time_bucket"].astype(str)).difference(TIME_BUCKETS)
    if invalid_buckets:
        raise ValueError(f"Unsupported time buckets: {sorted(invalid_buckets)}")
    if frame.duplicated(list(DIMENSION_COLUMNS)).any():
        raise ValueError("City supply facts contain duplicate date-city-zone-time_bucket grain")
    for column in ADDITIVE_METRIC_COLUMNS:
        if is_bool_dtype(frame[column].dtype) or not is_numeric_dtype(frame[column].dtype):
            raise ValueError(f"City supply metric {column} must be numeric")
        if not frame[column].dropna().map(lambda value: math.isfinite(float(value))).all():
            raise ValueError(f"City supply metric {column} must be finite")
        if frame[column].dropna().lt(0).any():
            raise ValueError(f"City supply metric {column} cannot be negative")
    invalid_completed = (
        frame["completed_orders"].notna()
        & frame["demand_orders"].notna()
        & frame["completed_orders"].gt(frame["demand_orders"])
    )
    if invalid_completed.any():
        raise ValueError("completed_orders cannot exceed demand_orders")


def aggregate_city_supply_metrics(
    frame: pd.DataFrame,
    *,
    group_by: Sequence[str] = (),
) -> pd.DataFrame:
    """Aggregate additive facts, then recompute every ratio from summed inputs."""
    validate_city_supply_facts(frame)
    dimensions = tuple(group_by)
    if len(set(dimensions)) != len(dimensions):
        raise ValueError("group_by dimensions must be unique")
    invalid_dimensions = set(dimensions).difference(DIMENSION_COLUMNS)
    if invalid_dimensions:
        raise ValueError(f"Unsupported group_by dimensions: {sorted(invalid_dimensions)}")
    output_columns = [*dimensions, *ADDITIVE_METRIC_COLUMNS, *DERIVED_METRIC_COLUMNS]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)

    if dimensions:
        aggregated = (
            frame.groupby(list(dimensions), dropna=False, sort=True)[list(ADDITIVE_METRIC_COLUMNS)]
            .agg(_strict_sum)
            .reset_index()
        )
    else:
        aggregated = pd.DataFrame(
            [
                {
                    column: _strict_sum(frame[column])
                    for column in ADDITIVE_METRIC_COLUMNS
                }
            ]
        )

    aggregated["gross_profit"] = (
        aggregated["platform_revenue"]
        - aggregated["driver_subsidy"]
        - aggregated["other_variable_cost"]
    )
    aggregated["completion_rate"] = _safe_divide(
        aggregated["completed_orders"], aggregated["demand_orders"]
    )
    aggregated["avg_order_value"] = _safe_divide(
        aggregated["gmv"], aggregated["completed_orders"]
    )
    aggregated["gmv_per_online_hour"] = _safe_divide(
        aggregated["gmv"], aggregated["online_hours"]
    )
    aggregated["orders_per_online_hour"] = _safe_divide(
        aggregated["completed_orders"], aggregated["online_hours"]
    )
    aggregated["gross_margin"] = _safe_divide(
        aggregated["gross_profit"], aggregated["platform_revenue"]
    )
    aggregated["subsidy_rate"] = _safe_divide(
        aggregated["driver_subsidy"], aggregated["gmv"]
    )
    return aggregated[output_columns]


def _strict_sum(values: pd.Series) -> object:
    """Return NULL when any fact needed for a complete aggregate is unknown."""
    return values.sum(min_count=len(values))


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide aligned series while preserving null and zero-denominator states."""
    valid = numerator.notna() & denominator.notna() & denominator.ne(0)
    result = pd.Series(pd.NA, index=numerator.index, dtype="Float64")
    result.loc[valid] = numerator.loc[valid] / denominator.loc[valid]
    finite = result.isna() | (result.ne(float("inf")) & result.ne(float("-inf")))
    return result.where(finite, pd.NA)
