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
    gross_margin_near_buffer: float
    significant_demand_growth: float
    significant_online_growth: float
    flat_demand_upper: float
    supply_lag_gap: float
    completion_drop_pp: float
    severe_completion_drop_pp: float
    efficiency_decline: float
    gmv_growth_lag: float


class GrossMarginFloorStatus(StrEnum):
    """Relationship between a calculated gross margin and its configured floor."""

    AT_OR_ABOVE_FLOOR = "at_or_above_floor"
    BELOW_FLOOR = "below_floor"
    UNAVAILABLE = "unavailable"


class GrossMarginBand(StrEnum):
    """Business-facing gross-margin buffer state."""

    SAFE = "安全"
    NEAR_FLOOR = "接近红线"
    AT_FLOOR = "触线"
    UNAVAILABLE = "不可用"


class SupplyDiagnosis(StrEnum):
    """Configured multi-metric supply-demand diagnosis label."""

    SUPPLY_GAP = "运力缺口"
    EXCESS_SUPPLY = "运力偏富余"
    EFFICIENCY_DECLINE = "效率下降"
    STABLE = "供需基本稳定"


def load_city_supply_policy(path: Path = DEFAULT_POLICY_PATH) -> CitySupplyPolicy:
    """Load and validate the V0.1 simulated operating policy."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("City supply policy must be a mapping")
    scope_label = payload.get("scope_label")
    floor = payload.get("gross_margin_floor")
    diagnostics = payload.get("diagnostics")
    if scope_label != "模拟经营口径":
        raise ValueError("City supply policy must be labelled 模拟经营口径")
    if isinstance(floor, bool) or not isinstance(floor, (int, float)):
        raise ValueError("gross_margin_floor must be numeric")
    if not 0 <= float(floor) <= 1:
        raise ValueError("gross_margin_floor must be between 0 and 1")
    if not isinstance(diagnostics, dict):
        raise ValueError("City supply diagnostics policy must be a mapping")
    required = {
        "gross_margin_near_buffer",
        "significant_demand_growth",
        "significant_online_growth",
        "flat_demand_upper",
        "supply_lag_gap",
        "completion_drop_pp",
        "severe_completion_drop_pp",
        "efficiency_decline",
        "gmv_growth_lag",
    }
    missing = required.difference(diagnostics)
    if missing:
        raise ValueError(f"City supply diagnostics missing settings: {sorted(missing)}")
    parsed: dict[str, float] = {}
    for key in required:
        value = diagnostics[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"City supply diagnostic setting {key} must be numeric")
        parsed[key] = float(value)
    if parsed["gross_margin_near_buffer"] < 0:
        raise ValueError("gross_margin_near_buffer cannot be negative")
    return CitySupplyPolicy(
        scope_label=scope_label,
        gross_margin_floor=float(floor),
        **parsed,
    )


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


def classify_gross_margin(
    gross_margin: float | None,
    policy: CitySupplyPolicy,
) -> GrossMarginBand:
    """Classify margin using the configured floor and finite buffer above it."""
    if gross_margin is None or not math.isfinite(float(gross_margin)):
        return GrossMarginBand.UNAVAILABLE
    if gross_margin <= policy.gross_margin_floor:
        return GrossMarginBand.AT_FLOOR
    if gross_margin <= policy.gross_margin_floor + policy.gross_margin_near_buffer:
        return GrossMarginBand.NEAR_FLOOR
    return GrossMarginBand.SAFE


def diagnose_supply(
    *,
    demand_change: float | None,
    online_hours_change: float | None,
    completion_rate_change_pp: float | None,
    gmv_change: float | None,
    efficiency_change: float | None,
    policy: CitySupplyPolicy,
) -> SupplyDiagnosis:
    """Apply transparent simulated rules across demand, supply, fulfilment and output."""
    values = (
        demand_change,
        online_hours_change,
        completion_rate_change_pp,
        gmv_change,
        efficiency_change,
    )
    if any(value is None or not math.isfinite(float(value)) for value in values):
        return SupplyDiagnosis.STABLE
    supply_lags_demand = (
        online_hours_change <= 0
        or online_hours_change <= demand_change - policy.supply_lag_gap
    )
    if (
        demand_change >= policy.significant_demand_growth
        and supply_lags_demand
        and completion_rate_change_pp <= policy.completion_drop_pp
    ):
        return SupplyDiagnosis.SUPPLY_GAP
    if (
        online_hours_change >= policy.significant_online_growth
        and demand_change <= policy.flat_demand_upper
        and efficiency_change <= policy.efficiency_decline
    ):
        return SupplyDiagnosis.EXCESS_SUPPLY
    if (
        online_hours_change >= policy.significant_online_growth
        and gmv_change <= online_hours_change - policy.gmv_growth_lag
        and efficiency_change <= policy.efficiency_decline
    ):
        return SupplyDiagnosis.EFFICIENCY_DECLINE
    return SupplyDiagnosis.STABLE
