"""YSB regional merchant metrics over the validated monthly staging dataset."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

QUALITY_VALID = "VALID"
QUALITY_MISSING = "MISSING"
QUALITY_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
QUALITY_UNRESOLVED_MERCHANT = "UNRESOLVED_MERCHANT"
QUALITY_UNAVAILABLE_FOR_PERIOD = "UNAVAILABLE_FOR_PERIOD"


def load_ysb_staging(path: Path) -> pd.DataFrame:
    """Load the persisted YSB monthly staging dataset and validate its grain."""
    frame = pd.read_csv(path, dtype={"month": "string", "merchant_key": "string"})
    required = {"month", "merchant_key", "merchant_name_raw", "mapping_status", "coverage_status"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"YSB staging missing columns: {sorted(missing)}")
    if frame[["month", "merchant_key"]].duplicated().any():
        raise ValueError("YSB staging grain is not unique: month + merchant_key")
    frame["month"] = pd.PeriodIndex(frame["month"], freq="M")
    return frame.sort_values(["month", "merchant_key"]).reset_index(drop=True)


def build_merchant_monthly_health(frame: pd.DataFrame) -> pd.DataFrame:
    """Build transparent M2A health metrics and quality gates from staging rows."""
    result = frame.copy()
    if not isinstance(result["month"].dtype, pd.PeriodDtype):
        result["month"] = pd.PeriodIndex(result["month"], freq="M")
    result["merchant_name"] = result["merchant_name_raw"]
    result["merchant_mapping_status"] = result["mapping_status"]
    result["metric_quality_status"] = QUALITY_VALID

    for metric in ("gmv", "cash_sales_amount", "order_count", "aftersales_order_count", "aftersales_rate"):
        status_column = f"{metric}_quality_status"
        result[status_column] = result.apply(lambda row: _base_quality(row, metric), axis=1)
        result["metric_quality_status"] = result.apply(
            lambda row: _worst_quality(row["metric_quality_status"], row[status_column]), axis=1
        )

    result["gmv_percentile"] = _monthly_percentile(result, "gmv")
    result["gmv_rank"] = _monthly_rank(result, "gmv")
    result["cash_sales_rank"] = _monthly_rank(result, "cash_sales_amount")
    result["gmv_mom"] = _period_change(result, "gmv")
    result["cash_sales_mom"] = _period_change(result, "cash_sales_amount")
    result["order_count_mom"] = _period_change(result, "order_count")
    result["aftersales_rate_mom"] = _period_change(result, "aftersales_rate")
    for metric, base_metric in (("gmv_mom", "gmv"), ("cash_sales_mom", "cash_sales_amount"), ("order_count_mom", "order_count"), ("aftersales_rate_mom", "aftersales_rate")):
        result[f"{metric}_quality_status"] = _change_quality(result, base_metric)

    result["gmv_rank_change"] = _period_delta(result, "gmv_rank")
    result["consecutive_gmv_decline"] = _consecutive_declines(result)
    result["business_attention_status"] = "NO_ALERT"
    result["attention_reasons"] = ""
    result["severity"] = "NONE"
    return result


def _base_quality(row: pd.Series, metric: str) -> str:
    if row.get("mapping_status") == "UNRESOLVED":
        return QUALITY_UNRESOLVED_MERCHANT
    if metric not in row or pd.isna(row[metric]):
        return QUALITY_MISSING
    return QUALITY_VALID


def _worst_quality(left: str, right: str) -> str:
    order = {
        QUALITY_VALID: 0,
        QUALITY_INSUFFICIENT_HISTORY: 1,
        QUALITY_UNAVAILABLE_FOR_PERIOD: 2,
        QUALITY_MISSING: 3,
        QUALITY_UNRESOLVED_MERCHANT: 4,
    }
    return left if order[left] >= order[right] else right


def _monthly_rank(frame: pd.DataFrame, metric: str) -> pd.Series:
    return frame.groupby("month", observed=True)[metric].rank(method="min", ascending=False, na_option="keep").astype("Int64")


def _monthly_percentile(frame: pd.DataFrame, metric: str) -> pd.Series:
    return frame.groupby("month", observed=True)[metric].rank(method="average", ascending=True, pct=True)


def _period_change(frame: pd.DataFrame, metric: str) -> pd.Series:
    previous = frame.set_index(["merchant_key", "month"])[metric]
    values = []
    for row in frame.itertuples(index=False):
        current = getattr(row, metric)
        prior = previous.get((row.merchant_key, row.month - 1), pd.NA)
        if row.mapping_status == "UNRESOLVED":
            values.append(pd.NA)
        elif pd.isna(current) or pd.isna(prior) or prior == 0:
            values.append(pd.NA)
        else:
            values.append(current / prior - 1)
    return pd.Series(values, index=frame.index, dtype="Float64")


def _period_delta(frame: pd.DataFrame, metric: str) -> pd.Series:
    previous = frame.set_index(["merchant_key", "month"])[metric]
    values = []
    for row in frame.itertuples(index=False):
        current = getattr(row, metric)
        prior = previous.get((row.merchant_key, row.month - 1), pd.NA)
        values.append(pd.NA if pd.isna(current) or pd.isna(prior) else current - prior)
    return pd.Series(values, index=frame.index, dtype="Float64")


def _change_quality(frame: pd.DataFrame, metric: str) -> pd.Series:
    values = []
    for row in frame.itertuples(index=False):
        if row.mapping_status == "UNRESOLVED":
            values.append(QUALITY_UNRESOLVED_MERCHANT)
        elif pd.isna(getattr(row, metric)):
            values.append(QUALITY_MISSING)
        else:
            previous = frame[(frame["merchant_key"] == row.merchant_key) & (frame["month"] == row.month - 1)][metric]
            values.append(QUALITY_VALID if not previous.empty and pd.notna(previous.iloc[0]) else QUALITY_INSUFFICIENT_HISTORY)
    return pd.Series(values, index=frame.index, dtype="string")


def _consecutive_declines(frame: pd.DataFrame) -> pd.Series:
    values = []
    for row in frame.itertuples(index=False):
        history = frame[(frame["merchant_key"] == row.merchant_key) & (frame["month"] <= row.month)].sort_values("month")["gmv"]
        run = 0
        for current, prior in zip(history.iloc[1:], history.iloc[:-1]):
            run = run + 1 if pd.notna(current) and pd.notna(prior) and current < prior else 0
        values.append(run)
    return pd.Series(values, index=frame.index, dtype="Int64")


def iter_quality_statuses() -> Iterable[str]:
    """Return the public M2A quality status vocabulary."""
    return (QUALITY_VALID, QUALITY_MISSING, QUALITY_INSUFFICIENT_HISTORY, QUALITY_UNRESOLVED_MERCHANT, QUALITY_UNAVAILABLE_FOR_PERIOD)
