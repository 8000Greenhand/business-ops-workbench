"""Build aggregate-only daily facts for the public Zhongende Dashboard B demo."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ops_workbench.diagnostics.ysb_merchant_case import read_case_csv


FORBIDDEN_COLUMNS = {
    "订单ID", "订单编号", "order_id", "customer_key", "customer_name", "药店编码", "药店名称", "药店全称"
}


def build_daily_demo(raw_dir: Path, output_dir: Path) -> tuple[Path, ...]:
    """Aggregate local raw exports to the four privacy-bounded daily demo files."""
    order = read_case_csv(raw_dir / "众恩德订单明细4-5月.csv")
    order["date"] = pd.to_datetime(order["下单时间"], errors="raise").dt.normalize()
    order["purchase_amount"] = pd.to_numeric(order["进货金额"], errors="raise")
    order["order_id"] = order["订单ID"].astype("string").str.strip()
    order_amount = order.groupby("order_id", observed=True)["purchase_amount"].transform("sum")
    order["positive_order_id"] = order["order_id"].where(order_amount.gt(0))

    result_daily = order.groupby("date", observed=True).agg(
        purchase_amount=("purchase_amount", "sum"),
        order_count=("positive_order_id", "nunique"),
    ).reset_index()
    result_daily["purchase_amount"] = result_daily["purchase_amount"].round(2)

    order["product_key"] = order["商品编码"].astype("string").str.strip()
    order["product_name"] = order["产品名称"].astype("string").str.strip()
    signatures = (
        order["厂家"].fillna("").astype(str).str.strip()
        + "|"
        + order["规格"].fillna("").astype(str).str.strip()
    )
    order["product_signature"] = signatures
    conflicts = order.groupby("product_key", observed=True)["product_signature"].nunique().gt(1)
    product_daily = order.groupby(["date", "product_key"], observed=True).agg(
        product_name=("product_name", _preferred),
        purchase_amount=("purchase_amount", "sum"),
        order_count=("positive_order_id", "nunique"),
    ).reset_index()
    product_daily["mapping_quality_status"] = product_daily["product_key"].map(
        lambda value: "CONFLICT" if bool(conflicts.get(value, False)) else "VALID"
    )
    product_daily["purchase_amount"] = product_daily["purchase_amount"].round(2)

    snapshots = pd.concat(
        [
            read_case_csv(raw_dir / "众恩德在架活动.csv"),
            read_case_csv(raw_dir / "众恩德结束活动.csv"),
        ],
        ignore_index=True,
    )
    snapshots["activity_id"] = snapshots["活动ID"].astype("string").str.strip()
    activity_meta = snapshots.groupby("activity_id", observed=True).agg(
        theme_name=("主题名称", _preferred),
        display_name=("app显示名称", _preferred),
        snapshot_product_code=("商品编码", _preferred),
    ).reset_index()
    order["activity_id"] = order["活动ID"].astype("string").str.strip()
    order["activity_type"] = order["活动类型"].astype("string").str.strip()
    activity_daily = order.dropna(subset=["activity_id", "activity_type"]).groupby(
        ["date", "activity_type", "activity_id"], observed=True
    ).agg(
        product_code=("product_key", _preferred),
        purchase_amount=("purchase_amount", "sum"),
        order_count=("positive_order_id", "nunique"),
    ).reset_index().merge(activity_meta, on="activity_id", how="left")
    mismatch = activity_daily["snapshot_product_code"].notna() & activity_daily["product_code"].ne(
        activity_daily["snapshot_product_code"]
    )
    if mismatch.any():
        raise ValueError("activity snapshot product mapping conflicts with order facts")
    activity_daily = activity_daily.drop(columns="snapshot_product_code")
    activity_daily["purchase_amount"] = activity_daily["purchase_amount"].round(2)

    traffic = pd.read_excel(raw_dir / "众恩德流量4-5月.xlsx")
    traffic.columns = [str(column).strip() for column in traffic.columns]
    compact = traffic["时间"].astype("string").str.replace(r"\.0$", "", regex=True)
    traffic_daily = pd.DataFrame(
        {
            "date": pd.to_datetime(compact, format="%Y%m%d", errors="raise"),
            "own_exposure": traffic["活动曝光数-我的店铺"],
            "own_clicks": traffic["详情点击数-我的店铺"],
            "own_visitors": traffic["店铺访客数-我的店铺"],
            "peer_exposure": traffic["活动曝光数-同行均值"],
            "peer_clicks": traffic["详情点击数-同行均值"],
            "peer_visitors": traffic["店铺访客数-同行均值"],
        }
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = (
        (output_dir / "result_daily.csv", result_daily),
        (output_dir / "traffic_daily.csv", traffic_daily),
        (output_dir / "activity_daily.csv", activity_daily),
        (output_dir / "product_daily.csv", product_daily),
    )
    for path, frame in outputs:
        forbidden = FORBIDDEN_COLUMNS.intersection(frame.columns)
        if forbidden:
            raise ValueError(f"privacy audit failed for {path.name}: {sorted(forbidden)}")
        persisted = frame.copy()
        persisted["date"] = pd.to_datetime(persisted["date"]).dt.date.astype(str)
        persisted.to_csv(path, index=False, encoding="utf-8")
    return tuple(path for path, _ in outputs)


def _preferred(values: pd.Series) -> object:
    populated = values.dropna().astype(str).map(str.strip)
    populated = populated[populated.ne("")]
    return populated.value_counts().sort_index().idxmax() if not populated.empty else pd.NA


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("demo_data/ysb_dashboard_b"))
    args = parser.parse_args()
    build_daily_demo(args.raw_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
