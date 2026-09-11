"""Tests for strict business anomaly rule configuration."""

from pathlib import Path

import pytest

from ops_workbench.alerts.rules import (
    DEFAULT_ALERTS_PATH,
    AnomalyRuleRegistry,
)
from ops_workbench.alerts.severity import BusinessSeverity
from ops_workbench.validation.quality_models import Severity as DataQualitySeverity


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "alerts.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _rule_body(overrides: str = "") -> str:
    return f"""rules:
  - id: test_rule
    name: Test rule
    metric_id: conversion_rate
    dimension: channel
    method: comparison
    comparison: rolling_7d_average
    direction: decrease
    thresholds:
      warning:
        relative_change: -0.10
{overrides}"""


def test_default_alerts_yaml_loads() -> None:
    registry = AnomalyRuleRegistry.from_yaml(DEFAULT_ALERTS_PATH)
    rules = registry.all()
    assert len(rules) == 3
    assert rules[0].metric_id == "valid_lead_rate"
    assert rules[1].dimension == "team"
    assert rules[2].thresholds


def test_business_and_data_quality_severity_are_separate_types() -> None:
    assert BusinessSeverity is not DataQualitySeverity
    assert BusinessSeverity.WARNING.value == "warning"
    assert DataQualitySeverity.WARNING.value == "WARNING"


def test_duplicate_rule_id_is_rejected(tmp_path: Path) -> None:
    body = _rule_body() + """  - id: test_rule
    name: Duplicate
    metric_id: leads
    dimension:
    method: comparison
    comparison: previous_week
    direction: decrease
    thresholds:
      warning:
        relative_change: -0.10
"""
    with pytest.raises(ValueError, match="Duplicate anomaly rule id"):
        AnomalyRuleRegistry.from_yaml(_write(tmp_path, body))


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("metric_id: conversion_rate", "metric_id: unknown", "Unknown metric id"),
        ("dimension: channel", "dimension: date", "invalid dimension"),
        (
            "comparison: rolling_7d_average",
            "comparison: previous_year",
            "invalid comparison",
        ),
        ("direction: decrease", "direction: sideways", "invalid direction"),
        (
            "relative_change: -0.10",
            "arbitrary_expression: -0.10",
            "invalid threshold type",
        ),
    ],
)
def test_invalid_rule_configuration_is_rejected(
    tmp_path: Path,
    field: str,
    replacement: str,
    message: str,
) -> None:
    body = _rule_body().replace(field, replacement)
    with pytest.raises(ValueError, match=message):
        AnomalyRuleRegistry.from_yaml(_write(tmp_path, body))


def test_arbitrary_formula_key_is_rejected(tmp_path: Path) -> None:
    body = _rule_body("    formula: __import__('os').system('unsafe')\n")
    with pytest.raises(ValueError, match="unsupported keys"):
        AnomalyRuleRegistry.from_yaml(_write(tmp_path, body))


def test_percentage_point_threshold_requires_percentage_metric(tmp_path: Path) -> None:
    body = _rule_body().replace(
        "metric_id: conversion_rate",
        "metric_id: leads",
    ).replace(
        "relative_change: -0.10",
        "percentage_point_change: -0.10",
    )
    with pytest.raises(ValueError, match="requires a percentage metric"):
        AnomalyRuleRegistry.from_yaml(_write(tmp_path, body))
