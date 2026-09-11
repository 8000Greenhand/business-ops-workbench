"""Configurable business metric definitions and calculation engine."""

from ops_workbench.metrics.engine import (
    MetricEngine,
    MetricGroupResult,
    MetricResult,
    MetricStatus,
)
from ops_workbench.metrics.comparisons import (
    MetricComparisonResult,
    MetricComparisonStatus,
    compare_metric,
    compare_metric_results,
    resolve_comparison_period,
)
from ops_workbench.metrics.funnel import (
    FunnelRegistry,
    FunnelResult,
    calculate_funnel,
)
from ops_workbench.metrics.registry import MetricDefinition, MetricRegistry
from ops_workbench.metrics.trend import (
    MetricDimensionSeries,
    MetricSeries,
    get_metric_series,
    get_metric_series_by_dimension,
    get_rolling_series,
)

__all__ = [
    "MetricDefinition",
    "MetricComparisonResult",
    "MetricComparisonStatus",
    "MetricDimensionSeries",
    "MetricEngine",
    "MetricGroupResult",
    "MetricRegistry",
    "MetricResult",
    "MetricSeries",
    "MetricStatus",
    "FunnelRegistry",
    "FunnelResult",
    "calculate_funnel",
    "compare_metric",
    "compare_metric_results",
    "resolve_comparison_period",
    "get_metric_series",
    "get_metric_series_by_dimension",
    "get_rolling_series",
]
