"""Tests for the V0.2 city supply dashboard assembly and Streamlit page."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from ops_workbench.diagnostics.city_supply import (
    GrossMarginBand,
    SupplyDiagnosis,
    classify_gross_margin,
    diagnose_supply,
    load_city_supply_policy,
)
from ops_workbench.simulation.city_supply import SCENARIO_A, SCENARIO_B, SCENARIO_C
from ops_workbench.ui.city_supply_dashboard import (
    ANOMALY_COLUMNS,
    build_city_supply_dashboard,
    default_period,
    format_point_change,
    load_city_supply_facts,
    resolve_periods,
)


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src" / "ops_workbench" / "ui" / "pages" / "8_city_supply_ops.py"
APP = ROOT / "src" / "ops_workbench" / "ui" / "app.py"


@pytest.fixture(scope="module")
def facts() -> pd.DataFrame:
    return load_city_supply_facts()


def test_dashboard_data_assembly_succeeds(facts: pd.DataFrame) -> None:
    start, end = default_period(facts)
    data = build_city_supply_dashboard(facts, current_start=start, current_end=end)
    assert data.periods.days == 14
    assert set(data.overview) >= {"gmv", "completion_rate", "gross_margin"}
    assert set(data.city_comparison["city"]) == {"成都", "重庆", "昆明", "贵阳"}
    assert not data.daily_trend.empty
    assert not data.supply_diagnosis.empty


def test_previous_period_is_immediately_prior_and_equal_length(
    facts: pd.DataFrame,
) -> None:
    periods = resolve_periods(facts, date(2026, 8, 3), date(2026, 8, 16))
    assert periods.days == 14
    assert periods.baseline_start == date(2026, 7, 20)
    assert periods.baseline_end == date(2026, 8, 2)


def test_city_filter_limits_every_dashboard_drilldown(facts: pd.DataFrame) -> None:
    data = build_city_supply_dashboard(
        facts,
        current_start=SCENARIO_A.start_date,
        current_end=SCENARIO_A.end_date,
        city="成都",
    )
    assert set(data.city_comparison["city"]) == {"成都"}
    assert set(data.supply_diagnosis["city"]) == {"成都"}
    assert set(data.anomalies["城市"]) == {"成都"}


def test_city_completion_rate_uses_weighted_additive_totals(
    facts: pd.DataFrame,
) -> None:
    data = build_city_supply_dashboard(
        facts,
        current_start=SCENARIO_A.start_date,
        current_end=SCENARIO_A.end_date,
        city="成都",
    )
    row = data.city_comparison.iloc[0]
    source = facts[
        facts["date"].between(
            pd.Timestamp(SCENARIO_A.start_date), pd.Timestamp(SCENARIO_A.end_date)
        )
        & facts["city"].eq("成都")
    ]
    expected = source["completed_orders"].sum() / source["demand_orders"].sum()
    assert row["completion_rate_current"] == pytest.approx(expected)


def test_percentage_point_change_is_not_relative_growth(facts: pd.DataFrame) -> None:
    data = build_city_supply_dashboard(
        facts,
        current_start=SCENARIO_A.start_date,
        current_end=SCENARIO_A.end_date,
        city="成都",
        time_bucket="evening_peak",
    )
    comparison = data.overview["completion_rate"]
    assert comparison.point_change == pytest.approx(
        comparison.current - comparison.baseline
    )
    assert format_point_change(comparison.point_change).endswith("pp")
    assert comparison.point_change != pytest.approx(comparison.relative_change)


def test_margin_band_has_safe_near_and_at_floor_states() -> None:
    policy = load_city_supply_policy()
    assert classify_gross_margin(0.20, policy) == GrossMarginBand.SAFE
    assert classify_gross_margin(0.06, policy) == GrossMarginBand.NEAR_FLOOR
    assert classify_gross_margin(0.05, policy) == GrossMarginBand.AT_FLOOR


def test_supply_gap_rule_uses_demand_supply_and_completion_together() -> None:
    policy = load_city_supply_policy()
    result = diagnose_supply(
        demand_change=0.30,
        online_hours_change=-0.20,
        completion_rate_change_pp=-0.25,
        gmv_change=-0.18,
        efficiency_change=0.03,
        policy=policy,
    )
    assert result == SupplyDiagnosis.SUPPLY_GAP


def test_low_efficiency_rule_requires_online_growth_and_output_lag() -> None:
    policy = load_city_supply_policy()
    result = diagnose_supply(
        demand_change=0.02,
        online_hours_change=0.50,
        completion_rate_change_pp=0.00,
        gmv_change=0.03,
        efficiency_change=-0.31,
        policy=policy,
    )
    assert result == SupplyDiagnosis.EXCESS_SUPPLY


def test_scenario_a_is_a_p0_supply_gap(facts: pd.DataFrame) -> None:
    data = build_city_supply_dashboard(
        facts,
        current_start=SCENARIO_A.start_date,
        current_end=SCENARIO_A.end_date,
        city="成都",
    )
    match = data.anomalies[
        data.anomalies["区域/时段"].eq("成都东站 · 晚高峰")
    ].iloc[0]
    assert match["优先级"] == "P0"
    assert match["问题"] == "运力缺口"


def test_scenario_b_is_identified_as_low_efficiency_supply(facts: pd.DataFrame) -> None:
    data = build_city_supply_dashboard(
        facts,
        current_start=SCENARIO_B.start_date,
        current_end=SCENARIO_B.end_date,
        city="重庆",
    )
    assert set(data.anomalies["问题"]) == {"低效运力"}
    assert all("日间平峰" in scope for scope in data.anomalies["区域/时段"])


def test_scenario_c_is_identified_as_margin_risk(facts: pd.DataFrame) -> None:
    data = build_city_supply_dashboard(
        facts,
        current_start=SCENARIO_C.start_date,
        current_end=SCENARIO_C.end_date,
        city="昆明",
    )
    assert data.margin_band == GrossMarginBand.NEAR_FLOOR
    assert "毛利逼近红线" in set(data.anomalies["问题"])
    margin = data.anomalies[data.anomalies["问题"].eq("毛利逼近红线")].iloc[0]
    assert margin["优先级"] == "P1"
    assert "补贴率" in margin["关键证据"]


def test_streamlit_page_and_navigation_import_without_error() -> None:
    page = AppTest.from_file(PAGE).run(timeout=30)
    assert not page.exception
    visible = _visible_text(page)
    for label in (
        "核心经营结果",
        "城市经营对比",
        "核心趋势",
        "时空供需诊断",
        "运力效率与毛利",
        "经营异常池",
    ):
        assert label in visible
    assert len(page.date_input) == 2
    assert len(page.selectbox) == 2

    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    sidebar = " ".join(str(item.value) for item in app.sidebar.markdown)
    assert "药师帮经营" in sidebar
    assert "城市运力经营" in sidebar


def test_streamlit_filters_surface_all_three_simulated_scenarios() -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    assert not app.exception
    checks = (
        (SCENARIO_A, "成都", "运力缺口"),
        (SCENARIO_B, "重庆", "低效运力"),
        (SCENARIO_C, "昆明", "毛利逼近红线"),
    )
    for scenario, city, expected_issue in checks:
        app.date_input[0].set_value(scenario.start_date)
        app.date_input[1].set_value(scenario.end_date)
        app.selectbox[0].set_value(city)
        app.selectbox[1].set_value("全部时段")
        app = app.run(timeout=30)
        assert not app.exception
        anomaly = _anomaly_table(app)
        assert expected_issue in set(anomaly["问题"])


def _anomaly_table(app: AppTest) -> pd.DataFrame:
    for element in app.dataframe:
        if set(ANOMALY_COLUMNS).issubset(element.value.columns):
            return element.value
    raise AssertionError("Anomaly pool table was not rendered")


def _visible_text(app: AppTest) -> str:
    collections = (
        app.title,
        app.subheader,
        app.markdown,
        app.caption,
        app.info,
        app.warning,
        app.success,
    )
    return " ".join(str(item.value) for collection in collections for item in collection)
