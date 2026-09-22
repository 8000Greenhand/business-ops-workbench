"""Generate deterministic city supply facts using a simulated operating model."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from ops_workbench.metrics.city_supply import (
    ADDITIVE_METRIC_COLUMNS,
    DIMENSION_COLUMNS,
    TIME_BUCKETS,
)


DEFAULT_SEED = 20260922
DEFAULT_START_DATE = date(2026, 5, 25)
DEFAULT_DAYS = 120

CITY_ZONES = {
    "成都": ("成都东站", "春熙路", "天府三街", "双流机场", "居住区"),
    "重庆": ("解放碑", "重庆北站", "观音桥", "江北机场", "南岸居住区"),
    "昆明": ("昆明站", "翠湖", "呈贡", "长水机场", "西山居住区"),
    "贵阳": ("贵阳北站", "喷水池", "观山湖", "龙洞堡机场", "花果园"),
}


@dataclass(frozen=True, slots=True)
class SimulationScenario:
    """Location and period where one deterministic operating pattern is injected."""

    scenario_id: str
    name: str
    city: str
    zones: tuple[str, ...]
    time_buckets: tuple[str, ...]
    start_date: date
    end_date: date


SCENARIO_A = SimulationScenario(
    scenario_id="A",
    name="晚高峰运力不足",
    city="成都",
    zones=("成都东站",),
    time_buckets=("evening_peak",),
    start_date=date(2026, 8, 3),
    end_date=date(2026, 8, 16),
)
SCENARIO_B = SimulationScenario(
    scenario_id="B",
    name="在线时长增长但效率下降",
    city="重庆",
    zones=CITY_ZONES["重庆"],
    time_buckets=("daytime_offpeak",),
    start_date=date(2026, 7, 6),
    end_date=date(2026, 7, 19),
)
SCENARIO_C = SimulationScenario(
    scenario_id="C",
    name="补贴拉动增长但逼近毛利红线",
    city="昆明",
    zones=CITY_ZONES["昆明"],
    time_buckets=TIME_BUCKETS,
    start_date=date(2026, 8, 24),
    end_date=date(2026, 9, 6),
)
SCENARIOS = (SCENARIO_A, SCENARIO_B, SCENARIO_C)

_CITY_DEMAND_SCALE = {"成都": 1.30, "重庆": 1.15, "昆明": 0.90, "贵阳": 0.78}
_CITY_AOV = {"成都": 34.0, "重庆": 33.0, "昆明": 30.0, "贵阳": 29.0}
_TIME_DEMAND_SCALE = {
    "morning_peak": 1.25,
    "daytime_offpeak": 0.82,
    "evening_peak": 1.42,
    "night": 0.68,
}
_TIME_AOV_SCALE = {
    "morning_peak": 1.03,
    "daytime_offpeak": 0.94,
    "evening_peak": 1.08,
    "night": 1.12,
}


def generate_city_supply_facts(
    *,
    seed: int = DEFAULT_SEED,
    start_date: date = DEFAULT_START_DATE,
    days: int = DEFAULT_DAYS,
) -> pd.DataFrame:
    """Return reproducible date-city-zone-time_bucket simulated facts.

    All values are synthetic and exist only for an operations-analysis portfolio.
    """
    if days <= 0:
        raise ValueError("days must be positive")
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    for day_number in range(days):
        business_date = start_date + timedelta(days=day_number)
        for city, zones in CITY_ZONES.items():
            for zone_index, zone in enumerate(zones):
                for time_bucket in TIME_BUCKETS:
                    rows.append(
                        _build_fact(
                            rng,
                            business_date,
                            day_number,
                            city,
                            zone,
                            zone_index,
                            time_bucket,
                        )
                    )
    return pd.DataFrame(rows, columns=[*DIMENSION_COLUMNS, *ADDITIVE_METRIC_COLUMNS])


def _build_fact(
    rng: random.Random,
    business_date: date,
    day_number: int,
    city: str,
    zone: str,
    zone_index: int,
    time_bucket: str,
) -> dict[str, object]:
    weekday_scale = (1.04, 1.03, 1.02, 1.01, 1.08, 1.12, 0.92)[business_date.weekday()]
    zone_scale = 0.86 + zone_index * 0.08
    trend_scale = 1.0 + day_number * 0.0009
    seasonality = 1.0 + 0.035 * math.sin(day_number * 2.0 * math.pi / 28.0)
    demand_mean = (
        155.0
        * _CITY_DEMAND_SCALE[city]
        * _TIME_DEMAND_SCALE[time_bucket]
        * weekday_scale
        * zone_scale
        * trend_scale
        * seasonality
    )
    demand_orders = max(1, round(rng.gauss(demand_mean, demand_mean * 0.035)))
    online_hours = max(0.25, demand_orders * 0.25 * rng.uniform(0.97, 1.03))
    target_completion_rate = 0.91 + rng.uniform(-0.012, 0.012)
    subsidy_rate = 0.045

    if _matches(SCENARIO_A, business_date, city, zone, time_bucket):
        demand_orders = round(demand_orders * 1.35)
        online_hours *= 0.68
    if _matches(SCENARIO_B, business_date, city, zone, time_bucket):
        demand_orders = round(demand_orders * 1.05)
        online_hours *= 1.55
    if _matches(SCENARIO_C, business_date, city, zone, time_bucket):
        demand_orders = round(demand_orders * 1.12)
        online_hours *= 1.25
        target_completion_rate = min(0.97, target_completion_rate + 0.05)
        subsidy_rate = 0.0958

    capacity_orders = math.floor(online_hours * 4.0)
    completed_orders = min(
        demand_orders,
        capacity_orders,
        round(demand_orders * target_completion_rate),
    )
    aov = (
        _CITY_AOV[city]
        * _TIME_AOV_SCALE[time_bucket]
        * rng.uniform(0.975, 1.025)
    )
    gmv = round(completed_orders * aov, 2)
    platform_revenue = round(gmv * 0.18, 2)
    driver_subsidy = round(gmv * subsidy_rate, 2)
    other_variable_cost = round(gmv * 0.075, 2)
    return {
        "date": pd.Timestamp(business_date),
        "city": city,
        "zone": zone,
        "time_bucket": time_bucket,
        "demand_orders": demand_orders,
        "completed_orders": completed_orders,
        "gmv": gmv,
        "online_hours": round(online_hours, 2),
        "platform_revenue": platform_revenue,
        "driver_subsidy": driver_subsidy,
        "other_variable_cost": other_variable_cost,
    }


def _matches(
    scenario: SimulationScenario,
    business_date: date,
    city: str,
    zone: str,
    time_bucket: str,
) -> bool:
    return (
        scenario.start_date <= business_date <= scenario.end_date
        and city == scenario.city
        and zone in scenario.zones
        and time_bucket in scenario.time_buckets
    )
