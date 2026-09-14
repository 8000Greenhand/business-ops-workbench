from pathlib import Path

import pandas as pd

from ops_workbench.diagnostics.ysb_merchant_b1 import (
    apply_order_policy,
    build_customer_contribution,
    build_monthly_diagnosis,
    build_product_contribution,
    build_quality_summary,
    latest_complete_pair,
    load_order_metric_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = load_order_metric_policy(ROOT / "config" / "ysb_dashboard_b_order_metric_policy.yaml")


def _items() -> pd.DataFrame:
    rows = []
    for month, days, amount in (("2025-04", 30, 10.0), ("2025-05", 31, 8.0)):
        for day in range(1, days + 1):
            rows.append(
                {
                    "order_date": pd.Timestamp(f"{month}-{day:02d}"),
                    "order_id": f"{month}-{day}",
                    "order_number": f"N-{month}-{day}",
                    "customer_key": "C1",
                    "customer_name": "Customer 1",
                    "product_key": "P1",
                    "product_code": "SKU1",
                    "product_name": "Product 1",
                    "manufacturer_raw": "Maker",
                    "specification_raw": "Spec",
                    "quantity": 1.0,
                    "unit_purchase_price": amount,
                    "purchase_amount": amount,
                    "order_status_raw": "交易完成",
                    "processing_status_raw": "配送完成",
                    "processing_remark_raw": pd.NA,
                    "settlement_status_raw": "已结算",
                    "order_type_raw": "商家直供",
                    "source_row": len(rows) + 2,
                    "source_sheet": "订单原始数据",
                }
            )
    return pd.DataFrame(rows)


def test_default_policy_counts_positive_orders_and_preserves_zero() -> None:
    frame = _items().iloc[:2].copy()
    frame.loc[1, ["quantity", "purchase_amount"]] = 0.0
    staged = apply_order_policy(frame, POLICY)
    assert staged["policy_purchase_amount"].sum() == 10.0
    assert staged["included_in_order_count"].tolist() == [True, False]
    assert staged["dq_zero_amount_order"].tolist() == [False, True]


def test_monthly_model_uses_latest_adjacent_complete_periods() -> None:
    staged = apply_order_policy(_items(), POLICY)
    monthly = build_monthly_diagnosis(staged)
    previous, current = latest_complete_pair(monthly)
    may = monthly[monthly["month"].eq("2025-05")].iloc[0]
    assert (str(previous), str(current)) == ("2025-04", "2025-05")
    assert may["purchase_amount"] == 248.0
    assert may["order_count"] == 31
    assert may["aov"] == 8.0
    assert may["comparison_quality_status"] == "VERIFIED"


def test_contribution_uses_objective_period_statuses() -> None:
    frame = _items().iloc[[0, 30]].copy()
    extra = frame.iloc[[0, 1]].copy()
    extra["customer_key"] = ["C2", "C3"]
    extra["customer_name"] = ["Customer 2", "Customer 3"]
    extra["product_key"] = ["P2", "P3"]
    extra["product_code"] = ["SKU2", "SKU3"]
    staged = apply_order_policy(pd.concat([frame, extra], ignore_index=True), POLICY)
    customers = build_customer_contribution(staged, pd.Period("2025-04", freq="M"), pd.Period("2025-05", freq="M"))
    products = build_product_contribution(staged, pd.Period("2025-04", freq="M"), pd.Period("2025-05", freq="M"))
    assert dict(zip(customers["customer_key"], customers["period_status"])) == {
        "C1": "RETAINED", "C2": "PREVIOUS_ONLY", "C3": "CURRENT_ONLY"
    }
    assert dict(zip(products["product_key"], products["period_status"])) == {
        "P1": "RETAINED_ACTIVE", "P2": "PREVIOUS_ONLY_ACTIVE", "P3": "CURRENT_ONLY_ACTIVE"
    }


def test_quality_flags_do_not_silently_repair_conflicts() -> None:
    frame = _items().iloc[:2].copy()
    frame.loc[1, "order_date"] = frame.loc[0, "order_date"] + pd.Timedelta(days=1)
    frame.loc[1, "order_id"] = frame.loc[0, "order_id"]
    frame.loc[1, "customer_name"] = "Different name"
    frame.loc[1, "product_code"] = "Different SKU"
    frame.loc[1, "purchase_amount"] = 99.0
    staged = apply_order_policy(frame, POLICY)
    quality = build_quality_summary(staged).set_index("rule")
    assert staged["dq_order_cross_date"].all()
    assert staged["dq_customer_name_conflict"].all()
    assert staged["dq_product_mapping_conflict"].all()
    assert staged.loc[1, "dq_purchase_amount_mismatch"]
    assert quality.loc["ORDER_CROSS_DATE", "affected_entities"] == 1
    assert quality.loc["PURCHASE_AMOUNT_MISMATCH", "affected_rows"] == 1

