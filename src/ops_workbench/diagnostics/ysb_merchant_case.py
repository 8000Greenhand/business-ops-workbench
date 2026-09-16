"""Optional real-case adapters for Dashboard B capability-based modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ops_workbench.diagnostics.ysb_merchant_b1 import (
    build_customer_contribution,
    build_product_contribution,
)
from ops_workbench.diagnostics.ysb_merchant_b2 import decompose_result

HAS_TRAFFIC = "HAS_TRAFFIC"
HAS_ACTIVITY = "HAS_ACTIVITY"
HAS_CUSTOMER = "HAS_CUSTOMER"
HAS_PRODUCT = "HAS_PRODUCT"

RETAINED_ACTIVITY = "RETAINED_ACTIVITY"
PREVIOUS_ONLY_ACTIVITY = "PREVIOUS_ONLY_ACTIVITY"
CURRENT_ONLY_ACTIVITY = "CURRENT_ONLY_ACTIVITY"
ZERO_AMOUNT_ONLY = "ZERO_AMOUNT_ONLY"

ACTIVITY_MAPPING_COLUMNS = (
    "snapshot_activity_type",
    "theme_name",
    "product_code",
    "display_name",
)

CONTRIBUTION_COLUMNS = [
    "previous_month", "current_month", "previous_amount", "current_amount",
    "amount_change", "period_status",
]


def read_case_csv(path: Path) -> pd.DataFrame:
    """Read one explicitly selected case CSV and trim export whitespace."""
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            frame = pd.read_csv(path, encoding=encoding)
            break
        except UnicodeDecodeError as error:
            last_error = error
    else:
        raise ValueError(f"无法识别 CSV 编码：{path.name}") from last_error
    frame.columns = [str(column).strip() for column in frame.columns]
    for column in frame.columns:
        if frame[column].dtype == object or isinstance(frame[column].dtype, pd.StringDtype):
            frame[column] = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)
    return frame


def detect_case_capabilities(
    order: pd.DataFrame,
    traffic: pd.DataFrame | None = None,
    activities: tuple[pd.DataFrame, ...] = (),
) -> frozenset[str]:
    """Detect optional diagnosis modules from present, populated source fields."""
    capabilities: set[str] = set()
    if _has_populated(order, {"商品编码", "产品名称", "进货金额"}):
        capabilities.add(HAS_PRODUCT)
    if (
        _has_populated(order, {"活动类型", "活动ID", "进货金额"})
        and any(_has_populated(activity, {"活动ID", "活动类型"}) for activity in activities)
    ):
        capabilities.add(HAS_ACTIVITY)
    if _has_populated(order, {"药店编码", "药店全称", "进货金额"}):
        capabilities.add(HAS_CUSTOMER)
    traffic_required = {
        "时间",
        "详情点击数-我的店铺", "详情点击数-同行均值",
        "店铺访客数-我的店铺", "店铺访客数-同行均值",
        "活动曝光数-我的店铺", "活动曝光数-同行均值",
    }
    if traffic is not None and _has_populated(traffic, traffic_required):
        capabilities.add(HAS_TRAFFIC)
    return frozenset(capabilities)


def build_real_case_data(
    order_path: Path,
    traffic_path: Path,
    activity_paths: tuple[Path, ...],
    *,
    merchant_name: str,
    previous_period: str,
    current_period: str,
) -> dict[str, Any]:
    """Build a bounded Dashboard B case layer without changing B1/B2 rules."""
    order = read_case_csv(order_path)
    required = {
        "下单时间", "订单ID", "商品编码", "产品名称", "厂家", "规格",
        "采购量", "进货价", "进货金额", "订单状态", "处理情况", "结算状态",
        "活动类型", "活动ID", "配送商",
    }
    missing = required.difference(order.columns)
    if missing:
        raise ValueError(f"众恩德订单源缺少字段：{sorted(missing)}")
    merchants = set(order["配送商"].dropna().astype(str))
    if merchants != {merchant_name}:
        raise ValueError(f"订单配送商范围无法确认为 {merchant_name}：{sorted(merchants)}")

    traffic = pd.read_excel(traffic_path)
    traffic.columns = [str(column).strip() for column in traffic.columns]
    activity_frames = tuple(read_case_csv(path) for path in activity_paths)
    capabilities = detect_case_capabilities(order, traffic, activity_frames)
    if HAS_PRODUCT not in capabilities or HAS_ACTIVITY not in capabilities or HAS_TRAFFIC not in capabilities:
        raise ValueError("默认案例缺少商品、活动或流量诊断所需字段")

    return build_case_data_from_frames(
        order,
        traffic,
        activity_frames,
        previous_period=previous_period,
        current_period=current_period,
    )


def build_case_data_from_frames(
    order: pd.DataFrame,
    traffic: pd.DataFrame | None = None,
    activity_frames: tuple[pd.DataFrame, ...] = (),
    *,
    previous_period: str | None = None,
    current_period: str | None = None,
) -> dict[str, Any]:
    """Build Dashboard B data from recognized raw source tables."""
    required = {"下单时间", "订单ID", "商品编码", "产品名称", "进货金额"}
    missing = required.difference(order.columns)
    if missing:
        raise ValueError(f"订单明细缺少字段：{sorted(missing)}")
    if not _has_populated(order, required):
        raise ValueError("订单明细必需字段存在但没有有效值。")

    capabilities = detect_case_capabilities(order, traffic, activity_frames)
    if HAS_PRODUCT not in capabilities:
        raise ValueError("订单明细缺少可用的商品字段。")

    staged = _stage_orders(order)
    if previous_period is None or current_period is None:
        previous_period, current_period = _latest_adjacent_periods(staged)
    monthly = _build_monthly(staged, previous_period, current_period)
    products = build_product_contribution(
        staged, pd.Period(previous_period, freq="M"), pd.Period(current_period, freq="M")
    )
    _propagate_product_name_conflicts(staged, products)
    if HAS_CUSTOMER in capabilities:
        customers = build_customer_contribution(
            staged, pd.Period(previous_period, freq="M"), pd.Period(current_period, freq="M")
        )
    else:
        customers = pd.DataFrame(columns=[*CONTRIBUTION_COLUMNS, "customer_key", "customer_name"])

    activities = pd.DataFrame()
    activity_details = pd.DataFrame()
    mapping_rate = None
    unmatched_snapshot_count = 0
    display_name_variation_count = 0
    if HAS_ACTIVITY in capabilities:
        snapshots = _normalize_activity_snapshots(activity_frames)
        activities = _build_activity_contribution(staged, previous_period, current_period)
        activity_details = _build_activity_details(staged, snapshots, previous_period, current_period)
        order_ids = set(staged["activity_id"].dropna().astype(str))
        snapshot_ids = set(snapshots["activity_id"].dropna().astype(str))
        mapping_rate = len(order_ids & snapshot_ids) / len(order_ids) if order_ids else None
        unmatched_snapshot_count = len(snapshot_ids - order_ids)
        name_counts = staged.dropna(subset=["activity_id"]).groupby("activity_id")["product_name"].nunique()
        display_name_variation_count = int(name_counts.gt(1).sum())

    traffic_mart = (
        _build_traffic_benchmark(traffic, previous_period, current_period)
        if HAS_TRAFFIC in capabilities and traffic is not None
        else pd.DataFrame()
    )
    quality = _build_quality(staged, products, HAS_CUSTOMER in capabilities)
    facts = _build_case_facts(
        monthly,
        products,
        activities,
        traffic_mart,
        previous_period,
        current_period,
        customer_available=HAS_CUSTOMER in capabilities,
    )
    return {
        "monthly": monthly,
        "customers": customers,
        "products": products,
        "facts": facts,
        "quality": quality,
        "traffic": traffic_mart,
        "activities": activities,
        "activity_details": activity_details,
        "capabilities": capabilities,
        "activity_mapping_rate": mapping_rate,
        "activity_unmatched_snapshot_count": unmatched_snapshot_count,
        "activity_display_name_variation_count": display_name_variation_count,
    }


def _stage_orders(order: pd.DataFrame) -> pd.DataFrame:
    purchase_amount = pd.to_numeric(order["进货金额"], errors="coerce")
    if purchase_amount.isna().any():
        raise ValueError("订单明细的进货金额存在空值或非数值，无法计算。")
    staged = pd.DataFrame(
        {
            "order_date": pd.to_datetime(order["下单时间"], errors="coerce").dt.normalize(),
            "order_id": order["订单ID"].map(_identifier_or_na).astype("string"),
            "product_key": order["商品编码"].map(_identifier_or_na).astype("string"),
            "product_code": order["商品编码"].map(_identifier_or_na).astype("string"),
            "product_name": _optional_text(order, "产品名称"),
            "manufacturer_raw": _optional_text(order, "厂家"),
            "specification_raw": _optional_text(order, "规格"),
            "quantity": _optional_number(order, "采购量"),
            "unit_purchase_price": _optional_number(order, "进货价"),
            "policy_purchase_amount": purchase_amount,
            "order_status_raw": _optional_text(order, "订单状态"),
            "processing_status_raw": _optional_text(order, "处理情况"),
            "settlement_status_raw": _optional_text(order, "结算状态"),
            "activity_type": _optional_text(order, "活动类型"),
            "activity_id": _optional_identifier(order, "活动ID"),
            "customer_key": _optional_identifier(order, "药店编码"),
            "customer_name": _optional_text(order, "药店全称"),
        }
    )
    if staged["order_date"].isna().any():
        raise ValueError("订单明细的下单时间存在空值或无法识别的日期。")
    order_amount = staged.groupby("order_id", dropna=False)["policy_purchase_amount"].transform("sum")
    staged["included_in_order_count"] = staged["order_id"].notna() & order_amount.gt(0)
    return staged


def _build_monthly(staged: pd.DataFrame, previous_period: str, current_period: str) -> pd.DataFrame:
    frame = staged.copy()
    frame["month"] = frame["order_date"].dt.to_period("M").astype("string")
    rows: list[dict[str, object]] = []
    for period in (previous_period, current_period):
        group = frame[frame["month"].eq(period)]
        amount = float(group["policy_purchase_amount"].sum())
        orders = int(group.loc[group["included_in_order_count"], "order_id"].nunique())
        rows.append(
            {
                "month": period,
                "previous_month": pd.NA,
                "purchase_amount": amount,
                "order_count": orders,
                "aov": amount / orders if orders else pd.NA,
                "active_customers": int(group.loc[group["policy_purchase_amount"].gt(0), "customer_key"].nunique())
                if group["customer_key"].notna().any()
                else pd.NA,
                "active_products": int(group.loc[group["policy_purchase_amount"].gt(0), "product_key"].nunique()),
                "comparison_quality_status": "CASE_EXPORT",
            }
        )
    result = pd.DataFrame(rows)
    previous = result.iloc[0]
    current = result.iloc[1]
    result.loc[1, "previous_month"] = previous_period
    for metric in ("purchase_amount", "order_count", "aov", "active_products"):
        change = float(current[metric] - previous[metric])
        result.loc[1, f"{metric}_change"] = change
        result.loc[1, f"{metric}_change_rate"] = change / float(previous[metric]) if float(previous[metric]) else pd.NA
        result.loc[0, f"{metric}_change"] = pd.NA
        result.loc[0, f"{metric}_change_rate"] = pd.NA
    result["active_customers_change"] = pd.NA
    result["active_customers_change_rate"] = pd.NA
    return result


def _build_activity_contribution(staged: pd.DataFrame, previous_period: str, current_period: str) -> pd.DataFrame:
    frame = staged.copy()
    frame["month"] = frame["order_date"].dt.to_period("M").astype("string")
    amount = frame.groupby(["activity_type", "month"], observed=True)["policy_purchase_amount"].sum().unstack(fill_value=0.0)
    orders = frame[frame["included_in_order_count"]].groupby(["activity_type", "month"], observed=True)["order_id"].nunique().unstack(fill_value=0)
    for period in (previous_period, current_period):
        if period not in amount:
            amount[period] = 0.0
        if period not in orders:
            orders[period] = 0
    result = amount[[previous_period, current_period]].reset_index().rename(
        columns={previous_period: "previous_amount", current_period: "current_amount"}
    )
    result["previous_orders"] = result["activity_type"].map(orders[previous_period]).fillna(0).astype(int)
    result["current_orders"] = result["activity_type"].map(orders[current_period]).fillna(0).astype(int)
    result["amount_change"] = result["current_amount"] - result["previous_amount"]
    result["change_rate"] = result.apply(
        lambda row: row["amount_change"] / row["previous_amount"] if row["previous_amount"] else pd.NA, axis=1
    )
    current_total = float(result["current_amount"].sum())
    result["current_amount_share"] = result["current_amount"] / current_total if current_total else pd.NA
    negative_total = float(-result.loc[result["amount_change"].lt(0), "amount_change"].sum())
    result["negative_contribution"] = result["amount_change"].map(
        lambda value: -float(value) / negative_total if value < 0 and negative_total else 0.0
    )
    return result.sort_values("amount_change").reset_index(drop=True)


def _normalize_activity_snapshots(activity_frames: tuple[pd.DataFrame, ...]) -> pd.DataFrame:
    """Merge activity snapshots by string ID and reject mapping conflicts."""
    rename = {
        "活动ID": "activity_id",
        "活动类型": "snapshot_activity_type",
        "主题名称": "theme_name",
        "商品编码": "product_code",
        "app显示名称": "display_name",
        "商品名称": "snapshot_product_name",
        "活动状态": "current_snapshot_status",
    }
    columns = [
        "activity_id",
        "snapshot_activity_type",
        "theme_name",
        "product_code",
        "display_name",
        "snapshot_product_name",
        "current_snapshot_status",
    ]
    normalized = []
    for frame in activity_frames:
        item = frame.rename(columns=rename).copy()
        for column in columns:
            if column not in item:
                item[column] = pd.NA
        item = item[columns]
        item["activity_id"] = item["activity_id"].map(_identifier_or_na).astype("string")
        item["product_code"] = item["product_code"].map(_identifier_or_na).astype("string")
        for column in set(columns) - {"activity_id", "product_code"}:
            item[column] = item[column].map(_clean_optional_text).astype("string")
        normalized.append(item.dropna(subset=["activity_id"]))
    if not normalized:
        return pd.DataFrame(columns=columns)

    combined = pd.concat(normalized, ignore_index=True)
    conflicts: dict[str, list[str]] = {}
    for activity_id, group in combined.groupby("activity_id", observed=True):
        fields = [
            column
            for column in ACTIVITY_MAPPING_COLUMNS
            if group[column].dropna().astype(str).nunique() > 1
        ]
        if fields:
            conflicts[str(activity_id)] = fields
    if conflicts:
        examples = "；".join(
            f"{activity_id}（{','.join(fields)}）"
            for activity_id, fields in list(conflicts.items())[:5]
        )
        raise ValueError(f"活动映射冲突：同一活动ID存在不同关键映射字段：{examples}")

    records = []
    for activity_id, group in combined.groupby("activity_id", sort=False, observed=True):
        record: dict[str, object] = {"activity_id": str(activity_id)}
        for column in columns[1:]:
            values = group[column].dropna().astype(str)
            record[column] = values.iloc[0] if not values.empty else pd.NA
        records.append(record)
    return pd.DataFrame(records, columns=columns)


def _build_activity_details(
    staged: pd.DataFrame,
    snapshots: pd.DataFrame,
    previous_period: str,
    current_period: str,
) -> pd.DataFrame:
    frame = staged.dropna(subset=["activity_id", "activity_type"]).copy()
    frame["month"] = frame["order_date"].dt.to_period("M").astype("string")
    frame = frame[frame["month"].isin([previous_period, current_period])]
    type_counts = frame.groupby("activity_id", observed=True)["activity_type"].nunique()
    if type_counts.gt(1).any():
        ids = "、".join(type_counts[type_counts.gt(1)].index.astype(str)[:5])
        raise ValueError(f"活动映射冲突：订单中的活动ID对应多个活动类型：{ids}")

    keys = ["activity_type", "activity_id"]
    amount = frame.groupby([*keys, "month"], observed=True)["policy_purchase_amount"].sum().unstack(fill_value=0.0)
    orders = (
        frame[frame["included_in_order_count"]]
        .groupby([*keys, "month"], observed=True)["order_id"]
        .nunique()
        .unstack(fill_value=0)
    )
    for period in (previous_period, current_period):
        if period not in amount:
            amount[period] = 0.0
        if period not in orders:
            orders[period] = 0
    result = amount[[previous_period, current_period]].reset_index().rename(
        columns={previous_period: "previous_amount", current_period: "current_amount"}
    )
    order_index = pd.MultiIndex.from_frame(result[keys])
    result["previous_orders"] = orders[previous_period].reindex(order_index, fill_value=0).to_numpy(dtype=int)
    result["current_orders"] = orders[current_period].reindex(order_index, fill_value=0).to_numpy(dtype=int)

    order_meta = (
        frame.groupby("activity_id", observed=True)
        .agg(
            order_product_code=("product_code", _preferred_nonempty),
            order_product_name=("product_name", _preferred_nonempty),
            product_name_variants=("product_name", lambda values: values.dropna().astype(str).nunique()),
        )
        .reset_index()
    )
    result = result.merge(order_meta, on="activity_id", how="left")
    result = result.merge(snapshots, on="activity_id", how="left")
    mismatch = (
        result["product_code"].notna()
        & result["order_product_code"].notna()
        & result["product_code"].ne(result["order_product_code"])
    )
    if mismatch.any():
        ids = "、".join(result.loc[mismatch, "activity_id"].astype(str).head(5))
        raise ValueError(f"活动映射冲突：活动快照与订单商品编码不一致：{ids}")
    result["product_code"] = result["product_code"].fillna(result["order_product_code"]).astype("string")
    result["display_name"] = (
        result["display_name"]
        .fillna(result["snapshot_product_name"])
        .fillna(result["order_product_name"])
        .astype("string")
    )
    result["theme_name"] = result["theme_name"].astype("string")
    return _finalize_activity_details(result)


def build_activity_layers_from_monthly_aggregates(
    frame: pd.DataFrame,
    previous_period: str,
    current_period: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build public-demo activity layers from activity-ID monthly aggregates."""
    required = {
        "month",
        "activity_type",
        "activity_id",
        "theme_name",
        "display_name",
        "product_code",
        "purchase_amount",
        "order_count",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"activity detail demo missing columns: {sorted(missing)}")
    source = frame.copy()
    source["activity_id"] = source["activity_id"].map(_identifier_or_na).astype("string")
    source["product_code"] = source["product_code"].map(_identifier_or_na).astype("string")
    source["purchase_amount"] = pd.to_numeric(source["purchase_amount"], errors="raise")
    source["order_count"] = pd.to_numeric(source["order_count"], errors="raise").astype(int)
    source = source[source["month"].astype(str).isin([previous_period, current_period])]
    keys = ["activity_type", "activity_id"]
    amounts = source.pivot_table(index=keys, columns="month", values="purchase_amount", aggfunc="sum", fill_value=0.0)
    orders = source.pivot_table(index=keys, columns="month", values="order_count", aggfunc="sum", fill_value=0)
    for period in (previous_period, current_period):
        if period not in amounts:
            amounts[period] = 0.0
        if period not in orders:
            orders[period] = 0
    details = amounts[[previous_period, current_period]].reset_index().rename(
        columns={previous_period: "previous_amount", current_period: "current_amount"}
    )
    index = pd.MultiIndex.from_frame(details[keys])
    details["previous_orders"] = orders[previous_period].reindex(index, fill_value=0).to_numpy(dtype=int)
    details["current_orders"] = orders[current_period].reindex(index, fill_value=0).to_numpy(dtype=int)
    metadata = (
        source.groupby(keys, observed=True)
        .agg(
            theme_name=("theme_name", _preferred_nonempty),
            display_name=("display_name", _preferred_nonempty),
            product_code=("product_code", _preferred_nonempty),
        )
        .reset_index()
    )
    details = _finalize_activity_details(details.merge(metadata, on=keys, how="left"))
    return _summarize_activity_types(details), details


