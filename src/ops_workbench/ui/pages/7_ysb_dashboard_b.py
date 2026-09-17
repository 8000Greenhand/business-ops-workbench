"""Dashboard B: single-merchant purchase-amount diagnosis."""

from __future__ import annotations

import hashlib
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from ops_workbench.ui.components.common import (
    configure_page,
    format_currency,
    format_currency_delta,
    format_delta,
    format_metric_value,
    render_metric_card,
    render_page_header,
    render_section_header,
    render_signed_contributions,
    render_status_badge,
)
from ops_workbench.ui.ysb_dashboard_b import (
    DashboardBData,
    DashboardBInputError,
    activity_detail_summary,
    activity_top_contributors,
    build_dashboard_b_from_uploads,
    contribution_summary,
    core_facts,
    current_metrics,
    has_capability,
    load_dashboard_b_marts,
    load_public_demo_dashboard_b,
    quality_count,
    result_decomposition,
    select_dashboard_b_periods,
    top_contributors,
)
from ops_workbench.diagnostics.ysb_dashboard_b_input import UploadedPayload
from ops_workbench.diagnostics.ysb_merchant_case import (
    HAS_ACTIVITY,
    HAS_CUSTOMER,
    HAS_PRODUCT,
    HAS_TRAFFIC,
)


ROOT = Path(__file__).resolve().parents[4]
MART_DIR = ROOT / "data" / "marts" / "ysb"
POLICY_PATH = ROOT / "config" / "ysb_dashboard_b_order_metric_policy.yaml"
RULES_PATH = ROOT / "config" / "ysb_dashboard_b_diagnosis_rules.yaml"
PUBLIC_DEMO_DIR = ROOT / "demo_data" / "ysb_dashboard_b"
CUSTOMER_LABELS = {
    "RETAINED": "两个周期持续活跃",
    "CURRENT_ONLY": "对比期新增活跃",
    "PREVIOUS_ONLY": "基准期活跃、对比期未活跃",
}
PRODUCT_LABELS = {
    "RETAINED_ACTIVE": "两个周期持续动销",
    "CURRENT_ONLY_ACTIVE": "对比期新增动销",
    "PREVIOUS_ONLY_ACTIVE": "基准期动销、对比期未动销",
}
DRIVER_LABELS = {
    "AOV_DRIVEN": "客单价变化主导",
    "ORDER_DRIVEN": "订单量变化主导",
    "MIXED": "订单量与客单价共同影响",
}
EVIDENCE_LABELS = {"HIGH": "高可信", "MEDIUM": "中等可信", "LIMITED": "证据有限"}
QUALITY_LABELS = {
    "ORDER_STATUS_SEMANTICS_UNCONFIRMED": "订单状态口径尚未确认",
    "PRODUCT_MAPPING_LIMITATION": "商品映射存在限制",
}
ACTIVITY_STATUS_LABELS = {
    "RETAINED_ACTIVITY": "两个周期都有成交",
    "PREVIOUS_ONLY_ACTIVITY": "基准期有、对比期无成交",
    "CURRENT_ONLY_ACTIVITY": "对比期新增成交",
    "ZERO_AMOUNT_ONLY": "仅零金额记录",
}


def _money(value: object) -> str:
    return format_currency(value)


def _signed_money(value: object, *, force_wan: bool = False) -> str:
    return format_currency_delta(value, force_wan=force_wan)


def _pct(value: object) -> str:
    return format_delta(value, percent=True)


def _ratio(value: object) -> str:
    return "不可用" if pd.isna(value) else f"{float(value):.1%}"


def _pct_direction(value: object) -> str:
    if pd.isna(value):
        return "不可用"
    rate = float(value)
    return f"增加 {rate:.1%}" if rate > 0 else f"下降 {abs(rate):.1%}" if rate < 0 else "持平"


def _quality_flag(value: object) -> str:
    if pd.isna(value) or not str(value).strip():
        return "无质量标记"
    return "；".join(QUALITY_LABELS.get(flag, flag) for flag in str(value).split(";"))


