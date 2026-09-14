"""Presentation data helpers for the YSB Dashboard A Streamlit page."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


QUALITY_ALERT = "DATA_QUALITY_ALERT"

# This is presentation metadata for the persisted Dashboard A mart.  It does
# not change the underlying monthly values or any M2A/M2B rule.
PERIOD_QUALITY: dict[str, str] = {
    "2026-03": "LIKELY_COMPLETE",
    "2026-04": "LIKELY_COMPLETE",
    "2026-05": "HISTORICAL_SNAPSHOT / PARTIAL_PERIOD",
    "2026-06": "PARTIAL_PERIOD",
}
RELIABLE_COMPARISON_QUALITIES = {"COMPLETE", "LIKELY_COMPLETE"}


def load_priority_mart(path: Path) -> pd.DataFrame:
    """Load the persisted priority mart without recalculating business rules."""
    frame = pd.read_csv(path)
    frame["month"] = frame["month"].astype(str)
    return frame


def latest_complete_period(frame: pd.DataFrame) -> str:
    """Return the latest reliable period with usable current and prior GMV."""
    for period in sorted(frame["month"].dropna().unique(), reverse=True):
        if period_quality_status(str(period)) not in RELIABLE_COMPARISON_QUALITIES:
            continue
        part = frame[frame["month"] == period]
        usable = part["current_gmv"].notna() & part["previous_gmv"].notna() & (part["merchant_mapping_status"] != "UNRESOLVED")
        if int(usable.sum()) > 0:
            return str(period)
    raise ValueError("No reliable business period exists in the YSB priority mart")


def period_quality_status(period: str) -> str:
    """Return the persisted-review quality status for a Dashboard A period."""
    return PERIOD_QUALITY.get(str(period), "UNRESOLVED")


def is_standard_comparison_period(period: str) -> bool:
    """Return whether a period may be presented as a standard full-month comparison."""
    return period_quality_status(period) in RELIABLE_COMPARISON_QUALITIES


def period_quality_label(period: str) -> str:
    """Return a business-friendly period label without exposing technical codes."""
    status = period_quality_status(period)
    if status in RELIABLE_COMPARISON_QUALITIES:
        return "完整周期候选"
    if "HISTORICAL_SNAPSHOT" in status:
        return "历史快照"
    if status == "PARTIAL_PERIOD":
        return "部分周期"
    return "待确认"


def filter_dashboard(
    frame: pd.DataFrame,
    period: str,
    *,
    owners: list[str] | None = None,
    scales: list[str] | None = None,
    priority_levels: list[str] | None = None,
) -> pd.DataFrame:
    """Apply only UI filters; priority and anomaly fields remain mart outputs."""
    result = frame[frame["month"] == period].copy()
    if owners:
        result = result[result["owner"].fillna("").isin(owners)]
    if scales:
        result = result[result["merchant_scale"].isin(scales)]
    if priority_levels:
        result = result[result["priority_level"].isin(priority_levels)]
    return result


def business_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Exclude data-quality-only rows from business ranking and loss analysis."""
    return frame[(frame["priority_level"] != QUALITY_ALERT) & frame["current_gmv"].notna() & frame["previous_gmv"].notna()].copy()


def quality_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Return isolated data-quality rows for the quality section."""
    return frame[(frame["priority_level"] == QUALITY_ALERT) | (frame["data_quality_status"] == QUALITY_ALERT)].copy()


def overview_metrics(frame: pd.DataFrame) -> dict[str, object]:
    """Calculate display-only overview aggregates from the selected comparable cohort."""
    comparable = business_rows(frame)
    current = comparable["current_gmv"].sum(min_count=1)
    previous = comparable["previous_gmv"].sum(min_count=1)
    mom = current / previous - 1 if pd.notna(previous) and previous != 0 else pd.NA
    return {
        "region_gmv": current,
        "region_gmv_previous": previous,
        "gmv_mom": mom,
        "declining_merchants": int((comparable["gmv_change_abs"] < 0).sum()),
        "growth_merchants": int((comparable["gmv_change_abs"] > 0).sum()),
        "priority_merchants": int((frame["priority_level"] == "PRIORITY").sum()),
        "attention_merchants": int((frame["priority_level"] == "ATTENTION").sum()),
        "watchlist_merchants": int((frame["priority_level"] == "WATCHLIST").sum()),
        "service_alerts": int(frame["diagnostic_dimensions"].fillna("").str.contains("Service", regex=False).sum()),
        "comparable_merchants": len(comparable),
    }


def top_loss(frame: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Return top negative GMV changes, excluding data-quality rows."""
    return business_rows(frame).query("gmv_loss > 0").sort_values("gmv_loss", ascending=False).head(n)


def top_growth(frame: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Return top positive GMV changes, excluding data-quality rows."""
    return business_rows(frame).query("gmv_change_abs > 0").sort_values("gmv_change_abs", ascending=False).head(n)


def merchant_trend(frame: pd.DataFrame, merchant_key: str, periods: int = 12) -> pd.DataFrame:
    """Return a merchant's recent trend with NULL gaps preserved."""
    result = frame[frame["merchant_key"] == merchant_key].sort_values("month").tail(periods).copy()
    return result[["month", "current_gmv", "gmv_mom", "gmv_rank_current", "aftersales_rate", "metric_quality_status", "data_quality_status"]].rename(columns={"current_gmv": "gmv"})


def format_rank_change(value: object) -> str:
    """Render rank movement with an explicit direction; positive means worse rank."""
    if value is None or pd.isna(value):
        return "NULL"
    change = int(value)
    if change > 0:
        return f"↓{change}名"
    if change < 0:
        return f"↑{abs(change)}名"
    return "持平"


def summarize_attention_reasons(value: object, limit: int = 3) -> str:
    """Render at most the key presentation reasons without changing mart reason codes."""
    if value is None or pd.isna(value) or not str(value):
        return ""
    reasons = [part.strip() for part in str(value).split("；") if part.strip()]
    translated = []
    for reason in reasons[:limit]:
        text = (
            re.sub(r"^Trend:\s*", "GMV趋势：", reason)
            .replace("Scale / Impact: ", "区域影响：")
            .replace("Relative Position: ", "相对位置：")
            .replace("Order: ", "订单：")
            .replace("Service: ", "服务风险：")
        )
        text = re.sub(
            r"排名变化(-?\d+)",
            lambda match: (
                f"排名下降{int(match.group(1))}名"
                if int(match.group(1)) > 0
                else f"排名上升{abs(int(match.group(1)))}名"
                if int(match.group(1)) < 0
                else "排名持平"
            ),
            text,
        )
        translated.append(text)
    return "｜".join(translated)