def _finalize_activity_details(result: pd.DataFrame) -> pd.DataFrame:
    result = result.copy()
    result["activity_id"] = result["activity_id"].map(_identifier_or_na).astype("string")
    if "product_code" in result:
        result["product_code"] = result["product_code"].map(_identifier_or_na).astype("string")
    result["amount_change"] = result["current_amount"] - result["previous_amount"]
    result["change_rate"] = result.apply(
        lambda row: row["amount_change"] / row["previous_amount"] if row["previous_amount"] else pd.NA,
        axis=1,
    )
    result["period_status"] = result.apply(_activity_period_status, axis=1)
    negative_total = result.groupby("activity_type", observed=True)["amount_change"].transform(
        lambda values: float(-values[values.lt(0)].sum())
    )
    result["negative_contribution"] = result.apply(
        lambda row: -float(row["amount_change"]) / float(negative_total.loc[row.name])
        if row["amount_change"] < 0 and negative_total.loc[row.name]
        else 0.0,
        axis=1,
    )
    return result.sort_values(["activity_type", "amount_change", "activity_id"]).reset_index(drop=True)


def _summarize_activity_types(details: pd.DataFrame) -> pd.DataFrame:
    result = (
        details.groupby("activity_type", observed=True)
        .agg(
            previous_amount=("previous_amount", "sum"),
            current_amount=("current_amount", "sum"),
            previous_orders=("previous_orders", "sum"),
            current_orders=("current_orders", "sum"),
        )
        .reset_index()
    )
    result["amount_change"] = result["current_amount"] - result["previous_amount"]
    result["change_rate"] = result.apply(
        lambda row: row["amount_change"] / row["previous_amount"] if row["previous_amount"] else pd.NA,
        axis=1,
    )
    current_total = float(result["current_amount"].sum())
    result["current_amount_share"] = result["current_amount"] / current_total if current_total else pd.NA
    negative_total = float(-result.loc[result["amount_change"].lt(0), "amount_change"].sum())
    result["negative_contribution"] = result["amount_change"].map(
        lambda value: -float(value) / negative_total if value < 0 and negative_total else 0.0
    )
    return result.sort_values("amount_change").reset_index(drop=True)


