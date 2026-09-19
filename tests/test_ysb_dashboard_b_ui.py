import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from ops_workbench.ui.ysb_dashboard_b import (
    DashboardBData,
    DashboardBInputError,
    activity_detail_summary,
    build_dashboard_b_from_upload,
    contribution_summary,
    core_facts,
    has_capability,
    load_public_demo_dashboard_b,
    quality_count,
    result_decomposition,
)
from ops_workbench.diagnostics.ysb_merchant_case import (
    HAS_ACTIVITY,
    HAS_CUSTOMER,
    HAS_PRODUCT,
    HAS_TRAFFIC,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo_data" / "ysb_dashboard_b"
PAGE = ROOT / "src" / "ops_workbench" / "ui" / "pages" / "7_ysb_dashboard_b.py"
POLICY = ROOT / "config" / "ysb_dashboard_b_order_metric_policy.yaml"
RULES = ROOT / "config" / "ysb_dashboard_b_diagnosis_rules.yaml"


def test_sample_marts_feed_b2_facts_and_reconcile() -> None:
    data = load_public_demo_dashboard_b(DEMO_DIR)
    facts = core_facts(data)
    result = result_decomposition(data)
    _, product_error = contribution_summary(data, "PRODUCT")
    assert len(facts) == 5
    assert result["driver_classification"] == "MIXED"
    assert result["purchase_amount_change"] == pytest.approx(-352_638.74)
    assert abs(product_error) <= 0.01
    assert quality_count(data, "ZERO_AMOUNT_ORDER") == 58
    assert quality_count(data, "PRODUCT_KEY_MAPPING_CONFLICT") == 23


def test_null_quality_count_stays_unavailable() -> None:
    data = DashboardBData(
        monthly=pd.DataFrame(),
        customers=pd.DataFrame(),
        products=pd.DataFrame(),
        facts=pd.DataFrame(),
        quality=pd.DataFrame([{"rule": "ZERO_AMOUNT_ORDER", "affected_entities": pd.NA}]),
        previous_period="2025-04",
        current_period="2025-05",
        source_label="test",
    )
    assert quality_count(data, "ZERO_AMOUNT_ORDER") is None
    assert quality_count(data, "MISSING") is None


def test_page_capability_helper_is_part_of_the_ui_module_contract() -> None:
    from ops_workbench.ui.ysb_dashboard_b import has_capability

    data = DashboardBData(
        monthly=pd.DataFrame(),
        customers=pd.DataFrame(),
        products=pd.DataFrame(),
        facts=pd.DataFrame(),
        quality=pd.DataFrame(),
        previous_period="2025-04",
        current_period="2025-05",
        source_label="test",
        capabilities=frozenset({"HAS_PRODUCT"}),
    )
    assert has_capability(data, "HAS_PRODUCT")
    assert not has_capability(data, "HAS_CUSTOMER")


def test_invalid_upload_fails_without_guessing_structure() -> None:
    with pytest.raises(DashboardBInputError):
        build_dashboard_b_from_upload(b"not an xlsx workbook", POLICY, RULES, "bad.xlsx")


def test_streamlit_page_displays_facts_evidence_and_safe_status_language() -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    assert not app.exception
    visible = " ".join(
        str(element.value)
        for collection in (app.title, app.subheader, app.markdown, app.caption, app.info, app.warning, app.success)
        for element in collection
    )
    assert "进货金额" in visible
    assert "订单量与客单价共同下滑" in visible
    assert "高可信" in visible
    assert "中等可信" in visible
    assert "证据有限" in visible
    assert "流量表现：本店 vs 同行" in visible
    assert "活动分析" in visible
    assert "活动类型概览" in visible
    assert "具体活动" in visible
    activity_headers = " ".join(
        " ".join(frame.value.columns.astype(str)) for frame in app.dataframe
    )
    assert "活动主题 商品/活动内容 变化额 基准期金额 对比期金额 周期状态 负向贡献占比 活动ID" in activity_headers
    assert "活动主题 商品/活动内容 变化额 基准期金额 对比期金额 周期状态 活动ID" in activity_headers
    assert len(app.date_input) == 2
    assert app.date_input[0].value == (date(2026, 4, 1), date(2026, 4, 30))
    assert app.date_input[1].value == (date(2026, 5, 1), date(2026, 5, 30))
    assert not any("两个周期长度不同" in str(item.value) for item in app.warning)
    assert "当前数据来自中台账号，订单导出不包含药店标识" in visible
    limitations = app.expander[1]
    limitation_text = " ".join(str(element.value) for element in limitations.markdown)
    limitation_rows = limitations.dataframe[0].value.to_string(index=False)
    assert "订单状态、退款、配送和结算口径尚未完全确认。" in limitation_rows
    assert "23 个商品存在展示映射冲突" in limitation_rows
    assert "当前系统识别相关经营事实，不自动推断因果。" in limitation_text
    assert "PRODUCT_MAPPING_LIMITATION" not in visible
    assert "ORDER_STATUS_SEMANTICS_UNCONFIRMED" not in visible
    assert "Quality: nan" not in visible
    assert "新增客户" not in visible
    assert "流失客户" not in visible


def test_dashboard_b_ratio_tables_use_one_decimal_percentages() -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    assert not app.exception
    ratio_columns = {
        "本店变化", "同行变化", "相对同行差距", "变化率",
        "对比期金额占比", "负向变化贡献度", "负向贡献占比",
    }
    for table in app.dataframe:
        for column in ratio_columns.intersection(table.value.columns):
            assert all(
                value == "不可用" or re.fullmatch(r"[+-]?\d+\.\d%", value)
                for value in table.value[column]
            )


def test_dashboard_b_no_upload_default_demo_smoke() -> None:
    data = load_public_demo_dashboard_b(DEMO_DIR)
    assert isinstance(data, DashboardBData)
    assert not data.monthly.empty
    assert data.source_label == "四川众恩德科技聚合演示案例"
    assert has_capability(data, HAS_TRAFFIC)
    assert has_capability(data, HAS_ACTIVITY)
    assert has_capability(data, HAS_PRODUCT)
    assert not has_capability(data, HAS_CUSTOMER)
    assert data.customer_unavailable_reason == (
        "当前数据来自中台账号，订单导出不包含药店标识；药店贡献诊断需要商家账号权限。"
    )
    assert data.monthly.iloc[0]["purchase_amount"] == pytest.approx(476_865.08)
    assert data.monthly.iloc[1]["purchase_amount"] == pytest.approx(124_226.34)
    assert data.activity_details["activity_id"].nunique() == 154
    assert activity_detail_summary(data, "拼团")["activity_count"] == 142

    app = AppTest.from_file(PAGE).run(timeout=30)
    assert not app.exception
    visible = " ".join(
        str(element.value)
        for collection in (app.markdown, app.info, app.caption)
        for element in collection
    )
    assert "四川众恩德科技聚合演示案例" in visible
    assert "经营概览" in visible
    assert "活动类型概览" in visible
    assert "具体活动" in visible


def test_streamlit_page_renders_one_sidebar_upload_section() -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    assert not app.exception
    sidebar_text = " ".join(
        str(element.value)
        for collection in (app.sidebar.subheader, app.sidebar.markdown, app.sidebar.caption)
        for element in collection
    )
    assert sidebar_text.count("上传商家原始数据") == 1
    assert "直接上传后台导出的商家经营数据，无需人工整理日报" in sidebar_text
    assert "订单明细为必需；流量、活动为可选；订单中存在有效药店字段时自动启用药店诊断" in sidebar_text
    assert "单商家日报" not in sidebar_text
    assert "上传药师帮日报" not in sidebar_text
    assert sidebar_text.count("文件仅在当前会话处理，不写入项目原始数据目录。") == 1
    assert len(app.sidebar.file_uploader) == 1
