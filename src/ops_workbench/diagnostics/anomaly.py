"""Configuration-driven business anomaly detection over metric results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from ops_workbench.alerts.rules import AnomalyRule, AnomalyRuleRegistry
from ops_workbench.alerts.severity import BusinessSeverity
from ops_workbench.diagnostics.models import AnomalyEvent, AnomalyScanResult
from ops_workbench.metrics.comparisons import (
    MetricComparisonStatus,
    compare_metric_results,
)
from ops_workbench.metrics.engine import (
    FilterValue,
    MetricEngine,
    MetricResult,
    MetricStatus,
)
from ops_workbench.metrics.trend import (
    MetricDimensionSeriesPoint,
    MetricSeriesPoint,
    average_daily_metric,
    get_metric_series,
    get_metric_series_by_dimension,
)

SkipReason = Literal["no_data", "low_volume"]


@dataclass(frozen=True, slots=True)
class _Evaluation:
    rule: AnomalyRule
    date: date
    dimension_value: str | None
    current: MetricResult
    baseline: MetricResult | None
    delta: Decimal | None
    relative_change: Decimal | None
    percentage_point_change: Decimal | None
    z_score: Decimal | None
    severity: BusinessSeverity | None
    skip_reason: SkipReason | None = None


@dataclass(slots=True)
class _DayAccumulator:
    groups_evaluated: int = 0
    events: list[AnomalyEvent] = field(default_factory=list)
    skipped_no_data_count: int = 0
    skipped_low_volume_count: int = 0


class AnomalyEngine:
    """Scan business metric deviations without inferring their causes."""

    def __init__(
        self,
        metric_engine: MetricEngine,
        *,
        rule_registry: AnomalyRuleRegistry | None = None,
    ) -> None:
        self.metric_engine = metric_engine
        self.rule_registry = rule_registry or AnomalyRuleRegistry.from_yaml(
            metric_registry=metric_engine.registry
        )

    def scan_date(
        self,
        scan_date: date | str,
        *,
        rule_ids: Sequence[str] | None = None,
        filters: Mapping[str, FilterValue] | None = None,
    ) -> AnomalyScanResult:
        """Scan one date across overall or all members of each rule dimension."""
        target = _as_date(scan_date)
        return self.scan_range(
            target,
            target,
            rule_ids=rule_ids,
            filters=filters,
        )[0]

    def scan_range(
        self,
        start_date: date | str,
        end_date: date | str,
        *,
        rule_ids: Sequence[str] | None = None,
        filters: Mapping[str, FilterValue] | None = None,
    ) -> tuple[AnomalyScanResult, ...]:
        """Bulk-scan a date range with one metric-series query per selected rule."""
        start = _as_date(start_date)
        end = _as_date(end_date)
        if start > end:
            raise ValueError("start_date must not be after end_date")
        if isinstance(rule_ids, str):
            raise ValueError("rule_ids must be a sequence of rule ids")
        selected_ids = None if rule_ids is None else tuple(rule_ids)
        rules = self.rule_registry.select(selected_ids)
        dates = _date_range(start, end)
        accumulators = {current_date: _DayAccumulator() for current_date in dates}

        for rule in rules:
            evaluations = self._evaluate_rule(rule, start, end, filters)
            by_key = {
                (evaluation.date, evaluation.dimension_value): evaluation
                for evaluation in evaluations
            }
            members = tuple(
                dict.fromkeys(
                    evaluation.dimension_value
                    for evaluation in evaluations
                    if start <= evaluation.date <= end
                )
            )
            for current_date in dates:
                for member in members:
                    evaluation = by_key[(current_date, member)]
                    accumulator = accumulators[current_date]
                    accumulator.groups_evaluated += 1
                    if evaluation.skip_reason == "no_data":
                        accumulator.skipped_no_data_count += 1
                        continue
                    if evaluation.skip_reason == "low_volume":
                        accumulator.skipped_low_volume_count += 1
                        continue
                    if evaluation.severity is None:
                        continue
                    if not self._meets_consecutive_days(
                        rule,
                        current_date,
                        member,
                        by_key,
                    ):
                        continue
                    accumulator.events.append(_build_event(evaluation))

        return tuple(
            _scan_result(current_date, len(rules), accumulators[current_date])
            for current_date in dates
        )

    def _evaluate_rule(
        self,
        rule: AnomalyRule,
        start: date,
        end: date,
        filters: Mapping[str, FilterValue] | None,
    ) -> tuple[_Evaluation, ...]:
        lookback = 7 if rule.method == "comparison" else rule.history_window_days
        evaluation_start = start - timedelta(days=rule.consecutive_days - 1)
        query_start = evaluation_start - timedelta(days=lookback)
        points, members = self._load_points(rule, query_start, end, filters)
        evaluations: list[_Evaluation] = []
        for current_date in _date_range(evaluation_start, end):
            for member in members:
                current = points.get((current_date, member)) or _no_data_result(
                    self.metric_engine,
                    rule.metric_id,
                )
                if rule.method == "zscore":
                    evaluation = self._evaluate_zscore(
                        rule,
                        current_date,
                        member,
                        current,
                        points,
                    )
                else:
                    evaluation = self._evaluate_comparison(
                        rule,
                        current_date,
                        member,
                        current,
                        points,
                    )
                evaluations.append(evaluation)
        return tuple(evaluations)

    def _load_points(
        self,
        rule: AnomalyRule,
        start: date,
        end: date,
        filters: Mapping[str, FilterValue] | None,
    ) -> tuple[dict[tuple[date, str | None], MetricResult], tuple[str | None, ...]]:
        if rule.dimension is None:
            series = get_metric_series(
                self.metric_engine,
                rule.metric_id,
                start,
                end,
                filters=filters,
            )
            return (
                {
                    (point.date, None): _point_result(self.metric_engine, point)
                    for point in series.points
                },
                (None,),
            )
        series = get_metric_series_by_dimension(
            self.metric_engine,
            rule.metric_id,
            rule.dimension,
            start,
            end,
            filters=filters,
        )
        points = {
            (point.date, point.dimension_value): _point_result(
                self.metric_engine,
                point,
            )
            for point in series.points
        }
        members = tuple(dict.fromkeys(point.dimension_value for point in series.points))
        return points, members

    def _evaluate_comparison(
        self,
        rule: AnomalyRule,
        current_date: date,
        member: str | None,
        current: MetricResult,
        points: Mapping[tuple[date, str | None], MetricResult],
    ) -> _Evaluation:
        if rule.comparison == "previous_week":
            baseline_start = baseline_end = current_date - timedelta(days=7)
            baseline = points.get((baseline_start, member)) or _no_data_result(
                self.metric_engine,
                rule.metric_id,
            )
        else:
            baseline_start = current_date - timedelta(days=7)
            baseline_end = current_date - timedelta(days=1)
            daily = tuple(
                points.get((history_date, member))
                or _no_data_result(self.metric_engine, rule.metric_id)
                for history_date in _date_range(baseline_start, baseline_end)
            )
            baseline = average_daily_metric(
                self.metric_engine,
                rule.metric_id,
                daily,
            )
        comparison = compare_metric_results(
            rule.metric_id,
            rule.comparison,
            current,
            current_date,
            current_date,
            baseline,
            baseline_start,
            baseline_end,
        )
        if comparison.status != MetricComparisonStatus.AVAILABLE:
            return _skipped(rule, current_date, member, current, baseline, "no_data")
        low_volume = _low_volume(rule, current, baseline)
        if low_volume:
            return _skipped(rule, current_date, member, current, baseline, "low_volume")
        severity = _match_severity(
            rule,
            comparison.relative_change,
            comparison.percentage_point_change,
            None,
        )
        return _Evaluation(
            rule,
            current_date,
            member,
            current,
            baseline,
            comparison.delta,
            comparison.relative_change,
            comparison.percentage_point_change,
            None,
            severity,
        )

    def _evaluate_zscore(
        self,
        rule: AnomalyRule,
        current_date: date,
        member: str | None,
        current: MetricResult,
        points: Mapping[tuple[date, str | None], MetricResult],
    ) -> _Evaluation:
        if current.status != MetricStatus.AVAILABLE:
            return _skipped(rule, current_date, member, current, None, "no_data")
        history_start = current_date - timedelta(days=rule.history_window_days)
        history = tuple(
            points.get((history_date, member))
            for history_date in _date_range(
                history_start,
                current_date - timedelta(days=1),
            )
        )
        values = tuple(
            Decimal(result.value)
            for result in history
            if result is not None and result.status == MetricStatus.AVAILABLE
        )
        if len(values) < rule.min_history_days:
            return _skipped(rule, current_date, member, current, None, "no_data")
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        standard_deviation = variance.sqrt()
        if standard_deviation == 0:
            baseline = _baseline_result(self.metric_engine, rule.metric_id, mean)
            return _skipped(rule, current_date, member, current, baseline, "no_data")
        baseline = _baseline_result(self.metric_engine, rule.metric_id, mean)
        if _low_volume(rule, current, baseline):
            return _skipped(rule, current_date, member, current, baseline, "low_volume")
        delta = Decimal(current.value) - mean
        relative_change = None if mean == 0 else delta / mean
        percentage_point_change = delta if current.format == "percentage" else None
        z_score = delta / standard_deviation
        severity = _match_severity(
            rule,
            relative_change,
            percentage_point_change,
            z_score,
        )
        return _Evaluation(
            rule,
            current_date,
            member,
            current,
            baseline,
            delta,
            relative_change,
            percentage_point_change,
            z_score,
            severity,
        )

    @staticmethod
    def _meets_consecutive_days(
        rule: AnomalyRule,
        current_date: date,
        member: str | None,
        evaluations: Mapping[tuple[date, str | None], _Evaluation],
    ) -> bool:
        if rule.consecutive_days == 1:
            return True
        qualifying = {BusinessSeverity.WARNING, BusinessSeverity.CRITICAL}
        return all(
            evaluations[(current_date - timedelta(days=offset), member)].severity
            in qualifying
            for offset in range(rule.consecutive_days)
        )


def _match_severity(
    rule: AnomalyRule,
    relative_change: Decimal | None,
    percentage_point_change: Decimal | None,
    z_score: Decimal | None,
) -> BusinessSeverity | None:
    measures = {
        "relative_change": relative_change,
        "percentage_point_change": percentage_point_change,
        "z_score": z_score,
    }
    for severity, threshold in rule.thresholds.items():
        observed = measures[threshold.measure]
        if observed is None:
            continue
        if rule.direction == "decrease" and observed <= threshold.value:
            return severity
        if rule.direction == "increase" and observed >= threshold.value:
            return severity
        if rule.direction == "both" and abs(observed) >= threshold.value:
            return severity
    return None


def _low_volume(
    rule: AnomalyRule,
    current: MetricResult,
    baseline: MetricResult | None,
) -> bool:
    if rule.min_denominator is not None:
        if current.denominator_value is None:
            return True
        if Decimal(current.denominator_value) < rule.min_denominator:
            return True
    if rule.min_baseline_value is not None:
        if baseline is None or baseline.value is None:
            return True
        if abs(Decimal(baseline.value)) < rule.min_baseline_value:
            return True
    return False


def _skipped(
    rule: AnomalyRule,
    current_date: date,
    member: str | None,
    current: MetricResult,
    baseline: MetricResult | None,
    reason: SkipReason,
) -> _Evaluation:
    return _Evaluation(
        rule,
        current_date,
        member,
        current,
        baseline,
        None,
        None,
        None,
        None,
        None,
        reason,
    )


def _build_event(evaluation: _Evaluation) -> AnomalyEvent:
    rule = evaluation.rule
    current = evaluation.current
    baseline = evaluation.baseline
    if (
        baseline is None
        or current.value is None
        or baseline.value is None
        or evaluation.delta is None
        or evaluation.severity is None
    ):
        raise RuntimeError("Cannot build an event from an unavailable evaluation")
    return AnomalyEvent(
        rule_id=rule.id,
        rule_name=rule.name,
        metric_id=rule.metric_id,
        metric_name=current.name,
        date=evaluation.date,
        dimension=rule.dimension,
        dimension_value=evaluation.dimension_value,
        current_value=current.value,
        baseline_value=baseline.value,
        delta=evaluation.delta,
        relative_change=evaluation.relative_change,
        percentage_point_change=evaluation.percentage_point_change,
        severity=evaluation.severity,
        comparison_type=rule.comparison or "zscore",
        current_status=current.status,
        baseline_status=baseline.status,
        evidence=_evidence(evaluation),
        z_score=evaluation.z_score,
    )


def _evidence(evaluation: _Evaluation) -> str:
    rule = evaluation.rule
    current = evaluation.current
    baseline = evaluation.baseline
    if baseline is None or current.value is None or baseline.value is None:
        return ""
    subject = (
        "整体"
        if rule.dimension is None
        else f"{rule.dimension}={evaluation.dimension_value}"
    )
    baseline_label = {
        "rolling_7d_average": "过去7日基线",
        "previous_week": "上周同期基线",
        None: "历史均值",
    }[rule.comparison]
    pieces = [
        f"{evaluation.date.isoformat()} {subject}的{current.name}为"
        f"{_format_value(current.value, current.format)}，"
        f"{baseline_label}为{_format_value(baseline.value, current.format)}"
    ]
    if evaluation.relative_change is not None:
        pieces.append(f"，相对变化{evaluation.relative_change * 100:+.2f}%")
    if evaluation.percentage_point_change is not None:
        pieces.append(f"，百分点变化{evaluation.percentage_point_change * 100:+.2f}pct")
    if evaluation.z_score is not None:
        pieces.append(f"，z-score为{evaluation.z_score:+.2f}")
    return "".join(pieces) + "。"


def _format_value(value: object, metric_format: str) -> str:
    decimal_value = Decimal(value)
    if metric_format == "percentage":
        return f"{decimal_value * 100:.2f}%"
    if metric_format == "currency":
        return f"{decimal_value:.2f}"
    return f"{decimal_value:.2f}"


def _scan_result(
    current_date: date,
    rules_evaluated: int,
    accumulator: _DayAccumulator,
) -> AnomalyScanResult:
    events = tuple(accumulator.events)
    return AnomalyScanResult(
        date=current_date,
        rules_evaluated=rules_evaluated,
        groups_evaluated=accumulator.groups_evaluated,
        events=events,
        warning_count=sum(
            event.severity == BusinessSeverity.WARNING for event in events
        ),
        critical_count=sum(
            event.severity == BusinessSeverity.CRITICAL for event in events
        ),
        info_count=sum(event.severity == BusinessSeverity.INFO for event in events),
        skipped_no_data_count=accumulator.skipped_no_data_count,
        skipped_low_volume_count=accumulator.skipped_low_volume_count,
    )


def _point_result(
    engine: MetricEngine,
    point: MetricSeriesPoint | MetricDimensionSeriesPoint,
) -> MetricResult:
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


def _no_data_result(engine: MetricEngine, metric_id: str) -> MetricResult:
    definition = engine.registry.get(metric_id)
    return MetricResult(
        metric_id=metric_id,
        name=definition.name,
        value=None,
        status=MetricStatus.UNAVAILABLE_NO_DATA,
        format=definition.format,
        reason="No data exists for this date and dimension member",
    )


def _baseline_result(
    engine: MetricEngine,
    metric_id: str,
    value: Decimal,
) -> MetricResult:
    definition = engine.registry.get(metric_id)
    return MetricResult(
        metric_id=metric_id,
        name=definition.name,
        value=value,
        status=MetricStatus.AVAILABLE,
        format=definition.format,
    )


def _as_date(value: date | str) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _date_range(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset) for offset in range((end - start).days + 1)
    )