def _activity_period_status(row: pd.Series) -> str:
    if row["previous_orders"] > 0 and row["current_orders"] > 0:
        return RETAINED_ACTIVITY
    if row["previous_orders"] > 0:
        return PREVIOUS_ONLY_ACTIVITY
    if row["current_orders"] > 0:
        return CURRENT_ONLY_ACTIVITY
    return ZERO_AMOUNT_ONLY


def _build_traffic_benchmark(traffic: pd.DataFrame, previous_period: str, current_period: str) -> pd.DataFrame:
    source = traffic.copy()
    source["month"] = pd.to_datetime(source["时间"].astype(str), format="%Y%m%d", errors="coerce").dt.to_period("M").astype("string")
    mappings = (
        ("曝光", "活动曝光数-我的店铺", "活动曝光数-同行均值"),
        ("点击", "详情点击数-我的店铺", "详情点击数-同行均值"),
        ("访客", "店铺访客数-我的店铺", "店铺访客数-同行均值"),
    )
    rows = []
    for metric, own_column, peer_column in mappings:
        own_previous = float(pd.to_numeric(source.loc[source["month"].eq(previous_period), own_column]).sum())
        own_current = float(pd.to_numeric(source.loc[source["month"].eq(current_period), own_column]).sum())
        peer_previous = float(pd.to_numeric(source.loc[source["month"].eq(previous_period), peer_column]).sum())
        peer_current = float(pd.to_numeric(source.loc[source["month"].eq(current_period), peer_column]).sum())
        own_change = own_current / own_previous - 1 if own_previous else pd.NA
        peer_change = peer_current / peer_previous - 1 if peer_previous else pd.NA
        rows.append(
            {
                "metric": metric,
                "previous_own": own_previous,
                "current_own": own_current,
                "own_change_rate": own_change,
                "previous_peer": peer_previous,
                "current_peer": peer_current,
                "peer_change_rate": peer_change,
                "relative_gap": own_change - peer_change if pd.notna(own_change) and pd.notna(peer_change) else pd.NA,
            }
        )
    return pd.DataFrame(rows)


