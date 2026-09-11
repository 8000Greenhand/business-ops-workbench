import pandas as pd
import pytest

from ops_workbench.ui.ysb_dashboard import (
    business_rows,
    filter_dashboard,
    format_rank_change,
    latest_complete_period,
    merchant_trend,
    overview_metrics,
    summarize_attention_reasons,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"month": "2026-05", "merchant_key": "ID:A", "merchant_name": "A", "owner": "O1", "merchant_scale": "KEY", "priority_level": "PRIORITY", "merchant_mapping_status": "ID_MATCHED", "current_gmv": 80.0, "previous_gmv": 100.0, "gmv_change_abs": -20.0, "gmv_loss": 20.0, "gmv_mom": -0.2, "gmv_rank_current": 2, "gmv_rank_change": 1, "previous_gmv_share": 0.5, "diagnostic_dimensions": "Trend", "data_quality_status": "NO_ALERT", "metric_quality_status": "VALID", "aftersales_rate": 0.01},
            {"month": "2026-05", "merchant_key": "ID:B", "merchant_name": "B", "owner": "O2", "merchant_scale": "MID", "priority_level": "ATTENTION", "merchant_mapping_status": "ID_MATCHED", "current_gmv": 50.0, "previous_gmv": 40.0, "gmv_change_abs": 10.0, "gmv_loss": 0.0, "gmv_mom": 0.25, "gmv_rank_current": 1, "gmv_rank_change": -1, "previous_gmv_share": 0.2, "diagnostic_dimensions": "", "data_quality_status": "NO_ALERT", "metric_quality_status": "VALID", "aftersales_rate": 0.01},
            {"month": "2026-05", "merchant_key": "ID:C", "merchant_name": "C", "owner": "O2", "merchant_scale": "MID", "priority_level": "WATCHLIST", "merchant_mapping_status": "ID_MATCHED", "current_gmv": 30.0, "previous_gmv": None, "gmv_change_abs": None, "gmv_loss": None, "gmv_mom": None, "gmv_rank_current": 3, "gmv_rank_change": None, "previous_gmv_share": None, "diagnostic_dimensions": "", "data_quality_status": "NO_ALERT", "metric_quality_status": "INSUFFICIENT_HISTORY", "aftersales_rate": 0.01},
            {"month": "2026-06", "merchant_key": "ID:A", "merchant_name": "A", "owner": "O1", "merchant_scale": "KEY", "priority_level": "DATA_QUALITY_ALERT", "merchant_mapping_status": "ID_MATCHED", "current_gmv": None, "previous_gmv": 80.0, "gmv_change_abs": None, "gmv_loss": None, "gmv_mom": None, "gmv_rank_current": None, "gmv_rank_change": None, "previous_gmv_share": None, "diagnostic_dimensions": "", "data_quality_status": "DATA_QUALITY_ALERT", "metric_quality_status": "MISSING", "aftersales_rate": None},
        ]
    )


def test_latest_complete_period_ignores_latest_missing_gmv() -> None:
    assert latest_complete_period(_frame()) == "2026-05"


def test_filters_and_business_rows_exclude_quality_only_rows() -> None:
    selected = filter_dashboard(_frame(), "2026-05", owners=["O1"], priority_levels=["PRIORITY"])
    assert selected["merchant_key"].tolist() == ["ID:A"]
    assert len(business_rows(filter_dashboard(_frame(), "2026-06"))) == 0


def test_trend_preserves_nulls_and_overview_uses_comparable_rows() -> None:
    trend = merchant_trend(_frame(), "ID:A", 12)
    assert trend["gmv"].isna().any()
    metrics = overview_metrics(filter_dashboard(_frame(), "2026-05"))
    assert metrics["region_gmv"] == 130.0
    assert metrics["region_gmv_previous"] == 140.0
    assert metrics["gmv_mom"] == pytest.approx(130 / 140 - 1)
    assert metrics["comparable_merchants"] == 2
    assert metrics["declining_merchants"] == 1


def test_rank_direction_and_reason_summary_are_explicit() -> None:
    assert format_rank_change(23) == "↓23名"
    assert format_rank_change(-4) == "↑4名"
    assert format_rank_change(0) == "持平"
    summary = summarize_attention_reasons("Trend: GMV环比-30%；Scale / Impact: GMV损失100；Relative Position: 排名变化23；Service: 售后风险")
    assert summary == "GMV趋势：GMV环比-30%｜区域影响：GMV损失100｜相对位置：排名下降23名"
