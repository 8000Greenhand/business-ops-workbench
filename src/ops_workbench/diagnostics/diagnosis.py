"""Structured orchestration from an anomaly to one-level diagnostic evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import MappingProxyType

from ops_workbench.diagnostics.contribution import ContributionEngine
from ops_workbench.diagnostics.models import (
    AnomalyEvent,
    ComponentObservation,
    ContributionDirection,
    ContributionStatus,
    DiagnosisResult,
    DiagnosisStatus,
    DrilldownFinding,
    EvidenceItem,
    EvidenceKind,
    SkippedDimension,
)
from ops_workbench.diagnostics.recipes import (
    DiagnosticRecipe,
    DiagnosticRecipeRegistry,
)
from ops_workbench.metrics.comparisons import compare_metric
from ops_workbench.metrics.engine import FilterValue, MetricEngine, MetricStatus

LIMITATION = (
    "当前仅确认数据偏离、指标组成变化和单层算术分布，"
    "不能确认具体业务原因或因果影响。"
)


class DiagnosisEngine:
    """Combine configured metric observations and bounded contribution findings."""

    def __init__(
        self,
        metric_engine: MetricEngine,
        *,
        recipe_registry: DiagnosticRecipeRegistry | None = None,
        contribution_engine: ContributionEngine | None = None,
    ) -> None:
        self.metric_engine = metric_engine
        self.recipe_registry = recipe_registry or DiagnosticRecipeRegistry.from_yaml(
            metric_registry=metric_engine.registry
        )
        self.contribution_engine = contribution_engine or ContributionEngine(
            metric_engine
        )

    def diagnose_event(
        self,
        event: AnomalyEvent,
        *,
        filters: Mapping[str, FilterValue] | None = None,
    ) -> DiagnosisResult:
        """Diagnose one structured anomaly event without causal conclusions."""
        self.metric_engine._build_where(
            start_date=None,
            end_date=None,
            filters=filters,
        )
        recipe = self.recipe_registry.get(event.metric_id)
        base_scope = _copy_filters(filters)
        if recipe is None:
            return _empty_result(
                event,
                DiagnosisStatus.UNSUPPORTED,
                base_scope,
                None,
                f"No diagnostic recipe is configured for {event.metric_id}",
            )
        scope, conflict = _merge_scope(base_scope, event)
        if conflict is not None:
            return _empty_result(
                event,
                DiagnosisStatus.INSUFFICIENT_DATA,
                base_scope,
                recipe.contribution_comparison,
                conflict,
            )

        observations = tuple(
            self._observe_component(component, event, recipe, scope)
            for component in recipe.components
        )
        observations_by_metric = {
            observation.metric_id: observation for observation in observations
        }
        has_available_observation = any(
            observation.current_status == MetricStatus.AVAILABLE
            and observation.baseline_status == MetricStatus.AVAILABLE
            for observation in observations
        )
        findings: list[DrilldownFinding] = []
        skipped: list[SkippedDimension] = []
        failed_attempt = False
        candidate_dimensions = []
        for dimension in recipe.candidate_dimensions:
            if dimension == event.dimension:
                skipped.append(
                    SkippedDimension(event.metric_id, dimension, "trigger dimension excluded")
                )
                continue
            if dimension in scope:
                skipped.append(
                    SkippedDimension(event.metric_id, dimension, "dimension fixed by scope filter")
                )
                continue
            candidate_dimensions.append(dimension)

        for metric_id in recipe.contribution_metrics:
            observation = observations_by_metric.get(metric_id)
            metric_observation_available = (
                observation is None
                or (
                    observation.current_status == MetricStatus.AVAILABLE
                    and observation.baseline_status == MetricStatus.AVAILABLE
                )
            )
            if not has_available_observation or not metric_observation_available:
                failed_attempt = True
                for dimension in candidate_dimensions:
                    skipped.append(
                        SkippedDimension(
                            metric_id,
                            dimension,
                            "component current or baseline is unavailable",
                        )
                    )
                continue
            for dimension in candidate_dimensions:
                result = self.contribution_engine.analyze_contribution(
                    metric_id,
                    event.date,
                    event.date,
                    dimension,
                    comparison=recipe.contribution_comparison,
                    filters=scope,
                )
                if result.status not in {
                    ContributionStatus.AVAILABLE,
                    ContributionStatus.AVAILABLE_NO_CHANGE,
                }:
                    failed_attempt = True
                    skipped.append(
                        SkippedDimension(
                            metric_id,
                            dimension,
                            result.reason or f"contribution status is {result.status}",
                        )
                    )
                    continue
                if result.segments and all(
                    segment.dimension_value is None for segment in result.segments
                ):
                    failed_attempt = True
                    skipped.append(
                        SkippedDimension(
                            metric_id,
                            dimension,
                            "candidate dimension has no classified values",
                        )
                    )
                    continue
                findings.append(
                    DrilldownFinding(
                        metric_id=metric_id,
                        dimension=dimension,
                        overall_delta=Decimal(result.overall_delta),
                        top_increases=result.top_increases(recipe.top_n),
                        top_decreases=result.top_decreases(recipe.top_n),
                        top_movements=result.top_movements(recipe.top_n),
                        reconciliation_status=result.status,
                        comparison_type=result.comparison_type,
                        scope_filters=scope,
                    )
                )

        available_observations = tuple(
            observation
            for observation in observations
            if observation.current_status == MetricStatus.AVAILABLE
            and observation.baseline_status == MetricStatus.AVAILABLE
        )
        if not available_observations and not findings:
            status = DiagnosisStatus.INSUFFICIENT_DATA
        elif (
            len(available_observations) != len(observations)
            or failed_attempt
            or not findings
        ):
            status = DiagnosisStatus.PARTIAL
        else:
            status = DiagnosisStatus.COMPLETE
        recommended_checks = _recommended_checks(recipe, findings)
        evidence = _build_evidence(event, observations, findings, recommended_checks)
        reason = (
            None
            if status == DiagnosisStatus.COMPLETE
            else "Some configured observations or drilldowns were unavailable"
            if status == DiagnosisStatus.PARTIAL
            else "No component observation or drilldown had sufficient data"
        )
        return DiagnosisResult(
            status=status,
            source_event=event,
            anomaly_comparison_type=event.comparison_type,
            diagnostic_comparison_type=recipe.contribution_comparison,
            scope_filters=scope,
            component_observations=observations,
            drilldown_findings=tuple(findings),
            evidence=evidence,
            recommended_checks=recommended_checks,
            skipped_dimensions=tuple(skipped),
            limitations=(LIMITATION,),
            reason=reason,
        )

    def _observe_component(
        self,
        metric_id: str,
        event: AnomalyEvent,
        recipe: DiagnosticRecipe,
        scope: Mapping[str, FilterValue],
    ) -> ComponentObservation:
        comparison = compare_metric(
            self.metric_engine,
            metric_id,
            event.date,
            event.date,
            comparison=recipe.contribution_comparison,
            filters=scope,
        )
        definition = self.metric_engine.registry.get(metric_id)
        direction = _direction(comparison.delta)
        return ComponentObservation(
            metric_id=metric_id,
            metric_name=definition.name,
            current_value=comparison.current.value,
            baseline_value=comparison.baseline.value,
            delta=comparison.delta,
            relative_change=comparison.relative_change,
            current_status=comparison.current.status,
            baseline_status=comparison.baseline.status,
            comparison_type=recipe.contribution_comparison,
            direction=direction,
        )


def render_diagnosis_summary(result: DiagnosisResult) -> str:
    """Render a short deterministic summary from structured diagnosis evidence."""
    lines = [
        f"诊断状态：{result.status.value}",
        f"异常基准：{result.anomaly_comparison_type}",
        f"诊断基准：{result.diagnostic_comparison_type or '未配置'}",
        "组成观察：",
    ]
    for observation in result.component_observations:
        if observation.delta is None:
            lines.append(
                f"- {observation.metric_name}：不可用（current={observation.current_status.value}, "
                f"baseline={observation.baseline_status.value}）"
            )
        else:
            lines.append(
                f"- {observation.metric_name}：current={observation.current_value}，"
                f"baseline={observation.baseline_value}，delta={observation.delta}"
            )
    lines.append("单层观察：")
    for finding in result.drilldown_findings:
        members = "、".join(
            str(item.dimension_value) for item in finding.top_movements
        )
        lines.append(
            f"- {finding.metric_id} 按 {finding.dimension}："
            f"变化幅度较大的分组为 {members or '无'}"
        )
    lines.append("建议检查：")
    lines.extend(f"- {check}" for check in result.recommended_checks)
    lines.append(f"限制：{result.limitations[0]}")
    return "\n".join(lines)


def _copy_filters(
    filters: Mapping[str, FilterValue] | None,
) -> Mapping[str, FilterValue]:
    copied: dict[str, FilterValue] = {}
    for field, value in (filters or {}).items():
        copied[field] = value if isinstance(value, str) else tuple(value)
    return MappingProxyType(copied)


def _merge_scope(
    filters: Mapping[str, FilterValue],
    event: AnomalyEvent,
) -> tuple[Mapping[str, FilterValue], str | None]:
    scope = dict(filters)
    if event.dimension is None:
        return MappingProxyType(scope), None
    if event.dimension_value is None:
        return (
            MappingProxyType(scope),
            "NULL anomaly dimension cannot be represented by the current filter API",
        )
    existing = scope.get(event.dimension)
    if existing is not None:
        values = (existing,) if isinstance(existing, str) else tuple(existing)
        if event.dimension_value not in values:
            return (
                MappingProxyType(scope),
                f"Anomaly scope conflicts with filter {event.dimension}",
            )
    scope[event.dimension] = event.dimension_value
    return MappingProxyType(scope), None


def _direction(delta: Decimal | None) -> ContributionDirection | None:
    if delta is None:
        return None
    if delta > 0:
        return ContributionDirection.INCREASE
    if delta < 0:
        return ContributionDirection.DECREASE
    return ContributionDirection.UNCHANGED


def _recommended_checks(
    recipe: DiagnosticRecipe,
    findings: Sequence[DrilldownFinding],
) -> tuple[str, ...]:
    checks = list(recipe.suggested_checks)
    seen = set(checks)
    for finding in findings:
        if not finding.top_movements:
            continue
        member = finding.top_movements[0].dimension_value
        check = (
            f"优先核对 {finding.dimension}={member} 的 {finding.metric_id} "
            "数据记录与口径变化"
        )
        if check not in seen:
            checks.append(check)
            seen.add(check)
        if len(checks) >= len(recipe.suggested_checks) + 3:
            break
    return tuple(checks)


def _build_evidence(
    event: AnomalyEvent,
    observations: Sequence[ComponentObservation],
    findings: Sequence[DrilldownFinding],
    checks: Sequence[str],
) -> tuple[EvidenceItem, ...]:
    evidence = [
        EvidenceItem(
            EvidenceKind.FACT,
            f"异常事件记录：{event.evidence}",
            (event.metric_id,),
            event.dimension,
        )
    ]
    for observation in observations:
        if observation.delta is None:
            message = (
                f"{observation.metric_name}在诊断基准"
                f"{observation.comparison_type}下不可用。"
            )
        else:
            message = (
                f"诊断基准{observation.comparison_type}下，"
                f"{observation.metric_name}当前值为{observation.current_value}，"
                f"基线值为{observation.baseline_value}，变化量为{observation.delta}。"
            )
        evidence.append(
            EvidenceItem(EvidenceKind.FACT, message, (observation.metric_id,))
        )
    for finding in findings:
        members = "、".join(
            str(item.dimension_value) for item in finding.top_movements
        )
        evidence.append(
            EvidenceItem(
                EvidenceKind.DIAGNOSTIC,
                f"按{finding.dimension}观察{finding.metric_id}，"
                f"变化幅度较大的分组包括{members or '无'}。",
                (finding.metric_id,),
                finding.dimension,
            )
        )
    evidence.extend(
        EvidenceItem(EvidenceKind.RECOMMENDATION, check, ()) for check in checks
    )
    return tuple(evidence)


def _empty_result(
    event: AnomalyEvent,
    status: DiagnosisStatus,
    scope: Mapping[str, FilterValue],
    diagnostic_comparison: str | None,
    reason: str,
) -> DiagnosisResult:
    return DiagnosisResult(
        status=status,
        source_event=event,
        anomaly_comparison_type=event.comparison_type,
        diagnostic_comparison_type=diagnostic_comparison,
        scope_filters=scope,
        component_observations=(),
        drilldown_findings=(),
        evidence=(
            EvidenceItem(EvidenceKind.FACT, f"异常事件记录：{event.evidence}", (event.metric_id,)),
        ),
        recommended_checks=(),
        skipped_dimensions=(),
        limitations=(LIMITATION,),
        reason=reason,
    )
