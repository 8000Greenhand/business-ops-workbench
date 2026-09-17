"""Optional real-case adapters for Dashboard B capability-based modules."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

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
    baseline_start: date | str | None = None,
    baseline_end: date | str | None = None,
    comparison_start: date | str | None = None,
    comparison_end: date | str | None = None,
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
    bounds = _resolve_period_bounds(
        staged,
        previous_period=previous_period,
        current_period=current_period,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        comparison_start=comparison_start,
        comparison_end=comparison_end,
    )
    previous_period, current_period, baseline_start_ts, baseline_end_ts, comparison_start_ts, comparison_end_ts = bounds
    monthly = _build_period_metrics(
        staged,
        previous_period,
        current_period,
        baseline_start_ts,
        baseline_end_ts,
        comparison_start_ts,
        comparison_end_ts,
    )
    products = _build_period_contribution(
        staged,
        previous_period,
        current_period,
        baseline_start_ts,
        baseline_end_ts,
        comparison_start_ts,
        comparison_end_ts,
        key="product_key",
        label="product_name",
        product=True,
    )
    _propagate_product_name_conflicts(staged, products)
    if HAS_CUSTOMER in capabilities:
        customers = _build_period_contribution(
            staged,
            previous_period,
            current_period,
            baseline_start_ts,
            baseline_end_ts,
            comparison_start_ts,
            comparison_end_ts,
            key="customer_key",
            label="customer_name",
            product=False,
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
        activities = _build_activity_contribution(
            staged, previous_period, current_period,
            baseline_start_ts, baseline_end_ts, comparison_start_ts, comparison_end_ts,
        )
        activity_details = _build_activity_details(
            staged, snapshots, previous_period, current_period,
            baseline_start_ts, baseline_end_ts, comparison_start_ts, comparison_end_ts,
        )
        order_ids = set(staged["activity_id"].dropna().astype(str))
        snapshot_ids = set(snapshots["activity_id"].dropna().astype(str))
        mapping_rate = len(order_ids & snapshot_ids) / len(order_ids) if order_ids else None
        unmatched_snapshot_count = len(snapshot_ids - order_ids)
        name_counts = staged.dropna(subset=["activity_id"]).groupby("activity_id")["product_name"].nunique()
        display_name_variation_count = int(name_counts.gt(1).sum())

    traffic_mart = (
        _build_traffic_benchmark(
            traffic, previous_period, current_period,
            baseline_start_ts, baseline_end_ts, comparison_start_ts, comparison_end_ts,
        )
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
        "baseline_start": baseline_start_ts.date(),
        "baseline_end": baseline_end_ts.date(),
        "comparison_start": comparison_start_ts.date(),
        "comparison_end": comparison_end_ts.date(),
        "available_start": staged["order_date"].min().date(),
        "available_end": staged["order_date"].max().date(),
        "period_source": {
            "kind": "raw",
            "order": order.copy(),
            "traffic": None if traffic is None else traffic.copy(),
            "activities": tuple(frame.copy() for frame in activity_frames),
        },
    }


def build_case_data_from_staged_orders(
    staged: pd.DataFrame,
    *,
    baseline_start: date | str,
    baseline_end: date | str,
    comparison_start: date | str,
    comparison_end: date | str,
) -> dict[str, Any]:
    """Recompute legacy staged orders for arbitrary selected date periods."""
    b_start, b_end, c_start, c_end = (
        pd.Timestamp(value).normalize() for value in (baseline_start, baseline_end, comparison_start, comparison_end)
    )
    previous_period = _period_label(b_start, b_end)
    current_period = _period_label(c_start, c_end)
    monthly = _build_period_metrics(staged, previous_period, current_period, b_start, b_end, c_start, c_end)
    products = _build_period_contribution(
        staged, previous_period, current_period, b_start, b_end, c_start, c_end,
        key="product_key", label="product_name", product=True,
    )
    customer_available = staged["customer_key"].notna().any() and staged["customer_name"].notna().any()
    customers = (
        _build_period_contribution(
            staged, previous_period, current_period, b_start, b_end, c_start, c_end,
            key="customer_key", label="customer_name", product=False,
        )
        if customer_available
        else pd.DataFrame(columns=[*CONTRIBUTION_COLUMNS, "customer_key", "customer_name"])
    )
    facts = _build_case_facts(
        monthly, products, pd.DataFrame(), pd.DataFrame(), previous_period, current_period,
        customer_available=customer_available,
    )
    return {
        "monthly": monthly,
        "customers": customers,
        "products": products,
        "facts": facts,
        "quality": _build_quality(staged, products, customer_available),
        "traffic": pd.DataFrame(),
        "activities": pd.DataFrame(),
        "activity_details": pd.DataFrame(),
        "capabilities": frozenset({HAS_PRODUCT, *([HAS_CUSTOMER] if customer_available else [])}),
        "activity_mapping_rate": None,
        "activity_unmatched_snapshot_count": 0,
        "activity_display_name_variation_count": 0,
        "baseline_start": b_start.date(),
        "baseline_end": b_end.date(),
        "comparison_start": c_start.date(),
        "comparison_end": c_end.date(),
        "available_start": staged["order_date"].min().date(),
        "available_end": staged["order_date"].max().date(),
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


def _build_period_metrics(
    staged: pd.DataFrame,
    previous_period: str,
    current_period: str,
    baseline_start: pd.Timestamp,
    baseline_end: pd.Timestamp,
    comparison_start: pd.Timestamp,
    comparison_end: pd.Timestamp,
) -> pd.DataFrame:
    """Aggregate result metrics from dated order rows for two selected periods."""
    rows: list[dict[str, object]] = []
    for period, start, end in (
        (previous_period, baseline_start, baseline_end),
        (current_period, comparison_start, comparison_end),
    ):
        group = staged[staged["order_date"].between(start, end)]
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
                "coverage_start": start.date().isoformat(),
                "coverage_end": end.date().isoformat(),
                "comparison_quality_status": "SELECTED_PERIOD",
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


def _build_period_contribution(
    staged: pd.DataFrame,
    previous_period: str,
    current_period: str,
    baseline_start: pd.Timestamp,
    baseline_end: pd.Timestamp,
    comparison_start: pd.Timestamp,
    comparison_end: pd.Timestamp,
    *,
    key: str,
    label: str,
    product: bool,
) -> pd.DataFrame:
    """Build customer or product contribution directly from selected dates."""
    frame = staged.copy()
    frame["period"] = pd.NA
    frame.loc[frame["order_date"].between(baseline_start, baseline_end), "period"] = previous_period
    frame.loc[frame["order_date"].between(comparison_start, comparison_end), "period"] = current_period
    active = frame[frame["policy_purchase_amount"].gt(0) & frame["period"].notna() & frame[key].notna()]
    amounts = active.groupby([key, "period"], observed=True)["policy_purchase_amount"].sum().unstack().fillna(0.0)
    for period in (previous_period, current_period):
        if period not in amounts:
            amounts[period] = 0.0
    result = amounts[[previous_period, current_period]].reset_index().rename(
        columns={previous_period: "previous_amount", current_period: "current_amount"}
    )
    preferred = _preferred_values(active, key, label)
    result[label] = result[key].map(preferred)
    result["previous_month"] = previous_period
    result["current_month"] = current_period
    result["amount_change"] = result["current_amount"] - result["previous_amount"]
    result["period_status"] = result.apply(
        lambda row: _contribution_period_status(row["previous_amount"], row["current_amount"], product), axis=1
    )
    if not product:
        return result[[
            "previous_month", "current_month", key, label,
            "previous_amount", "current_amount", "amount_change", "period_status",
        ]].sort_values(["amount_change", key]).reset_index(drop=True)

    source = staged.dropna(subset=["product_key"]).copy()
    source["signature"] = source["manufacturer_raw"].fillna("") + "|" + source["specification_raw"].fillna("")
    codes = source.groupby("product_key")["product_code"].nunique()
    signatures = source.groupby("product_key")["signature"].nunique()
    result["mapping_quality_status"] = result["product_key"].map(
        lambda value: "CONFLICT" if codes.get(value, 0) > 1 or signatures.get(value, 0) > 1 else "VALID"
    )
    result["product_code"] = result["product_key"].map(_preferred_values(source, "product_key", "product_code"))
    result["manufacturer"] = result["product_key"].map(_preferred_values(source, "product_key", "manufacturer_raw"))
    result["specification"] = result["product_key"].map(_preferred_values(source, "product_key", "specification_raw"))
    return result[[
        "previous_month", "current_month", "product_key", "product_code", "product_name",
        "manufacturer", "specification", "previous_amount", "current_amount", "amount_change",
        "period_status", "mapping_quality_status",
    ]].sort_values(["amount_change", "product_key"]).reset_index(drop=True)


def _build_activity_contribution(
    staged: pd.DataFrame,
    previous_period: str,
    current_period: str,
    baseline_start: pd.Timestamp,
    baseline_end: pd.Timestamp,
    comparison_start: pd.Timestamp,
    comparison_end: pd.Timestamp,
) -> pd.DataFrame:
    frame = staged.copy()
    frame["period"] = _period_bucket(frame["order_date"], previous_period, current_period, baseline_start, baseline_end, comparison_start, comparison_end)
    frame = frame[frame["period"].notna() & frame["activity_type"].notna()]
    if not {previous_period, current_period}.issubset(set(frame["period"].dropna().astype(str))):
        return pd.DataFrame()
    amount = frame.groupby(["activity_type", "period"], observed=True)["policy_purchase_amount"].sum().unstack().fillna(0.0)
    orders = frame[frame["included_in_order_count"]].groupby(["activity_type", "period"], observed=True)["order_id"].nunique().unstack().fillna(0)
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
    baseline_start: pd.Timestamp,
    baseline_end: pd.Timestamp,
    comparison_start: pd.Timestamp,
    comparison_end: pd.Timestamp,
) -> pd.DataFrame:
    frame = staged.dropna(subset=["activity_id", "activity_type"]).copy()
    frame["period"] = _period_bucket(frame["order_date"], previous_period, current_period, baseline_start, baseline_end, comparison_start, comparison_end)
    frame = frame[frame["period"].notna()]
    if not {previous_period, current_period}.issubset(set(frame["period"].dropna().astype(str))):
        return pd.DataFrame()
    type_counts = frame.groupby("activity_id", observed=True)["activity_type"].nunique()
    if type_counts.gt(1).any():
        ids = "、".join(type_counts[type_counts.gt(1)].index.astype(str)[:5])
        raise ValueError(f"活动映射冲突：订单中的活动ID对应多个活动类型：{ids}")

    keys = ["activity_type", "activity_id"]
    amount = frame.groupby([*keys, "period"], observed=True)["policy_purchase_amount"].sum().unstack().fillna(0.0)
    orders = (
        frame[frame["included_in_order_count"]]
        .groupby([*keys, "period"], observed=True)["order_id"]
        .nunique()
        .unstack()
        .fillna(0)
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


def build_case_data_from_daily_facts(
    result_daily: pd.DataFrame,
    product_daily: pd.DataFrame,
    traffic_daily: pd.DataFrame,
    activity_daily: pd.DataFrame,
    *,
    baseline_start: date | str,
    baseline_end: date | str,
    comparison_start: date | str,
    comparison_end: date | str,
) -> dict[str, Any]:
    """Build Dashboard B from tracked aggregate-only daily public facts."""
    dates = tuple(pd.Timestamp(value).normalize() for value in (
        baseline_start, baseline_end, comparison_start, comparison_end
    ))
    baseline_start_ts, baseline_end_ts, comparison_start_ts, comparison_end_ts = dates
    if baseline_start_ts > baseline_end_ts or comparison_start_ts > comparison_end_ts:
        raise ValueError("周期开始日期不能晚于结束日期。")
    previous_period = _period_label(baseline_start_ts, baseline_end_ts)
    current_period = _period_label(comparison_start_ts, comparison_end_ts)

    result_source = _normalize_daily(result_daily, {"purchase_amount", "order_count"}, "result_daily")
    product_source = _normalize_daily(
        product_daily,
        {"product_key", "product_name", "purchase_amount", "order_count", "mapping_quality_status"},
        "product_daily",
    )
    traffic_source = _normalize_daily(
        traffic_daily,
        {"own_exposure", "own_clicks", "own_visitors", "peer_exposure", "peer_clicks", "peer_visitors"},
        "traffic_daily",
    )
    activity_source = _normalize_daily(
        activity_daily,
        {"activity_type", "activity_id", "theme_name", "display_name", "product_code", "purchase_amount", "order_count"},
        "activity_daily",
    )

    monthly = _build_daily_result_metrics(
        result_source, previous_period, current_period,
        baseline_start_ts, baseline_end_ts, comparison_start_ts, comparison_end_ts,
    )
    products = _build_daily_contribution(
        product_source, previous_period, current_period,
        baseline_start_ts, baseline_end_ts, comparison_start_ts, comparison_end_ts,
    )
    activities, activity_details = build_activity_layers_from_daily_aggregates(
        activity_source,
        baseline_start=baseline_start_ts,
        baseline_end=baseline_end_ts,
        comparison_start=comparison_start_ts,
        comparison_end=comparison_end_ts,
    )
    traffic = _build_traffic_from_daily(
        traffic_source, previous_period, current_period,
        baseline_start_ts, baseline_end_ts, comparison_start_ts, comparison_end_ts,
    )
    facts = _build_case_facts(
        monthly, products, activities, traffic, previous_period, current_period, customer_available=False
    )
    return {
        "monthly": monthly,
        "customers": pd.DataFrame(columns=[*CONTRIBUTION_COLUMNS, "customer_key", "customer_name"]),
        "products": products,
        "facts": facts,
        "traffic": traffic,
        "activities": activities,
        "activity_details": activity_details,
        "baseline_start": baseline_start_ts.date(),
        "baseline_end": baseline_end_ts.date(),
        "comparison_start": comparison_start_ts.date(),
        "comparison_end": comparison_end_ts.date(),
        "available_start": result_source["date"].min().date(),
        "available_end": result_source["date"].max().date(),
    }


def build_activity_layers_from_daily_aggregates(
    frame: pd.DataFrame,
    *,
    baseline_start: date | str,
    baseline_end: date | str,
    comparison_start: date | str,
    comparison_end: date | str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate daily activity-ID facts for the selected periods."""
    source = _normalize_daily(
        frame,
        {"activity_type", "activity_id", "theme_name", "display_name", "product_code", "purchase_amount", "order_count"},
        "activity_daily",
    )
    b_start, b_end, c_start, c_end = (
        pd.Timestamp(value).normalize() for value in (baseline_start, baseline_end, comparison_start, comparison_end)
    )
    previous_period = _period_label(b_start, b_end)
    current_period = _period_label(c_start, c_end)
    source["period"] = _period_bucket(source["date"], previous_period, current_period, b_start, b_end, c_start, c_end)
    source = source[source["period"].notna()].copy()
    if not {previous_period, current_period}.issubset(set(source["period"].dropna().astype(str))):
        return pd.DataFrame(), pd.DataFrame()
    source["activity_id"] = source["activity_id"].map(_identifier_or_na).astype("string")
    source["product_code"] = source["product_code"].map(_identifier_or_na).astype("string")
    source["purchase_amount"] = pd.to_numeric(source["purchase_amount"], errors="raise")
    source["order_count"] = pd.to_numeric(source["order_count"], errors="raise").astype(int)
    keys = ["activity_type", "activity_id"]
    amounts = source.pivot_table(index=keys, columns="period", values="purchase_amount", aggfunc="sum", fill_value=0.0)
    orders = source.pivot_table(index=keys, columns="period", values="order_count", aggfunc="sum", fill_value=0)
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
    metadata = source.groupby(keys, observed=True).agg(
        theme_name=("theme_name", _preferred_nonempty),
        display_name=("display_name", _preferred_nonempty),
        product_code=("product_code", _preferred_nonempty),
    ).reset_index()
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


