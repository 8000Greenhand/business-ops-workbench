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
    gross_margin_attention_drop_pp: float
    significant_demand_growth: float
    significant_online_growth: float
    flat_demand_upper: float
    supply_lag_gap: float
    completion_drop_pp: float
    severe_completion_drop_pp: float
    efficiency_decline: float
    gmv_growth_lag: float
    effective_online_rate_drop_pp: float
    active_driver_growth: float
    driver_efficiency_decline: float


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
    EFFECTIVE_SUPPLY_GAP = "有效运力不足"
    EXCESS_SUPPLY = "运力偏富余"
    DRIVER_EFFICIENCY_DECLINE = "司机效率下降"
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
        "gross_margin_attention_drop_pp",
        "significant_demand_growth",
        "significant_online_growth",
        "flat_demand_upper",
        "supply_lag_gap",
        "completion_drop_pp",
        "severe_completion_drop_pp",
        "efficiency_decline",
        "gmv_growth_lag",
        "effective_online_rate_drop_pp",
        "active_driver_growth",
        "driver_efficiency_decline",
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
    effective_online_hours_change: float | None = None,
    effective_online_rate_change_pp: float | None = None,
    active_drivers_change: float | None = None,
    orders_per_active_driver_change: float | None = None,
    effective_efficiency_change: float | None = None,
) -> SupplyDiagnosis:
    """Apply transparent V2 rules across demand, driver supply, fulfilment and output."""
    values = (
        demand_change,
        online_hours_change,
        completion_rate_change_pp,
        gmv_change,
        efficiency_change,
    )
    if any(value is None or not math.isfinite(float(value)) for value in values):
        return SupplyDiagnosis.STABLE

    effective_supply_change = (
        float(effective_online_hours_change)
        if effective_online_hours_change is not None
        and math.isfinite(float(effective_online_hours_change))
        else float(online_hours_change)
    )
    effective_efficiency = (
        float(effective_efficiency_change)
        if effective_efficiency_change is not None
        and math.isfinite(float(effective_efficiency_change))
        else float(efficiency_change)
    )
    supply_lags_demand = (
        effective_supply_change <= 0
        or effective_supply_change <= demand_change - policy.supply_lag_gap
    )
    if (
        demand_change >= policy.significant_demand_growth
        and supply_lags_demand
        and completion_rate_change_pp <= policy.completion_drop_pp
    ):
        return SupplyDiagnosis.SUPPLY_GAP

    effective_rate_drop = (
        effective_online_rate_change_pp is not None
        and math.isfinite(float(effective_online_rate_change_pp))
        and effective_online_rate_change_pp <= policy.effective_online_rate_drop_pp
    )
    gross_online_keeps_up = (
        online_hours_change > 0
        and online_hours_change >= demand_change - policy.supply_lag_gap
    )
    if (
        gross_online_keeps_up
        and effective_rate_drop
        and completion_rate_change_pp <= policy.completion_drop_pp
    ):
        return SupplyDiagnosis.EFFECTIVE_SUPPLY_GAP

    if (
        effective_supply_change >= policy.significant_online_growth
        and demand_change <= policy.flat_demand_upper
        and effective_efficiency <= policy.efficiency_decline
    ):
        return SupplyDiagnosis.EXCESS_SUPPLY

    driver_efficiency_decline = (
        active_drivers_change is not None
        and math.isfinite(float(active_drivers_change))
        and active_drivers_change >= policy.active_driver_growth
        and orders_per_active_driver_change is not None
        and math.isfinite(float(orders_per_active_driver_change))
        and orders_per_active_driver_change <= policy.driver_efficiency_decline
    )
    if (
        driver_efficiency_decline
        and effective_efficiency <= policy.efficiency_decline
    ):
        return SupplyDiagnosis.DRIVER_EFFICIENCY_DECLINE

    if (
        effective_supply_change >= policy.significant_online_growth
        and gmv_change <= effective_supply_change - policy.gmv_growth_lag
        and effective_efficiency <= policy.efficiency_decline
    ):
        return SupplyDiagnosis.EFFICIENCY_DECLINE
    return SupplyDiagnosis.STABLE