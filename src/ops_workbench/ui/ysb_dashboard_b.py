"""Presentation data helpers for the single-merchant YSB Dashboard B."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from zipfile import BadZipFile

import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from ops_workbench.diagnostics.ysb_merchant_b1 import (
    apply_order_policy,
    build_customer_contribution,
    build_monthly_diagnosis,
    build_product_contribution,
    build_quality_summary,
    latest_complete_pair,
    load_order_metric_policy,
    read_order_items,
)
from ops_workbench.diagnostics.ysb_merchant_b2 import (
    build_diagnosis_facts,
    load_b1_marts,
    load_diagnosis_rules,
)
from ops_workbench.diagnostics.ysb_merchant_case import (
    HAS_ACTIVITY,
    HAS_CUSTOMER,
    HAS_PRODUCT,
    HAS_TRAFFIC,
    build_case_data_from_daily_facts,
    build_case_data_from_frames,
    build_case_data_from_staged_orders,
    build_real_case_data,
)
from ops_workbench.diagnostics.ysb_dashboard_b_input import (
    UploadedPayload,
    recognize_uploaded_inputs,
)


@dataclass(frozen=True, slots=True)
class DashboardBInputSummary:
    """Business-facing upload recognition summary."""

    order_label: str | None = None
    traffic_label: str | None = None
    activity_file_count: int = 0
    customer_available: bool = False
    legacy: bool = False
    unknown_labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardBData:
    """B1/B2 outputs required by the Dashboard B presentation."""

    monthly: pd.DataFrame
    customers: pd.DataFrame
    products: pd.DataFrame
    facts: pd.DataFrame
    quality: pd.DataFrame
    previous_period: str
    current_period: str
    source_label: str
    merchant_name: str = ""
    traffic: pd.DataFrame = field(default_factory=pd.DataFrame)
    activities: pd.DataFrame = field(default_factory=pd.DataFrame)
    activity_details: pd.DataFrame = field(default_factory=pd.DataFrame)
    capabilities: frozenset[str] = frozenset()
    activity_mapping_rate: float | None = None
    activity_unmatched_snapshot_count: int = 0
    activity_display_name_variation_count: int = 0
    customer_unavailable_reason: str | None = None
    input_summary: DashboardBInputSummary = field(default_factory=DashboardBInputSummary)
    baseline_start: date | None = None
    baseline_end: date | None = None
    comparison_start: date | None = None
    comparison_end: date | None = None
    available_start: date | None = None
    available_end: date | None = None
    period_source: dict[str, Any] | None = field(default=None, repr=False, compare=False)


class DashboardBInputError(ValueError):
    """Raised when an uploaded workbook cannot satisfy the existing pipeline."""


def load_dashboard_b_marts(mart_dir: Path) -> DashboardBData:
    """Load the existing sample B1/B2 outputs without recalculating diagnoses."""
    monthly, customers, products = load_b1_marts(mart_dir)
    facts = pd.read_csv(mart_dir / "mart_merchant_diagnosis_facts.csv")
    quality = pd.read_csv(mart_dir / "mart_merchant_data_quality.csv")
    _require_fact_columns(facts)
    periods = facts.loc[facts["is_core_fact"].eq(True), ["previous_period", "current_period"]].drop_duplicates()
    if len(periods) != 1:
        raise ValueError("facts mart must contain exactly one core comparison period")
    period = periods.iloc[0]
    return DashboardBData(
        monthly=monthly,
        customers=customers,
        products=products,
        facts=facts,
        quality=quality,
        previous_period=str(period["previous_period"]),
        current_period=str(period["current_period"]),
        source_label="当前样本数据",
        capabilities=frozenset({HAS_CUSTOMER, HAS_PRODUCT}),
    )


def load_real_case_dashboard_b(
    order_path: Path,
    traffic_path: Path,
    activity_paths: tuple[Path, ...],
    *,
    merchant_name: str,
    previous_period: str,
    current_period: str,
) -> DashboardBData:
    """Load one configured real case through the optional capability adapter."""
    try:
        result = build_real_case_data(
            order_path,
            traffic_path,
            activity_paths,
            merchant_name=merchant_name,
            previous_period=previous_period,
            current_period=current_period,
        )
    except (KeyError, OSError, ValueError) as error:
        raise DashboardBInputError(f"默认真实案例无法加载：{error}") from error
    _require_fact_columns(result["facts"])
    return DashboardBData(
        monthly=result["monthly"],
        customers=result["customers"],
        products=result["products"],
        facts=result["facts"],
        quality=result["quality"],
        previous_period=previous_period,
        current_period=current_period,
        source_label=f"{merchant_name}真实案例",
        merchant_name=merchant_name,
        traffic=result["traffic"],
        activities=result["activities"],
        activity_details=result["activity_details"],
        capabilities=result["capabilities"],
        activity_mapping_rate=result["activity_mapping_rate"],
        activity_unmatched_snapshot_count=result["activity_unmatched_snapshot_count"],
        activity_display_name_variation_count=result["activity_display_name_variation_count"],
        customer_unavailable_reason=(
            None
            if HAS_CUSTOMER in result["capabilities"]
            else "当前数据来自中台账号，订单导出不包含药店标识；药店贡献诊断需要商家账号权限。"
        ),
        baseline_start=result["baseline_start"],
        baseline_end=result["baseline_end"],
        comparison_start=result["comparison_start"],
        comparison_end=result["comparison_end"],
        available_start=result["available_start"],
        available_end=result["available_end"],
        period_source=result["period_source"],
    )


def load_public_demo_dashboard_b(directory: Path) -> DashboardBData:
    """Load the tracked aggregate-only Dashboard B public demo."""
    try:
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        quality = pd.read_csv(directory / "quality.csv")
        result_daily = pd.read_csv(directory / "result_daily.csv")
        traffic_daily = pd.read_csv(directory / "traffic_daily.csv")
        product_daily = pd.read_csv(directory / "product_daily.csv", dtype={"product_key": "string"})
        activity_daily = pd.read_csv(
            directory / "activity_daily.csv",
            dtype={"activity_id": "string", "product_code": "string"},
        )
    except (OSError, ValueError, KeyError) as error:
        raise DashboardBInputError(f"公开演示数据无法加载：{error}") from error

    defaults = metadata.get("default_periods", {})
    baseline_start = defaults.get("baseline_start", "2026-04-01")
    baseline_end = defaults.get("baseline_end", "2026-04-30")
    comparison_start = defaults.get("comparison_start", "2026-05-01")
    comparison_end = defaults.get("comparison_end", "2026-05-30")
    result = build_case_data_from_daily_facts(
        result_daily,
        product_daily,
        traffic_daily,
        activity_daily,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        comparison_start=comparison_start,
        comparison_end=comparison_end,
    )
    _require_fact_columns(result["facts"])
    source = {
        "kind": "daily",
        "result": result_daily,
        "product": product_daily,
        "traffic": traffic_daily,
        "activity": activity_daily,
    }
    return DashboardBData(
        monthly=result["monthly"],
        customers=result["customers"],
        products=result["products"],
        facts=result["facts"],
        quality=quality,
        previous_period=str(result["monthly"].iloc[0]["month"]),
        current_period=str(result["monthly"].iloc[1]["month"]),
        source_label=str(metadata["source_label"]),
        merchant_name=str(metadata["merchant_name"]),
        traffic=result["traffic"],
        activities=result["activities"],
        activity_details=result["activity_details"],
        capabilities=frozenset(metadata["capabilities"]),
        activity_mapping_rate=float(metadata["activity_mapping_rate"]),
        activity_unmatched_snapshot_count=int(metadata.get("activity_unmatched_snapshot_count", 0)),
        activity_display_name_variation_count=int(metadata.get("activity_display_name_variation_count", 0)),
        customer_unavailable_reason=str(metadata["customer_unavailable_reason"]),
        baseline_start=result["baseline_start"],
        baseline_end=result["baseline_end"],
        comparison_start=result["comparison_start"],
        comparison_end=result["comparison_end"],
        available_start=result["available_start"],
        available_end=result["available_end"],
        period_source=source,
    )


def build_dashboard_b_from_upload(
    content: bytes,
    policy_path: Path,
    rules_path: Path,
    filename: str,
) -> DashboardBData:
    """Compatibility wrapper for one uploaded Dashboard B file."""
    return build_dashboard_b_from_uploads(
        (UploadedPayload(filename, content),),
        policy_path,
        rules_path,
    )


def build_dashboard_b_from_uploads(
    payloads: Iterable[UploadedPayload],
    policy_path: Path,
    rules_path: Path,
) -> DashboardBData:
    """Recognize uploaded raw files and build one capability-aware Dashboard B."""
    payloads = tuple(payloads)
    if not payloads:
        raise DashboardBInputError("未识别到订单明细。Dashboard B 至少需要订单数据。")
    try:
        recognized = recognize_uploaded_inputs(payloads)
    except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as error:
        raise DashboardBInputError(str(error)) from error

    if recognized.legacy is not None:
        data = _build_legacy_dashboard_b(
            recognized.legacy.content,
            policy_path,
            rules_path,
            recognized.legacy.name,
        )
        return DashboardBData(
            monthly=data.monthly,
            customers=data.customers,
            products=data.products,
            facts=data.facts,
            quality=data.quality,
            previous_period=data.previous_period,
            current_period=data.current_period,
            source_label=data.source_label,
            capabilities=data.capabilities,
            customer_unavailable_reason=data.customer_unavailable_reason,
            input_summary=DashboardBInputSummary(
                order_label=recognized.legacy.name,
                customer_available=True,
                legacy=True,
                unknown_labels=recognized.unknown_labels,
            ),
            baseline_start=data.baseline_start,
            baseline_end=data.baseline_end,
            comparison_start=data.comparison_start,
            comparison_end=data.comparison_end,
            available_start=data.available_start,
            available_end=data.available_end,
            period_source=data.period_source,
        )

    if recognized.order is None:
        raise DashboardBInputError("未识别到订单明细。Dashboard B 至少需要订单数据。")
    try:
        result = build_case_data_from_frames(
            recognized.order,
            recognized.traffic,
            recognized.activities,
        )
    except (KeyError, OSError, ValueError) as error:
        raise DashboardBInputError(str(error)) from error
    customer_available = HAS_CUSTOMER in result["capabilities"]
    return DashboardBData(
        monthly=result["monthly"],
        customers=result["customers"],
        products=result["products"],
        facts=result["facts"],
        quality=result["quality"],
        previous_period=str(result["monthly"].iloc[0]["month"]),
        current_period=str(result["monthly"].iloc[1]["month"]),
        source_label=recognized.order_label or "上传订单明细",
        traffic=result["traffic"],
        activities=result["activities"],
        activity_details=result["activity_details"],
        capabilities=result["capabilities"],
        activity_mapping_rate=result["activity_mapping_rate"],
        activity_unmatched_snapshot_count=result["activity_unmatched_snapshot_count"],
        activity_display_name_variation_count=result["activity_display_name_variation_count"],
        customer_unavailable_reason=(
            None if customer_available else "当前订单数据不包含有效药店编码和名称，药店贡献不可用。"
        ),
        input_summary=DashboardBInputSummary(
            order_label=recognized.order_label,
            traffic_label=recognized.traffic_label,
            activity_file_count=len(recognized.activity_labels),
            customer_available=customer_available,
            unknown_labels=recognized.unknown_labels,
        ),
        baseline_start=result["baseline_start"],
        baseline_end=result["baseline_end"],
        comparison_start=result["comparison_start"],
        comparison_end=result["comparison_end"],
        available_start=result["available_start"],
        available_end=result["available_end"],
        period_source=result["period_source"],
    )


def _build_legacy_dashboard_b(
    content: bytes,
    policy_path: Path,
    rules_path: Path,
    filename: str,
) -> DashboardBData:
    """Run the unchanged B1/B2 pipeline against one legacy workbook."""
    if not content:
        raise DashboardBInputError("上传文件为空。")
    try:
        with tempfile.TemporaryDirectory(prefix="ysb-dashboard-b-") as temporary:
            source = Path(temporary) / "uploaded.xlsx"
            source.write_bytes(content)
            policy = load_order_metric_policy(policy_path)
            staged = apply_order_policy(read_order_items(source), policy)
            monthly = build_monthly_diagnosis(staged)
            previous, current = latest_complete_pair(monthly)
            customers = build_customer_contribution(staged, previous, current)
            products = build_product_contribution(staged, previous, current)
            quality = build_quality_summary(staged)
            rules = load_diagnosis_rules(rules_path)
            facts, _ = build_diagnosis_facts(monthly, customers, products, rules)
    except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as error:
        raise DashboardBInputError(
            "文件无法按现有药师帮日报结构处理。请确认包含“订单原始数据”工作表及全部必需列。"
            f" 原因：{error}"
        ) from error
    return DashboardBData(
        monthly=monthly,
        customers=customers,
        products=products,
        facts=facts,
        quality=quality,
        previous_period=str(previous),
        current_period=str(current),
        source_label=filename,
        capabilities=frozenset({HAS_CUSTOMER, HAS_PRODUCT}),
        baseline_start=previous.start_time.date(),
        baseline_end=previous.end_time.date(),
        comparison_start=current.start_time.date(),
        comparison_end=current.end_time.date(),
        available_start=staged["order_date"].min().date(),
        available_end=staged["order_date"].max().date(),
        period_source={"kind": "staged", "staged": staged},
    )


def select_dashboard_b_periods(
    data: DashboardBData,
    *,
    baseline_start: date,
    baseline_end: date,
    comparison_start: date,
    comparison_end: date,
) -> DashboardBData:
    """Recompute every available Dashboard B module for selected date periods."""
    if data.period_source is None:
        return data
    if baseline_start > baseline_end or comparison_start > comparison_end:
        raise DashboardBInputError("周期开始日期不能晚于结束日期。")
    if data.available_start and min(baseline_start, comparison_start) < data.available_start:
        raise DashboardBInputError("所选周期早于当前数据源的可用日期。")
    if data.available_end and max(baseline_end, comparison_end) > data.available_end:
        raise DashboardBInputError("所选周期晚于当前数据源的可用日期。")

    source = data.period_source
    kind = source["kind"]
    _require_order_coverage(source, kind, baseline_start, baseline_end, comparison_start, comparison_end)
    try:
        if kind == "raw":
            result = build_case_data_from_frames(
                source["order"],
                source["traffic"],
                source["activities"],
                baseline_start=baseline_start,
                baseline_end=baseline_end,
                comparison_start=comparison_start,
                comparison_end=comparison_end,
            )
        elif kind == "staged":
            result = build_case_data_from_staged_orders(
                source["staged"],
                baseline_start=baseline_start,
                baseline_end=baseline_end,
                comparison_start=comparison_start,
                comparison_end=comparison_end,
            )
        elif kind == "daily":
            result = build_case_data_from_daily_facts(
                source["result"],
                source["product"],
                source["traffic"],
                source["activity"],
                baseline_start=baseline_start,
                baseline_end=baseline_end,
                comparison_start=comparison_start,
                comparison_end=comparison_end,
            )
        else:
            raise ValueError(f"unsupported period source: {kind}")
    except (KeyError, TypeError, ValueError) as error:
        raise DashboardBInputError(f"所选周期无法计算：{error}") from error

    customer_available = HAS_CUSTOMER in result.get("capabilities", data.capabilities)
    return DashboardBData(
        monthly=result["monthly"],
        customers=result["customers"],
        products=result["products"],
        facts=result["facts"],
        quality=result.get("quality", data.quality),
        previous_period=str(result["monthly"].iloc[0]["month"]),
        current_period=str(result["monthly"].iloc[1]["month"]),
        source_label=data.source_label,
        merchant_name=data.merchant_name,
        traffic=result.get("traffic", pd.DataFrame()),
        activities=result.get("activities", pd.DataFrame()),
        activity_details=result.get("activity_details", pd.DataFrame()),
        capabilities=result.get("capabilities", data.capabilities),
        activity_mapping_rate=result.get("activity_mapping_rate", data.activity_mapping_rate),
        activity_unmatched_snapshot_count=result.get(
            "activity_unmatched_snapshot_count", data.activity_unmatched_snapshot_count
        ),
        activity_display_name_variation_count=result.get(
            "activity_display_name_variation_count", data.activity_display_name_variation_count
        ),
        customer_unavailable_reason=(
            None if customer_available else data.customer_unavailable_reason
        ),
        input_summary=data.input_summary,
        baseline_start=result["baseline_start"],
        baseline_end=result["baseline_end"],
        comparison_start=result["comparison_start"],
        comparison_end=result["comparison_end"],
        available_start=data.available_start,
        available_end=data.available_end,
        period_source=data.period_source,
    )


def _require_order_coverage(
    source: dict[str, Any],
    kind: str,
    baseline_start: date,
    baseline_end: date,
    comparison_start: date,
    comparison_end: date,
) -> None:
    if kind == "daily":
        dates = pd.to_datetime(source["result"]["date"], errors="coerce")
    elif kind == "staged":
        dates = pd.to_datetime(source["staged"]["order_date"], errors="coerce")
    else:
        dates = pd.to_datetime(source["order"]["下单时间"], errors="coerce")
    for label, start, end in (
        ("基准期", baseline_start, baseline_end),
        ("对比期", comparison_start, comparison_end),
    ):
        if not dates.between(pd.Timestamp(start), pd.Timestamp(end)).any():
            raise DashboardBInputError(f"{label}没有可用订单数据，请调整日期范围。")


def has_capability(data: DashboardBData, capability: str) -> bool:
    """Return whether the loaded source supports an optional diagnosis module."""
    return capability in data.capabilities


def current_metrics(data: DashboardBData) -> pd.Series:
    """Return the selected B1 monthly metric row."""
    rows = data.monthly[data.monthly["month"].eq(data.current_period)]
    if len(rows) != 1:
        raise ValueError("current monthly metric row is missing or duplicated")
    return rows.iloc[0]


def core_facts(data: DashboardBData) -> pd.DataFrame:
    """Return ranked B2 core facts exactly as persisted or generated."""
    return data.facts[data.facts["is_core_fact"].eq(True)].sort_values("fact_rank").copy()


def result_decomposition(data: DashboardBData) -> dict[str, Any]:
    """Read the persisted B2 result decomposition supporting data."""
    rows = core_facts(data)
    rows = rows[rows["diagnosis_dimension"].eq("RESULT")]
    if len(rows) != 1:
        raise ValueError("result diagnosis fact is missing or duplicated")
    fact = rows.iloc[0]
    supporting = json.loads(fact["supporting_data"])
    required = {"driver_classification", "order_effect", "aov_effect", "decomposition_error"}
    if not required.issubset(supporting):
        raise ValueError("result diagnosis supporting data is incomplete")
    return {
        "purchase_amount_change": fact["impact_amount"],
        "evidence_level": fact["evidence_level"],
        "quality_flags": fact["quality_flags"],
        **supporting,
    }


def contribution_summary(data: DashboardBData, dimension: str) -> tuple[pd.DataFrame, float]:
    """Aggregate B1 contribution rows for display and independently reconcile them."""
    if dimension == "CUSTOMER":
        frame = data.customers
        statuses = ("RETAINED", "CURRENT_ONLY", "PREVIOUS_ONLY")
    elif dimension == "PRODUCT":
        frame = data.products
        statuses = ("RETAINED_ACTIVE", "CURRENT_ONLY_ACTIVE", "PREVIOUS_ONLY_ACTIVE")
    else:
        raise ValueError(f"unsupported contribution dimension: {dimension}")
    selected = frame[
        frame["previous_month"].eq(data.previous_period) & frame["current_month"].eq(data.current_period)
    ]
    summary = (
        selected.groupby("period_status", observed=True)
        .agg(
            entity_count=("amount_change", "size"),
            previous_amount=("previous_amount", "sum"),
            current_amount=("current_amount", "sum"),
            amount_change=("amount_change", "sum"),
        )
        .reindex(statuses, fill_value=0)
        .reset_index()
    )
    overall_change = float(current_metrics(data)["purchase_amount_change"])
    return summary, float(summary["amount_change"].sum() - overall_change)


def top_contributors(data: DashboardBData, dimension: str, positive: bool, limit: int = 5) -> pd.DataFrame:
    """Return top positive or negative B1 contribution rows for presentation."""
    frame = data.customers if dimension == "CUSTOMER" else data.products
    selected = frame[
        frame["previous_month"].eq(data.previous_period) & frame["current_month"].eq(data.current_period)
    ]
    selected = selected[selected["amount_change"].gt(0) if positive else selected["amount_change"].lt(0)]
    return selected.sort_values("amount_change", ascending=not positive).head(limit).copy()


def activity_detail_summary(data: DashboardBData, activity_type: str) -> dict[str, float | int]:
    """Return ID-level activity counts and loss concentration for one type."""
    selected = data.activity_details[data.activity_details["activity_type"].eq(activity_type)]
    losses = selected[selected["amount_change"].lt(0)].sort_values("amount_change")
    total_loss = float(-losses["amount_change"].sum())
    top5_loss = float(-losses.head(5)["amount_change"].sum())
    return {
        "activity_count": len(selected),
        "negative_count": int(selected["amount_change"].lt(0).sum()),
        "positive_count": int(selected["amount_change"].gt(0).sum()),
        "flat_count": int(selected["amount_change"].eq(0).sum()),
        "top5_loss_concentration": top5_loss / total_loss if total_loss else 0.0,
    }


def activity_top_contributors(
    data: DashboardBData,
    activity_type: str,
    *,
    positive: bool,
    limit: int = 10,
) -> pd.DataFrame:
    """Return the largest ID-level activity losses or growth rows."""
    selected = data.activity_details[data.activity_details["activity_type"].eq(activity_type)]
    selected = selected[selected["amount_change"].gt(0) if positive else selected["amount_change"].lt(0)]
    return selected.sort_values("amount_change", ascending=not positive).head(limit).copy()


def quality_count(data: DashboardBData, rule: str, field: str = "affected_entities") -> int | None:
    """Return an explicit B1 quality count, preserving unavailable values as None."""
    rows = data.quality[data.quality["rule"].eq(rule)]
    if len(rows) != 1 or pd.isna(rows.iloc[0][field]):
        return None
    return int(rows.iloc[0][field])


def _require_fact_columns(facts: pd.DataFrame) -> None:
    required = {
        "current_period", "previous_period", "fact_rank", "is_core_fact", "output_type",
        "diagnosis_dimension", "fact_code", "fact_text", "evidence_level", "impact_amount",
        "impact_ratio", "quality_flags", "supporting_data",
    }
    missing = required.difference(facts.columns)
    if missing:
        raise ValueError(f"facts mart missing columns: {sorted(missing)}")
