from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from ops_workbench.ui.ysb_dashboard import (
    business_rows,
    filter_dashboard,
    format_rank_change,
    is_standard_comparison_period,
    latest_complete_period,
    load_priority_mart,
    merchant_trend,
    overview_metrics,
    period_quality_status,
    summarize_attention_reasons,
    top_growth,
    top_loss,
)


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src" / "ops_workbench" / "ui" / "pages" / "6_ysb_dashboard_a.py"
MART = ROOT / "demo_data" / "ysb_dashboard_a" / "mart_merchant_monthly_priority.csv"


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"month": "2026-03", "merchant_key": "ID:A", "merchant_name": "A", "owner": "O1", "merchant_scale": "KEY", "priority_level": "NO_PRIORITY", "merchant_mapping_status": "ID_MATCHED", "current_gmv": 100.0, "previous_gmv": 90.0, "gmv_change_abs": 10.0, "gmv_loss": 0.0, "gmv_mom": 1 / 9, "gmv_rank_current": 2, "gmv_rank_change": 1, "previous_gmv_share": 0.5, "diagnostic_dimensions": "Trend", "data_quality_status": "NO_ALERT", "metric_quality_status": "VALID", "aftersales_rate": 0.01},
            {"month": "2026-04", "merchant_key": "ID:A", "merchant_name": "A", "owner": "O1", "merchant_scale": "KEY", "priority_level": "PRIORITY", "merchant_mapping_status": "ID_MATCHED", "current_gmv": 80.0, "previous_gmv": 100.0, "gmv_change_abs": -20.0, "gmv_loss": 20.0, "gmv_mom": -0.2, "gmv_rank_current": 2, "gmv_rank_change": 1, "previous_gmv_share": 0.5, "diagnostic_dimensions": "Trend", "data_quality_status": "NO_ALERT", "metric_quality_status": "VALID", "aftersales_rate": 0.01},
            {"month": "2026-04", "merchant_key": "ID:B", "merchant_name": "B", "owner": "O2", "merchant_scale": "MID", "priority_level": "ATTENTION", "merchant_mapping_status": "ID_MATCHED", "current_gmv": 50.0, "previous_gmv": 40.0, "gmv_change_abs": 10.0, "gmv_loss": 0.0, "gmv_mom": 0.25, "gmv_rank_current": 1, "gmv_rank_change": -1, "previous_gmv_share": 0.2, "diagnostic_dimensions": "", "data_quality_status": "NO_ALERT", "metric_quality_status": "VALID", "aftersales_rate": 0.01},
            {"month": "2026-05", "merchant_key": "ID:A", "merchant_name": "A", "owner": "O1", "merchant_scale": "KEY", "priority_level": "PRIORITY", "merchant_mapping_status": "ID_MATCHED", "current_gmv": 80.0, "previous_gmv": 100.0, "gmv_change_abs": -20.0, "gmv_loss": 20.0, "gmv_mom": -0.2, "gmv_rank_current": 2, "gmv_rank_change": 1, "previous_gmv_share": 0.5, "diagnostic_dimensions": "Trend", "data_quality_status": "NO_ALERT", "metric_quality_status": "VALID", "aftersales_rate": 0.01},
            {"month": "2026-05", "merchant_key": "ID:B", "merchant_name": "B", "owner": "O2", "merchant_scale": "MID", "priority_level": "ATTENTION", "merchant_mapping_status": "ID_MATCHED", "current_gmv": 50.0, "previous_gmv": 40.0, "gmv_change_abs": 10.0, "gmv_loss": 0.0, "gmv_mom": 0.25, "gmv_rank_current": 1, "gmv_rank_change": -1, "previous_gmv_share": 0.2, "diagnostic_dimensions": "", "data_quality_status": "NO_ALERT", "metric_quality_status": "VALID", "aftersales_rate": 0.01},
            {"month": "2026-05", "merchant_key": "ID:C", "merchant_name": "C", "owner": "O2", "merchant_scale": "MID", "priority_level": "WATCHLIST", "merchant_mapping_status": "ID_MATCHED", "current_gmv": 30.0, "previous_gmv": None, "gmv_change_abs": None, "gmv_loss": None, "gmv_mom": None, "gmv_rank_current": 3, "gmv_rank_change": None, "previous_gmv_share": None, "diagnostic_dimensions": "", "data_quality_status": "NO_ALERT", "metric_quality_status": "INSUFFICIENT_HISTORY", "aftersales_rate": 0.01},
            {"month": "2026-06", "merchant_key": "ID:A", "merchant_name": "A", "owner": "O1", "merchant_scale": "KEY", "priority_level": "DATA_QUALITY_ALERT", "merchant_mapping_status": "ID_MATCHED", "current_gmv": None, "previous_gmv": 80.0, "gmv_change_abs": None, "gmv_loss": None, "gmv_mom": None, "gmv_rank_current": None, "gmv_rank_change": None, "previous_gmv_share": None, "diagnostic_dimensions": "", "data_quality_status": "DATA_QUALITY_ALERT", "metric_quality_status": "MISSING", "aftersales_rate": None},
        ]
    )


