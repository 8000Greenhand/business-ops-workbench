"""Generate bounded, factual Dashboard B diagnoses from B1 marts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

EVIDENCE_HIGH = "HIGH"
EVIDENCE_MEDIUM = "MEDIUM"
EVIDENCE_LIMITED = "LIMITED"
OUTPUT_FACT = "FACT"
OUTPUT_LIMITATION = "LIMITATION"
OUTPUT_DO_NOT_INFER = "DO_NOT_INFER"


def load_diagnosis_rules(path: Path) -> dict[str, Any]:
    """Load and validate the bounded B2 diagnosis rules."""
    rules = yaml.safe_load(path.read_text(encoding="utf-8"))
    required = {
        "name", "max_core_facts", "reconciliation_tolerance", "loss_concentration_top_n",
        "result_decomposition", "customer_status_labels", "product_status_labels", "do_not_infer",
    }
    missing = required.difference(rules)
    if missing:
        raise ValueError(f"diagnosis rules missing keys: {sorted(missing)}")
    if rules["result_decomposition"]["method"] != "symmetric_two_factor":
        raise ValueError("unsupported result decomposition method")
    return rules


def load_b1_marts(mart_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load only the three B1 marts required by B2 and validate their schemas."""
    monthly = pd.read_csv(mart_dir / "mart_merchant_monthly_diagnosis.csv", dtype={"month": "string"})
    customers = pd.read_csv(
        mart_dir / "mart_customer_monthly_contribution.csv",
        dtype={"customer_key": "string", "previous_month": "string", "current_month": "string"},
    )
    products = pd.read_csv(
        mart_dir / "mart_product_monthly_contribution.csv",
        dtype={"product_key": "string", "product_code": "string", "previous_month": "string", "current_month": "string"},
    )
    _require_columns(
        monthly,
        {
            "month", "previous_month", "purchase_amount", "order_count", "aov",
            "purchase_amount_change", "purchase_amount_change_rate", "order_count_change",
            "order_count_change_rate", "aov_change", "aov_change_rate", "comparison_quality_status",
        },
        "monthly diagnosis",
    )
    contribution_columns = {
        "previous_month", "current_month", "previous_amount", "current_amount", "amount_change", "period_status"
    }
    _require_columns(customers, contribution_columns | {"customer_key", "customer_name"}, "customer contribution")
    _require_columns(
        products,
        contribution_columns | {"product_key", "product_name", "mapping_quality_status"},
        "product contribution",
    )
    return monthly, customers, products


def decompose_result(previous: pd.Series, current: pd.Series) -> dict[str, float | str]:
    """Exactly decompose purchase amount change into symmetric order and AOV effects."""
    purchase_change = float(current["purchase_amount"] - previous["purchase_amount"])
    order_effect = float(
        (current["order_count"] - previous["order_count"])
        * (previous["aov"] + current["aov"])
        / 2
    )
    aov_effect = float(
        (current["aov"] - previous["aov"])
        * (previous["order_count"] + current["order_count"])
        / 2
    )
    return {
        "purchase_amount_change": purchase_change,
        "order_effect": order_effect,
        "aov_effect": aov_effect,
        "decomposition_error": order_effect + aov_effect - purchase_change,
        "driver_classification": _classify_driver(purchase_change, order_effect, aov_effect),
    }


def build_contribution_summary(
    frame: pd.DataFrame,
    expected_statuses: tuple[str, ...],
    overall_change: float,
    top_n: int,
) -> dict[str, Any]:
    """Build a status bridge, top contributors, concentration, and reconciliation error."""
    unknown = set(frame["period_status"].dropna()) - set(expected_statuses)
    if unknown:
        raise ValueError(f"unknown period statuses: {sorted(unknown)}")
    bridge = (
        frame.groupby("period_status", observed=True)
        .agg(
            entity_count=("amount_change", "size"),
            previous_amount=("previous_amount", "sum"),
            current_amount=("current_amount", "sum"),
            amount_change=("amount_change", "sum"),
        )
        .reindex(expected_statuses, fill_value=0)
        .reset_index()
    )
    losses = frame[frame["amount_change"].lt(0)].sort_values("amount_change")
    growth = frame[frame["amount_change"].gt(0)].sort_values("amount_change", ascending=False)
    total_loss = float(-losses["amount_change"].sum())
    top_loss = float(-losses.head(top_n)["amount_change"].sum())
    return {
        "bridge": bridge,
        "reconciliation_error": float(frame["amount_change"].sum() - overall_change),
        "top_losses": losses.head(top_n),
        "top_growth": growth.head(top_n),
        "total_loss_amount": total_loss,
        "top_loss_amount": top_loss,
        "loss_concentration": top_loss / total_loss if total_loss else pd.NA,
    }