def _build_traffic_benchmark(
    traffic: pd.DataFrame,
    previous_period: str,
    current_period: str,
    baseline_start: pd.Timestamp,
    baseline_end: pd.Timestamp,
    comparison_start: pd.Timestamp,
    comparison_end: pd.Timestamp,
) -> pd.DataFrame:
    source = traffic.copy()
    compact = source["时间"].astype("string").str.replace(r"\.0$", "", regex=True)
    source["date"] = pd.to_datetime(compact, format="%Y%m%d", errors="coerce")
    fallback = pd.to_datetime(source["时间"], errors="coerce")
    source["date"] = source["date"].fillna(fallback).dt.normalize()
    source["period"] = _period_bucket(source["date"], previous_period, current_period, baseline_start, baseline_end, comparison_start, comparison_end)
    if not {previous_period, current_period}.issubset(set(source["period"].dropna().astype(str))):
        return pd.DataFrame()
    mappings = (
        ("曝光", "活动曝光数-我的店铺", "活动曝光数-同行均值"),
        ("点击", "详情点击数-我的店铺", "详情点击数-同行均值"),
        ("访客", "店铺访客数-我的店铺", "店铺访客数-同行均值"),
    )
    rows = []
    for metric, own_column, peer_column in mappings:
        own_previous = float(pd.to_numeric(source.loc[source["period"].eq(previous_period), own_column]).sum())
        own_current = float(pd.to_numeric(source.loc[source["period"].eq(current_period), own_column]).sum())
        peer_previous = float(pd.to_numeric(source.loc[source["period"].eq(previous_period), peer_column]).sum())
        peer_current = float(pd.to_numeric(source.loc[source["period"].eq(current_period), peer_column]).sum())
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
    total_product_loss = float(-product_losses["amount_change"].sum())
    top5_product_loss = float(-product_losses.head(5)["amount_change"].sum())
    product_concentration = top5_product_loss / total_product_loss if total_product_loss else pd.NA
    amount_rate = float(current["purchase_amount_change_rate"])
    order_rate = float(current["order_count_change_rate"])
    aov_rate = float(current["aov_change_rate"])

    facts = [
        _fact(
            previous_period,
            current_period,
            1,
            "FACT",
            "RESULT",
            f"RESULT_{result['driver_classification']}",
            f"对比期进货金额较基准期{_rate_phrase(amount_rate)}，订单数{_rate_phrase(order_rate)}，"
            f"客单价{_rate_phrase(aov_rate)}；结果层判断为 {result['driver_classification']}。",
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
                f"本店访客{_rate_phrase(float(visitor['own_change_rate']))}，同期同行"
                f"{_rate_phrase(float(visitor['peer_change_rate']))}；两者仅作同期变化比较。",
                "HIGH",
                pd.NA,
                float(visitor["relative_gap"]),
                "PEER_DEFINITION_UNCONFIRMED",
                visitor.to_dict(),
            )
        )
    if not activities.empty:
        losses = activities[activities["amount_change"].lt(0)].sort_values("amount_change")
        largest_activity = losses.iloc[0] if not losses.empty else activities.sort_values("amount_change", ascending=False).iloc[0]
        activity_is_loss = float(largest_activity["amount_change"]) < 0
        facts.append(
            _fact(
                previous_period,
                current_period,
                len(facts) + 1,
                "FACT",
                "ACTIVITY",
                "ACTIVITY_TOP_LOSS" if activity_is_loss else "ACTIVITY_TOP_GROWTH",
                (
                    f"活动负向变化主要集中在{largest_activity['activity_type']}，金额减少 "
                    f"{abs(float(largest_activity['amount_change'])) / 10_000:.2f} 万，占活动类型全部负向变化 "
                    f"{float(largest_activity['negative_contribution']):.1%}。"
                    if activity_is_loss
                    else f"活动正向变化最高的是{largest_activity['activity_type']}，金额增加 "
                    f"{float(largest_activity['amount_change']) / 10_000:.2f} 万。"
                ),
                "LIMITED",
                float(largest_activity["amount_change"]),
                float(largest_activity["negative_contribution"]),
                "ORDER_STATUS_SEMANTICS_UNCONFIRMED",
                largest_activity.to_dict(),
            )
        )
    if not products.empty:
        largest_product = (
            product_losses.iloc[0]
            if not product_losses.empty
            else products.sort_values("amount_change", ascending=False).iloc[0]
        )
        product_is_loss = float(largest_product["amount_change"]) < 0
        facts.append(
            _fact(
                previous_period,
                current_period,
                len(facts) + 1,
                "FACT",
                "PRODUCT",
                "PRODUCT_TOP_LOSS" if product_is_loss else "PRODUCT_TOP_GROWTH",
                (
                    f"最大单品负向变化为{largest_product['product_name']}，进货金额减少 "
                    f"{abs(float(largest_product['amount_change'])) / 10_000:.2f} 万；Top 5 损失商品占全部商品负向变化 "
                    f"{float(product_concentration):.1%}。"
                    if product_is_loss
                    else f"最大单品正向变化为{largest_product['product_name']}，进货金额增加 "
                    f"{float(largest_product['amount_change']) / 10_000:.2f} 万。"
                ),
                "MEDIUM",
                float(largest_product["amount_change"]),
                float(product_concentration) if product_is_loss else pd.NA,
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


def _rate_phrase(value: float) -> str:
    if value > 0:
        return f"增加 {value:.1%}"
    if value < 0:
        return f"下降 {abs(value):.1%}"
    return "持平"


def _resolve_period_bounds(
    staged: pd.DataFrame,
    *,
    previous_period: str | None,
    current_period: str | None,
    baseline_start: date | str | None,
    baseline_end: date | str | None,
    comparison_start: date | str | None,
    comparison_end: date | str | None,
) -> tuple[str, str, pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    explicit_dates = (baseline_start, baseline_end, comparison_start, comparison_end)
    if any(value is not None for value in explicit_dates):
        if not all(value is not None for value in explicit_dates):
            raise ValueError("基准期和对比期必须同时提供开始与结束日期。")
        starts_ends = tuple(pd.Timestamp(value).normalize() for value in explicit_dates)
        baseline_start_ts, baseline_end_ts, comparison_start_ts, comparison_end_ts = starts_ends
        previous_label = _period_label(baseline_start_ts, baseline_end_ts)
        current_label = _period_label(comparison_start_ts, comparison_end_ts)
    else:
        if previous_period is None and current_period is None:
            (
                baseline_start_ts,
                baseline_end_ts,
                comparison_start_ts,
                comparison_end_ts,
            ) = _default_period_bounds(staged)
            previous_label = _period_label(baseline_start_ts, baseline_end_ts)
            current_label = _period_label(comparison_start_ts, comparison_end_ts)
            return (
                previous_label,
                current_label,
                baseline_start_ts,
                baseline_end_ts,
                comparison_start_ts,
                comparison_end_ts,
            )
        if previous_period is None or current_period is None:
            raise ValueError("previous_period and current_period must be provided together")
        previous = pd.Period(previous_period, freq="M")
        current = pd.Period(current_period, freq="M")
        baseline_start_ts = previous.start_time.normalize()
        baseline_end_ts = previous.end_time.normalize()
        comparison_start_ts = current.start_time.normalize()
        comparison_end_ts = current.end_time.normalize()
        previous_label = str(previous_period)
        current_label = str(current_period)
    if baseline_start_ts > baseline_end_ts or comparison_start_ts > comparison_end_ts:
        raise ValueError("周期开始日期不能晚于结束日期。")
    return (
        previous_label,
        current_label,
        baseline_start_ts,
        baseline_end_ts,
        comparison_start_ts,
        comparison_end_ts,
    )


def _default_period_bounds(staged: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """Choose the latest two complete months, else equal observed spans in adjacent months."""
    frame = staged.dropna(subset=["order_date"]).copy()
    frame["calendar_month"] = frame["order_date"].dt.to_period("M")
    periods = sorted(frame["calendar_month"].unique())
    if len(periods) < 2:
        raise ValueError("订单明细至少需要两个可比较日期周期的数据。")
    for current in reversed(periods):
        previous = current - 1
        if previous not in periods:
            continue
        previous_dates = frame.loc[frame["calendar_month"].eq(previous), "order_date"]
        current_dates = frame.loc[frame["calendar_month"].eq(current), "order_date"]
        previous_complete = (
            previous_dates.min() == previous.start_time.normalize()
            and previous_dates.max() == previous.end_time.normalize()
            and previous_dates.dt.normalize().nunique() == previous.days_in_month
        )
        current_complete = (
            current_dates.min() == current.start_time.normalize()
            and current_dates.max() == current.end_time.normalize()
            and current_dates.dt.normalize().nunique() == current.days_in_month
        )
        if previous_complete and current_complete:
            return (
                previous.start_time.normalize(), previous.end_time.normalize(),
                current.start_time.normalize(), current.end_time.normalize(),
            )
        comparable_days = min(
            (previous_dates.max() - previous_dates.min()).days + 1,
            (current_dates.max() - current_dates.min()).days + 1,
        )
        return (
            previous_dates.min().normalize(),
            previous_dates.min().normalize() + pd.Timedelta(days=comparable_days - 1),
            current_dates.min().normalize(),
            current_dates.min().normalize() + pd.Timedelta(days=comparable_days - 1),
        )
    raise ValueError("订单明细至少需要两个相邻月份的数据。")


def _normalize_daily(frame: pd.DataFrame, required: set[str], name: str) -> pd.DataFrame:
    missing = ({"date"} | required).difference(frame.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    if result["date"].isna().any():
        raise ValueError(f"{name} contains invalid dates")
    return result


def _build_daily_result_metrics(
    frame: pd.DataFrame,
    previous_period: str,
    current_period: str,
    baseline_start: pd.Timestamp,
    baseline_end: pd.Timestamp,
    comparison_start: pd.Timestamp,
    comparison_end: pd.Timestamp,
) -> pd.DataFrame:
    rows = []
    for label, start, end in (
        (previous_period, baseline_start, baseline_end),
        (current_period, comparison_start, comparison_end),
    ):
        selected = frame[frame["date"].between(start, end)]
        amount = float(pd.to_numeric(selected["purchase_amount"], errors="raise").sum())
        orders = int(pd.to_numeric(selected["order_count"], errors="raise").sum())
        rows.append({
            "month": label,
            "previous_month": pd.NA,
            "purchase_amount": amount,
            "order_count": orders,
            "aov": amount / orders if orders else pd.NA,
            "active_customers": pd.NA,
            "active_products": pd.NA,
            "coverage_start": start.date().isoformat(),
            "coverage_end": end.date().isoformat(),
            "comparison_quality_status": "SELECTED_PERIOD",
        })
    result = pd.DataFrame(rows)
    result.loc[1, "previous_month"] = previous_period
    for metric in ("purchase_amount", "order_count", "aov"):
        previous = result.loc[0, metric]
        current = result.loc[1, metric]
        result.loc[0, f"{metric}_change"] = pd.NA
        result.loc[0, f"{metric}_change_rate"] = pd.NA
        result.loc[1, f"{metric}_change"] = current - previous if pd.notna(current) and pd.notna(previous) else pd.NA
        result.loc[1, f"{metric}_change_rate"] = current / previous - 1 if pd.notna(previous) and previous != 0 else pd.NA
    for metric in ("active_customers", "active_products"):
        result[f"{metric}_change"] = pd.NA
        result[f"{metric}_change_rate"] = pd.NA
    return result


def _build_daily_contribution(
    frame: pd.DataFrame,
    previous_period: str,
    current_period: str,
    baseline_start: pd.Timestamp,
    baseline_end: pd.Timestamp,
    comparison_start: pd.Timestamp,
    comparison_end: pd.Timestamp,
) -> pd.DataFrame:
    source = frame.copy()
    source["period"] = _period_bucket(source["date"], previous_period, current_period, baseline_start, baseline_end, comparison_start, comparison_end)
    source = source[source["period"].notna()]
    source["purchase_amount"] = pd.to_numeric(source["purchase_amount"], errors="raise")
    amounts = source[source["purchase_amount"].gt(0)].pivot_table(
        index="product_key", columns="period", values="purchase_amount", aggfunc="sum", fill_value=0.0
    )
    for period in (previous_period, current_period):
        if period not in amounts:
            amounts[period] = 0.0
    result = amounts[[previous_period, current_period]].reset_index().rename(
        columns={previous_period: "previous_amount", current_period: "current_amount"}
    )
    metadata = source.groupby("product_key", observed=True).agg(
        product_name=("product_name", _preferred_nonempty),
        mapping_quality_status=("mapping_quality_status", _preferred_nonempty),
    ).reset_index()
    result = result.merge(metadata, on="product_key", how="left")
    result["product_code"] = result["product_key"].astype("string")
    result["manufacturer"] = pd.NA
    result["specification"] = pd.NA
    result["previous_month"] = previous_period
    result["current_month"] = current_period
    result["amount_change"] = result["current_amount"] - result["previous_amount"]
    result["period_status"] = result.apply(
        lambda row: _contribution_period_status(row["previous_amount"], row["current_amount"], True), axis=1
    )
    return result[[
        "previous_month", "current_month", "product_key", "product_code", "product_name",
        "manufacturer", "specification", "previous_amount", "current_amount", "amount_change",
        "period_status", "mapping_quality_status",
    ]].sort_values(["amount_change", "product_key"]).reset_index(drop=True)


def _build_traffic_from_daily(
    frame: pd.DataFrame,
    previous_period: str,
    current_period: str,
    baseline_start: pd.Timestamp,
    baseline_end: pd.Timestamp,
    comparison_start: pd.Timestamp,
    comparison_end: pd.Timestamp,
) -> pd.DataFrame:
    mappings = (
        ("曝光", "own_exposure", "peer_exposure"),
        ("点击", "own_clicks", "peer_clicks"),
        ("访客", "own_visitors", "peer_visitors"),
    )
    rows = []
    for metric, own_column, peer_column in mappings:
        baseline = frame[frame["date"].between(baseline_start, baseline_end)]
        comparison = frame[frame["date"].between(comparison_start, comparison_end)]
        if baseline.empty or comparison.empty:
            return pd.DataFrame()
        own_previous = float(pd.to_numeric(baseline[own_column], errors="raise").sum())
        own_current = float(pd.to_numeric(comparison[own_column], errors="raise").sum())
        peer_previous = float(pd.to_numeric(baseline[peer_column], errors="raise").sum())
        peer_current = float(pd.to_numeric(comparison[peer_column], errors="raise").sum())
        own_change = own_current / own_previous - 1 if own_previous else pd.NA
        peer_change = peer_current / peer_previous - 1 if peer_previous else pd.NA
        rows.append({
            "metric": metric,
            "previous_own": own_previous,
            "current_own": own_current,
            "own_change_rate": own_change,
            "previous_peer": peer_previous,
            "current_peer": peer_current,
            "peer_change_rate": peer_change,
            "relative_gap": own_change - peer_change if pd.notna(own_change) and pd.notna(peer_change) else pd.NA,
        })
    return pd.DataFrame(rows)


def _period_label(start: pd.Timestamp, end: pd.Timestamp) -> str:
    return f"{start.date().isoformat()} ～ {end.date().isoformat()}"


def _period_bucket(
    values: pd.Series,
    previous_period: str,
    current_period: str,
    baseline_start: pd.Timestamp,
    baseline_end: pd.Timestamp,
    comparison_start: pd.Timestamp,
    comparison_end: pd.Timestamp,
) -> pd.Series:
    result = pd.Series(None, index=values.index, dtype="object")
    result.loc[values.between(baseline_start, baseline_end)] = previous_period
    result.loc[values.between(comparison_start, comparison_end)] = current_period
    return result


def _contribution_period_status(previous: float, current: float, product: bool) -> str:
    if previous > 0 and current > 0:
        return "RETAINED_ACTIVE" if product else "RETAINED"
    if current > 0:
        return "CURRENT_ONLY_ACTIVE" if product else "CURRENT_ONLY"
    return "PREVIOUS_ONLY_ACTIVE" if product else "PREVIOUS_ONLY"


def _preferred_values(frame: pd.DataFrame, key: str, value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for entity, group in frame.dropna(subset=[key]).groupby(key, observed=True):
        values = group[value].dropna().astype(str)
        if not values.empty:
            result[str(entity)] = sorted(values.value_counts().items(), key=lambda item: (-item[1], item[0]))[0][0]
    return result


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
