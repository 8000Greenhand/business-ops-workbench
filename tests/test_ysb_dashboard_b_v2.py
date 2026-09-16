from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.diagnostics.ysb_dashboard_b_input import (
    UploadedPayload,
    detect_table_role,
    recognize_uploaded_inputs,
)
from ops_workbench.diagnostics.ysb_merchant_b1 import SOURCE_COLUMNS
from ops_workbench.diagnostics.ysb_merchant_case import (
    CURRENT_ONLY_ACTIVITY,
    HAS_ACTIVITY,
    HAS_CUSTOMER,
    HAS_PRODUCT,
    HAS_TRAFFIC,
    PREVIOUS_ONLY_ACTIVITY,
    RETAINED_ACTIVITY,
    ZERO_AMOUNT_ONLY,
    build_case_data_from_frames,
    detect_case_capabilities,
    read_case_csv,
)
from ops_workbench.ui.ysb_dashboard_b import (
    DashboardBInputError,
    build_dashboard_b_from_uploads,
    load_public_demo_dashboard_b,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
POLICY = ROOT / "config" / "ysb_dashboard_b_order_metric_policy.yaml"
RULES = ROOT / "config" / "ysb_dashboard_b_diagnosis_rules.yaml"


def _csv_payload(path: Path) -> UploadedPayload:
    return UploadedPayload(path.name, path.read_bytes())


def _xlsx_payload(name: str, sheets: dict[str, pd.DataFrame]) -> UploadedPayload:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet, frame in sheets.items():
            frame.to_excel(writer, sheet_name=sheet, index=False)
    return UploadedPayload(name, buffer.getvalue())


def _small_orders(*, customers: bool = False) -> pd.DataFrame:
    rows = [
        ["2025-04-01", "O1", "P1", "商品一", 100.0, "拼团", "001"],
        ["2025-05-01", "O2", "P1", "商品一", 40.0, "拼团", "001"],
        ["2025-04-02", "O3", "P2", "商品二", 20.0, "拼团", "002"],
        ["2025-05-02", "O4", "P3", "商品三", 30.0, "拼团", "003"],
        ["2025-04-03", "Z1", "P4", "商品四", 0.0, "拼团", "004"],
    ]
    frame = pd.DataFrame(
        rows,
        columns=["下单时间", "订单ID", "商品编码", "产品名称", "进货金额", "活动类型", "活动ID"],
    )
    if customers:
        frame["药店编码"] = ["C1", "C1", "C2", "C3", "C4"]
        frame["药店全称"] = ["药店一", "药店一", "药店二", "药店三", "药店四"]
    return frame


def _small_activities() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "活动ID": ["001", "002", "003", "004"],
            "活动类型": ["拼团"] * 4,
            "主题名称": ["主题一", "主题二", "主题三", "主题四"],
            "商品编码": ["P1", "P2", "P3", "P4"],
            "app显示名称": ["商品一", "商品二", "商品三", "商品四"],
        }
    )


def test_raw_order_csv_and_xlsx_are_recognized_without_manual_role_selection() -> None:
    order = _small_orders()
    csv = UploadedPayload("orders.csv", order.to_csv(index=False).encode("utf-8-sig"))
    xlsx = _xlsx_payload("orders.xlsx", {"导出结果": order})
    for payload in (csv, xlsx):
        recognized = recognize_uploaded_inputs((payload,))
        assert recognized.order is not None
        assert recognized.legacy is None
        assert recognized.unknown_labels == ()
        data = build_dashboard_b_from_uploads((payload,), POLICY, RULES)
        assert data.capabilities == frozenset({HAS_PRODUCT})
        assert data.monthly["purchase_amount"].tolist() == pytest.approx([120.0, 70.0])


def test_optional_traffic_and_multiple_activity_files_are_recognized() -> None:
    order = _csv_payload(RAW / "众恩德订单明细4-5月.csv")
    traffic = UploadedPayload("众恩德流量4-5月.xlsx", (RAW / "众恩德流量4-5月.xlsx").read_bytes())
    active = _csv_payload(RAW / "众恩德在架活动.csv")
    ended = _csv_payload(RAW / "众恩德结束活动.csv")
    recognized = recognize_uploaded_inputs((order, traffic, active, ended))
    assert recognized.order is not None
    assert recognized.traffic is not None
    assert len(recognized.activities) == 2
    assert len(recognized.activity_labels) == 2


def test_real_raw_upload_reconciles_all_activity_ids_and_capabilities() -> None:
    data = build_dashboard_b_from_uploads(
        (
            _csv_payload(RAW / "众恩德订单明细4-5月.csv"),
            UploadedPayload("众恩德流量4-5月.xlsx", (RAW / "众恩德流量4-5月.xlsx").read_bytes()),
            _csv_payload(RAW / "众恩德在架活动.csv"),
            _csv_payload(RAW / "众恩德结束活动.csv"),
        ),
        POLICY,
        RULES,
    )
    assert data.capabilities == frozenset({HAS_PRODUCT, HAS_TRAFFIC, HAS_ACTIVITY})
    assert data.activity_mapping_rate == pytest.approx(1.0)
    assert data.activity_details["activity_id"].dtype.name == "string"
    assert data.activity_details["activity_id"].nunique() == 154
    assert data.activity_details.groupby("activity_type")["activity_id"].nunique().to_dict() == {
        "拼团": 142,
        "批购包邮": 12,
    }
    assert data.activity_details["amount_change"].sum() == pytest.approx(
        data.activities["amount_change"].sum()
    )
    assert data.activities["amount_change"].sum() == pytest.approx(
        data.monthly.iloc[1]["purchase_amount_change"]
    )