def _evidence_label(value: object) -> str:
    return EVIDENCE_LABELS.get(str(value), "证据有限")


def _driver_label(value: object) -> str:
    return DRIVER_LABELS.get(str(value), "订单量与客单价共同影响")


def _business_fact_text(value: str) -> str:
    """Replace persisted technical tokens only when presenting fact text."""
    replacements = {
        "AOV_DRIVEN": "客单价变化主导",
        "ORDER_DRIVEN": "订单量变化主导",
        "MIXED": "订单量与客单价共同影响",
        "AOV": "客单价",
        "CUSTOMER": "药店",
        "PRODUCT": "商品",
        "PREVIOUS_ONLY": "基准期活跃、对比期未活跃",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def _render_upload_section() -> list[object]:
    """Render the Dashboard B upload controls exactly once per page run."""
    st.sidebar.subheader("上传商家原始数据")
    st.sidebar.markdown(
        "直接上传后台导出的商家经营数据，无需人工整理日报。  \n"
        "订单明细为必需；流量、活动为可选；订单中存在有效药店字段时自动启用药店诊断。"
    )
    uploaded = st.sidebar.file_uploader(
        "选择 CSV / XLSX 文件",
        type=["csv", "xlsx"],
        accept_multiple_files=True,
    )
    st.sidebar.caption("文件仅在当前会话处理，不写入项目原始数据目录。")
    return uploaded


def _get_data(uploaded: list[object]) -> DashboardBData | None:
    if not uploaded:
        return _load_default_demo()

    payloads = tuple(UploadedPayload(item.name, item.getvalue()) for item in uploaded)
    digest_source = b"".join(
        item.name.encode("utf-8") + b"\0" + item.content
        for item in payloads
    )
    digest = hashlib.sha256(digest_source).hexdigest()
    cached = st.session_state.get("ysb_dashboard_b_upload")
    if cached and cached["digest"] == digest:
        data = cached["data"]
        _render_input_summary(data)
        return data
    try:
        with st.spinner("正在识别并处理商家原始数据…"):
            data = build_dashboard_b_from_uploads(payloads, POLICY_PATH, RULES_PATH)
    except DashboardBInputError as error:
        st.error(f"{error} 已恢复默认众恩德 Demo。")
        return _load_default_demo()
    st.session_state["ysb_dashboard_b_upload"] = {"digest": digest, "data": data}
    _render_input_summary(data)
    return data


def _load_default_demo() -> DashboardBData | None:
    """Load the aggregate-only default demo used whenever no valid upload exists."""
    try:
        return _cached_public_demo(str(PUBLIC_DEMO_DIR))
    except DashboardBInputError as error:
        st.error(str(error))
        return None


@st.cache_data(show_spinner=False)
def _cached_public_demo(directory: str) -> DashboardBData:
    """Cache the tracked daily aggregates across Streamlit reruns."""
    return load_public_demo_dashboard_b(Path(directory))


def _select_periods(data: DashboardBData) -> DashboardBData | None:
    """Render the two date ranges and rebuild the selected comparison."""
    if not all(
        value is not None
        for value in (
            data.baseline_start,
            data.baseline_end,
            data.comparison_start,
            data.comparison_end,
            data.available_start,
            data.available_end,
        )
    ):
        return data
    source_key = hashlib.sha256(
        f"{data.source_label}|{data.available_start}|{data.available_end}".encode("utf-8")
    ).hexdigest()[:12]
    render_section_header("对比周期", "日期边界来自当前数据源的实际可用范围。")
    columns = st.columns(2)
    with columns[0]:
        baseline = st.date_input(
            "基准周期",
            value=(data.baseline_start, data.baseline_end),
            min_value=data.available_start,
            max_value=data.available_end,
            key=f"ysb_b_baseline_{source_key}",
        )
    with columns[1]:
        comparison = st.date_input(
            "对比周期",
            value=(data.comparison_start, data.comparison_end),
            min_value=data.available_start,
            max_value=data.available_end,
            key=f"ysb_b_comparison_{source_key}",
        )
    if not isinstance(baseline, tuple) or len(baseline) != 2:
        st.info("请选择完整的基准周期开始和结束日期。")
        return None
    if not isinstance(comparison, tuple) or len(comparison) != 2:
        st.info("请选择完整的对比周期开始和结束日期。")
        return None
    baseline_days = (baseline[1] - baseline[0]).days + 1
    comparison_days = (comparison[1] - comparison[0]).days + 1
    st.caption(f"基准期：{baseline_days} 天　·　对比期：{comparison_days} 天")
    if baseline_days != comparison_days:
        st.warning("两个周期长度不同，金额、订单量及流量总量受周期天数影响，请谨慎比较。")
    try:
        return select_dashboard_b_periods(
            data,
            baseline_start=baseline[0],
            baseline_end=baseline[1],
            comparison_start=comparison[0],
            comparison_end=comparison[1],
        )
    except DashboardBInputError as error:
        st.warning(str(error))
        return None


def _render_input_summary(data: DashboardBData) -> None:
    summary = data.input_summary
    st.sidebar.caption("已识别")
    st.sidebar.markdown("✓ 订单明细")
    st.sidebar.markdown("✓ 流量数据" if has_capability(data, HAS_TRAFFIC) else "— 流量数据未提供")
    st.sidebar.markdown(
        f"✓ 活动数据 × {summary.activity_file_count}"
        if has_capability(data, HAS_ACTIVITY)
        else "— 活动数据未提供"
    )
    st.sidebar.markdown("✓ 药店维度" if summary.customer_available else "— 药店维度不可用")
    if summary.legacy:
        st.sidebar.caption("已自动兼容旧版药师帮日报。")
    st.sidebar.caption("默认比较周期已根据订单实际日期自动选择，可在页面顶部修改。")
    if summary.unknown_labels:
        st.sidebar.caption(f"未识别文件：{'、'.join(summary.unknown_labels)}")


def _overview(data: DashboardBData) -> None:
    metrics = current_metrics(data)
    result = result_decomposition(data)
    render_section_header("经营概览", f"数据来源：{data.source_label}")
    first = st.columns(4)
    with first[0]:
        render_metric_card("对比期进货金额", _money(metrics["purchase_amount"]), data.current_period, "primary")
    with first[1]:
        render_metric_card(
            "进货金额变化",
            _signed_money(metrics["purchase_amount_change"]),
            _pct(metrics["purchase_amount_change_rate"]),
            "negative"
            if pd.notna(metrics["purchase_amount_change"])
            and float(metrics["purchase_amount_change"]) < 0
            else "positive",
        )
    with first[2]:
        order_value = int(metrics["order_count_change"]) if pd.notna(metrics["order_count_change"]) else None
        render_metric_card("订单数变化", "不可用" if order_value is None else f"{'↑' if order_value > 0 else '↓' if order_value < 0 else '—'} {abs(order_value):,}", _pct(metrics["order_count_change_rate"]), "positive" if order_value is not None and order_value >= 0 else "negative")
    with first[3]:
        render_metric_card(
            "客单价变化",
            _signed_money(metrics["aov_change"]),
            _pct(metrics["aov_change_rate"]),
            "negative"
            if pd.notna(metrics["aov_change"]) and float(metrics["aov_change"]) < 0
            else "positive",
        )
    st.caption(
        f"判断：{_driver_label(result['driver_classification'])} · "
        f"数据可信度：{_evidence_label(result['evidence_level'])}"
    )


def _diagnosis_hero(data: DashboardBData) -> None:
    """Render the existing result fact as a compact, Chinese business summary."""
    metrics = current_metrics(data)
    result = result_decomposition(data)
    change_rate = float(metrics["purchase_amount_change_rate"])
    direction = "下降" if change_rate < 0 else "上升"
    order_change = _pct(metrics["order_count_change_rate"])
    aov_change = _pct(metrics["aov_change_rate"])
    changes_have_same_direction = float(metrics["order_count_change_rate"]) * float(metrics["aov_change_rate"]) > 0
    connector = "，" if changes_have_same_direction else "，但"
    driver_label = _driver_label(result["driver_classification"])
    if (
        result["driver_classification"] == "MIXED"
        and float(metrics["order_count_change_rate"]) < 0
        and float(metrics["aov_change_rate"]) < 0
    ):
        driver_label = "订单量与客单价共同下滑"
    st.markdown(
        "<section class=\"ops-diagnosis-hero\">"
        f"<h3>对比期进货金额较基准期{direction} {abs(change_rate):.1%}</h3>"
        f"<p>订单数 {escape(order_change)}{connector}客单价 {escape(aov_change)}；"
        f"对比期变化主要表现为「{escape(driver_label)}」。</p>"
        "</section>",
        unsafe_allow_html=True,
    )
    render_status_badge(_driver_label(result["driver_classification"]))
    render_status_badge(_evidence_label(result["evidence_level"]))


def _facts(data: DashboardBData) -> None:
    facts = core_facts(data)
    render_section_header("诊断要点", "以下内容直接呈现既有 B2 facts 与 B1 汇总，不生成经营建议。")
    dimension_labels = {"RESULT": "经营结果", "TRAFFIC": "流量", "ACTIVITY": "活动分析", "PRODUCT": "商品", "CUSTOMER": "药店"}
    for start in range(0, len(facts), 3):
        group = facts.iloc[start : start + 3]
        cards = st.columns(len(group), gap="small")
        for column, fact in zip(cards, group.itertuples(index=False), strict=True):
            with column:
                label = dimension_labels.get(fact.diagnosis_dimension, "数据说明")
                prefix = "限制" if fact.output_type == "LIMITATION" else "信号" if fact.output_type == "SIGNAL" else "事实"
                summary = _business_fact_text(str(fact.fact_text))
                st.markdown(
                    f"<section class=\"ops-compact-fact\"><strong>{escape(label)} · {prefix}</strong>"
                    f"<p>{escape(summary)}</p></section>",
                    unsafe_allow_html=True,
                )
    with st.expander("查看事实证据等级", expanded=False):
        for fact in facts.itertuples(index=False):
            label = dimension_labels.get(fact.diagnosis_dimension, "数据说明")
            st.markdown(
                f"**{label} · {_evidence_label(fact.evidence_level)}**"
                f" {_business_fact_text(str(fact.fact_text))}"
            )


def _result(data: DashboardBData) -> None:
    result = result_decomposition(data)
    render_section_header("结果拆解", "将对比期较基准期的进货金额变化拆为订单量与客单价两项影响。")
    cards = st.columns(3)
    with cards[0]:
        render_metric_card("进货金额变化", _signed_money(result["purchase_amount_change"], force_wan=True), "两项影响合计", "negative" if result["purchase_amount_change"] < 0 else "positive")
    with cards[1]:
        render_metric_card("订单量效应", _signed_money(result["order_effect"], force_wan=True), "订单量变化带来的影响", "positive" if result["order_effect"] >= 0 else "negative")
    with cards[2]:
        render_metric_card("客单价效应", _signed_money(result["aov_effect"], force_wan=True), "客单价变化带来的影响", "positive" if result["aov_effect"] >= 0 else "negative")
    render_signed_contributions(
        (
            ("订单量效应", result["order_effect"]),
            ("客单价效应", result["aov_effect"]),
        )
    )
    st.caption(f"两项拆解误差：{_money(result['decomposition_error'])}；数据由所选日期周期实时重算。")


def _traffic(data: DashboardBData) -> None:
    render_section_header("流量表现：本店 vs 同行", "比较两个周期的曝光、点击和访客变化，仅呈现事实与信号。")
    if data.traffic.empty:
        st.info("当前所选周期无可用流量数据。")
        return
    display = data.traffic.rename(
        columns={
            "metric": "流量指标", "previous_own": "基准期本店", "current_own": "对比期本店",
            "own_change_rate": "本店变化", "previous_peer": "基准期同行", "current_peer": "对比期同行",
            "peer_change_rate": "同行变化", "relative_gap": "相对同行差距",
        }
    ).copy()
    for column in ("基准期本店", "对比期本店", "基准期同行", "对比期同行"):
        display[column] = display[column].map(lambda value: f"{int(value):,}")
    for column in ("本店变化", "同行变化", "相对同行差距"):
        display[column] = display[column].map(lambda value: "不可用" if pd.isna(value) else f"{float(value):+.1%}")
    st.dataframe(display, hide_index=True, width="stretch")
    visitor = data.traffic[data.traffic["metric"].eq("访客")].iloc[0]
    st.info(
        f"本店访客{_pct_direction(visitor['own_change_rate'])}，同期同行"
        f"{_pct_direction(visitor['peer_change_rate'])}；两者仅作同期变化比较。"
    )
    st.caption("该信号不证明流量下降导致进货金额下降；当前不计算 CTR 或访客到订单转化率。")


def _activity(data: DashboardBData) -> None:
    render_section_header("活动分析", "先查看活动类型，再下钻到订单中实际出现的具体活动。")
    if data.activities.empty or data.activity_details.empty:
        st.info("当前所选周期无可用活动数据。")
        return
    st.markdown("#### 活动类型概览")
    display = data.activities.rename(
        columns={
            "activity_type": "活动类型", "previous_amount": "基准期进货金额", "current_amount": "对比期进货金额",
            "amount_change": "金额变化", "change_rate": "变化率", "current_amount_share": "对比期金额占比",
            "negative_contribution": "负向变化贡献度",
        }
    ).copy()
    for column in ("基准期进货金额", "对比期进货金额", "金额变化"):
        display[column] = display[column].map(format_metric_value)
    for column in ("变化率", "对比期金额占比", "负向变化贡献度"):
        display[column] = display[column].map(lambda value: "不可用" if pd.isna(value) else f"{float(value):.1%}")
    st.dataframe(
        display[["活动类型", "基准期进货金额", "对比期进货金额", "金额变化", "变化率", "对比期金额占比", "负向变化贡献度"]],
        hide_index=True,
        width="stretch",
        column_config={"活动类型": st.column_config.TextColumn(width="large")},
    )
    losses = data.activities[data.activities["amount_change"].lt(0)].sort_values("amount_change")
    if not losses.empty:
        top = losses.iloc[0]
        st.info(
            f"主要损失来自{top['activity_type']}：进货金额减少 {abs(float(top['amount_change'])) / 10_000:.2f} 万，"
            f"占活动类型全部负向变化 {float(top['negative_contribution']):.1%}。"
        )

    st.markdown("#### 具体活动")
    options = data.activities["activity_type"].astype(str).tolist()
    selected_type = st.selectbox("选择活动类型", options, index=0)
    summary = activity_detail_summary(data, selected_type)
    cards = st.columns(4)
    with cards[0]:
        render_metric_card("具体活动数", f"{summary['activity_count']:,}", selected_type)
    with cards[1]:
        render_metric_card("负向活动数", f"{summary['negative_count']:,}", "金额变化 < 0", "negative")
    with cards[2]:
        render_metric_card("正向活动数", f"{summary['positive_count']:,}", "金额变化 > 0", "positive")
    with cards[3]:
        render_metric_card(
            "Top 5 Loss 集中度",
            f"{float(summary['top5_loss_concentration']):.1%}",
            f"金额无变化 {summary['flat_count']:,} 个",
        )

    loss_tab, growth_tab = st.tabs(["Top Loss", "Top Growth"])
    with loss_tab:
        _activity_detail_table(
            activity_top_contributors(data, selected_type, positive=False),
            positive=False,
        )
    with growth_tab:
        _activity_detail_table(
            activity_top_contributors(data, selected_type, positive=True),
            positive=True,
        )
    if data.activity_mapping_rate is not None:
        st.caption(
            f"订单活动 ID 与活动快照的映射覆盖率：{data.activity_mapping_rate:.1%}。"
            "活动状态如展示，仅代表当前上传快照，不代表比较月份的历史状态。"
        )


def _activity_detail_table(frame: pd.DataFrame, *, positive: bool) -> None:
    """Present activity contributors with business labels before their stable ID."""
    display = frame.copy()
    display["活动主题"] = display["theme_name"].map(
        lambda value: str(value).strip() if pd.notna(value) and str(value).strip() else "—"
    )
    display["商品/活动内容"] = display["display_name"].map(
        lambda value: str(value).strip() if pd.notna(value) and str(value).strip() else "—"
    )
    display = display.rename(
        columns={
            "activity_id": "活动ID",
            "product_code": "商品编码",
            "previous_amount": "基准期金额",
            "current_amount": "对比期金额",
            "amount_change": "变化额",
            "change_rate": "变化率",
            "previous_orders": "基准期订单数",
            "current_orders": "对比期订单数",
            "period_status": "周期状态",
            "negative_contribution": "负向贡献占比",
            "current_snapshot_status": "当前快照状态",
        }
    )
    display["周期状态"] = display["周期状态"].map(ACTIVITY_STATUS_LABELS)
    for column in ("基准期金额", "对比期金额"):
        display[column] = display[column].map(format_metric_value)
    display["变化额"] = display["变化额"].map(_signed_activity_money)
    display["负向贡献占比"] = display["负向贡献占比"].map(lambda value: f"{float(value):.1%}")
    columns = ["活动主题", "商品/活动内容", "变化额", "基准期金额", "对比期金额", "周期状态"]
    if not positive:
        columns.append("负向贡献占比")
    columns.append("活动ID")
    st.dataframe(
        display[columns],
        hide_index=True,
        width="stretch",
        column_config={
            "活动主题": st.column_config.TextColumn(width="medium"),
            "商品/活动内容": st.column_config.TextColumn(width="large"),
            "变化额": st.column_config.TextColumn(width="small"),
            "基准期金额": st.column_config.TextColumn(width="small"),
            "对比期金额": st.column_config.TextColumn(width="small"),
            "周期状态": st.column_config.TextColumn(width="medium"),
            "负向贡献占比": st.column_config.TextColumn(width="small"),
            "活动ID": st.column_config.TextColumn(width="medium"),
        },
    )


def _signed_activity_money(value: object) -> str:
    """Format an activity change with an explicit plus or minus sign."""
    if pd.isna(value):
        return "不可用"
    amount = float(value)
    prefix = "+" if amount > 0 else "-" if amount < 0 else ""
    return f"{prefix}{format_metric_value(abs(amount))}"


def _customer(data: DashboardBData) -> None:
    render_section_header("药店诊断", "药店贡献可独立回加到总进货金额变化。", "高可信")
    summary, error = contribution_summary(data, "CUSTOMER")
    display = summary.copy()
    display["周期状态"] = display["period_status"].map(CUSTOMER_LABELS)
    display = display.rename(
        columns={"entity_count": "药店数", "previous_amount": "基准期进货金额", "current_amount": "对比期进货金额", "amount_change": "进货金额贡献"}
    )
    for column in ("基准期进货金额", "对比期进货金额", "进货金额贡献"):
        display[column] = display[column].map(format_metric_value)
    st.dataframe(
        display[["周期状态", "药店数", "基准期进货金额", "对比期进货金额", "进货金额贡献"]],
        hide_index=True,
        width="stretch",
        column_config={"周期状态": st.column_config.TextColumn(width="large")},
    )
    if abs(error) <= 0.01:
        st.success(f"药店贡献可回加到总进货金额变化；核对误差 {_money(error)}。")
    else:
        st.error(f"药店贡献核对误差：{_money(error)}。")
    union_count = int(summary["entity_count"].sum())
    retained_count = int(summary.loc[summary["period_status"].eq("RETAINED"), "entity_count"].iloc[0])
    overlap = retained_count / union_count if union_count else None
    st.info(
        f"两个周期持续活跃药店占两个周期去重活跃药店 {_ratio(overlap)}。"
        "这是周期活跃重合情况，请勿将基准期活跃、对比期未活跃药店直接解释为永久流失。"
    )
    loss_tab, growth_tab = st.tabs(["负向贡献药店", "正向贡献药店"])
    with loss_tab:
        _customer_table(top_contributors(data, "CUSTOMER", positive=False))
    with growth_tab:
        _customer_table(top_contributors(data, "CUSTOMER", positive=True))


def _customer_table(frame: pd.DataFrame) -> None:
    display = frame[["customer_name", "customer_key", "previous_amount", "current_amount", "amount_change", "period_status"]].rename(
        columns={"customer_name": "药店", "customer_key": "药店编码", "previous_amount": "基准期进货金额", "current_amount": "对比期进货金额", "amount_change": "金额变化", "period_status": "周期状态"}
    )
    display["周期状态"] = display["周期状态"].map(CUSTOMER_LABELS)
    for column in ("基准期进货金额", "对比期进货金额", "金额变化"):
        display[column] = display[column].map(format_metric_value)
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "药店": st.column_config.TextColumn(width="large"),
            "药店编码": st.column_config.TextColumn(width="medium"),
            "基准期进货金额": st.column_config.TextColumn(width="small"),
            "对比期进货金额": st.column_config.TextColumn(width="small"),
            "金额变化": st.column_config.TextColumn(width="small"),
            "周期状态": st.column_config.TextColumn(width="medium"),
        },
    )


