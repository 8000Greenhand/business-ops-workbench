"""Configuration-backed guardrails for simulated city supply operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from pathlib import Path

import yaml


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[3] / "config" / "city_supply_ops.yaml"


@dataclass(frozen=True, slots=True)
class CitySupplyPolicy:
    """Configurable policy values for the simulated operating model."""

    scope_label: str
    gross_margin_floor: float


class GrossMarginFloorStatus(StrEnum):
    """Relationship between a calculated gross margin and its configured floor."""

    AT_OR_ABOVE_FLOOR = "at_or_above_floor"
    BELOW_FLOOR = "below_floor"
    UNAVAILABLE = "unavailable"


def load_city_supply_policy(path: Path = DEFAULT_POLICY_PATH) -> CitySupplyPolicy:
    """Load and validate the V0.1 simulated operating policy."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("City supply policy must be a mapping")
    scope_label = payload.get("scope_label")
    floor = payload.get("gross_margin_floor")
    if scope_label != "模拟经营口径":
        raise ValueError("City supply policy must be labelled 模拟经营口径")
    if isinstance(floor, bool) or not isinstance(floor, (int, float)):
        raise ValueError("gross_margin_floor must be numeric")
    if not 0 <= float(floor) <= 1:
        raise ValueError("gross_margin_floor must be between 0 and 1")
    return CitySupplyPolicy(scope_label=scope_label, gross_margin_floor=float(floor))


def assess_gross_margin_floor(
    gross_margin: float | None,
    policy: CitySupplyPolicy,
) -> GrossMarginFloorStatus:
    """Classify a simulated gross margin against the configured red line."""
    if gross_margin is None or not math.isfinite(float(gross_margin)):
        return GrossMarginFloorStatus.UNAVAILABLE
    if gross_margin < policy.gross_margin_floor:
        return GrossMarginFloorStatus.BELOW_FLOOR
    return GrossMarginFloorStatus.AT_OR_ABOVE_FLOOR
