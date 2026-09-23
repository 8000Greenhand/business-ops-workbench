"""Tests for the V0.1 city supply operating foundation."""

from __future__ import annotations

from dataclasses import replace
import math
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.diagnostics.city_supply import (
    GrossMarginFloorStatus,
    assess_gross_margin_floor,
    load_city_supply_policy,
)
from ops_workbench.metrics.city_supply import (
    ADDITIVE_METRIC_COLUMNS,
    DERIVED_METRIC_COLUMNS,
    DIMENSION_COLUMNS,
    TIME_BUCKETS,
    aggregate_city_supply_metrics,
)
from ops_workbench.simulation.city_supply import (
    CITY_ZONES,
    DEFAULT_DAYS,
    SCENARIO_A,
    SCENARIO_B,
    SCENARIO_C,
    SimulationScenario,
    generate_city_supply_facts,
)


@pytest.fixture(scope="module")
def facts() -> pd.DataFrame:
    """Generate one shared deterministic city supply fact table."""
    return generate_city_supply_facts()


def _scenario_rows(frame: pd.DataFrame, scenario: SimulationScenario) -> pd.DataFrame:
    start = pd.Timestamp(scenario.start_date)
    end = pd.Timestamp(scenario.end_date)
    return frame[
        frame["date"].between(start, end)
        & frame["city"].eq(scenario.city)
        & frame["zone"].isin(scenario.zones)
        & frame["time_bucket"].isin(scenario.time_buckets)
    ]


def _baseline_rows(frame: pd.DataFrame, scenario: SimulationScenario) -> pd.DataFrame:
    duration = (scenario.end_date - scenario.start_date).days + 1
    baseline_end = scenario.start_date - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=duration - 1)
    comparison = replace(
        scenario,
        start_date=baseline_start,
        end_date=baseline_end,
    )
    return _scenario_rows(frame, comparison)


def _summary(frame: pd.DataFrame) -> pd.Series:
    return aggregate_city_supply_metrics(frame).iloc[0]


def test_completion_rate_is_calculated_from_additive_inputs() -> None:
    frame = _small_frame(demand_orders=100, completed_orders=82)
    assert _summary(frame)["completion_rate"] == pytest.approx(0.82)


def test_multirow_completion_rate_uses_weighted_aggregation() -> None:
    frame = pd.concat(
        [
            _small_frame(demand_orders=10, completed_orders=10),
            _small_frame(demand_orders=90, completed_orders=45, zone="B"),
        ],
        ignore_index=True,
    )
    result = _summary(frame)
    assert result["completion_rate"] == pytest.approx(0.55)
    assert result["completion_rate"] != pytest.approx((1.0 + 0.5) / 2)


def test_gross_margin_uses_aggregated_revenue_and_costs() -> None:
    frame = pd.concat(
        [
            _small_frame(platform_revenue=100, driver_subsidy=20, other_variable_cost=10),
            _small_frame(
                platform_revenue=900,
                driver_subsidy=270,
                other_variable_cost=180,
                zone="B",
            ),
        ],
        ignore_index=True,
    )
    result = _summary(frame)
    assert result["gross_profit"] == pytest.approx(520)
    assert result["gross_margin"] == pytest.approx(0.52)
    assert result["gross_margin"] != pytest.approx((0.70 + 0.50) / 2)


def test_online_hour_efficiency_metrics_are_correct() -> None:
    result = _summary(
        _small_frame(gmv=1_200, completed_orders=60, demand_orders=75, online_hours=30)
    )
    assert result["gmv_per_online_hour"] == pytest.approx(40)
    assert result["orders_per_online_hour"] == pytest.approx(2)
    assert result["avg_order_value"] == pytest.approx(20)


def test_zero_denominators_return_null_without_infinity() -> None:
    result = _summary(
        _small_frame(
            demand_orders=0,
            completed_orders=0,
            gmv=0,
            online_hours=0,
            platform_revenue=0,
            driver_subsidy=0,
            other_variable_cost=0,
        )
    )
    for column in DERIVED_METRIC_COLUMNS:
        value = result[column]
        assert pd.isna(value) or not math.isinf(float(value))
    assert pd.isna(result["completion_rate"])
    assert pd.isna(result["gross_margin"])


def test_null_input_remains_unavailable() -> None:
    frame = _small_frame()
    frame["online_hours"] = pd.Series([None], dtype="Float64")
    result = _summary(frame)
    assert pd.isna(result["online_hours"])
    assert pd.isna(result["gmv_per_online_hour"])
    assert pd.isna(result["orders_per_online_hour"])