def _activity_mapping_rate(order: pd.DataFrame, activity_paths: tuple[Path, ...]) -> float | None:
    ids = set(order["活动ID"].dropna().map(_identifier))
    if not ids or not activity_paths:
        return None
    mapped: set[str] = set()
    for path in activity_paths:
        activity = read_case_csv(path)
        if "活动ID" not in activity:
            return None
        mapped.update(activity["活动ID"].dropna().map(_identifier))
    return len(ids & mapped) / len(ids)


def _propagate_product_name_conflicts(staged: pd.DataFrame, products: pd.DataFrame) -> None:
    conflicts = staged.groupby("product_key", observed=True)["product_name"].nunique()
    conflict_keys = set(conflicts[conflicts.gt(1)].index)
    products.loc[products["product_key"].isin(conflict_keys), "mapping_quality_status"] = "CONFLICT"


def _build_quality(staged: pd.DataFrame, products: pd.DataFrame, customer_available: bool) -> pd.DataFrame:
    order_amounts = staged.groupby("order_id", observed=True)["policy_purchase_amount"].sum()
    conflicts = int(products["mapping_quality_status"].eq("CONFLICT").sum())
    return pd.DataFrame(
        [
            {"rule": "ZERO_AMOUNT_ORDER", "affected_rows": int(staged["policy_purchase_amount"].eq(0).sum()), "affected_entities": int(order_amounts.eq(0).sum()), "quality_status": "REVIEW_REQUIRED"},
            {"rule": "PRODUCT_KEY_MAPPING_CONFLICT", "affected_rows": pd.NA, "affected_entities": conflicts, "quality_status": "REVIEW_REQUIRED" if conflicts else "VALID"},
            {
                "rule": "MISSING_CUSTOMER_KEY",
                "affected_rows": int(staged["customer_key"].isna().sum()),
                "affected_entities": pd.NA,
                "quality_status": "VALID" if customer_available else "UNAVAILABLE",
            },
        ]
    )


