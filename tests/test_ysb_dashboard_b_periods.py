from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from ops_workbench.diagnostics.ysb_merchant_case import build_case_data_from_frames
from ops_workbench.ui.ysb_dashboard_b import (
    build_dashboard_b_from_upload,
    current_metrics,
    load_public_demo_dashboard_b,
    select_dashboard_b_periods,
)


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_data" / "ysb_dashboard_b"
PAGE = ROOT / "src" / "ops_workbench" / "ui" / "pages" / "7_ysb_dashboard_b.py"


def test_default_reliable_equal_length_periods_reconcile_result_facts() -> None:
    data = load_public_demo_dashboard_b(DEMO)
    metrics = current_metrics(data)
    assert (data.baseline_start, data.baseline_end) == (date(2026, 4, 1), date(2026, 4, 30))
    assert (data.comparison_start, data.comparison_end) == (date(2026, 5, 1), date(2026, 5, 30))
    assert metrics["purchase_amount"] == pytest.approx(124_226.34)
    assert metrics["purchase_amount_change"] == pytest.approx(-352_638.74)
    assert metrics["order_count"] == 1_059
    assert metrics["order_count_change_rate"] == pytest.approx(-0.4518633540)
    assert metrics["aov_change_rate"] == pytest.approx(-0.5247421149)
    assert float(data.products["amount_change"].sum()) == pytest.approx(metrics["purchase_amount_change"])
    traffic = data.traffic.set_index("metric")
    assert (traffic.loc["曝光", "previous_own"], traffic.loc["曝光", "current_own"]) == (144_664, 81_169)
    assert (traffic.loc["点击", "previous_own"], traffic.loc["点击", "current_own"]) == (8_640, 4_383)
    assert (traffic.loc["访客", "previous_own"], traffic.loc["访客", "current_own"]) == (4_008, 1_947)


def test_arbitrary_equal_length_periods_filter_all_daily_modules() -> None:
    data = load_public_demo_dashboard_b(DEMO)
    selected = select_dashboard_b_periods(
        data,
        baseline_start=date(2026, 4, 1),
        baseline_end=date(2026, 4, 15),
        comparison_start=date(2026, 5, 1),
        comparison_end=date(2026, 5, 15),
    )
    result_daily = pd.read_csv(DEMO / "result_daily.csv", parse_dates=["date"])
    expected = result_daily[result_daily["date"].between("2026-05-01", "2026-05-15")]
    metrics = current_metrics(selected)
    assert metrics["purchase_amount"] == pytest.approx(expected["purchase_amount"].sum())
    assert metrics["order_count"] == expected["order_count"].sum()

    traffic_daily = pd.read_csv(DEMO / "traffic_daily.csv", parse_dates=["date"])
    traffic_expected = traffic_daily[traffic_daily["date"].between("2026-05-01", "2026-05-15")]
    exposure = selected.traffic.set_index("metric").loc["曝光"]
    assert exposure["current_own"] == traffic_expected["own_exposure"].sum()
    assert exposure["current_peer"] == traffic_expected["peer_exposure"].sum()

    activity_daily = pd.read_csv(DEMO / "activity_daily.csv", parse_dates=["date"])
    activity_expected = activity_daily[activity_daily["date"].between("2026-05-01", "2026-05-15")]
    assert selected.activities["current_amount"].sum() == pytest.approx(activity_expected["purchase_amount"].sum())

    product_daily = pd.read_csv(DEMO / "product_daily.csv", parse_dates=["date"])
    product_expected = product_daily[product_daily["date"].between("2026-05-01", "2026-05-15")]
    assert selected.products["current_amount"].sum() == pytest.approx(product_expected["purchase_amount"].sum())
    assert selected.products["amount_change"].sum() == pytest.approx(metrics["purchase_amount_change"])


def test_unequal_periods_show_non_blocking_warning() -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    app.date_input[0].set_value((date(2026, 4, 1), date(2026, 4, 15)))
    app.date_input[1].set_value((date(2026, 5, 1), date(2026, 5, 20)))
    app.run(timeout=30)
    assert not app.exception
    assert any("两个周期长度不同" in str(item.value) for item in app.warning)


