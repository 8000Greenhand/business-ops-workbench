"""Load and validate the single metric-definition registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

import yaml

from ops_workbench.models.canonical_schema import COLUMN_METADATA

DEFAULT_METRICS_PATH = Path(__file__).resolve().parents[3] / "config" / "metrics.yaml"
MetricType = Literal["atomic", "ratio", "difference"]
MetricFormat = Literal["integer", "currency", "percentage"]
VALID_TYPES = frozenset({"atomic", "ratio", "difference"})
VALID_FORMATS = frozenset({"integer", "currency", "percentage"})
COMMON_KEYS = frozenset({"name", "type", "format", "higher_is_better"})
TYPE_KEYS = {
    "atomic": frozenset({"field", "aggregation"}),
    "ratio": frozenset({"numerator", "numerator_metric", "denominator"}),
    "difference": frozenset({"minuend", "subtrahend"}),
}


class DuplicateKeyError(ValueError):
    """Raised when a YAML mapping repeats a key."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DuplicateKeyError(f"Duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One validated atomic, ratio, or difference metric definition."""

    id: str
    name: str
    type: MetricType
    format: MetricFormat
    higher_is_better: bool
    dependencies: tuple[str, ...]
    field: str | None = None
    aggregation: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    minuend: str | None = None
    subtrahend: str | None = None


class MetricRegistry:
    """Immutable, validated registry loaded once from a metrics YAML file."""

    def __init__(self, definitions: Mapping[str, MetricDefinition]) -> None:
        self._definitions = MappingProxyType(dict(definitions))

    @classmethod
    def from_yaml(cls, path: Path = DEFAULT_METRICS_PATH) -> MetricRegistry:
        """Load definitions, rejecting malformed configuration immediately."""
        raw = load_unique_yaml(path)
        if not isinstance(raw, dict) or set(raw) != {"metrics"}:
            raise ValueError("Metrics YAML must contain only a 'metrics' mapping")
        metrics = raw["metrics"]
        if not isinstance(metrics, dict) or not metrics:
            raise ValueError("'metrics' must be a non-empty mapping")

        definitions: dict[str, MetricDefinition] = {}
        for metric_id, config in metrics.items():
            if not isinstance(metric_id, str) or not metric_id:
                raise ValueError("Metric ids must be non-empty strings")
            definitions[metric_id] = _parse_definition(metric_id, config)
        _validate_references(definitions)
        _validate_acyclic(definitions)
        return cls(definitions)

    def get(self, metric_id: str) -> MetricDefinition:
        """Return one definition or reject an unknown metric id."""
        try:
            return self._definitions[metric_id]
        except KeyError as error:
            raise ValueError(f"Unknown metric id: {metric_id}") from error

    def all(self) -> tuple[MetricDefinition, ...]:
        """Return all definitions in configuration order."""
        return tuple(self._definitions.values())

    def dependency_order(self, metric_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Return the requested metrics and dependencies in dependency-first order."""
        ordered: list[str] = []
        visited: set[str] = set()

        def visit(metric_id: str) -> None:
            definition = self.get(metric_id)
            if metric_id in visited:
                return
            for dependency in definition.dependencies:
                visit(dependency)
            visited.add(metric_id)
            ordered.append(metric_id)

        for metric_id in metric_ids:
            visit(metric_id)
        return tuple(ordered)


def load_unique_yaml(path: Path) -> object:
    """Safely load YAML while rejecting duplicate mapping keys."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.load(handle, Loader=_UniqueKeyLoader)


def _required_string(config: Mapping[str, object], key: str, metric_id: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Metric {metric_id} requires non-empty '{key}'")
    return value


def _parse_definition(metric_id: str, config: object) -> MetricDefinition:
    if not isinstance(config, dict):
        raise ValueError(f"Metric {metric_id} must be a mapping")
    metric_type = config.get("type")
    if metric_type not in VALID_TYPES:
        raise ValueError(f"Metric {metric_id} has invalid type: {metric_type}")
    allowed_keys = COMMON_KEYS | TYPE_KEYS[str(metric_type)]
    unexpected = set(config) - allowed_keys
    if unexpected:
        raise ValueError(f"Metric {metric_id} has unsupported keys: {sorted(unexpected)}")
    name = _required_string(config, "name", metric_id)
    metric_format = config.get("format")
    if metric_format not in VALID_FORMATS:
        raise ValueError(f"Metric {metric_id} has invalid format: {metric_format}")
    higher_is_better = config.get("higher_is_better")
    if not isinstance(higher_is_better, bool):
        raise ValueError(f"Metric {metric_id} requires boolean 'higher_is_better'")

    kwargs: dict[str, object] = {}
    dependencies: tuple[str, ...]
    if metric_type == "atomic":
        field = _required_string(config, "field", metric_id)
        if config.get("aggregation") != "sum":
            raise ValueError(f"Metric {metric_id} only supports aggregation 'sum'")
        kwargs.update(field=field, aggregation="sum")
        dependencies = ()
    elif metric_type == "ratio":
        numerator = config.get("numerator")
        numerator_metric = config.get("numerator_metric")
        if bool(numerator) == bool(numerator_metric):
            raise ValueError(
                f"Metric {metric_id} requires exactly one of numerator or numerator_metric"
            )
        numerator_id = str(numerator or numerator_metric)
        denominator = _required_string(config, "denominator", metric_id)
        kwargs.update(numerator=numerator_id, denominator=denominator)
        dependencies = (numerator_id, denominator)
    else:
        minuend = _required_string(config, "minuend", metric_id)
        subtrahend = _required_string(config, "subtrahend", metric_id)
        kwargs.update(minuend=minuend, subtrahend=subtrahend)
        dependencies = (minuend, subtrahend)

    return MetricDefinition(
        id=metric_id,
        name=name,
        type=metric_type,
        format=metric_format,
        higher_is_better=higher_is_better,
        dependencies=dependencies,
        **kwargs,
    )


def _validate_references(definitions: Mapping[str, MetricDefinition]) -> None:
    for definition in definitions.values():
        if definition.type == "atomic":
            metadata = COLUMN_METADATA.get(str(definition.field))
            if metadata is None or metadata.kind != "metric":
                raise ValueError(
                    f"Metric {definition.id} references non-metric canonical field: "
                    f"{definition.field}"
                )
        for dependency in definition.dependencies:
            if dependency not in definitions:
                raise ValueError(
                    f"Metric {definition.id} references unknown dependency: {dependency}"
                )


def _validate_acyclic(definitions: Mapping[str, MetricDefinition]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(metric_id: str) -> None:
        if metric_id in visiting:
            raise ValueError(f"Metric dependency cycle includes: {metric_id}")
        if metric_id in visited:
            return
        visiting.add(metric_id)
        for dependency in definitions[metric_id].dependencies:
            visit(dependency)
        visiting.remove(metric_id)
        visited.add(metric_id)

    for metric_id in definitions:
        visit(metric_id)
