"""Data assembly and presentation helpers for the city supply dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math

import pandas as pd

from ops_workbench.diagnostics.city_supply import (
    CitySupplyPolicy,
    GrossMarginBand,
    SupplyDiagnosis,
    classify_gross_margin,
    diagnose_supply,
    load_city_supply_policy,
)
from ops_workbench.metrics.city_supply import aggregate_city_supply_metrics
from ops_workbench.simulation.city_supply import generate_city_supply_facts


TIME_BUCKET_LABELS = {
    "morning_peak": "早高峰",
    "daytime_offpeak": "日间平峰",
    "evening_peak": "晚高峰",
    "night": "夜间",
}
COMPARISON_METRICS = (
    "gmv",
    "completion_rate",
    "gross_margin",
    "online_hours",
    "completed_orders",
    "gmv_per_online_hour",
    "orders_per_online_hour",
    "subsidy_rate",
    "demand_orders",
)
ANOMALY_COLUMNS = (
    "优先级",
    "城市",
    "区域/时段",
    "问题",
    "关键证据",
    "经营判断",
    "建议动作",
)


@dataclass(frozen=True, slots=True)
class PeriodWindow:
    """Current period and its immediately preceding equal-length baseline."""

    current_start: date
    current_end: date
    baseline_start: date
    baseline_end: date

    @property
    def days(self) -> int:
        return (self.current_end - self.current_start).days + 1


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """Current and baseline values with ratio and percentage-point changes."""

    current: float | None
    baseline: float | None
    relative_change: float | None
    point_change: float | None


@dataclass(frozen=True, slots=True)
class CitySupplyDashboardData:
    """All period-aware outputs required by the single-page dashboard."""

    periods: PeriodWindow
    city: str | None
    time_bucket: str | None
    overview: dict[str, MetricComparison]
    city_comparison: pd.DataFrame
    daily_trend: pd.DataFrame
    supply_diagnosis: pd.DataFrame
    efficiency_comparison: pd.DataFrame
    anomalies: pd.DataFrame
    margin_band: GrossMarginBand
    policy: CitySupplyPolicy


def load_city_supply_facts() -> pd.DataFrame:
    """Load the deterministic V0.1 simulation used by the demonstration page."""
    return generate_city_supply_facts()


def default_period(facts: pd.DataFrame, *, days: int = 30) -> tuple[date, date]:
    """Return the latest complete fixed-length period in the available simulation."""
    if facts.empty or days <= 0:
        raise ValueError("City supply facts and a positive period length are required")
    end = pd.Timestamp(facts["date"].max()).date()
    start = end - timedelta(days=days - 1)
    return start, end


def resolve_periods(
    facts: pd.DataFrame,
    current_start: date,
    current_end: date,
) -> PeriodWindow:
    """Resolve the immediately preceding period with exactly the same day count."""
    if current_start > current_end:
        raise ValueError("当前周期起始日不能晚于结束日")
    days = (current_end - current_start).days + 1
    baseline_end = current_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=days - 1)
    minimum = pd.Timestamp(facts["date"].min()).date()
    maximum = pd.Timestamp(facts["date"].max()).date()
    if current_end > maximum or current_start < minimum:
        raise ValueError("当前周期超出模拟数据覆盖范围")
    if baseline_start < minimum:
        raise ValueError("当前选择没有足够的上一等长周期数据")
    return PeriodWindow(
        current_start=current_start,
        current_end=current_end,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
    )


def build_city_supply_dashboard(
    facts: pd.DataFrame,
    *,
    current_start: date,
    current_end: date,
    city: str | None = None,
    time_bucket: str | None = None,
    policy: CitySupplyPolicy | None = None,
) -> CitySupplyDashboardData:
    """Build weighted comparisons, diagnostics and action-oriented anomalies."""
    periods = resolve_periods(facts, current_start, current_end)
    active_policy = policy or load_city_supply_policy()
    current = _filter_facts(
        facts,
        periods.current_start,
        periods.current_end,
        city=city,
        time_bucket=time_bucket,
    )
    baseline = _filter_facts(
        facts,
        periods.baseline_start,
        periods.baseline_end,
        city=city,
        time_bucket=time_bucket,
    )
    if current.empty or baseline.empty:
        raise ValueError("当前筛选条件下没有完整的本期与上期数据")

    overview = _overview(current, baseline)
    city_comparison = _comparison_frame(current, baseline, ("city",))
    supply = _comparison_frame(
        current,
        baseline,
        ("city", "zone", "time_bucket"),
    )
    supply["diagnosis"] = supply.apply(
        lambda row: diagnose_supply(
            demand_change=_optional_float(row["demand_orders_change"]),
            online_hours_change=_optional_float(row["online_hours_change"]),
            completion_rate_change_pp=_optional_float(row["completion_rate_change_pp"]),
            gmv_change=_optional_float(row["gmv_change"]),
            efficiency_change=_optional_float(row["gmv_per_online_hour_change"]),
            policy=active_policy,
        ).value,
        axis=1,
    )
    daily_trend = aggregate_city_supply_metrics(current, group_by=("date",))
    efficiency_comparison = _efficiency_comparison(overview)
    anomalies = _build_anomaly_pool(supply, city_comparison, active_policy)
    gross_margin = overview["gross_margin"].current
    return CitySupplyDashboardData(
        periods=periods,
        city=city,
        time_bucket=time_bucket,
        overview=overview,
        city_comparison=city_comparison.sort_values("gmv_current", ascending=False),
        daily_trend=daily_trend.sort_values("date"),
        supply_diagnosis=supply.sort_values(
            ["diagnosis", "completion_rate_change_pp", "gmv_change"],
            ascending=[True, True, True],
        ),
        efficiency_comparison=efficiency_comparison,
        anomalies=anomalies,
        margin_band=classify_gross_margin(gross_margin, active_policy),
        policy=active_policy,
    )


def format_money(value: object) -> str:
    """Format simulated currency using yuan, ten-thousand yuan or hundred-million yuan."""
    if pd.isna(value):
        return "不可用"
    amount = float(value)
    absolute = abs(amount)
    if absolute >= 100_000_000:
        return f"¥{amount / 100_000_000:.2f}亿"
    if absolute >= 10_000:
        return f"¥{amount / 10_000:.2f}万"
    return f"¥{amount:,.0f}"


def format_hours(value: object) -> str:
    """Format online hours using hours or ten-thousand hours."""
    if pd.isna(value):
        return "不可用"
    hours = float(value)
    if abs(hours) >= 10_000:
        return f"{hours / 10_000:.2f}万小时"
    return f"{hours:,.0f}小时"


def format_percentage(value: object) -> str:
    """Format one ratio as a one-decimal percentage."""
    return "不可用" if pd.isna(value) else f"{float(value):.1%}"


def format_relative_change(value: object) -> str:
    """Format a relative period change with an explicit sign."""
    return "不可用" if pd.isna(value) else f"{float(value):+.1%}"


def format_point_change(value: object) -> str:
    """Format a ratio difference as percentage points, not relative growth."""
    return "不可用" if pd.isna(value) else f"{float(value) * 100:+.1f}pp"


def _filter_facts(
    facts: pd.DataFrame,
    start: date,
    end: date,
    *,
    city: str | None,
    time_bucket: str | None,
) -> pd.DataFrame:
    mask = facts["date"].between(pd.Timestamp(start), pd.Timestamp(end))
    if city is not None:
        mask &= facts["city"].eq(city)
    if time_bucket is not None:
        mask &= facts["time_bucket"].eq(time_bucket)
    return facts.loc[mask].copy()


def _overview(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
) -> dict[str, MetricComparison]:
    current_metrics = aggregate_city_supply_metrics(current).iloc[0]
    baseline_metrics = aggregate_city_supply_metrics(baseline).iloc[0]
    return {
        metric: MetricComparison(
            current=_optional_float(current_metrics[metric]),
            baseline=_optional_float(baseline_metrics[metric]),
            relative_change=_relative_change(
                current_metrics[metric], baseline_metrics[metric]
            ),
            point_change=(
                _point_change(current_metrics[metric], baseline_metrics[metric])
                if metric in {"completion_rate", "gross_margin", "subsidy_rate"}
                else None
            ),
        )
        for metric in COMPARISON_METRICS
    }


def _comparison_frame(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    group_by: tuple[str, ...],
) -> pd.DataFrame:
    current_metrics = aggregate_city_supply_metrics(current, group_by=group_by)
    baseline_metrics = aggregate_city_supply_metrics(baseline, group_by=group_by)
    current_metrics = current_metrics.rename(
        columns={column: f"{column}_current" for column in COMPARISON_METRICS}
    )
    baseline_metrics = baseline_metrics.rename(
        columns={column: f"{column}_baseline" for column in COMPARISON_METRICS}
    )
    compared = current_metrics.merge(baseline_metrics, on=list(group_by), how="outer")
    for metric in COMPARISON_METRICS:
        compared[f"{metric}_change"] = compared.apply(
            lambda row: _relative_change(
                row[f"{metric}_current"], row[f"{metric}_baseline"]
            ),
            axis=1,
        )
        if metric in {"completion_rate", "gross_margin", "subsidy_rate"}:
            compared[f"{metric}_change_pp"] = (
                compared[f"{metric}_current"] - compared[f"{metric}_baseline"]
            )
    return compared


def _efficiency_comparison(
    overview: dict[str, MetricComparison],
) -> pd.DataFrame:
    labels = {
        "gmv_per_online_hour": "GMV / 在线小时",
        "orders_per_online_hour": "完单 / 在线小时",
        "subsidy_rate": "补贴率",
        "gross_margin": "毛利率",
    }
    rows = []
    for metric, label in labels.items():
        comparison = overview[metric]
        rows.append(
            {
                "metric": metric,
                "指标": label,
                "上期": comparison.baseline,
                "本期": comparison.current,
                "变化": (
                    comparison.point_change
                    if metric in {"subsidy_rate", "gross_margin"}
                    else comparison.relative_change
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_anomaly_pool(
    supply: pd.DataFrame,
    city_comparison: pd.DataFrame,
    policy: CitySupplyPolicy,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for _, item in supply.iterrows():
        diagnosis = SupplyDiagnosis(item["diagnosis"])
        if diagnosis == SupplyDiagnosis.STABLE:
            continue
        completion_pp = _optional_float(item["completion_rate_change_pp"])
        is_gap = diagnosis == SupplyDiagnosis.SUPPLY_GAP
        priority = (
            "P0"
            if is_gap
            and completion_pp is not None
            and completion_pp <= policy.severe_completion_drop_pp
            else "P1"
        )
        issue = "运力缺口" if is_gap else "低效运力"
        judgment = (
            "需求增长与有效在线供给变化不同步，完单率同步下降。"
            if is_gap
            else "在线供给增长未转化为同等幅度的有效交易。"
        )
        action = (
            "优先增加该区域目标时段的定向运力，避免全天无差别补贴。"
            if is_gap
            else "收缩低效率时段增量，将供给转向需求更强的区域与时段。"
        )
        rows.append(
            {
                "优先级": priority,
                "城市": str(item["city"]),
                "区域/时段": (
                    f"{item['zone']} · {TIME_BUCKET_LABELS.get(str(item['time_bucket']), item['time_bucket'])}"
                ),
                "问题": issue,
                "关键证据": (
                    f"需求 {format_relative_change(item['demand_orders_change'])}；"
                    f"在线 {format_relative_change(item['online_hours_change'])}；"
                    f"完单率 {format_point_change(item['completion_rate_change_pp'])}；"
                    f"GMV/在线小时 {format_relative_change(item['gmv_per_online_hour_change'])}"
                ),
                "经营判断": judgment,
                "建议动作": action,
            }
        )

    for _, item in city_comparison.iterrows():
        current_margin = _optional_float(item["gross_margin_current"])
        margin_change_pp = _optional_float(item["gross_margin_change_pp"])
        band = classify_gross_margin(current_margin, policy)
        if band in {GrossMarginBand.AT_FLOOR, GrossMarginBand.NEAR_FLOOR}:
            rows.append(
                {
                    "优先级": "P0" if band == GrossMarginBand.AT_FLOOR else "P1",
                    "城市": str(item["city"]),
                    "区域/时段": "全市",
                    "问题": "毛利触线" if band == GrossMarginBand.AT_FLOOR else "毛利逼近红线",
                    "关键证据": (
                        f"补贴率 {format_point_change(item['subsidy_rate_change_pp'])}；"
                        f"GMV {format_relative_change(item['gmv_change'])}；"
                        f"完单率 {format_point_change(item['completion_rate_change_pp'])}；"
                        f"毛利率 {format_percentage(item['gross_margin_current'])}"
                    ),
                    "经营判断": "当前增长伴随明显成本投入，继续加码存在毛利风险。",
                    "建议动作": "停止全面加补贴，优先保留对完单率改善最有效的时段与区域。",
                }
            )
            continue
        if (
            band == GrossMarginBand.SAFE
            and margin_change_pp is not None
            and margin_change_pp <= policy.gross_margin_attention_drop_pp
        ):
            rows.append(
                {
                    "优先级": "P2",
                    "城市": str(item["city"]),
                    "区域/时段": "全市",
                    "问题": "毛利缓冲收窄",
                    "关键证据": (
                        f"毛利率 {format_point_change(item['gross_margin_change_pp'])}；"
                        f"当前毛利率 {format_percentage(item['gross_margin_current'])}；"
                        f"补贴率 {format_point_change(item['subsidy_rate_change_pp'])}；"
                        f"GMV {format_relative_change(item['gmv_change'])}"
                    ),
                    "经营判断": "当前毛利仍高于红线，但较上期显著收窄，需要确认增长是否依赖更高成本投入。",
                    "建议动作": "优先拆解补贴与其他变动成本变化，避免规模增长持续侵蚀毛利缓冲。",
                }
            )
    if not rows:
        return pd.DataFrame(columns=ANOMALY_COLUMNS)
    result = pd.DataFrame(rows)
    result["_priority"] = result["优先级"].map({"P0": 0, "P1": 1, "P2": 2})
    return (
        result.sort_values(["_priority", "城市", "区域/时段"])
        .drop(columns="_priority")
        .reset_index(drop=True)
    )


def finite_chart_rows(
    frame: pd.DataFrame,
    numeric_columns: tuple[str, ...],
) -> pd.DataFrame:
    """Return rows whose required chart metrics are present and finite."""
    if frame.empty or any(column not in frame.columns for column in numeric_columns):
        return frame.iloc[0:0].copy()
    result = frame.copy()
    valid = pd.Series(True, index=result.index, dtype=bool)
    for column in numeric_columns:
        numeric = pd.to_numeric(result[column], errors="coerce")
        valid &= numeric.notna() & numeric.map(
            lambda value: math.isfinite(float(value)) if pd.notna(value) else False
        )
        result[column] = numeric
    return result.loc[valid].copy()


def _relative_change(current: object, baseline: object) -> float | None:
    current_value = _optional_float(current)
    baseline_value = _optional_float(baseline)
    if current_value is None or baseline_value in {None, 0.0}:
        return None
    return current_value / baseline_value - 1.0


def _point_change(current: object, baseline: object) -> float | None:
    current_value = _optional_float(current)
    baseline_value = _optional_float(baseline)
    if current_value is None or baseline_value is None:
        return None
    return current_value - baseline_value


def _optional_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None
