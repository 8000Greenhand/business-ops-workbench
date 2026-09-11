"""Arithmetic contribution analysis for strictly additive metrics."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from ops_workbench.diagnostics.models import (
    ContributionDirection,
    ContributionResult,
    ContributionSegment,
    ContributionStatus,
)
from ops_workbench.metrics.comparisons import resolve_comparison_period
from ops_workbench.metrics.engine import (
    FilterValue,
    MetricEngine,
    MetricGroupResult,
    MetricResult,
    MetricStatus,
)
from ops_workbench.metrics.registry import MetricRegistry
from ops_workbench.models.canonical_schema import DIMENSION_FIELDS

SUPPORTED_COMPARISONS = frozenset({"previous_period", "previous_week"})


class UnsupportedContributionMetric(ValueError):
    """Raised when a metric lacks strict additive semantics."""


class UnsupportedContributionComparison(ValueError):
    """Raised for comparison semantics not defined for contribution analysis."""


def is_contribution_eligible(
    metric_id: str,
    registry: MetricRegistry,
) -> bool:
    """Return whether a metric is recursively additive by its definition."""
    definition = registry.get(metric_id)
    if definition.type == "atomic":
        return definition.aggregation == "sum"
    if definition.type == "ratio":
        return False
    return all(
        is_contribution_eligible(dependency, registry)
        for dependency in definition.dependencies
    )


class ContributionEngine:
    """Decompose additive current-versus-baseline changes by one dimension."""

    def __init__(self, metric_engine: MetricEngine) -> None:
        self.metric_engine = metric_engine

    def is_contribution_eligible(self, metric_id: str) -> bool:
        """Return additive eligibility using the current metric registry."""
        return is_contribution_eligible(metric_id, self.metric_engine.registry)

    def analyze_contribution(
        self,
        metric_id: str,
        start_date: date | str,
        end_date: date | str,
        dimension: str,
        *,
        comparison: str = "previous_period",
        filters: Mapping[str, FilterValue] | None = None,
    ) -> ContributionResult:
        """Return a reconciled arithmetic contribution result."""
        definition = self.metric_engine.registry.get(metric_id)
        if not self.is_contribution_eligible(metric_id):
            raise UnsupportedContributionMetric(
                f"{metric_id} is a non-additive {definition.type} metric and cannot "
                "be decomposed using arithmetic contribution in V1"
            )
        if comparison not in SUPPORTED_COMPARISONS:
            raise UnsupportedContributionComparison(
                f"{comparison} contribution is not supported in V1; use "
                "previous_period or previous_week"
            )
        if dimension not in DIMENSION_FIELDS:
            raise ValueError(f"Invalid contribution dimension: {dimension}")
        current_start, current_end, baseline_start, baseline_end = (
            resolve_comparison_period(start_date, end_date, comparison)
        )

        current_groups = self.metric_engine.calculate_metric_by_dimension(
            metric_id,
            dimension,
            start_date=current_start,
            end_date=current_end,
            filters=filters,
        )
        baseline_groups = self.metric_engine.calculate_metric_by_dimension(
            metric_id,
            dimension,
            start_date=baseline_start,
            end_date=baseline_end,
            filters=filters,
        )
        overall_current_result = self.metric_engine.calculate_metric(
            metric_id,
            start_date=current_start,
            end_date=current_end,
            filters=filters,
        )
        overall_baseline_result = self.metric_engine.calculate_metric(
            metric_id,
            start_date=baseline_start,
            end_date=baseline_end,
            filters=filters,
        )
        unavailable_reason = _unavailable_reason(
            current_groups,
            baseline_groups,
            overall_current_result,
            overall_baseline_result,
        )
        if unavailable_reason is not None:
            return _unavailable_result(
                metric_id,
                definition.name,
                dimension,
                comparison,
                current_start,
                current_end,
                baseline_start,
                baseline_end,
                unavailable_reason,
            )

        current_values = _group_values(current_groups)
        baseline_values = _group_values(baseline_groups)
        members = tuple(dict.fromkeys((*current_values, *baseline_values)))
        overall_current = _overall_value(overall_current_result, current_groups)
        overall_baseline = _overall_value(overall_baseline_result, baseline_groups)
        overall_delta = overall_current - overall_baseline
        movement_total = sum(
            abs(current_values.get(member, Decimal(0)) - baseline_values.get(member, Decimal(0)))
            for member in members
        )

        raw_segments = [
            _segment(
                dimension,
                member,
                current_values.get(member, Decimal(0)),
                baseline_values.get(member, Decimal(0)),
                overall_delta,
                movement_total,
            )
            for member in members
        ]
        raw_segments.sort(
            key=lambda item: (-abs(item.delta), _member_sort_key(item.dimension_value))
        )
        segments = tuple(
            ContributionSegment(
                dimension=item.dimension,
                dimension_value=item.dimension_value,
                current_value=item.current_value,
                baseline_value=item.baseline_value,
                delta=item.delta,
                net_change_share=item.net_change_share,
                movement_share=item.movement_share,
                direction=item.direction,
                rank_by_absolute_change=rank,
            )
            for rank, item in enumerate(raw_segments, start=1)
        )
        current_difference = sum(item.current_value for item in segments) - overall_current
        baseline_difference = sum(item.baseline_value for item in segments) - overall_baseline
        delta_difference = sum(item.delta for item in segments) - overall_delta
        tolerance = Decimal("0.01") if definition.format == "currency" else Decimal(0)
        reconciled = all(
            abs(value) <= tolerance
            for value in (current_difference, baseline_difference, delta_difference)
        )
        status = (
            ContributionStatus.RECONCILIATION_FAILED
            if not reconciled
            else ContributionStatus.AVAILABLE_NO_CHANGE
            if overall_delta == 0 and movement_total == 0
            else ContributionStatus.AVAILABLE
        )
        reason = None if reconciled else "Segment sums do not reconcile to overall values"
        increases = tuple(
            sorted(
                (item for item in segments if item.direction == ContributionDirection.INCREASE),
                key=lambda item: item.delta,
                reverse=True,
            )
        )
        decreases = tuple(
            sorted(
                (item for item in segments if item.direction == ContributionDirection.DECREASE),
                key=lambda item: item.delta,
            )
        )
        unchanged = tuple(
            item for item in segments if item.direction == ContributionDirection.UNCHANGED
        )
        return ContributionResult(
            metric_id=metric_id,
            metric_name=definition.name,
            dimension=dimension,
            comparison_type=comparison,
            current_start=current_start,
            current_end=current_end,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            overall_current=overall_current,
            overall_baseline=overall_baseline,
            overall_delta=overall_delta,
            net_change_share_available=overall_delta != 0,
            segments=segments,
            increase_segments=increases,
            decrease_segments=decreases,
            unchanged_segments=unchanged,
            current_reconciliation_difference=current_difference,
            baseline_reconciliation_difference=baseline_difference,
            reconciliation_difference=delta_difference,
            status=status,
            reason=reason,
        )


def _unavailable_reason(
    current_groups: tuple[MetricGroupResult, ...],
    baseline_groups: tuple[MetricGroupResult, ...],
    current: MetricResult,
    baseline: MetricResult,
) -> str | None:
    for label, result in (("current", current), ("baseline", baseline)):
        if result.status == MetricStatus.UNAVAILABLE_NO_DATA:
            groups = current_groups if label == "current" else baseline_groups
            if not groups:
                continue
        if result.status != MetricStatus.AVAILABLE:
            return f"{label} metric is unavailable: {result.status}"
    for label, groups in (("current", current_groups), ("baseline", baseline_groups)):
        unavailable = next(
            (item for item in groups if item.status != MetricStatus.AVAILABLE),
            None,
        )
        if unavailable is not None:
            return (
                f"{label} segment {unavailable.dimension_value} is unavailable: "
                f"{unavailable.status}"
            )
    return None


def _overall_value(
    result: MetricResult,
    groups: tuple[MetricGroupResult, ...],
) -> Decimal:
    if result.status == MetricStatus.UNAVAILABLE_NO_DATA and not groups:
        return Decimal(0)
    return Decimal(result.value)


def _group_values(groups: tuple[MetricGroupResult, ...]) -> dict[str | None, Decimal]:
    return {
        item.dimension_value: Decimal(item.value)
        for item in groups
        if item.status == MetricStatus.AVAILABLE
    }


def _segment(
    dimension: str,
    member: str | None,
    current: Decimal,
    baseline: Decimal,
    overall_delta: Decimal,
    movement_total: Decimal,
) -> ContributionSegment:
    delta = current - baseline
    direction = (
        ContributionDirection.INCREASE
        if delta > 0
        else ContributionDirection.DECREASE
        if delta < 0
        else ContributionDirection.UNCHANGED
    )
    return ContributionSegment(
        dimension=dimension,
        dimension_value=member,
        current_value=current,
        baseline_value=baseline,
        delta=delta,
        net_change_share=None if overall_delta == 0 else delta / overall_delta,
        movement_share=None if movement_total == 0 else abs(delta) / movement_total,
        direction=direction,
        rank_by_absolute_change=0,
    )


def _member_sort_key(member: str | None) -> tuple[int, str]:
    return (1, "") if member is None else (0, member)


def _unavailable_result(
    metric_id: str,
    metric_name: str,
    dimension: str,
    comparison: str,
    current_start: date,
    current_end: date,
    baseline_start: date,
    baseline_end: date,
    reason: str,
) -> ContributionResult:
    return ContributionResult(
        metric_id=metric_id,
        metric_name=metric_name,
        dimension=dimension,
        comparison_type=comparison,
        current_start=current_start,
        current_end=current_end,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        overall_current=None,
        overall_baseline=None,
        overall_delta=None,
        net_change_share_available=False,
        segments=(),
        increase_segments=(),
        decrease_segments=(),
        unchanged_segments=(),
        current_reconciliation_difference=None,
        baseline_reconciliation_difference=None,
        reconciliation_difference=None,
        status=ContributionStatus.UNAVAILABLE,
        reason=reason,
    )
