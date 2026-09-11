"""Strict loading and validation for configured business anomaly rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from ops_workbench.alerts.severity import BusinessSeverity
from ops_workbench.metrics.registry import MetricRegistry, load_unique_yaml
from ops_workbench.models.canonical_schema import DIMENSION_FIELDS

DEFAULT_ALERTS_PATH = Path(__file__).resolve().parents[3] / "config" / "alerts.yaml"
RuleMethod = Literal["comparison", "zscore"]
RuleComparison = Literal["rolling_7d_average", "previous_week"]
RuleDirection = Literal["increase", "decrease", "both"]
ThresholdMeasure = Literal[
    "relative_change",
    "percentage_point_change",
    "z_score",
]

_ALLOWED_RULE_KEYS = frozenset(
    {
        "id",
        "name",
        "metric_id",
        "dimension",
        "method",
        "comparison",
        "direction",
        "thresholds",
        "min_denominator",
        "min_baseline_value",
        "history_window_days",
        "min_history_days",
        "consecutive_days",
    }
)
_SEVERITY_ORDER = (
    BusinessSeverity.CRITICAL,
    BusinessSeverity.WARNING,
    BusinessSeverity.INFO,
)


@dataclass(frozen=True, slots=True)
class AnomalyThreshold:
    """One severity threshold over one controlled comparison measure."""

    measure: ThresholdMeasure
    value: Decimal


@dataclass(frozen=True, slots=True)
class AnomalyRule:
    """One validated comparison or z-score anomaly rule."""

    id: str
    name: str
    metric_id: str
    dimension: str | None
    method: RuleMethod
    comparison: RuleComparison | None
    direction: RuleDirection
    thresholds: Mapping[BusinessSeverity, AnomalyThreshold]
    min_denominator: Decimal | None = None
    min_baseline_value: Decimal | None = None
    history_window_days: int = 28
    min_history_days: int = 28
    consecutive_days: int = 1


class AnomalyRuleRegistry:
    """Immutable registry loaded once from the anomaly-rule YAML."""

    def __init__(self, rules: Mapping[str, AnomalyRule]) -> None:
        self._rules = MappingProxyType(dict(rules))

    @classmethod
    def from_yaml(
        cls,
        path: Path = DEFAULT_ALERTS_PATH,
        *,
        metric_registry: MetricRegistry | None = None,
    ) -> AnomalyRuleRegistry:
        """Load all rules and fail immediately on invalid configuration."""
        raw = load_unique_yaml(path)
        if not isinstance(raw, dict) or set(raw) != {"rules"}:
            raise ValueError("Alerts YAML must contain only a 'rules' list")
        raw_rules = raw["rules"]
        if not isinstance(raw_rules, list) or not raw_rules:
            raise ValueError("'rules' must be a non-empty list")
        metrics = metric_registry or MetricRegistry.from_yaml()
        rules: dict[str, AnomalyRule] = {}
        for config in raw_rules:
            rule = _parse_rule(config, metrics)
            if rule.id in rules:
                raise ValueError(f"Duplicate anomaly rule id: {rule.id}")
            rules[rule.id] = rule
        return cls(rules)

    def get(self, rule_id: str) -> AnomalyRule:
        """Return one configured rule or reject an unknown id."""
        try:
            return self._rules[rule_id]
        except KeyError as error:
            raise ValueError(f"Unknown anomaly rule id: {rule_id}") from error

    def all(self) -> tuple[AnomalyRule, ...]:
        """Return rules in configuration order."""
        return tuple(self._rules.values())

    def select(self, rule_ids: tuple[str, ...] | None) -> tuple[AnomalyRule, ...]:
        """Return all rules or a validated requested subset."""
        if rule_ids is None:
            return self.all()
        return tuple(self.get(rule_id) for rule_id in rule_ids)


def _parse_rule(config: object, metrics: MetricRegistry) -> AnomalyRule:
    if not isinstance(config, dict):
        raise ValueError("Each anomaly rule must be a mapping")
    unexpected = set(config) - _ALLOWED_RULE_KEYS
    if unexpected:
        raise ValueError(f"Anomaly rule has unsupported keys: {sorted(unexpected)}")
    rule_id = _required_string(config, "id")
    name = _required_string(config, "name")
    metric_id = _required_string(config, "metric_id")
    metric = metrics.get(metric_id)
    dimension = config.get("dimension")
    if dimension is not None and dimension not in DIMENSION_FIELDS:
        raise ValueError(f"Rule {rule_id} has invalid dimension: {dimension}")
    method = config.get("method", "comparison")
    if method not in {"comparison", "zscore"}:
        raise ValueError(f"Rule {rule_id} has invalid method: {method}")
    comparison = config.get("comparison")
    if method == "comparison":
        if comparison not in {"rolling_7d_average", "previous_week"}:
            raise ValueError(f"Rule {rule_id} has invalid comparison: {comparison}")
    elif comparison is not None:
        raise ValueError(f"Z-score rule {rule_id} cannot define comparison")
    direction = config.get("direction")
    if direction not in {"increase", "decrease", "both"}:
        raise ValueError(f"Rule {rule_id} has invalid direction: {direction}")
    thresholds = _parse_thresholds(rule_id, config.get("thresholds"), method, direction)
    if metric.format != "percentage" and any(
        threshold.measure == "percentage_point_change"
        for threshold in thresholds.values()
    ):
        raise ValueError(
            f"Rule {rule_id} percentage_point_change requires a percentage metric"
        )
    min_denominator = _optional_nonnegative_decimal(
        rule_id, "min_denominator", config.get("min_denominator")
    )
    if min_denominator is not None and metric.type != "ratio":
        raise ValueError(f"Rule {rule_id} min_denominator requires a ratio metric")
    min_baseline_value = _optional_nonnegative_decimal(
        rule_id, "min_baseline_value", config.get("min_baseline_value")
    )
    history_window_days = _positive_int(
        rule_id,
        "history_window_days",
        config.get("history_window_days", 28),
        minimum=2,
    )
    min_history_days = _positive_int(
        rule_id,
        "min_history_days",
        config.get("min_history_days", history_window_days),
        minimum=2,
    )
    if min_history_days > history_window_days:
        raise ValueError(f"Rule {rule_id} min_history_days exceeds history window")
    consecutive_days = _positive_int(
        rule_id,
        "consecutive_days",
        config.get("consecutive_days", 1),
    )
    return AnomalyRule(
        id=rule_id,
        name=name,
        metric_id=metric_id,
        dimension=dimension,
        method=method,
        comparison=comparison,
        direction=direction,
        thresholds=MappingProxyType(thresholds),
        min_denominator=min_denominator,
        min_baseline_value=min_baseline_value,
        history_window_days=history_window_days,
        min_history_days=min_history_days,
        consecutive_days=consecutive_days,
    )


def _parse_thresholds(
    rule_id: str,
    raw: object,
    method: object,
    direction: object,
) -> dict[BusinessSeverity, AnomalyThreshold]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"Rule {rule_id} requires thresholds")
    thresholds: dict[BusinessSeverity, AnomalyThreshold] = {}
    allowed_measures = (
        {"z_score"}
        if method == "zscore"
        else {"relative_change", "percentage_point_change"}
    )
    for severity_name, raw_threshold in raw.items():
        try:
            severity = BusinessSeverity(str(severity_name))
        except ValueError as error:
            raise ValueError(
                f"Rule {rule_id} has invalid severity: {severity_name}"
            ) from error
        if not isinstance(raw_threshold, dict) or len(raw_threshold) != 1:
            raise ValueError(f"Rule {rule_id} severity {severity} requires one threshold")
        measure, raw_value = next(iter(raw_threshold.items()))
        if measure not in allowed_measures:
            raise ValueError(f"Rule {rule_id} has invalid threshold type: {measure}")
        value = _decimal(rule_id, str(measure), raw_value)
        if direction == "decrease" and value > 0:
            raise ValueError(f"Rule {rule_id} decrease thresholds must be non-positive")
        if direction in {"increase", "both"} and value < 0:
            raise ValueError(f"Rule {rule_id} {direction} thresholds must be non-negative")
        thresholds[severity] = AnomalyThreshold(str(measure), value)
    return {
        severity: thresholds[severity]
        for severity in _SEVERITY_ORDER
        if severity in thresholds
    }


def _required_string(config: Mapping[str, object], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Anomaly rule requires non-empty '{key}'")
    return value


def _decimal(rule_id: str, field: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"Rule {rule_id} {field} must be numeric")
    return Decimal(str(value))


def _optional_nonnegative_decimal(
    rule_id: str,
    field: str,
    value: object,
) -> Decimal | None:
    if value is None:
        return None
    parsed = _decimal(rule_id, field, value)
    if parsed < 0:
        raise ValueError(f"Rule {rule_id} {field} must be non-negative")
    return parsed


def _positive_int(
    rule_id: str,
    field: str,
    value: object,
    *,
    minimum: int = 1,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"Rule {rule_id} {field} must be >= {minimum}")
    return value