def test_activity_states_zero_order_policy_and_loss_concentration_inputs() -> None:
    result = build_case_data_from_frames(
        _small_orders(),
        activity_frames=(_small_activities(),),
        previous_period="2025-04",
        current_period="2025-05",
    )
    details = result["activity_details"].set_index("activity_id")
    assert details.loc["001", "period_status"] == RETAINED_ACTIVITY
    assert details.loc["002", "period_status"] == PREVIOUS_ONLY_ACTIVITY
    assert details.loc["003", "period_status"] == CURRENT_ONLY_ACTIVITY
    assert details.loc["004", "period_status"] == ZERO_AMOUNT_ONLY
    assert details.loc["004", "previous_orders"] == 0
    assert details.loc["004", "current_orders"] == 0
    assert details["amount_change"].sum() == pytest.approx(-50.0)
    assert details.loc["001", "negative_contribution"] == pytest.approx(0.75)
    assert details.loc["002", "negative_contribution"] == pytest.approx(0.25)


def test_duplicate_activity_mapping_dedupes_or_flags_conflict() -> None:
    activities = _small_activities()
    same = activities.iloc[[0]].copy()
    result = build_case_data_from_frames(
        _small_orders(),
        activity_frames=(activities, same),
        previous_period="2025-04",
        current_period="2025-05",
    )
    assert result["activity_details"]["activity_id"].nunique() == 4

    conflict = same.copy()
    conflict["主题名称"] = "冲突主题"
    with pytest.raises(ValueError, match="活动映射冲突.*001"):
        build_case_data_from_frames(
            _small_orders(),
            activity_frames=(activities, conflict),
            previous_period="2025-04",
            current_period="2025-05",
        )


def test_capabilities_require_populated_values_and_degrade_naturally() -> None:
    order = _small_orders(customers=True)
    assert HAS_CUSTOMER in detect_case_capabilities(order)
    order["药店编码"] = ""
    assert HAS_CUSTOMER not in detect_case_capabilities(order)
    assert HAS_ACTIVITY not in detect_case_capabilities(order)
    assert detect_case_capabilities(order) == frozenset({HAS_PRODUCT})

    result = build_case_data_from_frames(order, previous_period="2025-04", current_period="2025-05")
    assert result["traffic"].empty
    assert result["activities"].empty
    assert result["customers"].empty


def test_missing_order_and_unknown_file_fail_cleanly() -> None:
    unknown = UploadedPayload("unknown.csv", b"foo,bar\n1,2\n")
    recognized = recognize_uploaded_inputs((unknown,))
    assert recognized.unknown_labels == ("unknown.csv",)
    with pytest.raises(DashboardBInputError, match="未识别到订单明细.*至少需要订单数据"):
        build_dashboard_b_from_uploads((unknown,), POLICY, RULES)

    order = UploadedPayload("orders.csv", _small_orders().to_csv(index=False).encode("utf-8-sig"))
    data = build_dashboard_b_from_uploads((order, unknown), POLICY, RULES)
    assert data.input_summary.unknown_labels == ("unknown.csv",)


def test_legacy_workbook_is_auto_detected_and_old_pipeline_still_runs() -> None:
    payload = UploadedPayload("药师帮日报.xlsx", (ROOT / "药师帮日报.xlsx").read_bytes())
    recognized = recognize_uploaded_inputs((payload,))
    assert recognized.legacy is not None
    data = build_dashboard_b_from_uploads((payload,), POLICY, RULES)
    assert data.input_summary.legacy
    assert data.capabilities == frozenset({HAS_CUSTOMER, HAS_PRODUCT})
    assert not data.monthly.empty


def test_legacy_requires_all_18_fields_before_priority_routing() -> None:
    incomplete = pd.DataFrame({column: ["x"] for column in list(SOURCE_COLUMNS)[:-1]})
    payload = _xlsx_payload("incomplete.xlsx", {"订单原始数据": incomplete})
    assert recognize_uploaded_inputs((payload,)).legacy is None


def test_public_demo_detail_is_aggregate_only_and_preserves_baseline_metrics() -> None:
    source = pd.read_csv(ROOT / "demo_data" / "ysb_dashboard_b" / "activity_detail.csv")
    assert list(source.columns) == [
        "month",
        "activity_type",
        "activity_id",
        "theme_name",
        "display_name",
        "product_code",
        "purchase_amount",
        "order_count",
    ]
    assert "订单ID" not in source.columns
    assert "药店编码" not in source.columns
    data = load_public_demo_dashboard_b(ROOT / "demo_data" / "ysb_dashboard_b")
    assert data.monthly.iloc[0]["purchase_amount"] == pytest.approx(476_865.08)
    assert data.monthly.iloc[1]["purchase_amount"] == pytest.approx(124_226.34)
    assert data.traffic.set_index("metric").loc["访客", "own_change_rate"] == pytest.approx(-0.4995010)
    assert data.products["amount_change"].sum() == pytest.approx(-352_638.74)
    assert data.activity_details["activity_id"].nunique() == 154


def test_column_signatures_do_not_accept_empty_required_fields() -> None:
    empty = _small_orders()
    empty["订单ID"] = ""
    empty["活动ID"] = ""
    assert detect_table_role(empty) is None
