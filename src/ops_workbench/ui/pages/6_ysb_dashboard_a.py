"""Dashboard A: regional YSB merchant operations."""

import re
from pathlib import Path

import pandas as pd
import streamlit as st

from ops_workbench.ui.components.common import (
    configure_page,
    format_currency,
    format_delta,
    format_metric_value,
    format_ratio,
    render_metric_card,
    render_page_header,
    render_ranked_bars,
    render_section_header,
)
from ops_workbench.ui.ysb_dashboard import (
    business_rows,
    filter_dashboard,
    format_rank_change,
    is_standard_comparison_period,
    latest_complete_period,
    load_priority_mart,
    merchant_trend,
    overview_metrics,
    period_quality_label,
    period_quality_status,
    summarize_attention_reasons,
    top_growth,
    top_loss,
)


ROOT = Path(__file__).resolve().parents[4]
LOCAL_MART_PATH = ROOT / "data" / "marts" / "ysb" / "mart_merchant_monthly_priority.csv"
DEMO_MART_PATH = ROOT / "demo_data" / "ysb_dashboard_a" / "mart_merchant_monthly_priority.csv"
SCALE_LABELS = {"KEY": "核心", "MID": "中等", "LONG_TAIL": "长尾", "UNAVAILABLE": "不可用"}
PRIORITY_LABELS = {"PRIORITY": "高优先级", "ATTENTION": "需关注", "WATCHLIST": "观察"}


def _format_reason_text(value: object) -> str:
    """Apply presentation-only amount formatting to the existing reason summary."""
    text = str(value)

    def replace_amount(match: re.Match[str]) -> str:
        return f"{match.group(1)}{format_metric_value(float(match.group(2)))}"

    return re.sub(r"(GMV损失)(-?\d+(?:\.\d+)?)", replace_amount, text)


def _short_reason_text(value: object) -> str:
    """Condense an existing reason summary into at most three display labels."""
    full = _format_reason_text(summarize_attention_reasons(value))
    reasons: list[str] = []
    trend = re.search(r"GMV环比(-?\d+(?:\.\d+)?)%", full)
    if trend:
        rate = float(trend.group(1))
        reasons.append(f"GMV{'下降' if rate < 0 else '增长'}{abs(rate):.1f}%")
    loss = re.search(r"GMV损失¥([\d,.]+(?:万)?)", full)
    if loss:
        reasons.append(f"区域损失{loss.group(1)}")
    consecutive = re.search(r"连续下降(\d+)个月", full)
    if consecutive:
        reasons.append(f"连续下降{consecutive.group(1)}个月")
    rank = re.search(r"排名下降(\d+)名", full)
    if rank and len(reasons) < 3:
        reasons.append(f"排名下降{rank.group(1)}名")
    return "｜".join(reasons[:3]) or full