def _product(data: DashboardBData) -> None:
    render_section_header("商品诊断", "商品贡献可独立回加到总进货金额变化。", "中等可信")
    summary, error = contribution_summary(data, "PRODUCT")
    display = summary.copy()
    display["周期状态"] = display["period_status"].map(PRODUCT_LABELS)
    display = display.rename(
        columns={"entity_count": "商品数", "previous_amount": "基准期进货金额", "current_amount": "对比期进货金额", "amount_change": "进货金额贡献"}
    )
    for column in ("基准期进货金额", "对比期进货金额", "进货金额贡献"):
        display[column] = display[column].map(format_metric_value)
    st.dataframe(
        display[["周期状态", "商品数", "基准期进货金额", "对比期进货金额", "进货金额贡献"]],
        hide_index=True,
        width="stretch",
        column_config={"周期状态": st.column_config.TextColumn(width="large")},
    )
    if abs(error) <= 0.01:
        st.success(f"商品贡献可回加到总进货金额变化；核对误差 {_money(error)}。")
    else:
        st.error(f"商品贡献核对误差：{_money(error)}。")
    loss_tab, growth_tab = st.tabs(["负向贡献商品", "正向贡献商品"])
    with loss_tab:
        _product_table(top_contributors(data, "PRODUCT", positive=False))
    with growth_tab:
        _product_table(top_contributors(data, "PRODUCT", positive=True))
    if data.products["mapping_quality_status"].eq("CONFLICT").any():
        st.caption("部分商品存在映射冲突，详细说明见页面底部的数据说明。")