def test_simulation_covers_at_least_90_days(facts: pd.DataFrame) -> None:
    assert facts["date"].nunique() == DEFAULT_DAYS
    assert DEFAULT_DAYS >= 90


def test_simulation_contains_four_cities(facts: pd.DataFrame) -> None:
    assert set(facts["city"]) == set(CITY_ZONES)


def test_simulation_contains_all_time_buckets(facts: pd.DataFrame) -> None:
    assert set(facts["time_bucket"]) == set(TIME_BUCKETS)


def test_simulation_has_exact_unique_fact_grain_and_no_stored_ratios(
    facts: pd.DataFrame,
) -> None:
    assert list(facts.columns) == [*DIMENSION_COLUMNS, *ADDITIVE_METRIC_COLUMNS]
    assert not facts.duplicated(list(DIMENSION_COLUMNS)).any()


def test_simulation_is_reproducible(facts: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(facts, generate_city_supply_facts())


def test_scenario_a_has_demand_but_insufficient_evening_supply(
    facts: pd.DataFrame,
) -> None:
    current = _summary(_scenario_rows(facts, SCENARIO_A))
    baseline = _summary(_baseline_rows(facts, SCENARIO_A))
    assert current["demand_orders"] > baseline["demand_orders"] * 1.20
    assert current["online_hours"] < baseline["online_hours"] * 0.80
    assert current["completion_rate"] < baseline["completion_rate"] - 0.20
    assert current["gmv"] < baseline["gmv"]


def test_scenario_b_adds_low_efficiency_online_hours(facts: pd.DataFrame) -> None:
    current = _summary(_scenario_rows(facts, SCENARIO_B))
    baseline = _summary(_baseline_rows(facts, SCENARIO_B))
    online_growth = current["online_hours"] / baseline["online_hours"] - 1
    gmv_growth = current["gmv"] / baseline["gmv"] - 1
    assert online_growth > 0.40
    assert gmv_growth > 0
    assert gmv_growth < online_growth
    assert current["gmv_per_online_hour"] < baseline["gmv_per_online_hour"] * 0.80


def test_scenario_c_grows_with_subsidy_near_margin_floor(facts: pd.DataFrame) -> None:
    current = _summary(_scenario_rows(facts, SCENARIO_C))
    baseline = _summary(_baseline_rows(facts, SCENARIO_C))
    policy = load_city_supply_policy()
    assert current["online_hours"] > baseline["online_hours"] * 1.15
    assert current["completion_rate"] > baseline["completion_rate"] + 0.02
    assert current["gmv"] > baseline["gmv"] * 1.10
    assert current["gross_margin"] == pytest.approx(policy.gross_margin_floor, abs=0.002)
    assert current["gross_margin"] < baseline["gross_margin"] - 0.20
    assert (
        assess_gross_margin_floor(float(current["gross_margin"]), policy)
        == GrossMarginFloorStatus.AT_OR_ABOVE_FLOOR
    )


def test_default_policy_is_explicitly_simulated_and_configurable() -> None:
    policy = load_city_supply_policy()
    assert policy.scope_label == "模拟经营口径"
    assert policy.gross_margin_floor == pytest.approx(0.05)


def test_policy_loader_honors_a_custom_margin_floor(tmp_path: Path) -> None:
    path = tmp_path / "city_supply_ops.yaml"
    default_policy = (
        Path(__file__).resolve().parents[1] / "config" / "city_supply_ops.yaml"
    ).read_text(encoding="utf-8")
    path.write_text(
        default_policy.replace("gross_margin_floor: 0.05", "gross_margin_floor: 0.12"),
        encoding="utf-8",
    )
    policy = load_city_supply_policy(path)
    assert policy.gross_margin_floor == pytest.approx(0.12)
    assert (
        assess_gross_margin_floor(0.10, policy)
        == GrossMarginFloorStatus.BELOW_FLOOR
    )


def _small_frame(
    *,
    demand_orders: float = 100,
    completed_orders: float = 80,
    gmv: float = 2_400,
    online_hours: float = 40,
    platform_revenue: float = 500,
    driver_subsidy: float = 100,
    other_variable_cost: float = 50,
    zone: str = "A",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-01-01"),
                "city": "测试市",
                "zone": zone,
                "time_bucket": "morning_peak",
                "demand_orders": demand_orders,
                "completed_orders": completed_orders,
                "gmv": gmv,
                "online_hours": online_hours,
                "platform_revenue": platform_revenue,
                "driver_subsidy": driver_subsidy,
                "other_variable_cost": other_variable_cost,
            }
        ]
    )
