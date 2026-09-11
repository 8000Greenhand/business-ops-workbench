"""Explainable M2B prioritization over the M2A merchant health mart."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


WATCHLIST = "WATCHLIST"
ATTENTION = "ATTENTION"
PRIORITY = "PRIORITY"
BUSINESS_ALERT = "BUSINESS_ALERT"
DATA_QUALITY = "DATA_QUALITY_ALERT"
NO_PRIORITY = "NO_PRIORITY"


def build_priority_mart(health: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """Add impact, scale, independent dimensions, and priority levels to M2A health."""
    result = health.copy()
    result["month"] = pd.PeriodIndex(result["month"], freq="M")
    result = _add_previous_values(result)
    result = _add_impact_and_scale(result)
    thresholds = derive_priority_thresholds(result)
    result = _add_dimensions(result, thresholds)
    result = _assign_priority(result)
    return result, thresholds


def derive_priority_thresholds(frame: pd.DataFrame) -> dict[str, float]:
    """Derive priority cutoffs from the valid historical merchant-month distribution."""
    valid = frame[frame["mapping_status"] != "UNRESOLVED"]
    return {
        "severe_gmv_mom": _negative_quantile(valid["gmv_mom"], 0.10, -0.20),
        "severe_order_mom": _negative_quantile(valid["order_count_mom"], 0.10, -0.20),
        "high_loss": _positive_quantile(valid["gmv_loss"], 0.75, 0.0),
        "important_share": _positive_quantile(valid["previous_gmv_share"], 0.75, 0.0),
        "rank_drop": _positive_quantile(valid["gmv_rank_change"], 0.90, 10.0),
        "high_aftersales": _quantile(valid["aftersales_rate"], 0.90, 0.0),
        "aftersales_worsening": _positive_quantile(valid["aftersales_rate_mom"], 0.90, 0.20),
        "low_percentile": 0.20,
        "order_rise_divergence": _positive_quantile(valid["order_count_mom"], 0.75, 0.10),
    }


def _add_previous_values(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    prior = result[["merchant_key", "month", "gmv", "gmv_rank", "order_count"]].copy()
    prior["month"] = prior["month"] + 1
    prior = prior.rename(columns={"gmv": "previous_gmv", "gmv_rank": "rank_previous", "order_count": "previous_order_count"})
    result = result.merge(prior, on=["merchant_key", "month"], how="left", suffixes=("", "_prior_join"))
    result["current_gmv"] = result["gmv"]
    result["gmv_change_abs"] = result["current_gmv"] - result["previous_gmv"]
    result["gmv_loss"] = result["previous_gmv"] - result["current_gmv"]
    result.loc[result["gmv_change_abs"] >= 0, "gmv_loss"] = 0.0
    result.loc[result["gmv_change_abs"].isna(), "gmv_loss"] = pd.NA
    result["order_change"] = result["order_count_mom"]
    result["gmv_rank_current"] = result["gmv_rank"]
    result["gmv_rank_change"] = result["gmv_rank_current"] - result["rank_previous"]
    return result


def _add_impact_and_scale(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    valid = result["previous_gmv"].notna() & (result["mapping_status"] != "UNRESOLVED")
    totals = result.loc[valid].groupby("month", observed=True)["previous_gmv"].sum().rename("regional_previous_gmv")
    current_totals = result.loc[result["current_gmv"].notna() & valid].groupby("month", observed=True)["current_gmv"].sum().rename("regional_current_gmv")
    result = result.join(totals, on="month").join(current_totals, on="month")
    result["regional_gmv_change_abs"] = result["regional_current_gmv"] - result["regional_previous_gmv"]
    result["regional_gmv_loss"] = -result["regional_gmv_change_abs"]
    result.loc[result["regional_gmv_loss"] <= 0, "regional_gmv_loss"] = pd.NA
    result["regional_gmv_loss_contribution"] = result["gmv_loss"] / result["regional_gmv_loss"]
    result["previous_gmv_share"] = result["previous_gmv"] / result["regional_previous_gmv"]

    def scale(row: pd.Series) -> str:
        values = result.loc[(result["month"] == row["month"]) & result["previous_gmv"].notna() & (result["mapping_status"] != "UNRESOLVED"), "previous_gmv"]
        if pd.isna(row["previous_gmv"]) or len(values) < 4:
            return "UNAVAILABLE"
        q25, q75 = values.quantile(0.25), values.quantile(0.75)
        if row["previous_gmv"] >= q75: return "KEY"
        if row["previous_gmv"] >= q25: return "MID"
        return "LONG_TAIL"

    result["merchant_scale"] = result.apply(scale, axis=1)
    return result


def _add_dimensions(frame: pd.DataFrame, thresholds: Mapping[str, float]) -> pd.DataFrame:
    result = frame.copy()
    dimensions = []
    reasons = []
    for _, row in result.iterrows():
        dims: list[str] = []
        texts: list[str] = []
        if row["mapping_status"] == "UNRESOLVED":
            dimensions.append(""); reasons.append(""); continue
        trend = (pd.notna(row["gmv_mom"]) and row["gmv_mom"] <= thresholds["severe_gmv_mom"] and row["gmv_mom"] < 0) or row["consecutive_gmv_decline"] >= 3
        if trend:
            dims.append("Trend")
            text = f"GMV环比{row['gmv_mom']:.1%}" if pd.notna(row["gmv_mom"]) else "GMV连续下降"
            if row["consecutive_gmv_decline"] >= 3: text += f"，连续下降{int(row['consecutive_gmv_decline'])}个月"
            texts.append(f"Trend: {text}")
        impact = (pd.notna(row["gmv_loss"]) and row["gmv_loss"] >= thresholds["high_loss"]) or (pd.notna(row["previous_gmv_share"]) and row["previous_gmv_share"] >= thresholds["important_share"])
        if impact:
            dims.append("Scale / Impact")
            texts.append(f"Scale / Impact: GMV损失{row['gmv_loss']:.2f}，上月区域占比{row['previous_gmv_share']:.1%}")
        relative = (pd.notna(row["gmv_rank_change"]) and row["gmv_rank_change"] >= thresholds["rank_drop"]) or (pd.notna(row["gmv_percentile"]) and row["gmv_percentile"] <= thresholds["low_percentile"])
        if relative:
            dims.append("Relative Position")
            texts.append(f"Relative Position: 排名变化{int(row['gmv_rank_change']) if pd.notna(row['gmv_rank_change']) else 'NA'}，同月分位{row['gmv_percentile']:.1%}" )
        order_signal = (pd.notna(row["order_count_mom"]) and row["order_count_mom"] <= thresholds["severe_order_mom"] and row["order_count_mom"] < 0) or (pd.notna(row["gmv_mom"]) and pd.notna(row["order_count_mom"]) and row["gmv_mom"] <= thresholds["severe_gmv_mom"] and row["order_count_mom"] >= thresholds["order_rise_divergence"])
        if order_signal:
            dims.append("Order")
            texts.append(f"Order: 订单环比{row['order_count_mom']:.1%}" if pd.notna(row["order_count_mom"]) else "Order: 订单信号")
        service = (pd.notna(row["aftersales_rate"]) and row["aftersales_rate"] >= thresholds["high_aftersales"]) or (pd.notna(row["aftersales_rate_mom"]) and row["aftersales_rate_mom"] >= thresholds["aftersales_worsening"])
        if service:
            dims.append("Service")
            texts.append(f"Service: 售后率{row['aftersales_rate']:.1%}，环比变化{row['aftersales_rate_mom']:.1%}" if pd.notna(row["aftersales_rate_mom"]) else f"Service: 售后率{row['aftersales_rate']:.1%}")
        dimensions.append("|".join(dims)); reasons.append("；".join(texts))
    result["diagnostic_dimensions"] = dimensions
    result["attention_reasons"] = reasons
    result["diagnostic_dimension_count"] = result["diagnostic_dimensions"].str.count(r"\|") + result["diagnostic_dimensions"].ne("").astype(int)
    return result


def _assign_priority(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    levels = []
    statuses = []
    for _, row in result.iterrows():
        if row["mapping_status"] == "UNRESOLVED":
            levels.append(DATA_QUALITY); statuses.append(DATA_QUALITY); continue
        if pd.isna(row["gmv"]):
            levels.append(DATA_QUALITY); statuses.append(DATA_QUALITY); continue
        dims = set(filter(None, str(row["diagnostic_dimensions"]).split("|")))
        if not dims:
            levels.append(NO_PRIORITY); statuses.append(NO_PRIORITY); continue
        trend = "Trend" in dims
        impact = "Scale / Impact" in dims
        service = "Service" in dims
        p1 = trend and (impact or service or row["consecutive_gmv_decline"] >= 3)
        if p1:
            levels.append(PRIORITY)
        elif len(dims) >= 2:
            levels.append(ATTENTION)
        else:
            levels.append(WATCHLIST)
        statuses.append(BUSINESS_ALERT)
    result["priority_level"] = levels
    result["attention_pool"] = statuses
    result["priority_sort_loss"] = result["gmv_loss"].fillna(0)
    result["priority_sort_share"] = result["previous_gmv_share"].fillna(0)
    return result


def _quantile(series: pd.Series, q: float, fallback: float) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.quantile(q)) if len(values) >= 4 else fallback


def _positive_quantile(series: pd.Series, q: float, fallback: float) -> float:
    values = pd.to_numeric(series, errors="coerce")
    return _quantile(values[values > 0], q, fallback)


def _negative_quantile(series: pd.Series, q: float, fallback: float) -> float:
    values = pd.to_numeric(series, errors="coerce")
    return _quantile(values[values < 0], q, fallback)
