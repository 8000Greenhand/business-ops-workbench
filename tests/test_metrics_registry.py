"""Tests for strict configuration-time metric validation."""

from pathlib import Path

import pytest

from ops_workbench.metrics.registry import (
    DEFAULT_METRICS_PATH,
    DuplicateKeyError,
    MetricRegistry,
)


def _write_metrics(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "metrics.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_default_metrics_yaml_loads_all_v1_metrics() -> None:
    registry = MetricRegistry.from_yaml(DEFAULT_METRICS_PATH)
    definitions = registry.all()

    assert len(definitions) == 21
    assert registry.get("leads").field == "leads"
    assert registry.get("net_revenue").dependencies == (
        "gross_revenue",
        "refund_amount",
    )
    assert registry.get("revenue_per_lead").dependencies == (
        "net_revenue",
        "leads",
    )
    with pytest.raises(ValueError, match="Unknown metric id"):
        registry.get("target_completion_rate")


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    path = _write_metrics(
        tmp_path,
        """metrics:
  leads:
    name: Leads
    name: Duplicate
    type: atomic
    field: leads
    aggregation: sum
    format: integer
    higher_is_better: true
""",
    )
    with pytest.raises(DuplicateKeyError, match="Duplicate YAML key"):
        MetricRegistry.from_yaml(path)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            """metrics:
  leads:
    name: Leads
    type: formula
    format: integer
    higher_is_better: true
""",
            "invalid type",
        ),
        (
            """metrics:
  bad:
    name: Bad
    type: atomic
    field: not_canonical
    aggregation: sum
    format: integer
    higher_is_better: true
""",
            "non-metric canonical field",
        ),
        (
            """metrics:
  leads:
    name: Leads
    type: atomic
    field: leads
    aggregation: sum
    format: integer
    higher_is_better: true
  broken_rate:
    name: Broken
    type: ratio
    numerator: leads
    format: percentage
    higher_is_better: true
""",
            "denominator",
        ),
        (
            """metrics:
  leads:
    name: Leads
    type: atomic
    field: leads
    aggregation: sum
    format: invalid
    higher_is_better: true
""",
            "invalid format",
        ),
    ],
)
def test_invalid_metric_configuration_is_rejected(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        MetricRegistry.from_yaml(_write_metrics(tmp_path, body))


def test_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    path = _write_metrics(
        tmp_path,
        """metrics:
  leads:
    name: Leads
    type: atomic
    field: leads
    aggregation: sum
    format: integer
    higher_is_better: true
  rate_a:
    name: A
    type: ratio
    numerator: rate_b
    denominator: leads
    format: percentage
    higher_is_better: true
  rate_b:
    name: B
    type: ratio
    numerator: rate_a
    denominator: leads
    format: percentage
    higher_is_better: true
""",
    )
    with pytest.raises(ValueError, match="dependency cycle"):
        MetricRegistry.from_yaml(path)
