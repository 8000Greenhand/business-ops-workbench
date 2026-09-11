"""Dashboard A: regional YSB merchant operations."""

from pathlib import Path

import pandas as pd
import streamlit as st

from ops_workbench.ui.components.common import configure_page
from ops_workbench.ui.ysb_dashboard import (
    business_rows,
    filter_dashboard,
    format_rank_change,
    latest_complete_period,
    load_priority_mart,
    merchant_trend,
    overview_metrics,
    quality_rows,
    summarize_attention_reasons,
    top_growth,
    top_loss,
)


ROOT = Path(__file__).resolve().parents[4]
MART_PATH = ROOT / "data" / "marts" / "ysb" / "mart_merchant_monthly_priority.csv"


def _money(value: object) -> str:
    return "NULL" if pd.isna(value) else f"{float(value):,.2f}"


def _money_compact(value: object) -> str:
    if pd.isna(value):
        return "NULL"
    amount = float(value)
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M"
    if abs(amount) >= 1_000:
        return f"{amount / 1_000:.1f}K"
    return f"{amount:.0f}"


def _pct(value: object) -> str:
    return "NULL" if pd.isna(value) else f"{float(value):.1%}"


def main() -> None:
    configure_page("YSB Dashboard A · 区域商家经营")
    if not MART_PATH.is_file():
        st.error("未找到 YSB priority mart，请先生成 M2B 数据集。")
        return
    frame = load_priority_mart(MART_PATH)
    default_period = latest_complete_period(frame)
    periods = sorted(frame["month"].dropna().unique(), reverse=True)

    with st.sidebar:
        st.subheader("筛选")
        period = st.selectbox("月份", periods, index=periods.index(default_period))
        owners = sorted(x for x in frame["owner"].dropna().astype(str).unique() if x)
        selected_owners = st.multiselect("运营 / 商务归属", owners)
        selected_scales = st.multiselect("商家规模", ["KEY", "MID", "LONG_TAIL", "UNAVAILABLE"])
        selected_levels = st.multiselect("处理层级", ["PRIORITY", "ATTENTION", "WATCHLIST"], default=["PRIORITY"])

    selected = filter_dashboard(frame, period, owners=selected_owners, scales=selected_scales, priority_levels=None)
    metrics = overview_metrics(selected)
    st.caption(f"当前月份：{period} · 区域 GMV 使用当前月与上月均有有效值的可比商家；可比商家 {metrics['comparable_merchants']} 家")
    cards = st.columns(5)
    cards[0].metric("Comparable GMV", _money_compact(metrics["region_gmv"]), help=f"{period} 可比 cohort 当前 GMV：{_money(metrics['region_gmv'])}；{metrics['comparable_merchants']} 家")
    cards[1].metric("GMV MoM", _pct(metrics["gmv_mom"]), help=f"同一批 {metrics['comparable_merchants']} 家可比商家：{period} GMV / 上月 GMV - 1")
    cards[2].metric("Declining Merchants", metrics["declining_merchants"], help=f"{period} GMV 下降商家")
    cards[3].metric("Priority Merchants", metrics["priority_merchants"], help=f"{period} PRIORITY")
    cards[4].metric("Service Alerts", metrics["service_alerts"], help=f"{period} Service 维度告警")

    st.subheader("区域 GMV 损失")
    loss = top_loss(selected)
    if loss.empty:
        st.info("当前筛选没有可比较的 GMV 损失数据。")
    else:
        chart = loss.assign(label=loss["merchant_name"], value=loss["gmv_loss"]).sort_values("value").set_index("label")[["value"]]
        st.bar_chart(chart, horizontal=True, height=max(320, len(chart) * 34))
        st.dataframe(loss[["merchant_name", "gmv_loss", "previous_gmv_share", "merchant_scale"]].rename(columns={"merchant_name": "商家", "gmv_loss": "GMV损失", "previous_gmv_share": "上月区域份额", "merchant_scale": "规模"}), hide_index=True, use_container_width=True)
        st.caption("损失排序排除了 GMV 缺失和 unresolved 商家；占比为上月可比区域 GMV 份额。")

    with st.expander("Top Growth Merchants", expanded=False):
        growth = top_growth(selected)
        st.dataframe(growth[["merchant_name", "gmv_change_abs", "gmv_mom", "merchant_scale"]].rename(columns={"merchant_name": "商家", "gmv_change_abs": "GMV增长额", "gmv_mom": "GMV环比", "merchant_scale": "规模"}), hide_index=True, use_container_width=True)

    st.subheader("Priority Merchant Table")
    pool = selected[selected["priority_level"].isin(selected_levels)] if selected_levels else selected.iloc[0:0]
    pool = pool.assign(_level_order=pool["priority_level"].map({"PRIORITY": 1, "ATTENTION": 2, "WATCHLIST": 3}), _scale_order=pool["merchant_scale"].map({"KEY": 1, "MID": 2, "LONG_TAIL": 3, "UNAVAILABLE": 4})).sort_values(["_level_order", "_scale_order", "gmv_loss"], ascending=[True, True, False]).drop(columns=["_level_order", "_scale_order"])
    display = pool[["merchant_name", "merchant_scale", "current_gmv", "previous_gmv", "gmv_mom", "gmv_loss", "previous_gmv_share", "gmv_rank_current", "gmv_rank_change", "aftersales_rate", "priority_level", "attention_reasons"]].copy()
    display["gmv_rank_change"] = display["gmv_rank_change"].map(format_rank_change)
    display["attention_reasons"] = display["attention_reasons"].map(summarize_attention_reasons)
    display = display.rename(columns={"merchant_name": "商家", "merchant_scale": "规模", "current_gmv": "当前GMV", "previous_gmv": "上月GMV", "gmv_mom": "GMV环比", "gmv_loss": "GMV损失", "previous_gmv_share": "上月区域份额", "gmv_rank_current": "当前排名", "gmv_rank_change": "排名变化", "aftersales_rate": "售后率", "priority_level": "处理层级", "attention_reasons": "关注原因"})
    st.dataframe(display, hide_index=True, use_container_width=True)

    st.subheader("Merchant Quick View")
    candidates = business_rows(selected)
    if candidates.empty:
        st.info("当前筛选没有可查看的可比商家。")
    else:
        options = candidates[["merchant_key", "merchant_name"]].drop_duplicates().sort_values("merchant_name")
        choice = st.selectbox("选择商家", options["merchant_key"].tolist(), format_func=lambda key: str(options.loc[options["merchant_key"] == key, "merchant_name"].iloc[0]))
        chosen = selected[selected["merchant_key"] == choice].sort_values("month").iloc[-1]
        qcols = st.columns(4)
        qcols[0].metric("当前规模", chosen["merchant_scale"])
        qcols[1].metric("处理层级", chosen["priority_level"])
        qcols[2].metric("当前 GMV", _money(chosen["current_gmv"]))
        qcols[3].metric("GMV 环比", _pct(chosen["gmv_mom"]))
        st.write(summarize_attention_reasons(chosen["attention_reasons"]) or "当前没有经营关注原因。")
        trend = merchant_trend(frame, choice, 12)
        st.line_chart(trend.set_index("month")[["gmv"]], height=300)
        st.dataframe(trend.rename(columns={"month": "月份", "gmv": "GMV", "gmv_mom": "GMV环比", "gmv_rank_current": "排名", "aftersales_rate": "售后率", "metric_quality_status": "指标质量", "data_quality_status": "数据质量"}), hide_index=True, use_container_width=True)
        st.info("Deep Diagnosis / 商家深度诊断：请上传该商家的日报进行深度诊断（Dashboard B 尚未启用）。")

    with st.expander("Data Quality", expanded=False):
        quality = quality_rows(selected)
        if quality.empty:
            st.success("当前筛选没有数据质量告警。")
        else:
            quality_display = quality[["merchant_name", "month", "data_quality_reasons", "merchant_mapping_status", "metric_quality_status"]].rename(columns={"merchant_name": "商家", "month": "月份", "data_quality_reasons": "质量原因", "merchant_mapping_status": "映射状态", "metric_quality_status": "指标质量"})
            st.dataframe(quality_display, hide_index=True, use_container_width=True)


main()
