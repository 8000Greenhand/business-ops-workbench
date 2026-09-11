"""Transparent M2A health rules for regional YSB merchant monitoring."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ops_workbench.metrics.ysb_regional import (
    QUALITY_INSUFFICIENT_HISTORY,
    QUALITY_MISSING,
    QUALITY_UNRESOLVED_MERCHANT,
    QUALITY_VALID,
    build_merchant_monthly_health,
    load_ysb_staging,
)


BUSINESS_ALERT = "BUSINESS_ALERT"
DATA_QUALITY_ALERT = "DATA_QUALITY_ALERT"
NO_ALERT = "NO_ALERT"


def build_ysb_health(path: Path) -> tuple[pd.DataFrame, dict[str, float]]:
    """Build M2A health mart and empirically derived rule thresholds."""
    health = build_merchant_monthly_health(load_ysb_staging(path))
    thresholds = derive_thresholds(health)
    return apply_attention_rules(health, thresholds), thresholds


def derive_thresholds(frame: pd.DataFrame) -> dict[str, float]:
    """Derive transparent thresholds from valid historical merchant-month observations."""
    return {
        "gmv_decline": _quantile_of_negative(frame["gmv_mom"], 0.10, fallback=-0.20),
        "cash_decline": _quantile_of_negative(frame["cash_sales_mom"], 0.10, fallback=-0.20),
        "order_decline": _quantile_of_negative(frame["order_count_mom"], 0.10, fallback=-0.20),
        "rank_drop": _quantile_of_positive(frame["gmv_rank_change"], 0.90, fallback=10.0),
        "aftersales_high": _quantile(frame["aftersales_rate"], 0.90, fallback=0.0),
        "aftersales_worsening": _quantile_of_positive(frame["aftersales_rate_mom"], 0.90, fallback=0.20),
        "low_gmv_percentile": 0.20,
        "order_rise_for_divergence": _quantile_of_positive(frame["order_count_mom"], 0.75, fallback=0.10),
    }


def apply_attention_rules(frame: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    """Apply explainable rule signals without converting data-quality gaps to business alerts."""
    result = frame.copy()
    result["attention_reasons"] = ""
    result["attention_reason_types"] = ""
    result["data_quality_status"] = NO_ALERT
    result["data_quality_reasons"] = ""
    result["business_attention_status"] = NO_ALERT
    result["severity"] = "NONE"
    result["priority_score"] = 0
    latest = result["month"].max()
    for idx, row in result.iterrows():
        business: list[str] = []
        quality: list[str] = []
        if row["mapping_status"] == "UNRESOLVED":
            quality.append("UNRESOLVED_MERCHANT")
        else:
            if _at_or_below(row["gmv_mom"], thresholds["gmv_decline"]) and row["gmv_mom"] < 0:
                business.append(f"GMV环比明显下降({row['gmv_mom']:.1%})")
            if _at_or_above(row["gmv_rank_change"], thresholds["rank_drop"]):
                business.append(f"GMV排名恶化({int(row['gmv_rank_change'])}名)")
            if pd.notna(row["gmv_percentile"]) and row["gmv_percentile"] <= thresholds["low_gmv_percentile"]:
                business.append("GMV处于同月区域低分位")
            if _at_or_above(row["aftersales_rate"], thresholds["aftersales_high"]):
                business.append("售后率处于同月区域高位")
            if _at_or_above(row["aftersales_rate_mom"], thresholds["aftersales_worsening"]):
                business.append(f"售后率明显恶化({row['aftersales_rate_mom']:.1%})")
            if _at_or_below(row["order_count_mom"], thresholds["order_decline"]) and row["order_count_mom"] < 0:
                business.append(f"订单数明显下降({row['order_count_mom']:.1%})")
            if _at_or_below(row["gmv_mom"], thresholds["gmv_decline"]) and _at_or_above(row["order_count_mom"], thresholds["order_rise_for_divergence"]):
                business.append("GMV下降与订单数上升方向背离")
            if row["consecutive_gmv_decline"] >= 3:
                business.append(f"GMV连续下降{int(row['consecutive_gmv_decline'])}个月")
            if row["month"] == latest and pd.isna(row["gmv"]):
                quality.append("近期GMV缺失")
            if row["month"] == latest and pd.isna(row["cash_sales_amount"]):
                quality.append("近期现金额缺失")
        reasons = business + quality
        result.at[idx, "attention_reasons"] = "；".join(reasons)
        result.at[idx, "attention_reason_types"] = "|".join(filter(None, ("BUSINESS_ALERT" if business else "", "DATA_QUALITY_ALERT" if quality else "")))
        result.at[idx, "data_quality_status"] = DATA_QUALITY_ALERT if quality else NO_ALERT
        result.at[idx, "data_quality_reasons"] = "；".join(quality)
        result.at[idx, "business_attention_status"] = BUSINESS_ALERT if business else (DATA_QUALITY_ALERT if quality else NO_ALERT)
        result.at[idx, "priority_score"] = len(business)
        if len(business) >= 3: result.at[idx, "severity"] = "HIGH"
        elif len(business) >= 1: result.at[idx, "severity"] = "MEDIUM"
        elif quality: result.at[idx, "severity"] = "DATA_QUALITY"
    return result


def _quantile(series: pd.Series, q: float, fallback: float) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.quantile(q)) if len(values) >= 3 else fallback


def _quantile_of_negative(series: pd.Series, q: float, fallback: float) -> float:
    values = pd.to_numeric(series, errors="coerce")
    values = values[(values < 0) & values.notna()]
    return float(values.quantile(q)) if len(values) >= 3 else fallback


def _quantile_of_positive(series: pd.Series, q: float, fallback: float) -> float:
    values = pd.to_numeric(series, errors="coerce")
    values = values[(values > 0) & values.notna()]
    return float(values.quantile(q)) if len(values) >= 3 else fallback


def _at_or_below(value: object, threshold: float) -> bool:
    return pd.notna(value) and float(value) <= threshold


def _at_or_above(value: object, threshold: float) -> bool:
    return pd.notna(value) and float(value) >= threshold
