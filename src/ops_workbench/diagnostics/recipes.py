"""Strict configuration registry for controlled diagnostic recipes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from ops_workbench.diagnostics.contribution import (
    SUPPORTED_COMPARISONS,
    is_contribution_eligible,
)
from ops_workbench.metrics.registry import MetricRegistry, load_unique_yaml
from ops_workbench.models.canonical_schema import DIMENSION_FIELDS

DEFAULT_DIAGNOSTICS_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "diagnostics.yaml"
)
DiagnosticType = Literal["ratio", "additive"]
_RECIPE_KEYS = frozenset(
    {
        "diagnostic_type",
        "components",
        "contribution_metrics",
        "contribution_comparison",
        "candidate_dimensions",
        "suggested_checks",
        "top_n",
    }
)


@dataclass(frozen=True, slots=True)
class DiagnosticRecipe:
    """One validated recipe for inspecting an anomaly metric."""

    metric_id: str
    diagnostic_type: DiagnosticType
    components: tuple[str, ...]
    contribution_metrics: tuple[str, ...]
    contribution_comparison: str
    candidate_dimensions: tuple[str, ...]
    suggested_checks: tuple[str, ...]
    top_n: int


class DiagnosticRecipeRegistry:
    """Immutable registry of validated diagnostic recipes."""

    def __init__(self, recipes: Mapping[str, DiagnosticRecipe]) -> None:
        self._recipes = MappingProxyType(dict(recipes))

    @classmethod
    def from_yaml(
        cls,
        path: Path = DEFAULT_DIAGNOSTICS_PATH,
        *,
        metric_registry: MetricRegistry | None = None,
    ) -> DiagnosticRecipeRegistry:
        """Load recipes and reject invalid metrics, dimensions, or expressions."""
        raw = load_unique_yaml(path)
        if not isinstance(raw, dict) or set(raw) != {"recipes"}:
            raise ValueError("Diagnostics YAML must contain only a 'recipes' mapping")
        raw_recipes = raw["recipes"]
        if not isinstance(raw_recipes, dict) or not raw_recipes:
            raise ValueError("'recipes' must be a non-empty mapping")
        metrics = metric_registry or MetricRegistry.from_yaml()
        recipes: dict[str, DiagnosticRecipe] = {}
        for metric_id, config in raw_recipes.items():
            if not isinstance(metric_id, str) or not metric_id:
                raise ValueError("Diagnostic recipe ids must be metric-id strings")
            recipes[metric_id] = _parse_recipe(metric_id, config, metrics)
        return cls(recipes)

    def get(self, metric_id: str) -> DiagnosticRecipe | None:
        """Return a recipe or None when a metric has no controlled recipe."""
        return self._recipes.get(metric_id)

    def all(self) -> tuple[DiagnosticRecipe, ...]:
        """Return all recipes in configuration order."""
        return tuple(self._recipes.values())


def _parse_recipe(
    metric_id: str,
    config: object,
    metrics: MetricRegistry,
) -> DiagnosticRecipe:
    metric = metrics.get(metric_id)
    if not isinstance(config, dict) or set(config) != _RECIPE_KEYS:
        raise ValueError(f"Recipe {metric_id} has invalid configuration keys")
    diagnostic_type = config["diagnostic_type"]
    if diagnostic_type not in {"ratio", "additive"}:
        raise ValueError(f"Recipe {metric_id} has invalid diagnostic_type")
    if diagnostic_type == "ratio" and metric.type != "ratio":
        raise ValueError(f"Recipe {metric_id} ratio type does not match metric definition")
    if diagnostic_type == "additive" and not is_contribution_eligible(
        metric_id, metrics
    ):
        raise ValueError(f"Recipe {metric_id} is not additive")
    components = _metric_list(metric_id, "components", config["components"], metrics)
    contribution_metrics = _metric_list(
        metric_id,
        "contribution_metrics",
        config["contribution_metrics"],
        metrics,
    )
    for contribution_metric in contribution_metrics:
        if not is_contribution_eligible(contribution_metric, metrics):
            raise ValueError(
                f"Recipe {metric_id} contribution metric {contribution_metric} "
                "is not additive"
            )
    if diagnostic_type == "ratio":
        missing_dependencies = set(metric.dependencies) - set(components)
        if missing_dependencies:
            raise ValueError(
                f"Recipe {metric_id} is missing ratio components: "
                f"{sorted(missing_dependencies)}"
            )
        if not all(is_contribution_eligible(item, metrics) for item in components):
            raise ValueError(f"Recipe {metric_id} ratio components must be additive")
    comparison = config["contribution_comparison"]
    if comparison not in SUPPORTED_COMPARISONS:
        raise ValueError(f"Recipe {metric_id} has invalid contribution comparison")
    dimensions = _string_list(
        metric_id,
        "candidate_dimensions",
        config["candidate_dimensions"],
    )
    if any(dimension not in DIMENSION_FIELDS for dimension in dimensions):
        raise ValueError(f"Recipe {metric_id} has invalid candidate dimension")
    checks = _string_list(metric_id, "suggested_checks", config["suggested_checks"])
    top_n = config["top_n"]
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n <= 0:
        raise ValueError(f"Recipe {metric_id} top_n must be a positive integer")
    return DiagnosticRecipe(
        metric_id=metric_id,
        diagnostic_type=diagnostic_type,
        components=components,
        contribution_metrics=contribution_metrics,
        contribution_comparison=str(comparison),
        candidate_dimensions=dimensions,
        suggested_checks=checks,
        top_n=top_n,
    )


def _metric_list(
    recipe_id: str,
    field: str,
    value: object,
    metrics: MetricRegistry,
) -> tuple[str, ...]:
    items = _string_list(recipe_id, field, value)
    for item in items:
        metrics.get(item)
    return items


def _string_list(recipe_id: str, field: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str) or not value:
        raise ValueError(f"Recipe {recipe_id} {field} must be a non-empty list")
    items = tuple(value)
    if not all(isinstance(item, str) and item for item in items):
        raise ValueError(f"Recipe {recipe_id} {field} requires non-empty strings")
    if len(set(items)) != len(items):
        raise ValueError(f"Recipe {recipe_id} {field} contains duplicates")
    return items