def _product_table(frame: pd.DataFrame) -> None:
    display = frame[["product_name", "product_key", "previous_amount", "current_amount", "amount_change", "mapping_quality_status"]].rename(
        columns={"product_name": "商品", "product_key": "商品ID", "previous_amount": "基准期进货金额", "current_amount": "对比期进货金额", "amount_change": "金额变化", "mapping_quality_status": "映射质量"}
    )
    display["映射质量"] = display["映射质量"].map(lambda value: "存在映射冲突" if value == "CONFLICT" else "映射正常")
    for column in ("基准期进货金额", "对比期进货金额", "金额变化"):
        display[column] = display[column].map(format_metric_value)
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "商品": st.column_config.TextColumn(width="large"),
            "商品ID": st.column_config.TextColumn(width="small"),
            "基准期进货金额": st.column_config.TextColumn(width="small"),
            "对比期进货金额": st.column_config.TextColumn(width="small"),
            "金额变化": st.column_config.TextColumn(width="small"),
            "映射质量": st.column_config.TextColumn(width="medium"),
        },
    )


def _evidence(data: DashboardBData) -> None:
    render_section_header("数据说明与限制", "数据可信度：有限。详细口径和限制按需展开查看。", "证据有限")
    product_conflicts = quality_count(data, "PRODUCT_KEY_MAPPING_CONFLICT")
    with st.expander("查看数据口径与限制", expanded=False):
        product_conflict_text = (
            "商品映射冲突数量暂不可用。"
            if product_conflicts is None
            else (
                f"{product_conflicts:,} 个商品存在展示映射冲突，不影响商品金额贡献计算，"
                "但商品名称/规格展示可能受限。"
            )
        )
        rows = [
            {"数据说明": "订单口径", "当前状态": "订单状态、退款、配送和结算口径尚未完全确认。"},
            {"数据说明": "商品映射", "当前状态": product_conflict_text},
            {"数据说明": "药店贡献", "当前状态": data.customer_unavailable_reason or "可用"},
        ]
        if data.activity_unmatched_snapshot_count:
            rows.append(
                {
                    "数据说明": "活动快照",
                    "当前状态": "活动快照中存在未出现在当前订单导出周期的活动记录；其不参与所选周期成交贡献计算。",
                }
            )
        if data.activity_display_name_variation_count:
            rows.append(
                {
                    "数据说明": "活动展示名称",
                    "当前状态": "部分活动商品展示名称存在文案差异，不影响金额贡献计算。",
                }
            )
        st.dataframe(rows, hide_index=True, width="stretch")
        st.markdown("**当前系统识别相关经营事实，不自动推断因果。**")
        for statement in (
            "流量下降导致进货金额下降",
            "活动变化导致销售下降",
            "缺货导致商品下降",
            "退款导致金额下降",
            "客户永久流失",
        ):
            st.write(f"- {statement}")


