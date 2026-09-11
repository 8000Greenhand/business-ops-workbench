"""Configured business funnel assembly using MetricEngine results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

from ops_workbench.metrics.engine import (
    FilterValue,
    MetricEngine,
    MetricResult,
    MetricStatus,
    MetricValue,
)
from ops_workbench.metrics.registry import MetricRegistry, load_unique_yaml

DEFAULT_FUNNELS_PATH = Path(__file__).resolve().parents[3] / "config" / "funnels.yaml"


@dataclass(frozen=True, slots=True)
class FunnelStepDefinition:
    """One explicitly configured numerator/denominator relationship."""

    numerator: str
    denominator: str


@dataclass(frozen=True, slots=True)
class FunnelDefinition:
    """One validated funnel layout."""

    id: str
    name: str
    stages: tuple[str, ...]
    step_rates: tuple[FunnelStepDefinition, ...]
    outcomes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FunnelStepResult:
    """One configured step conversion result."""

    from_stage: str
    to_stage: str
    value: MetricValue | None
    status: MetricStatus
    numerator_value: MetricValue | None = None
    denominator_value: MetricValue | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class FunnelResult:
    """Configured stage, step-rate, and outcome metric results."""

    funnel_id: str
    name: str
    stages: tuple[MetricResult, ...]
    step_rates: tuple[FunnelStepResult, ...]
    outcomes: tuple[MetricResult, ...]


class FunnelRegistry:
    """Immutable validated registry for configured funnels."""

    def __init__(self, definitions: Mapping[str, FunnelDefinition]) -> None:
        self._definitions = MappingProxyType(dict(definitions))

    @classmethod
    def from_yaml(
        cls,
        path: Path = DEFAULT_FUNNELS_PATH,
        *,
        metric_registry: MetricRegistry | None = None,
    ) -> FunnelRegistry:
        """Load funnels and reject unknown metrics or executable expressions."""
        raw = load_unique_yaml(path)
        if not isinstance(raw, dict) or set(raw) != {"funnels"}:
            raise ValueError("Funnels YAML must contain only a 'funnels' mapping")
        funnels = raw["funnels"]
        if not isinstance(funnels, dict) or not funnels:
            raise ValueError("'funnels' must be a non-empty mapping")
        metrics = metric_registry or MetricRegistry.from_yaml()
        metric_ids = {definition.id for definition in metrics.all()}
        definitions: dict[str, FunnelDefinition] = {}
        for funnel_id, config in funnels.items():
            if not isinstance(funnel_id, str) or not funnel_id:
                raise ValueError("Funnel ids must be non-empty strings")
            definitions[funnel_id] = _parse_funnel(
                funnel_id,
                config,
                metric_ids,
            )
        return cls(definitions)

    def get(self, funnel_id: str) -> FunnelDefinition:
        """Return one funnel or reject an unknown id."""
        try:
            return self._definitions[funnel_id]
        except KeyError as error:
            raise ValueError(f"Unknown funnel id: {funnel_id}") from error


def calculate_funnel(
    engine: MetricEngine,
    funnel_id: str = "business_funnel",
    *,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    filters: Mapping[str, FilterValue] | None = None,
    registry: FunnelRegistry | None = None,
) -> FunnelResult:
    """Calculate a funnel in one batch metric query using engine filters."""
    funnels = registry or FunnelRegistry.from_yaml(metric_registry=engine.registry)
    definition = funnels.get(funnel_id)
    requested = tuple(
        dict.fromkeys(
            (
                *definition.stages,
                *(step.numerator for step in definition.step_rates),
                *(step.denominator for step in definition.step_rates),
                *definition.outcomes,
            )
        )
    )
    calculated = engine.calculate_metrics(
        requested,
        start_date=start_date,
        end_date=end_date,
        filters=filters,
    )
    by_metric = {result.metric_id: result for result in calculated}
    steps = tuple(
        _calculate_step(
            step,
            by_metric[step.numerator],
            by_metric[step.denominator],
        )
        for step in definition.step_rates
    )
    return FunnelResult(
        funnel_id=definition.id,
        name=definition.name,
        stages=tuple(by_metric[metric_id] for metric_id in definition.stages),
        step_rates=steps,
        outcomes=tuple(by_metric[metric_id] for metric_id in definition.outcomes),
    )


def _parse_funnel(
    funnel_id: str,
    config: object,
    metric_ids: set[str],
) -> FunnelDefinition:
    if not funnel_id:
        raise ValueError("Funnel ids must be non-empty strings")
    if not isinstance(config, dict) or set(config) != {
        "name",
        "stages",
        "step_rates",
        "outcomes",
    }:
        raise ValueError(f"Funnel {funnel_id} has invalid configuration keys")
    name = config["name"]
    if not isinstance(name, str) or not name:
        raise ValueError(f"Funnel {funnel_id} requires a non-empty name")
    stages = _metric_sequence(funnel_id, "stages", config["stages"], metric_ids)
    outcomes = _metric_sequence(funnel_id, "outcomes", config["outcomes"], metric_ids)
    raw_steps = config["step_rates"]
    if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, str):
        raise ValueError(f"Funnel {funnel_id} step_rates must be a list")
    steps: list[FunnelStepDefinition] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict) or set(raw_step) != {
            "numerator",
            "denominator",
        }:
            raise ValueError(
                f"Funnel {funnel_id} steps allow only numerator and denominator"
            )
        numerator = raw_step["numerator"]
        denominator = raw_step["denominator"]
        if (
            not isinstance(numerator, str)
            or not isinstance(denominator, str)
            or numerator not in metric_ids
            or denominator not in metric_ids
        ):
            raise ValueError(f"Funnel {funnel_id} step references unknown metric")
        steps.append(FunnelStepDefinition(str(numerator), str(denominator)))
    return FunnelDefinition(funnel_id, name, stages, tuple(steps), outcomes)


def _metric_sequence(
    funnel_id: str,
    field: str,
    value: object,
    metric_ids: set[str],
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str) or not value:
        raise ValueError(f"Funnel {funnel_id} {field} must be a non-empty list")
    items = tuple(value)
    if not all(isinstance(item, str) and item in metric_ids for item in items):
        raise ValueError(f"Funnel {funnel_id} {field} references unknown metric")
    return items


def _calculate_step(
    definition: FunnelStepDefinition,
    numerator: MetricResult,
    denominator: MetricResult,
) -> FunnelStepResult:
    for dependency in (numerator, denominator):
        if dependency.status != MetricStatus.AVAILABLE:
            return FunnelStepResult(
                from_stage=definition.denominator,
                to_stage=definition.numerator,
                value=None,
                status=dependency.status,
                reason=f"Dependency {dependency.metric_id} is unavailable",
            )
    if denominator.value == 0:
        return FunnelStepResult(
            from_stage=definition.denominator,
            to_stage=definition.numerator,
            value=None,
            status=MetricStatus.UNAVAILABLE_ZERO_DENOMINATOR,
            numerator_value=numerator.value,
            denominator_value=denominator.value,
            reason=f"{definition.denominator} aggregates to zero",
        )
    return FunnelStepResult(
        from_stage=definition.denominator,
        to_stage=definition.numerator,
        value=Decimal(numerator.value) / Decimal(denominator.value),
        status=MetricStatus.AVAILABLE,
        numerator_value=numerator.value,
        denominator_value=denominator.value,
    )