def main() -> None:
    configure_page("YSB Dashboard A · 区域商家经营", show_heading=False)
    mart_path = LOCAL_MART_PATH if LOCAL_MART_PATH.is_file() else DEMO_MART_PATH
    if not mart_path.is_file():
        st.error("未找到 Dashboard A 展示数据。")
        return
    frame = load_priority_mart(mart_path)
    default_period = latest_complete_period(frame)
    periods = sorted(frame["month"].dropna().unique(), reverse=True)

    with st.sidebar:
        st.markdown("#### 筛选条件")
        period = st.selectbox("月份", periods, index=periods.index(default_period))
        owners = sorted(x for x in frame["owner"].dropna().astype(str).unique() if x)
        selected_owners = st.multiselect("负责人", owners, placeholder="请选择负责人")
        selected_scales = st.multiselect("商家规模", ["KEY", "MID", "LONG_TAIL", "UNAVAILABLE"], format_func=SCALE_LABELS.get, placeholder="请选择商家规模")
        selected_levels = st.multiselect("处理层级", ["PRIORITY", "ATTENTION", "WATCHLIST"], default=["PRIORITY"], format_func=PRIORITY_LABELS.get, placeholder="请选择处理层级")

    selected = filter_dashboard(frame, period, owners=selected_owners, scales=selected_scales, priority_levels=None)
    standard_period = is_standard_comparison_period(period)
    quality_label = period_quality_label(period)
    quality_status = period_quality_status(period)

    if not standard_period:
        render_page_header(
            "区域商家经营看板",
            "当前仅提供历史快照查看，不作为标准完整月经营比较。",
            (f"查看月份：{period}", f"周期类型：{quality_label}"),
        )
        if "HISTORICAL_SNAPSHOT" in quality_status:
            st.warning("该月份来自历史阶段性快照，不代表完整自然月。")
        else:
            st.warning("该月份数据不完整，不代表完整自然月。")
        st.caption("原始快照可供历史查看；页面不展示基于完整月假设的月环比或优先级结论。")
        snapshot_columns = ["merchant_name", "current_gmv", "gmv_rank_current", "merchant_scale"]
        snapshot = selected[snapshot_columns].rename(
            columns={"merchant_name": "商家", "current_gmv": "快照GMV", "gmv_rank_current": "快照排名", "merchant_scale": "规模"}
        )
        snapshot["快照GMV"] = snapshot["快照GMV"].map(format_metric_value)
        snapshot["规模"] = snapshot["规模"].map(SCALE_LABELS)
        with st.expander("查看原始历史快照", expanded=False):
            st.dataframe(snapshot, hide_index=True, width="stretch")
        with st.expander("数据说明", expanded=False):
            st.caption(f"技术周期状态：{quality_status}")
        return

    metrics = overview_metrics(selected)
    previous_period = str(pd.Period(period, freq="M") - 1)
    render_page_header(
        "区域商家经营看板",
        "默认展示最近可靠可比完整周期：2026-04 vs 2026-03",
        (f"当前周期：{period}", f"可比商家：{metrics['comparable_merchants']} 家", f"周期类型：{quality_label}"),
    )
    render_section_header("经营概览", "优先关注可比商家的规模、趋势与风险。")
    cards = st.columns(5)
    with cards[0]:
        render_metric_card("可比 GMV", format_currency(metrics["region_gmv"], compact=True), f"基于 {metrics['comparable_merchants']} 家可比商家", "primary")
    with cards[1]:
        render_metric_card("上期可比 GMV", format_currency(metrics["region_gmv_previous"], compact=True), previous_period, "neutral")
    with cards[2]:
        render_metric_card(
            "GMV 环比",
            format_delta(metrics["gmv_mom"], percent=True),
            "较上月",
            "negative" if pd.notna(metrics["gmv_mom"]) and metrics["gmv_mom"] < 0 else "positive",
        )
    with cards[3]:
        render_metric_card("可比商家", f"{metrics['comparable_merchants']:,} 家", f"下降 {metrics['declining_merchants']:,} 家｜增长 {metrics['growth_merchants']:,} 家", "attention")
    with cards[4]:
        render_metric_card(
            "处理体系",
            f"高优先 {metrics['priority_merchants']:,}",
            f"需关注 {metrics['attention_merchants']:,}｜观察 {metrics['watchlist_merchants']:,}",
            "negative",
        )

    render_section_header("GMV 变化排行", "按绝对变化金额排序，帮助快速定位影响最大的商家。")
    loss = top_loss(selected)
    growth = top_growth(selected)
    loss_tab, growth_tab = st.tabs(["业绩损失 Top 10", "业绩增长 Top 10"])
    with loss_tab:
        if loss.empty:
            st.info("当前筛选没有可比较的 GMV 损失数据。")
        else:
            render_ranked_bars(loss[["merchant_name", "gmv_loss"]].itertuples(index=False, name=None))
            loss_display = loss[["merchant_name", "gmv_loss", "previous_gmv_share", "merchant_scale"]].rename(columns={"merchant_name": "商家", "gmv_loss": "GMV损失", "previous_gmv_share": "上月区域份额", "merchant_scale": "规模"})
            loss_display["GMV损失"] = loss_display["GMV损失"].map(format_metric_value)
            loss_display["上月区域份额"] = loss_display["上月区域份额"].map(format_ratio)
            loss_display["规模"] = loss_display["规模"].map(SCALE_LABELS)
            with st.expander("查看完整排行明细", expanded=False):
                st.dataframe(loss_display, hide_index=True, width="stretch")
            st.caption("损失排序排除了 GMV 缺失和无法映射的商家；份额为上月可比区域 GMV 占比。")
    with growth_tab:
        if growth.empty:
            st.info("当前筛选没有可比较的 GMV 增长数据。")
        else:
            render_ranked_bars(growth[["merchant_name", "gmv_change_abs"]].itertuples(index=False, name=None), growth=True)
            growth_display = growth[["merchant_name", "gmv_change_abs", "gmv_mom", "merchant_scale"]].rename(columns={"merchant_name": "商家", "gmv_change_abs": "GMV增长额", "gmv_mom": "GMV环比", "merchant_scale": "规模"})
            growth_display["GMV增长额"] = growth_display["GMV增长额"].map(format_metric_value)
            growth_display["GMV环比"] = growth_display["GMV环比"].map(format_ratio)
            growth_display["规模"] = growth_display["规模"].map(SCALE_LABELS)
            with st.expander("查看完整排行明细", expanded=False):
                st.dataframe(growth_display, hide_index=True, width="stretch")

    render_section_header("高优先级商家", "优先展示商家、GMV、环比、损失、规模和经营关注原因。", "高优先级")
    pool = selected[selected["priority_level"].isin(selected_levels)] if selected_levels else selected.iloc[0:0]
    pool = pool.assign(_level_order=pool["priority_level"].map({"PRIORITY": 1, "ATTENTION": 2, "WATCHLIST": 3}), _scale_order=pool["merchant_scale"].map({"KEY": 1, "MID": 2, "LONG_TAIL": 3, "UNAVAILABLE": 4})).sort_values(["_level_order", "_scale_order", "gmv_loss"], ascending=[True, True, False]).drop(columns=["_level_order", "_scale_order"])
    display = pool[["merchant_name", "merchant_scale", "current_gmv", "previous_gmv", "gmv_mom", "gmv_loss", "previous_gmv_share", "gmv_rank_current", "gmv_rank_change", "aftersales_rate", "priority_level", "attention_reasons"]].copy()
    display["gmv_rank_change"] = display["gmv_rank_change"].map(format_rank_change)
    display["attention_reasons"] = display["attention_reasons"].map(_short_reason_text)
    display = display.rename(columns={"merchant_name": "商家", "merchant_scale": "规模", "current_gmv": "当前GMV", "previous_gmv": "上月GMV", "gmv_mom": "GMV环比", "gmv_loss": "GMV损失", "previous_gmv_share": "上月区域份额", "gmv_rank_current": "当前排名", "gmv_rank_change": "排名变化", "aftersales_rate": "售后率", "priority_level": "处理层级", "attention_reasons": "核心原因"})
    display["规模"] = display["规模"].map(SCALE_LABELS)
    display["当前GMV"] = display["当前GMV"].map(format_metric_value)
    display["GMV环比"] = display["GMV环比"].map(format_ratio)
    display["GMV损失"] = display["GMV损失"].map(format_metric_value)
    display["上月区域份额"] = display["上月区域份额"].map(format_ratio)
    st.dataframe(
        display[["商家", "规模", "当前GMV", "GMV环比", "GMV损失", "上月区域份额", "核心原因"]],
        hide_index=True,
        width="stretch",
        column_config={
            "商家": st.column_config.TextColumn(width="medium"),
            "规模": st.column_config.TextColumn(width="small"),
            "当前GMV": st.column_config.TextColumn(width="small"),
            "GMV环比": st.column_config.TextColumn(width="small"),
            "GMV损失": st.column_config.TextColumn(width="small"),
            "上月区域份额": st.column_config.TextColumn(width="small"),
            "核心原因": st.column_config.TextColumn(width="large"),
        },
    )

    render_section_header("商家快速查看", "查看单个可比商家的规模、处理层级和近 12 个月 GMV。")
    candidates = business_rows(selected)
    if candidates.empty:
        st.info("当前筛选没有可查看的可比商家。")
    else:
        options = candidates[["merchant_key", "merchant_name"]].drop_duplicates().sort_values("merchant_name")
        choice = st.selectbox("选择商家", options["merchant_key"].tolist(), format_func=lambda key: str(options.loc[options["merchant_key"] == key, "merchant_name"].iloc[0]))
        chosen = selected[selected["merchant_key"] == choice].sort_values("month").iloc[-1]
        qcols = st.columns(4)
        with qcols[0]:
            render_metric_card("当前规模", SCALE_LABELS.get(str(chosen["merchant_scale"]), str(chosen["merchant_scale"])), "商家规模", "primary")
        with qcols[1]:
            render_metric_card("处理层级", PRIORITY_LABELS.get(str(chosen["priority_level"]), str(chosen["priority_level"])), "当前状态", "negative" if chosen["priority_level"] == "PRIORITY" else "attention")
        with qcols[2]:
            render_metric_card("当前 GMV", format_currency(chosen["current_gmv"]), period, "primary")
        with qcols[3]:
            render_metric_card(
                "GMV 环比",
                format_delta(chosen["gmv_mom"], percent=True),
                "较上月",
                "negative" if pd.notna(chosen["gmv_mom"]) and chosen["gmv_mom"] < 0 else "positive",
            )
        full_reason = summarize_attention_reasons(chosen["attention_reasons"])
        st.write(_format_reason_text(full_reason) if full_reason else "当前没有经营关注原因。")
        trend = merchant_trend(frame, choice, 12)
        st.line_chart(trend.set_index("month")[["gmv"]], height=300)
        trend_display = trend[["month", "gmv", "gmv_mom", "gmv_rank_current", "aftersales_rate"]].rename(
            columns={"month": "月份", "gmv": "GMV", "gmv_mom": "GMV环比", "gmv_rank_current": "排名", "aftersales_rate": "售后率"}
        )
        st.dataframe(trend_display, hide_index=True, width="stretch")
        st.info("单商家深度诊断请通过侧边栏打开 Dashboard B，并上传该商家的日报。")

main()