def test_latest_complete_period_requires_a_reliable_period_quality() -> None:
    assert latest_complete_period(_frame()) == "2026-04"
    assert period_quality_status("2026-05") == "HISTORICAL_SNAPSHOT / PARTIAL_PERIOD"
    assert not is_standard_comparison_period("2026-05")


def test_filters_and_business_rows_exclude_quality_only_rows() -> None:
    selected = filter_dashboard(_frame(), "2026-04", owners=["O1"], priority_levels=["PRIORITY"])
    assert selected["merchant_key"].tolist() == ["ID:A"]
    assert len(business_rows(filter_dashboard(_frame(), "2026-06"))) == 0


def test_trend_preserves_nulls_and_overview_uses_comparable_rows() -> None:
    trend = merchant_trend(_frame(), "ID:A", 12)
    assert trend["gmv"].isna().any()
    metrics = overview_metrics(filter_dashboard(_frame(), "2026-04"))
    assert metrics["region_gmv"] == 130.0
    assert metrics["region_gmv_previous"] == 140.0
    assert metrics["gmv_mom"] == pytest.approx(130 / 140 - 1)
    assert metrics["comparable_merchants"] == 2
    assert metrics["declining_merchants"] == 1
    assert metrics["growth_merchants"] == 1


def test_rank_direction_and_reason_summary_are_explicit() -> None:
    assert format_rank_change(23) == "↓23名"
    assert format_rank_change(-4) == "↑4名"
    assert format_rank_change(0) == "持平"
    summary = summarize_attention_reasons("Trend: GMV环比-30%；Scale / Impact: GMV损失100；Relative Position: 排名变化23；Service: 售后风险")
    assert summary == "GMV趋势：GMV环比-30%｜区域影响：GMV损失100｜相对位置：排名下降23名"


def test_dashboard_a_page_keeps_priority_hierarchy_and_starts() -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    assert not app.exception
    visible = " ".join(
        str(element.value)
        for collection in (app.markdown, app.caption, app.info, app.warning, app.success)
        for element in collection
    )
    assert "区域商家经营看板" in visible
    assert "默认展示最近可靠可比完整周期：2026-04 vs 2026-03" in visible
    assert "可比 GMV" in visible
    assert "高优先 14" in visible
    assert "高优先级商家" in visible
    assert "商家快速查看" in visible
    assert "数据质量说明" not in visible
    assert "LIKELY_COMPLETE" not in visible
    assert all(
        "指标质量" not in element.value.columns and "数据质量" not in element.value.columns
        for element in app.dataframe
    )


def test_dashboard_a_default_uses_april_and_treats_may_as_snapshot() -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    assert not app.exception
    assert app.sidebar.selectbox[0].value == "2026-04"
    visible = " ".join(
        str(element.value)
        for collection in (app.markdown, app.caption, app.info, app.warning, app.success)
        for element in collection
    )
    assert "¥948.20万" in visible
    assert "↓ 16.8%" in visible

    app.sidebar.selectbox[0].set_value("2026-05").run(timeout=30)
    snapshot_visible = " ".join(
        str(element.value)
        for collection in (app.markdown, app.caption, app.info, app.warning, app.success)
        for element in collection
    )
    assert "该月份来自历史阶段性快照，不代表完整自然月。" in snapshot_visible
    assert "不展示基于完整月假设的月环比或优先级结论" in snapshot_visible


def test_dashboard_a_reliable_default_metrics_match_persisted_mart() -> None:
    frame = load_priority_mart(MART)
    assert latest_complete_period(frame) == "2026-04"

    metrics = overview_metrics(filter_dashboard(frame, "2026-04"))
    assert metrics["region_gmv"] == pytest.approx(9_482_039.27)
    assert metrics["region_gmv_previous"] == pytest.approx(11_400_040.90)
    assert metrics["gmv_mom"] == pytest.approx(-0.1682451534)
    assert metrics["comparable_merchants"] == 78
    assert metrics["declining_merchants"] == 53
    assert metrics["growth_merchants"] == 25
    assert metrics["priority_merchants"] == 14
    assert metrics["attention_merchants"] == 4
    assert metrics["watchlist_merchants"] == 29
    assert top_loss(filter_dashboard(frame, "2026-04")).iloc[0]["merchant_name"] == "鲁鸿医疗"
    assert top_growth(filter_dashboard(frame, "2026-04")).iloc[0]["merchant_name"] == "成都瑞舒达健康管理"