def build_diagnosis_facts(
    monthly: pd.DataFrame,
    customers: pd.DataFrame,
    products: pd.DataFrame,
    rules: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Generate at most five ranked core facts plus explicit guardrail records."""
    verified = monthly[monthly["comparison_quality_status"].eq("VERIFIED")].sort_values("month")
    if verified.empty:
        raise ValueError("no verified adjacent complete period comparison")
    current = verified.iloc[-1]
    previous_rows = monthly[monthly["month"].eq(current["previous_month"])]
    if len(previous_rows) != 1:
        raise ValueError("previous monthly row is missing or duplicated")
    previous = previous_rows.iloc[0]
    previous_period = str(current["previous_month"])
    current_period = str(current["month"])
    customers = customers[
        customers["previous_month"].eq(previous_period) & customers["current_month"].eq(current_period)
    ].copy()
    products = products[
        products["previous_month"].eq(previous_period) & products["current_month"].eq(current_period)
    ].copy()
    if customers.empty or products.empty:
        raise ValueError("contribution mart is missing the selected comparison")

    result = decompose_result(previous, current)
    top_n = int(rules["loss_concentration_top_n"])
    customer = build_contribution_summary(
        customers, ("RETAINED", "CURRENT_ONLY", "PREVIOUS_ONLY"), float(result["purchase_amount_change"]), top_n
    )
    product = build_contribution_summary(
        products,
        ("RETAINED_ACTIVE", "CURRENT_ONLY_ACTIVE", "PREVIOUS_ONLY_ACTIVE"),
        float(result["purchase_amount_change"]),
        top_n,
    )
    tolerance = float(rules["reconciliation_tolerance"])
    customer_error = float(customer["reconciliation_error"])
    product_error = float(product["reconciliation_error"])
    product_has_conflict = products["mapping_quality_status"].eq("CONFLICT").any()
    product_evidence = EVIDENCE_MEDIUM if product_has_conflict else EVIDENCE_HIGH
    product_flags = "PRODUCT_MAPPING_LIMITATION" if product_has_conflict else ""

    facts = [
        _fact(
            previous_period,
            current_period,
            1,
            "RESULT",
            f"RESULT_{result['driver_classification']}",
            _result_text(previous_period, current_period, previous, current, result),
            EVIDENCE_LIMITED,
            float(result["purchase_amount_change"]),
            float(current["purchase_amount_change_rate"]),
            "ORDER_STATUS_SEMANTICS_UNCONFIRMED",
            {
                "driver_classification": result["driver_classification"],
                "order_effect": result["order_effect"],
                "aov_effect": result["aov_effect"],
                "decomposition_error": result["decomposition_error"],
            },
        ),
        _fact(
            previous_period,
            current_period,
            2,
            "CUSTOMER",
            "CUSTOMER_STATUS_BRIDGE",
            _bridge_text(customer["bridge"], rules["customer_status_labels"]),
            EVIDENCE_HIGH if abs(customer_error) <= tolerance else EVIDENCE_LIMITED,
            float(customer["bridge"]["amount_change"].sum()),
            1.0 if abs(customer_error) <= tolerance else pd.NA,
            "" if abs(customer_error) <= tolerance else "CUSTOMER_RECONCILIATION_ERROR",
            {"reconciliation_error": customer_error},
        ),
        _fact(
            previous_period,
            current_period,
            3,
            "CUSTOMER",
            "CUSTOMER_LOSS_CONCENTRATION",
            _concentration_text(customer, "customer_name", "药店"),
            EVIDENCE_HIGH,
            -float(customer["top_loss_amount"]),
            float(customer["loss_concentration"]),
            "",
            _top_details(customer, "customer_key", "customer_name"),
        ),
        _fact(
            previous_period,
            current_period,
            4,
            "PRODUCT",
            "PRODUCT_STATUS_BRIDGE",
            _bridge_text(product["bridge"], rules["product_status_labels"]),
            product_evidence if abs(product_error) <= tolerance else EVIDENCE_LIMITED,
            float(product["bridge"]["amount_change"].sum()),
            1.0 if abs(product_error) <= tolerance else pd.NA,
            product_flags if abs(product_error) <= tolerance else f"{product_flags};PRODUCT_RECONCILIATION_ERROR".strip(";"),
            {"reconciliation_error": product_error},
        ),
        _fact(
            previous_period,
            current_period,
            5,
            "PRODUCT",
            "PRODUCT_LOSS_CONCENTRATION",
            _concentration_text(product, "product_name", "商品"),
            product_evidence,
            -float(product["top_loss_amount"]),
            float(product["loss_concentration"]),
            product_flags,
            _top_details(product, "product_key", "product_name"),
        ),
    ][: int(rules["max_core_facts"])]

    facts.append(
        _guardrail(
            previous_period,
            current_period,
            OUTPUT_LIMITATION,
            "DATA_QUALITY",
            "ORDER_POLICY_AND_PRODUCT_MAPPING_LIMITATION",
            "订单、退款、配送和结算状态的业务语义尚未确认；产品贡献中存在商品映射冲突。当前结论只描述文件内部进货金额及其观察维度。",
            "ORDER_STATUS_SEMANTICS_UNCONFIRMED;PRODUCT_MAPPING_LIMITATION",
        )
    )
    for code, text in rules["do_not_infer"].items():
        facts.append(_guardrail(previous_period, current_period, OUTPUT_DO_NOT_INFER, "GUARDRAIL", code, text, ""))

    diagnostics = {
        "result": result,
        "customer": customer,
        "product": product,
        "previous_period": previous_period,
        "current_period": current_period,
    }
    return pd.DataFrame(facts), diagnostics


def _fact(
    previous_period: str,
    current_period: str,
    rank: int,
    dimension: str,
    code: str,
    text: str,
    evidence: str,
    impact_amount: float,
    impact_ratio: float | object,
    flags: str,
    supporting: dict[str, Any],
) -> dict[str, object]:
    return {
        "current_period": current_period,
        "previous_period": previous_period,
        "fact_rank": rank,
        "is_core_fact": True,
        "output_type": OUTPUT_FACT,
        "diagnosis_dimension": dimension,
        "fact_code": code,
        "fact_text": text,
        "evidence_level": evidence,
        "impact_amount": impact_amount,
        "impact_ratio": impact_ratio,
        "quality_flags": flags,
        "supporting_data": json.dumps(supporting, ensure_ascii=False, default=_json_default),
    }


def _guardrail(
    previous_period: str,
    current_period: str,
    output_type: str,
    dimension: str,
    code: str,
    text: str,
    flags: str,
) -> dict[str, object]:
    return {
        "current_period": current_period,
        "previous_period": previous_period,
        "fact_rank": pd.NA,
        "is_core_fact": False,
        "output_type": output_type,
        "diagnosis_dimension": dimension,
        "fact_code": code,
        "fact_text": text,
        "evidence_level": EVIDENCE_LIMITED,
        "impact_amount": pd.NA,
        "impact_ratio": pd.NA,
        "quality_flags": flags,
        "supporting_data": "{}",
    }


def _result_text(
    previous_period: str,
    current_period: str,
    previous: pd.Series,
    current: pd.Series,
    result: dict[str, float | str],
) -> str:
    direction = "下降" if result["purchase_amount_change"] < 0 else "增长"
    return (
        f"{current_period} 进货金额较 {previous_period} {direction} {_wan(abs(float(result['purchase_amount_change'])))}"
        f"（{float(current['purchase_amount_change_rate']):+.1%}）。同期订单数变化 "
        f"{float(current['order_count_change_rate']):+.1%}，AOV 变化 {float(current['aov_change_rate']):+.1%}；"
        f"对称两因素分解的订单效应为 {_signed_wan(float(result['order_effect']))}，"
        f"AOV 效应为 {_signed_wan(float(result['aov_effect']))}，"
        f"结果层判断为 {result['driver_classification']}。"
    )


def _bridge_text(bridge: pd.DataFrame, labels: dict[str, str]) -> str:
    parts = []
    for row in bridge.itertuples(index=False):
        parts.append(f"{labels[row.period_status]} {row.entity_count:,} 个，贡献 {_signed_wan(float(row.amount_change))}")
    total = float(bridge["amount_change"].sum())
    return "；".join(parts) + f"；该维度合计 {_signed_wan(total)}。"


def _concentration_text(summary: dict[str, Any], label_column: str, entity_label: str) -> str:
    losses = summary["top_losses"]
    growth = summary["top_growth"]
    largest_loss = losses.iloc[0]
    largest_growth = growth.iloc[0]
    return (
        f"Top {len(losses)} {entity_label}负向变化合计 {_signed_wan(-float(summary['top_loss_amount']))}，"
        f"占全部{entity_label}负向变化 {float(summary['loss_concentration']):.1%}。"
        f"最大负向变化为{largest_loss[label_column]} {_signed_wan(float(largest_loss['amount_change']))}；"
        f"最大正向变化为{largest_growth[label_column]} {_signed_wan(float(largest_growth['amount_change']))}。"
    )


def _top_details(summary: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    def records(frame: pd.DataFrame) -> list[dict[str, object]]:
        columns = [key, label, "amount_change", "period_status"]
        if "mapping_quality_status" in frame.columns:
            columns.append("mapping_quality_status")
        return frame[columns].to_dict("records")

    return {
        "top_losses": records(summary["top_losses"]),
        "top_growth": records(summary["top_growth"]),
        "total_loss_amount": summary["total_loss_amount"],
        "top_loss_amount": summary["top_loss_amount"],
    }


def _classify_driver(total: float, order_effect: float, aov_effect: float, tolerance: float = 0.01) -> str:
    if abs(total) <= tolerance:
        return "MIXED"
    total_sign = 1 if total > 0 else -1
    order_aligned = order_effect * total_sign > tolerance
    aov_aligned = aov_effect * total_sign > tolerance
    if order_aligned and not aov_aligned:
        return "ORDER_DRIVEN"
    if aov_aligned and not order_aligned:
        return "AOV_DRIVEN"
    return "MIXED"


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")


def _wan(value: float) -> str:
    return f"{value / 10_000:.2f} 万"


def _signed_wan(value: float) -> str:
    return f"{value / 10_000:+.2f} 万"


def _json_default(value: object) -> object:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")

