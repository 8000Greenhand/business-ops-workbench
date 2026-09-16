from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from ops_workbench.ui.ysb_dashboard_b import (
    DashboardBData,
    DashboardBInputError,
    build_dashboard_b_from_upload,
    contribution_summary,
    core_facts,
    load_public_demo_dashboard_b,
    quality_count,
    result_decomposition,
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
    with pytest.raises(DashboardBInputError, match="订单原始数据.*必需列"):
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
    assert "活动端口" in visible
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


def test_streamlit_page_renders_one_sidebar_upload_section() -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    assert not app.exception
    sidebar_text = " ".join(
        str(element.value)
        for collection in (app.sidebar.markdown, app.sidebar.caption)
        for element in collection
    )
    assert sidebar_text.count("单商家日报") == 1
    assert sidebar_text.count("原始文件仅在临时目录处理，不写入项目数据目录。") == 1
    assert len(app.sidebar.file_uploader) == 1
