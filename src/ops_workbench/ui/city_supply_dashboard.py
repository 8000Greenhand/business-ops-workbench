    "online_drivers",
    "effective_online_drivers",
    "effective_online_hours",
    "completed_orders",
    "avg_order_value",
    "gmv_per_online_hour",
    "orders_per_online_hour",
    "effective_online_rate",
    "drivers_effective_rate",
    "demand_per_effective_driver",
    "orders_per_active_driver",
    "gmv_per_active_driver",
    "online_hours_per_active_driver",
    "gmv_per_effective_online_hour",
    "orders_per_effective_online_hour",
    "subsidy_rate",
    "demand_orders",
)
POINT_CHANGE_METRICS = {
    "completion_rate",
    "gross_margin",
    "subsidy_rate",
    "effective_online_rate",
    "drivers_effective_rate",
}
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
    zone: str | None
    time_bucket: str | None
    overview: dict[str, MetricComparison]
    result_decomposition: pd.DataFrame
    diagnostic_summary: tuple[str, ...]
    city_comparison: pd.DataFrame
    zone_comparison: pd.DataFrame
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
    zone: str | None = None,
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
        zone=zone,
        time_bucket=time_bucket,
    )
    baseline = _filter_facts(
        facts,
        periods.baseline_start,
        periods.baseline_end,
        city=city,
        zone=zone,
        time_bucket=time_bucket,
    )
    if current.empty or baseline.empty:
        raise ValueError("当前筛选条件下没有完整的本期与上期数据")

    overview = _overview(current, baseline)
    result_decomposition = _result_decomposition(overview)
    diagnostic_summary = _build_diagnostic_summary(overview, result_decomposition)
    city_comparison = _comparison_frame(current, baseline, ("city",))
    zone_comparison = (
        _comparison_frame(current, baseline, ("zone",))
        if city is not None
        else pd.DataFrame()
    )
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
            effective_online_hours_change=_optional_float(
                row["effective_online_hours_change"]
            ),
            effective_online_rate_change_pp=_optional_float(
                row["effective_online_rate_change_pp"]
            ),
            active_drivers_change=_optional_float(row["active_drivers_change"]),
            orders_per_active_driver_change=_optional_float(
                row["orders_per_active_driver_change"]
            ),
            effective_efficiency_change=_optional_float(
                row["gmv_per_effective_online_hour_change"]
            ),
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
        zone=zone,
        time_bucket=time_bucket,
        overview=overview,
        result_decomposition=result_decomposition,
        diagnostic_summary=diagnostic_summary,
        city_comparison=city_comparison.sort_values("gmv_current", ascending=False),
        zone_comparison=(
            zone_comparison.sort_values("gmv_current", ascending=False)
            if not zone_comparison.empty
            else zone_comparison
        ),
        daily_trend=daily_trend.sort_values("date"),
        supply_diagnosis=_sort_supply_diagnosis(supply),
        efficiency_comparison=efficiency_comparison,