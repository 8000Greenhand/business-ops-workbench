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
from ops_workbench.metrics.city_supply import aggregate_city_supply_metrics
from ops_workbench.simulation.city_supply import SCENARIO_A, SCENARIO_B, SCENARIO_C
from ops_workbench.ui.city_supply_dashboard import (
    ANOMALY_COLUMNS,
    build_city_supply_dashboard,
    default_period,
    finite_chart_rows,
    format_point_change,
    load_city_supply_facts,
    resolve_periods,
)


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src" / "ops_workbench" / "ui" / "pages" / "8_city_supply_ops.py"
APP = ROOT / "src" / "ops_workbench" / "ui" / "app.py"
CITY_APP = ROOT / "src" / "ops_workbench" / "ui" / "city_supply_app.py"


@pytest.fixture(scope="module")
def facts() -> pd.DataFrame:
    return load_city_supply_facts()


def test_dashboard_data_assembly_succeeds(facts: pd.DataFrame) -> None:
    start, end = default_period(facts)
    data = build_city_supply_dashboard(facts, current_start=start, current_end=end)
    assert data.periods.days == 30
    assert set(data.overview) >= {"gmv", "completion_rate", "gross_margin"}
    assert set(data.city_comparison["city"]) == {"成都", "重庆", "昆明", "贵阳"}
    assert not data.daily_trend.empty
    assert not data.supply_diagnosis.empty
    assert not data.result_decomposition.empty
    assert data.diagnostic_summary


def test_default_period_uses_latest_thirty_days(facts: pd.DataFrame) -> None:
    start, end = default_period(facts)
    assert (end - start).days + 1 == 30
    assert end == pd.Timestamp(facts["date"].max()).date()
    assert start == end - pd.Timedelta(days=29)


def test_previous_period_is_immediately_prior_and_equal_length(
    facts: pd.DataFrame,
) -> None:
    periods = resolve_periods(facts, date(2026, 8, 3), date(2026, 8, 16))
    assert periods.days == 14
    assert periods.baseline_start == date(2026, 7, 20)
    assert periods.baseline_end == date(2026, 8, 2)


def test_result_decomposition_reconciles_to_gmv_and_order_changes(
    facts: pd.DataFrame,
) -> None:
    start, end = default_period(facts)
    data = build_city_supply_dashboard(facts, current_start=start, current_end=end)
    bridge = data.result_decomposition

    gmv = bridge[bridge["bridge"].eq("GMV")]
    orders = bridge[bridge["bridge"].eq("完成订单量")]
    assert gmv["contribution"].sum() == pytest.approx(gmv["total_change"].iloc[0])
    assert orders["contribution"].sum() == pytest.approx(
        orders["total_change"].iloc[0]
    )


def test_supply_diagnosis_keeps_full_detail_with_anomalies_first(
    facts: pd.DataFrame,
) -> None:
    data = build_city_supply_dashboard(
        facts,
        current_start=SCENARIO_A.start_date,
        current_end=SCENARIO_A.end_date,
        city="成都",
    )
    assert len(data.supply_diagnosis) == 20
    assert data.supply_diagnosis.iloc[0]["diagnosis"] == "运力缺口"
    assert "供需基本稳定" in set(data.supply_diagnosis["diagnosis"])


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


def test_single_city_builds_zone_comparison_sorted_by_gmv(facts: pd.DataFrame) -> None:
    data = build_city_supply_dashboard(
        facts,
        current_start=SCENARIO_A.start_date,
        current_end=SCENARIO_A.end_date,
        city="成都",
    )
    current = facts[
        facts["date"].between(
            pd.Timestamp(SCENARIO_A.start_date), pd.Timestamp(SCENARIO_A.end_date)
        )
        & facts["city"].eq("成都")
    ]
    expected = aggregate_city_supply_metrics(current, group_by=("zone",))

    assert set(data.zone_comparison["zone"]) == set(expected["zone"])
    assert data.zone_comparison["gmv_current"].is_monotonic_decreasing
    for _, row in data.zone_comparison.iterrows():
        expected_row = expected.loc[expected["zone"].eq(row["zone"])].iloc[0]
        assert row["completion_rate_current"] == pytest.approx(
            expected_row["completion_rate"]
        )
        assert row["gross_margin_current"] == pytest.approx(
            expected_row["gross_margin"]
        )


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


def test_finite_chart_rows_drops_null_and_infinite_values() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"]),
            "metric": [0.8, float("inf"), None],
        }
    )
    safe = finite_chart_rows(frame, ("metric",))
    assert len(safe) == 1
    assert safe.iloc[0]["metric"] == pytest.approx(0.8)


def test_percentage_chart_specs_use_percentage_axis_and_tooltip() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert '"format": ".0%"' in source
    assert '"format": ".1%"' in source


def test_default_period_surfaces_material_margin_buffer_deterioration(
    facts: pd.DataFrame,
) -> None:
    start, end = default_period(facts)
    data = build_city_supply_dashboard(facts, current_start=start, current_end=end)
    attention = data.anomalies[data.anomalies["问题"].eq("毛利缓冲收窄")]
    assert not attention.empty
    assert "昆明" in set(attention["城市"])
    assert set(attention["优先级"]) == {"P2"}


def test_chart_dates_use_compact_numeric_labels() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert '"format": "%m-%d"' in source
    assert '"format": "%Y-%m-%d"' in source


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


def test_anomaly_rows_keep_complete_decision_chain(facts: pd.DataFrame) -> None:
    data = build_city_supply_dashboard(
        facts,
        current_start=SCENARIO_A.start_date,
        current_end=SCENARIO_A.end_date,
        city="成都",
    )
    assert not data.anomalies.empty
    for column in ANOMALY_COLUMNS:
        assert data.anomalies[column].astype(str).str.strip().ne("").all()


def test_streamlit_page_and_navigation_import_without_error() -> None:
    page = AppTest.from_file(PAGE).run(timeout=30)
    assert not page.exception
    visible = _visible_text(page)
    for label in (
        "核心经营结果",
        "经营结果拆解",
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
    assert "城市运力经营" not in sidebar

    city_app = AppTest.from_file(CITY_APP).run(timeout=30)
    assert not city_app.exception
    city_visible = _visible_text(city_app)
    assert "城市运力经营" in city_visible
    assert "药师帮经营" not in " ".join(
        str(item.value) for item in city_app.sidebar.markdown
    )


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
        assert expected_issue in _visible_text(app)
        if city == "成都":
            visible = _visible_text(app)
            assert "区域经营对比" in visible
            assert "城市经营对比" not in visible
            assert "P0 运力缺口｜成都东站晚高峰" in visible
            assert "定位路径：成都 → 成都东站 → 晚高峰" in visible
            assert (
                "重点提升晚高峰目标区域有效在线供给，通过司机激励、热区运营等方式补充短时运力，避免扩大无效补贴覆盖。"
                in visible
            )


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