def _build_case_facts(
    monthly: pd.DataFrame,
    products: pd.DataFrame,
    activities: pd.DataFrame,
    traffic: pd.DataFrame,
    previous_period: str,
    current_period: str,
    *,
    customer_available: bool,
) -> pd.DataFrame:
    previous = monthly.iloc[0]
    current = monthly.iloc[1]
    result = decompose_result(previous, current)
    product_losses = products[products["amount_change"].lt(0)].sort_values("amount_change")
    largest_product = product_losses.iloc[0]
    total_product_loss = float(-product_losses["amount_change"].sum())
    top5_product_loss = float(-product_losses.head(5)["amount_change"].sum())
    product_concentration = top5_product_loss / total_product_loss if total_product_loss else pd.NA

    facts = [
        _fact(
            previous_period,
            current_period,
            1,
            "FACT",
            "RESULT",
            "RESULT_MIXED",
            f"{current_period} 进货金额较 {previous_period} 下降 {abs(float(current['purchase_amount_change_rate'])):.1%}，订单数下降 {abs(float(current['order_count_change_rate'])):.1%}，客单价下降 {abs(float(current['aov_change_rate'])):.1%}；订单量和客单价均为负向变化。",
            "LIMITED",
            float(result["purchase_amount_change"]),
            float(current["purchase_amount_change_rate"]),
            "ORDER_STATUS_SEMANTICS_UNCONFIRMED",
            result,
        )
    ]
    if not traffic.empty:
        visitor = traffic[traffic["metric"].eq("访客")].iloc[0]
        facts.append(
            _fact(
                previous_period,
                current_period,
                len(facts) + 1,
                "SIGNAL",
                "TRAFFIC",
                "TRAFFIC_WEAKER_THAN_PEERS",
                f"本店访客下降 {abs(float(visitor['own_change_rate'])):.1%}，同期同行下降 {abs(float(visitor['peer_change_rate'])):.1%}；本店流量表现明显弱于同行。",
                "HIGH",
                pd.NA,
                float(visitor["relative_gap"]),
                "PEER_DEFINITION_UNCONFIRMED",
                visitor.to_dict(),
            )
        )
    if not activities.empty:
        largest_activity = activities.iloc[0]
        facts.append(
            _fact(
                previous_period,
                current_period,
                len(facts) + 1,
                "FACT",
                "ACTIVITY",
                "ACTIVITY_TOP_LOSS",
                f"活动负向变化主要集中在{largest_activity['activity_type']}，金额减少 {abs(float(largest_activity['amount_change'])) / 10_000:.2f} 万，占活动类型全部负向变化 {float(largest_activity['negative_contribution']):.1%}。",
                "LIMITED",
                float(largest_activity["amount_change"]),
                float(largest_activity["negative_contribution"]),
                "ORDER_STATUS_SEMANTICS_UNCONFIRMED",
                largest_activity.to_dict(),
            )
        )
    facts.append(
        _fact(
            previous_period,
            current_period,
            len(facts) + 1,
            "FACT",
            "PRODUCT",
            "PRODUCT_TOP_LOSS",
            f"最大单品负向变化为{largest_product['product_name']}，进货金额减少 {abs(float(largest_product['amount_change'])) / 10_000:.2f} 万；Top 5 损失商品占全部商品负向变化 {float(product_concentration):.1%}。",
            "MEDIUM",
            float(largest_product["amount_change"]),
            float(product_concentration),
            "PRODUCT_MAPPING_LIMITATION",
            largest_product.to_dict(),
        )
    )
    if not customer_available:
        facts.append(
            _fact(
                previous_period,
                current_period,
                len(facts) + 1,
                "LIMITATION",
                "CUSTOMER",
                "CUSTOMER_CAPABILITY_UNAVAILABLE",
                "当前订单导出不包含有效药店标识；药店贡献诊断不可用。",
                "LIMITED",
                pd.NA,
                pd.NA,
                "CUSTOMER_KEY_UNAVAILABLE",
                {},
            )
        )
    facts.append(
        _fact(
            previous_period,
            current_period,
            pd.NA,
            "DO_NOT_INFER",
            "GUARDRAIL",
            "NO_CAUSAL_INFERENCE",
            "现有数据不能证明流量下降导致进货金额下降，也不能证明活动、价格、缺货或退款导致金额变化。",
            "LIMITED",
            pd.NA,
            pd.NA,
            "",
            {},
            core=False,
        )
    )
    return pd.DataFrame(facts)


