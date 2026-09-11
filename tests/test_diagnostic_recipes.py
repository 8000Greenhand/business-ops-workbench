"""Tests for strict diagnostic recipe configuration."""

from pathlib import Path

import pytest

from ops_workbench.diagnostics.recipes import (
    DEFAULT_DIAGNOSTICS_PATH,
    DiagnosticRecipeRegistry,
)
from ops_workbench.metrics.registry import DuplicateKeyError


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "diagnostics.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _body() -> str:
    return """recipes:
  valid_lead_rate:
    diagnostic_type: ratio
    components: [valid_leads, leads]
    contribution_metrics: [valid_leads, leads]
    contribution_comparison: previous_week
    candidate_dimensions: [product, team]
    suggested_checks: [核对数据变化]
    top_n: 3
"""


def test_default_diagnostics_yaml_loads() -> None:
    registry = DiagnosticRecipeRegistry.from_yaml(DEFAULT_DIAGNOSTICS_PATH)
    assert len(registry.all()) == 4
    recipe = registry.get("conversion_rate")
    assert recipe.components == ("paid_users", "valid_leads")
    assert recipe.top_n == 3


def test_unknown_recipe_metric_is_rejected(tmp_path: Path) -> None:
    body = _body().replace("valid_lead_rate:", "unknown_metric:", 1)
    with pytest.raises(ValueError, match="Unknown metric id"):
        DiagnosticRecipeRegistry.from_yaml(_write(tmp_path, body))


def test_non_additive_contribution_metric_is_rejected(tmp_path: Path) -> None:
    body = _body().replace(
        "contribution_metrics: [valid_leads, leads]",
        "contribution_metrics: [valid_lead_rate]",
    )
    with pytest.raises(ValueError, match="is not additive"):
        DiagnosticRecipeRegistry.from_yaml(_write(tmp_path, body))


def test_invalid_dimension_and_comparison_are_rejected(tmp_path: Path) -> None:
    invalid_dimension = _body().replace("[product, team]", "[date]")
    with pytest.raises(ValueError, match="invalid candidate dimension"):
        DiagnosticRecipeRegistry.from_yaml(_write(tmp_path, invalid_dimension))

    invalid_comparison = _body().replace("previous_week", "rolling_7d_average")
    with pytest.raises(ValueError, match="invalid contribution comparison"):
        DiagnosticRecipeRegistry.from_yaml(_write(tmp_path, invalid_comparison))


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    body = _body().replace("    top_n: 3", "    top_n: 3\n    top_n: 5")
    with pytest.raises(DuplicateKeyError):
        DiagnosticRecipeRegistry.from_yaml(_write(tmp_path, body))


def test_formula_key_is_rejected(tmp_path: Path) -> None:
    body = _body().replace(
        "    top_n: 3",
        "    top_n: 3\n    formula: __import__('os').system('unsafe')",
    )
    with pytest.raises(ValueError, match="invalid configuration keys"):
        DiagnosticRecipeRegistry.from_yaml(_write(tmp_path, body))
