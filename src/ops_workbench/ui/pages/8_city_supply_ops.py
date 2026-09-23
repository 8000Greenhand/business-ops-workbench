"""City supply operations: single-page simulated management diagnosis."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ops_workbench.diagnostics.city_supply import GrossMarginBand
from ops_workbench.ui.city_supply_dashboard import (
    TIME_BUCKET_LABELS,
    CitySupplyDashboardData,
    build_city_supply_dashboard,
    default_period,
    finite_chart_rows,
    format_hours,
    format_money,
    format_percentage,
    format_point_change,
    format_relative_change,
    load_city_supply_facts,
)
from ops_workbench.ui.components.common import (
    configure_page,
    render_metric_card,
    render_page_header,
    render_section_header,
)


CITY_OPTIONS = ("全部城市", "成都", "重庆", "昆明", "贵阳")
TIME_OPTIONS = {"全部时段": None, **{label: key for key, label in TIME_BUCKET_LABELS.items()}}


@st.cache_data(show_spinner=False)
def _cached_facts() -> pd.DataFrame:
    """Generate the fixed-seed V0.1 simulation once per Streamlit cache."""
    return load_city_supply_facts()


def _render_line_chart(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    y_title: str,
    percentage: bool = False,
    height: int = 250,
) -> None:
    """Render a finite-only Vega-Lite line chart with business-friendly axes."""
    safe = finite_chart_rows(frame, (y,))
    if safe.empty:
        st.info("当前筛选周期暂无可用于绘图的数据。")
        return
    y_axis = {"title": y_title}
    tooltip = {"field": y, "type": "quantitative", "title": y_title}
    if percentage:
        y_axis["format"] = ".0%"
        tooltip["format"] = ".1%"
    st.vega_lite_chart(
        safe,
        {
            "mark": {"type": "line", "point": False},
            "encoding": {
                "x": {
                    "field": x,
                    "type": "temporal",
                    "title": None,
                    "axis": {"format": "%m-%d", "labelAngle": 0},
                },
                "y": {"field": y, "type": "quantitative", "axis": y_axis},
                "tooltip": [
                    {
                        "field": x,
                        "type": "temporal",
                        "title": "日期",
                        "format": "%Y-%m-%d",
                    },
                    tooltip,
                ],
            },
            "height": height,
        },
        use_container_width=True,
    )


def _render_bar_chart(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    y_title: str,
    percentage: bool = False,
    height: int = 250,
) -> None:
    """Render a finite-only categorical bar chart."""
    safe = finite_chart_rows(frame, (y,))
    if safe.empty:
        st.info("当前筛选周期暂无可用于绘图的数据。")
        return
    y_axis = {"title": y_title}
    tooltip = {"field": y, "type": "quantitative", "title": y_title}
    if percentage:
        y_axis["format"] = ".0%"
        tooltip["format"] = ".1%"
    st.vega_lite_chart(
        safe,
        {
            "mark": {"type": "bar"},
            "encoding": {
                "x": {"field": x, "type": "nominal", "title": None},
                "y": {"field": y, "type": "quantitative", "axis": y_axis},
                "tooltip": [
                    {"field": x, "type": "nominal", "title": x},
                    tooltip,
                ],
            },
            "height": height,
        },
        use_container_width=True,
    )


def _render_margin_scatter(frame: pd.DataFrame) -> None:
    """Render the city efficiency-versus-margin view with a percentage y-axis."""
    safe = finite_chart_rows(frame, ("GMV/在线小时", "毛利率", "GMV"))
    if safe.empty:
        st.info("当前筛选周期暂无可用于绘图的数据。")
        return
    st.vega_lite_chart(
        safe,
        {
            "mark": {"type": "circle", "opacity": 0.78},
            "encoding": {
                "x": {
                    "field": "GMV/在线小时",
                    "type": "quantitative",
                    "title": "GMV / 在线小时（元）",
                },
                "y": {
                    "field": "毛利率",
                    "type": "quantitative",
                    "title": "毛利率",
                    "axis": {"format": ".0%"},
                },
                "color": {"field": "城市", "type": "nominal", "title": "城市"},
                "size": {"field": "GMV", "type": "quantitative", "title": "GMV"},
                "tooltip": [
                    {"field": "城市", "type": "nominal", "title": "城市"},
                    {
                        "field": "GMV/在线小时",
                        "type": "quantitative",
                        "title": "GMV / 在线小时",
                        "format": ".1f",
                    },
                    {
                        "field": "毛利率",
                        "type": "quantitative",
                        "title": "毛利率",
                        "format": ".1%",
                    },
                    {"field": "GMV", "type": "quantitative", "title": "GMV", "format": ",.0f"},
                ],
            },
            "height": 320,
        },
        use_container_width=True,
    )


def _render_anomaly_card(row: pd.Series) -> None:
    """Render one complete decision chain without horizontal truncation."""
    with st.container(border=True):
        st.markdown(
            f"**{row['优先级']} · {row['城市']} · {row['区域/时段']} · {row['问题']}**"
        )
        scope = str(row["区域/时段"]).replace(" · ", " → ")
        st.caption(f"定位路径｜{row['城市']} → {scope}")
        st.caption(f"关键证据｜{row['关键证据']}")
        st.markdown(f"**经营判断：** {row['经营判断']}")
        st.markdown(f"**建议动作：** {row['建议动作']}")


def _metric_detail(
    data: CitySupplyDashboardData,
    metric: str,
    *,
    percentage_points: bool = False,
) -> str:
    comparison = data.overview[metric]
    change = (
        format_point_change(comparison.point_change)
        if percentage_points
        else format_relative_change(comparison.relative_change)
    )
    return f"较上期 {change}"


def _render_filters(facts: pd.DataFrame) -> CitySupplyDashboardData | None:
    default_start, default_end = default_period(facts)
    minimum = pd.Timestamp(facts["date"].min()).date()
    maximum = pd.Timestamp(facts["date"].max()).date()
    controls = st.columns([1.1, 1.1, 1, 1])
    with controls[0]:
        current_start = st.date_input(
            "当前周期起始日",
            value=default_start,
            min_value=minimum,
            max_value=maximum,
        )
    with controls[1]:
        current_end = st.date_input(
            "当前周期结束日",
            value=default_end,
            min_value=minimum,
            max_value=maximum,
        )
    with controls[2]:
        city_label = st.selectbox("城市", CITY_OPTIONS, index=0)
    with controls[3]:
        time_label = st.selectbox("时段", tuple(TIME_OPTIONS), index=0)
    try:
        data = build_city_supply_dashboard(
            facts,
            current_start=current_start,
            current_end=current_end,
            city=None if city_label == "全部城市" else city_label,
            time_bucket=TIME_OPTIONS[time_label],
        )
    except ValueError as error:
        st.error(str(error))
        return None
    periods = data.periods
    st.caption(
        f"当前周期：{periods.current_start} ～ {periods.current_end}　｜　"
        f"对比周期：{periods.baseline_start} ～ {periods.baseline_end}　｜　"
        f"{periods.days} 天等长比较"
    )
    return data


def _render_kpis(data: CitySupplyDashboardData) -> None:
    render_section_header(
        "核心经营结果",
        "先看规模、履约和毛利，再判断在线供给是否真正转化为经营结果。",
        data.margin_band.value,
    )
    cards = st.columns(3)
    with cards[0]:
        render_metric_card(
            "GMV",
            format_money(data.overview["gmv"].current),
            _metric_detail(data, "gmv"),
        )
    with cards[1]:
        render_metric_card(
            "完单率",
            format_percentage(data.overview["completion_rate"].current),
            _metric_detail(data, "completion_rate", percentage_points=True),
        )
    with cards[2]:
        margin = data.overview["gross_margin"]
        tone = {
            GrossMarginBand.SAFE: "positive",
            GrossMarginBand.NEAR_FLOOR: "attention",
            GrossMarginBand.AT_FLOOR: "negative",
        }.get(data.margin_band, "neutral")
        render_metric_card(
            "毛利率 · 模拟经营口径",
            format_percentage(margin.current),
            (
                f"较上期 {format_point_change(margin.point_change)} · "
                f"{data.margin_band.value} · 红线 {format_percentage(data.policy.gross_margin_floor)}"
            ),
            tone,
        )
    cards = st.columns(3)
    with cards[0]:
        render_metric_card(
            "在线时长",
            format_hours(data.overview["online_hours"].current),
            _metric_detail(data, "online_hours"),
        )
    with cards[1]:
        completed = data.overview["completed_orders"]
        value = "不可用" if completed.current is None else f"{completed.current:,.0f}单"
        render_metric_card(
            "完成订单量",
            value,
            _metric_detail(data, "completed_orders"),
        )
    with cards[2]:
        efficiency = data.overview["gmv_per_online_hour"]
        value = "不可用" if efficiency.current is None else f"¥{efficiency.current:,.1f}/小时"
        render_metric_card(
            "GMV / 在线小时",
            value,
            _metric_detail(data, "gmv_per_online_hour"),
        )


def _format_signed_money(value: object) -> str:
    if pd.isna(value):
        return "不可用"
    amount = float(value)
    sign = "+" if amount > 0 else ""
    return f"{sign}{format_money(amount)}"


def _format_signed_orders(value: object) -> str:
    if pd.isna(value):
        return "不可用"
    amount = float(value)
    sign = "+" if amount > 0 else ""
    return f"{sign}{amount:,.0f}单"


def _render_result_decomposition(data: CitySupplyDashboardData) -> None:
    render_section_header(
        "经营结果拆解",
        "先拆清结果由什么驱动，再进入城市、区域和时段定位。",
    )
    st.caption("GMV = 完成订单量 × 客单价　｜　完成订单量 = 需求订单量 × 完单率")
    for message in data.diagnostic_summary:
        st.markdown(f"- {message}")

    bridge = data.result_decomposition.copy()
    columns = st.columns(2)
    for container, bridge_name in zip(columns, ("GMV", "完成订单量")):
        with container:
            st.markdown(f"#### {bridge_name}变化拆解")
            part = bridge[bridge["bridge"].eq(bridge_name)].copy()
            if part.empty:
                st.info("当前周期暂无完整拆解数据。")
                continue
            formatter = _format_signed_money if bridge_name == "GMV" else _format_signed_orders
            total_change = formatter(part["total_change"].iloc[0])
            display = pd.DataFrame(
                {
                    "驱动项": part["driver"],
                    "影响量": part["contribution"].map(formatter),
                }
            )
            st.dataframe(display, hide_index=True, width="stretch")
            st.caption(f"两项贡献回加后的总变化：{total_change}")


def _render_city_comparison(data: CitySupplyDashboardData) -> None:
    render_section_header(
        "城市经营对比",
        "回答哪个城市的规模、履约、供给效率或毛利约束出现偏离。",
    )
    frame = data.city_comparison.copy()
    display = pd.DataFrame(
        {
            "城市": frame["city"],
            "GMV": frame["gmv_current"].map(format_money),
            "GMV变化": frame["gmv_change"].map(format_relative_change),
            "完单率": frame["completion_rate_current"].map(format_percentage),
            "完单率变化": frame["completion_rate_change_pp"].map(format_point_change),
            "在线时长": frame["online_hours_current"].map(format_hours),
            "在线时长变化": frame["online_hours_change"].map(format_relative_change),
            "GMV/在线小时": frame["gmv_per_online_hour_current"].map(
                lambda value: f"¥{float(value):,.1f}" if pd.notna(value) else "不可用"
            ),
            "毛利率": frame["gross_margin_current"].map(format_percentage),
            "毛利率变化": frame["gross_margin_change_pp"].map(format_point_change),
        }
    )
    st.dataframe(display, hide_index=True, width="stretch")


def _render_trends(data: CitySupplyDashboardData) -> None:
    render_section_header(
        "核心趋势",
        "按日查看结果变化，并核对在线供给增长后效率是否同步改善。",
    )
    trend = data.daily_trend.copy()
    st.markdown("#### 经营结果：GMV 与完单率")
    charts = st.columns(2)
    with charts[0]:
        _render_line_chart(trend, x="date", y="gmv", y_title="GMV", height=210)
    with charts[1]:
        _render_line_chart(
            trend,
            x="date",
            y="completion_rate",
            y_title="完单率",
            percentage=True,
            height=210,
        )
    st.markdown("#### 运力投入：在线时长与 GMV / 在线小时")
    charts = st.columns(2)
    with charts[0]:
        _render_line_chart(trend, x="date", y="online_hours", y_title="在线时长", height=210)
    with charts[1]:
        _render_line_chart(
            trend,
            x="date",
            y="gmv_per_online_hour",
            y_title="GMV / 在线小时",
            height=210,
        )


def _render_supply_diagnosis(data: CitySupplyDashboardData) -> None:
    render_section_header(
        "时空供需诊断",
        "联合需求、在线供给、履约与效率判断，不依据单个指标直接下结论。",
    )
    frame = data.supply_diagnosis.copy()
    display = pd.DataFrame(
        {
            "城市": frame["city"],
            "区域": frame["zone"],
            "时段": frame["time_bucket"].map(TIME_BUCKET_LABELS),
            "需求订单变化": frame["demand_orders_change"].map(format_relative_change),
            "在线时长变化": frame["online_hours_change"].map(format_relative_change),
            "完单率": frame["completion_rate_current"].map(format_percentage),
            "完单率变化": frame["completion_rate_change_pp"].map(format_point_change),
            "GMV变化": frame["gmv_change"].map(format_relative_change),
            "诊断": frame["diagnosis"],
        }
    )
    abnormal_count = int(display["诊断"].ne("供需基本稳定").sum())
    st.caption(
        f"异常/关注项优先置顶：{abnormal_count} 条；"
        f"其余 {len(display) - abnormal_count} 条作为正常对照保留。"
    )
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=min(620, 36 + len(display) * 35),
        column_config={
            "区域": st.column_config.TextColumn(width="medium"),
            "诊断": st.column_config.TextColumn(width="medium"),
        },
    )
    st.caption("诊断阈值为模拟经营规则，集中配置在 config/city_supply_ops.yaml。")


def _render_efficiency_and_margin(data: CitySupplyDashboardData) -> None:
    render_section_header(
        "运力效率与毛利",
        "判断增长是否同时具备单位运力效率和毛利缓冲。",
    )
    table = data.efficiency_comparison.copy()
    formatted_rows = []
    for _, row in table.iterrows():
        metric = row["metric"]
        if metric in {"subsidy_rate", "gross_margin"}:
            baseline = format_percentage(row["上期"])
            current = format_percentage(row["本期"])
            change = format_point_change(row["变化"])
        else:
            unit = "元/小时" if metric == "gmv_per_online_hour" else "单/小时"
            baseline = "不可用" if pd.isna(row["上期"]) else f"{float(row['上期']):,.2f}{unit}"
            current = "不可用" if pd.isna(row["本期"]) else f"{float(row['本期']):,.2f}{unit}"
            change = format_relative_change(row["变化"])
        formatted_rows.append(
            {"指标": row["指标"], "上期": baseline, "本期": current, "变化": change}
        )
    st.dataframe(pd.DataFrame(formatted_rows), hide_index=True, width="stretch")
    scatter = data.city_comparison[
        ["city", "gmv_per_online_hour_current", "gross_margin_current", "gmv_current"]
    ].rename(
        columns={
            "city": "城市",
            "gmv_per_online_hour_current": "GMV/在线小时",
            "gross_margin_current": "毛利率",
            "gmv_current": "GMV",
        }
    )
    if len(scatter) > 1:
        st.caption("城市：GMV / 在线小时 vs 毛利率")
        _render_margin_scatter(scatter)


def _render_anomalies(data: CitySupplyDashboardData) -> None:
    render_section_header(
        "经营异常池",
        "将问题、证据、经营判断和建议动作放在同一条决策链上。",
    )
    if data.anomalies.empty:
        st.success("当前筛选周期未发现 P0/P1/P2 经营异常或关注项。")
        return
    visible = data.anomalies.head(6)
    for _, row in visible.iterrows():
        _render_anomaly_card(row)
    remaining = data.anomalies.iloc[6:]
    if not remaining.empty:
        with st.expander(f"查看其余 {len(remaining)} 条异常"):
            for _, row in remaining.iterrows():
                _render_anomaly_card(row)


def main() -> None:
    """Render the single-page city supply operating diagnosis."""
    configure_page("城市运力经营", show_heading=False)
    render_page_header(
        "城市运力经营",
        "模拟经营数据｜在毛利约束下提升 GMV、完单率与有效运力效率",
        ("单页经营诊断", "固定 Seed", "模拟经营口径"),
    )
    st.caption(
        "本页面使用模拟经营数据，仅用于经营分析能力演示，不代表任何平台内部真实数据或指标口径。"
    )
    render_section_header("筛选与周期", "选择当前周期，系统自动生成上一等长周期。")
    data = _render_filters(_cached_facts())
    if data is None:
        return
    _render_kpis(data)
    _render_result_decomposition(data)
    _render_anomalies(data)
    _render_city_comparison(data)
    _render_trends(data)
    _render_supply_diagnosis(data)
    _render_efficiency_and_margin(data)


main()