def main() -> None:
    configure_page("YSB Dashboard B · 单商家诊断", show_heading=False)
    uploaded = _render_upload_section()
    data = _get_data(uploaded)
    if data is None:
        return
    data = _select_periods(data)
    if data is None:
        return
    baseline_days = (data.baseline_end - data.baseline_start).days + 1 if data.baseline_start and data.baseline_end else None
    comparison_days = (data.comparison_end - data.comparison_start).days + 1 if data.comparison_start and data.comparison_end else None
    render_page_header(
        "单商家经营诊断",
        "从经营结果依次查看流量、活动分析、商品和可用的药店事实。",
        (
            f"商家：{data.merchant_name or data.source_label}",
            f"基准周期：{data.baseline_start} ～ {data.baseline_end}",
            f"对比周期：{data.comparison_start} ～ {data.comparison_end}",
            f"基准期天数：{baseline_days}",
            f"对比期天数：{comparison_days}",
            "数据口径：进货金额",
        ),
    )
    _overview(data)
    _diagnosis_hero(data)
    _facts(data)
    _result(data)
    if has_capability(data, HAS_TRAFFIC):
        _traffic(data)
    if has_capability(data, HAS_ACTIVITY):
        _activity(data)
    if has_capability(data, HAS_PRODUCT):
        _product(data)
    if has_capability(data, HAS_CUSTOMER):
        _customer(data)
    elif data.customer_unavailable_reason:
        render_section_header("药店诊断", "当前订单源不支持药店贡献分析。")
        st.info(data.customer_unavailable_reason)
    _evidence(data)


main()