def test_activity_without_both_periods_degrades_without_old_results() -> None:
    data = load_public_demo_dashboard_b(DEMO)
    source = dict(data.period_source or {})
    activity = source["activity"].copy()
    source["activity"] = activity[pd.to_datetime(activity["date"]).dt.month.eq(4)]
    selected = select_dashboard_b_periods(
        replace(data, period_source=source),
        baseline_start=date(2026, 4, 1),
        baseline_end=date(2026, 4, 15),
        comparison_start=date(2026, 5, 1),
        comparison_end=date(2026, 5, 15),
    )
    assert selected.activities.empty
    assert selected.activity_details.empty


def test_uploaded_customer_contribution_uses_selected_dates() -> None:
    order = pd.DataFrame(
        {
            "下单时间": ["2026-04-01", "2026-04-20", "2026-05-01", "2026-05-20"],
            "订单ID": ["A", "B", "C", "D"],
            "商品编码": ["P1", "P2", "P1", "P3"],
            "产品名称": ["商品1", "商品2", "商品1", "商品3"],
            "进货金额": [100.0, 900.0, 40.0, 500.0],
            "药店编码": ["C1", "C2", "C1", "C3"],
            "药店全称": ["药店1", "药店2", "药店1", "药店3"],
        }
    )
    result = build_case_data_from_frames(
        order,
        baseline_start=date(2026, 4, 1),
        baseline_end=date(2026, 4, 10),
        comparison_start=date(2026, 5, 1),
        comparison_end=date(2026, 5, 10),
    )
    assert result["monthly"]["purchase_amount"].tolist() == pytest.approx([100.0, 40.0])
    assert result["customers"]["amount_change"].sum() == pytest.approx(-60.0)
    assert set(result["customers"]["period_status"]) == {"RETAINED"}


def test_daily_demo_contains_no_order_or_customer_identifiers() -> None:
    forbidden = {"订单ID", "订单编号", "order_id", "药店编码", "药店名称", "药店全称", "customer_key", "customer_name"}
    for name in ("result_daily.csv", "traffic_daily.csv", "activity_daily.csv", "product_daily.csv"):
        columns = set(pd.read_csv(DEMO / name, nrows=0).columns)
        assert not columns.intersection(forbidden), name

    result = pd.read_csv(DEMO / "result_daily.csv")
    traffic = pd.read_csv(DEMO / "traffic_daily.csv")
    activity = pd.read_csv(DEMO / "activity_daily.csv", dtype={"activity_id": "string"})
    product = pd.read_csv(DEMO / "product_daily.csv", dtype={"product_key": "string"})
    assert not result["date"].duplicated().any()
    assert not traffic["date"].duplicated().any()
    assert not activity.duplicated(["date", "activity_id"]).any()
    assert not product.duplicated(["date", "product_key"]).any()


def test_legacy_workbook_can_be_recomputed_for_arbitrary_periods() -> None:
    data = build_dashboard_b_from_upload(
        (ROOT / "药师帮日报.xlsx").read_bytes(),
        ROOT / "config" / "ysb_dashboard_b_order_metric_policy.yaml",
        ROOT / "config" / "ysb_dashboard_b_diagnosis_rules.yaml",
        "药师帮日报.xlsx",
    )
    selected = select_dashboard_b_periods(
        data,
        baseline_start=date(2025, 4, 1),
        baseline_end=date(2025, 4, 15),
        comparison_start=date(2025, 5, 1),
        comparison_end=date(2025, 5, 15),
    )
    assert selected.baseline_start == date(2025, 4, 1)
    assert selected.comparison_end == date(2025, 5, 15)
    assert selected.customers["amount_change"].sum() == pytest.approx(
        current_metrics(selected)["purchase_amount_change"]
    )
    assert selected.products["amount_change"].sum() == pytest.approx(
        current_metrics(selected)["purchase_amount_change"]
    )
