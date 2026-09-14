"""Optional real-case adapters for Dashboard B capability-based modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ops_workbench.diagnostics.ysb_merchant_b1 import build_product_contribution
from ops_workbench.diagnostics.ysb_merchant_b2 import decompose_result

HAS_TRAFFIC = "HAS_TRAFFIC"
HAS_ACTIVITY = "HAS_ACTIVITY"
HAS_CUSTOMER = "HAS_CUSTOMER"
HAS_PRODUCT = "HAS_PRODUCT"

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


def detect_case_capabilities(order: pd.DataFrame, traffic: pd.DataFrame | None = None) -> frozenset[str]:
    """Detect optional diagnosis modules from present, populated source fields."""
    capabilities: set[str] = set()
    if _has_populated(order, {"商品编码", "产品名称", "进货金额"}):
        capabilities.add(HAS_PRODUCT)
    if _has_populated(order, {"活动类型", "活动ID", "进货金额"}):
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
    capabilities = detect_case_capabilities(order, traffic)
    if HAS_PRODUCT not in capabilities or HAS_ACTIVITY not in capabilities or HAS_TRAFFIC not in capabilities:
        raise ValueError("默认案例缺少商品、活动或流量诊断所需字段")

    staged = _stage_orders(order)
    monthly = _build_monthly(staged, previous_period, current_period)
    products = build_product_contribution(
        staged, pd.Period(previous_period, freq="M"), pd.Period(current_period, freq="M")
    )
    _propagate_product_name_conflicts(staged, products)
    activities = _build_activity_contribution(staged, previous_period, current_period)
    traffic_mart = _build_traffic_benchmark(traffic, previous_period, current_period)
    mapping_rate = _activity_mapping_rate(order, activity_paths)
    quality = _build_quality(staged, products)
    facts = _build_case_facts(monthly, products, activities, traffic_mart, previous_period, current_period)
    customers = pd.DataFrame(
        columns=[*CONTRIBUTION_COLUMNS, "customer_key", "customer_name"]
    )
    return {
        "monthly": monthly,
        "customers": customers,
        "products": products,
        "facts": facts,
        "quality": quality,
        "traffic": traffic_mart,
        "activities": activities,
        "capabilities": capabilities,
        "activity_mapping_rate": mapping_rate,
    }


def _stage_orders(order: pd.DataFrame) -> pd.DataFrame:
    staged = pd.DataFrame(
        {
            "order_date": pd.to_datetime(order["下单时间"], errors="coerce").dt.normalize(),
            "order_id": order["订单ID"].astype("string"),
            "product_key": order["商品编码"].astype("string"),
            "product_code": order["商品编码"].astype("string"),
            "product_name": order["产品名称"].astype("string"),
            "manufacturer_raw": order["厂家"].astype("string"),
            "specification_raw": order["规格"].astype("string"),
            "quantity": pd.to_numeric(order["采购量"], errors="coerce"),
            "unit_purchase_price": pd.to_numeric(order["进货价"], errors="coerce"),
            "policy_purchase_amount": pd.to_numeric(order["进货金额"], errors="coerce").fillna(0.0),
            "order_status_raw": order["订单状态"].astype("string"),
            "processing_status_raw": order["处理情况"].astype("string"),
            "settlement_status_raw": order["结算状态"].astype("string"),
            "activity_type": order["活动类型"].astype("string"),
            "activity_id": order["活动ID"].astype("string"),
        }
    )
    order_amount = staged.groupby("order_id", dropna=False)["policy_purchase_amount"].transform("sum")
    staged["included_in_order_count"] = staged["order_id"].notna() & order_amount.gt(0)
    staged["customer_key"] = pd.Series(pd.NA, index=staged.index, dtype="string")
    staged["customer_name"] = pd.Series(pd.NA, index=staged.index, dtype="string")
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
                "active_customers": pd.NA,
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


def _build_quality(staged: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    order_amounts = staged.groupby("order_id", observed=True)["policy_purchase_amount"].sum()
    conflicts = int(products["mapping_quality_status"].eq("CONFLICT").sum())
    return pd.DataFrame(
        [
            {"rule": "ZERO_AMOUNT_ORDER", "affected_rows": int(staged["policy_purchase_amount"].eq(0).sum()), "affected_entities": int(order_amounts.eq(0).sum()), "quality_status": "REVIEW_REQUIRED"},
            {"rule": "PRODUCT_KEY_MAPPING_CONFLICT", "affected_rows": pd.NA, "affected_entities": conflicts, "quality_status": "REVIEW_REQUIRED" if conflicts else "VALID"},
            {"rule": "MISSING_CUSTOMER_KEY", "affected_rows": len(staged), "affected_entities": pd.NA, "quality_status": "UNAVAILABLE"},
        ]
    )


def _build_case_facts(
    monthly: pd.DataFrame,
    products: pd.DataFrame,
    activities: pd.DataFrame,
    traffic: pd.DataFrame,
    previous_period: str,
    current_period: str,
) -> pd.DataFrame:
    previous = monthly.iloc[0]
    current = monthly.iloc[1]
    result = decompose_result(previous, current)
    visitor = traffic[traffic["metric"].eq("访客")].iloc[0]
    largest_activity = activities.iloc[0]
    product_losses = products[products["amount_change"].lt(0)].sort_values("amount_change")
    largest_product = product_losses.iloc[0]
    total_product_loss = float(-product_losses["amount_change"].sum())
    top5_product_loss = float(-product_losses.head(5)["amount_change"].sum())
    product_concentration = top5_product_loss / total_product_loss if total_product_loss else pd.NA

    facts = [
        _fact(previous_period, current_period, 1, "FACT", "RESULT", "RESULT_MIXED",
              f"{current_period} 进货金额较 {previous_period} 下降 {abs(float(current['purchase_amount_change_rate'])):.1%}，订单数下降 {abs(float(current['order_count_change_rate'])):.1%}，客单价下降 {abs(float(current['aov_change_rate'])):.1%}；订单量和客单价均为负向变化。",
              "LIMITED", float(result["purchase_amount_change"]), float(current["purchase_amount_change_rate"]), "ORDER_STATUS_SEMANTICS_UNCONFIRMED", result),
        _fact(previous_period, current_period, 2, "SIGNAL", "TRAFFIC", "TRAFFIC_WEAKER_THAN_PEERS",
              f"本店访客下降 {abs(float(visitor['own_change_rate'])):.1%}，同期同行下降 {abs(float(visitor['peer_change_rate'])):.1%}；本店流量表现明显弱于同行。",
              "HIGH", pd.NA, float(visitor["relative_gap"]), "PEER_DEFINITION_UNCONFIRMED", visitor.to_dict()),
        _fact(previous_period, current_period, 3, "FACT", "ACTIVITY", "ACTIVITY_TOP_LOSS",
              f"活动端口损失主要集中在{largest_activity['activity_type']}，金额减少 {abs(float(largest_activity['amount_change'])) / 10_000:.2f} 万，占活动端口全部负向变化 {float(largest_activity['negative_contribution']):.1%}。",
              "LIMITED", float(largest_activity["amount_change"]), float(largest_activity["negative_contribution"]), "ORDER_STATUS_SEMANTICS_UNCONFIRMED", largest_activity.to_dict()),
        _fact(previous_period, current_period, 4, "FACT", "PRODUCT", "PRODUCT_TOP_LOSS",
              f"最大单品负向变化为{largest_product['product_name']}，进货金额减少 {abs(float(largest_product['amount_change'])) / 10_000:.2f} 万；Top 5 损失商品占全部商品负向变化 {float(product_concentration):.1%}。",
              "MEDIUM", float(largest_product["amount_change"]), float(product_concentration), "PRODUCT_MAPPING_LIMITATION", largest_product.to_dict()),
        _fact(previous_period, current_period, 5, "LIMITATION", "CUSTOMER", "CUSTOMER_CAPABILITY_UNAVAILABLE",
              "当前数据来自中台账号，订单导出不包含药店标识；药店贡献诊断需要商家账号权限。",
              "LIMITED", pd.NA, pd.NA, "CUSTOMER_KEY_UNAVAILABLE", {}),
        _fact(previous_period, current_period, pd.NA, "DO_NOT_INFER", "GUARDRAIL", "NO_CAUSAL_INFERENCE",
              "现有数据不能证明流量下降导致进货金额下降，也不能证明活动、价格、缺货或退款导致金额变化。",
              "LIMITED", pd.NA, pd.NA, "", {}, core=False),
    ]
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


def _has_populated(frame: pd.DataFrame, required: set[str]) -> bool:
    return required.issubset(frame.columns) and all(frame[column].notna().any() for column in required)


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