def _fact(
    previous_period: str,
    current_period: str,
    rank: object,
    output_type: str,
    dimension: str,
    code: str,
    text: str,
    evidence: str,
    impact_amount: object,
    impact_ratio: object,
    flags: str,
    supporting: dict[str, Any],
    *,
    core: bool = True,
) -> dict[str, object]:
    return {
        "current_period": current_period,
        "previous_period": previous_period,
        "fact_rank": rank,
        "is_core_fact": core,
        "output_type": output_type,
        "diagnosis_dimension": dimension,
        "fact_code": code,
        "fact_text": text,
        "evidence_level": evidence,
        "impact_amount": impact_amount,
        "impact_ratio": impact_ratio,
        "quality_flags": flags,
        "supporting_data": json.dumps(supporting, ensure_ascii=False, default=_json_default),
    }


def _latest_adjacent_periods(staged: pd.DataFrame) -> tuple[str, str]:
    periods = sorted(set(staged["order_date"].dropna().dt.to_period("M")))
    for current in reversed(periods):
        if current - 1 in periods:
            return str(current - 1), str(current)
    raise ValueError("订单明细至少需要两个相邻月份的数据。")


def _has_populated(frame: pd.DataFrame, required: set[str]) -> bool:
    return required.issubset(frame.columns) and all(
        (frame[column].notna() & frame[column].astype("string").str.strip().ne("")).any()
        for column in required
    )


def _optional_text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    return frame[column].map(_clean_optional_text).astype("string")


def _optional_identifier(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    return frame[column].map(_identifier_or_na).astype("string")


def _optional_number(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _preferred_nonempty(values: pd.Series) -> object:
    populated = values.dropna().astype(str).map(str.strip)
    populated = populated[populated.ne("")]
    if populated.empty:
        return pd.NA
    return sorted(populated.value_counts().items(), key=lambda item: (-item[1], item[0]))[0][0]


def _clean_optional_text(value: object) -> object:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return pd.NA
    return str(value).strip()


def _identifier_or_na(value: object) -> object:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return pd.NA
    return _identifier(value)


def _identifier(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _json_default(value: object) -> object:
    if value is pd.NA or pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")
