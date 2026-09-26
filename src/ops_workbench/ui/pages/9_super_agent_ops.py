"""Five action-first views for a fully simulated agent operating demo."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ops_workbench.metrics.super_agent import HEAD
from ops_workbench.diagnostics.super_agent import BOTTLENECKS
from ops_workbench.ui.super_agent_dashboard import build_dashboard, decision_table, fmt_money, fmt_pct
from ops_workbench.ui.components.common import configure_page


def _data():
    return build_dashboard()


def _overview(data) -> None:
    k = data.kpis
    cols = st.columns(6)
    for col, (name, value) in zip(cols, [("头部人数", k["head_count"]), ("头部净新增", k["net_new_head"]),
                                   ("准头部晋级率", fmt_pct(k["near_top_to_head_upgrade_rate"])),
                                   ("头部留存率", fmt_pct(k["head_retention_rate"])),
                                   ("高潜池人数", k["high_potential_count"]), ("待经营高优任务", k["p0_count"])]):
        col.metric(name, value)
    st.subheader("城市经营对比")
    city = data.agents.groupby("city").agg(头部人数=("stage", lambda x: x.isin(HEAD).sum()),
        高潜人数=("stage", lambda x: x.eq("高潜").sum()), 待经营高优任务=("priority", lambda x: x.eq("P0").sum())).reset_index().rename(columns={"city": "城市"})
    st.dataframe(city, hide_index=True, width="stretch")
    st.subheader("本周期新增与流失头部")
    st.write(f"新增头部 {k['entered_head_count']} 人；退出头部 {k['exited_head_count']} 人；净新增 {k['net_new_head']} 人；头部留存 {fmt_pct(k['head_retention_rate'])}。迁移按相邻周快照计算。")
    st.subheader("本周任务负荷与首要经营问题")
    load = data.agents.loc[data.agents["priority"] == "P0"].groupby("manager_name").size().rename("待处理").reset_index().rename(columns={"manager_name": "城市经理"})
    st.dataframe(load, hide_index=True, width="stretch")
    top_issue = data.agents.loc[data.agents["priority"].isin(["P0", "P1"]), "primary_bottleneck"].value_counts()
    st.write("当前高优先人群最多的同群偏低环节：" + (BOTTLENECKS.get(top_issue.index[0], "未见持续异常") if not top_issue.empty else "暂无"))


def _funnel(data) -> None:
    order = ["活跃", "高潜", "准头部", "新晋头部", "稳定头部"]
    count = data.agents["stage"].value_counts()
    st.subheader("成长阶段")
    st.dataframe(pd.DataFrame({"阶段": order, "人数": [int(count.get(x, 0)) for x in order]}), hide_index=True, width="stretch")
    dates = sorted(data.history["snapshot_date"].unique())
    prior = data.history.loc[data.history["snapshot_date"] == dates[-2], ["agent_id", "stage"]].rename(columns={"stage": "上周"})
    now = data.history.loc[data.history["snapshot_date"] == dates[-1], ["agent_id", "stage"]].rename(columns={"stage": "本周"})
    moves = prior.merge(now, on="agent_id")
    st.subheader("阶段迁移与晋级回落")
    st.dataframe(moves.groupby(["上周", "本周"]).size().rename("人数").reset_index(), hide_index=True, width="stretch")
    hist = data.history.sort_values(["agent_id", "snapshot_date"]).copy()
    hist["change"] = hist["stage"].ne(hist.groupby("agent_id")["stage"].shift())
    hist["run"] = hist.groupby("agent_id")["change"].cumsum()
    runs = hist.groupby(["agent_id", "run", "stage"]).size().rename("周期").reset_index()
    st.subheader("平均阶段停留周期")
    st.dataframe(runs.groupby("stage")["周期"].mean().round(1).rename("平均周数").reset_index().rename(columns={"stage": "阶段"}), hide_index=True, width="stretch")


def _decision(data) -> None:
    frame = data.agents
    cols = st.columns(6)
    for col, (label, field) in zip(cols, [("城市", "city"), ("城市经理", "manager_name"), ("生命周期", "stage"),
                                          ("优先级", "priority"), ("主瓶颈", "primary_bottleneck"), ("置信度", "confidence")]):
        values = ["全部"] + (["低", "中", "高"] if field == "confidence" else sorted(frame[field].dropna().unique().tolist()))
        chosen = col.selectbox(label, values, key=f"filter_{field}")
        if chosen != "全部":
            if field == "confidence":
                frame = frame.loc[frame["confidence"].map(lambda x: "高" if x >= 0.8 else "中" if x >= 0.65 else "低") == chosen]
            else:
                frame = frame.loc[frame[field] == chosen]
    frame = frame.sort_values(["priority", "priority_score"], ascending=[True, False])
    st.caption("默认按 P0、P1、P2 与优先级分排序；主瓶颈只由持续或极端同群偏低信号触发。")
    st.dataframe(decision_table(frame), hide_index=True, width="stretch", height=470)
    if frame.empty:
        st.info("当前筛选没有经纪人。")
        return
    case_options = ["自由选择"] + [f"案例{x}" for x in "ABCDEFGH" if frame["case"].eq(x).any()]
    case_choice = st.selectbox("代表案例快速查看", case_options)
    choice = st.selectbox("查看经纪人详情", frame["agent_name"].tolist()) if case_choice == "自由选择" else frame.loc[frame["case"] == case_choice[-1], "agent_name"].iloc[0]
    row = frame.loc[frame["agent_name"] == choice].iloc[0]
    st.markdown(f"**事实｜{choice}：近28天成交 {int(row['deal_count'])} 单，成交额 {fmt_money(row['deal_gtv'])}；近56天带看 {int(row['showings_56d'])} 次。**")
    gap = {"deal_count": "成交量", "deal_gtv": "成交额"}.get(row["top_gap_dimension"], "不可用")
    st.write(f"同群：{row['peer_scope']}（样本 {int(row['peer_sample_size'])}）；潜力百分位 {fmt_pct(row['potential_percentile'])}；头部差距 {gap}。")
    ratios = pd.DataFrame({"环节": ["商机→承接", "承接→跟进", "跟进→带看", "带看→成交（56天）"],
        "本人": [fmt_pct(row[x]) for x in ("acceptance_rate", "followup_rate", "showing_rate", "closing_56d")],
        "同群百分位": [fmt_pct(row[x]) for x in ("acceptance_rate_pct", "followup_rate_pct", "showing_rate_pct", "closing_rate_pct")]})
    st.dataframe(ratios, hide_index=True, width="stretch")
    if pd.isna(row["potential_score"]):
        st.write("潜力分不适用：当前已达头部标准或缺少可计算证据。")
    else:
        st.write("潜力拆解：" + "｜".join(f"{label} {row[key]:.1f}" if pd.notna(row[key]) else f"{label} 不可用" for label, key in [("成长", "growth_score"), ("转化", "conversion_score"), ("稳定", "stability_score"), ("可经营空间", "headroom_score")]))
    st.write(f"诊断｜{row['diagnostic_status']}；主瓶颈 {BOTTLENECKS.get(row['primary_bottleneck'], '无')}；次瓶颈 {BOTTLENECKS.get(row['secondary_bottleneck'], '无')}。")
    st.write("历史阶段：" + " → ".join(data.history.loc[data.history["agent_id"] == row["agent_id"], "stage"].tolist()))
    st.write(f"最近触达：{row['last_action_at'] if pd.notna(row['last_action_at']) else '无'}；近7/14/30天：{row['touches_7d']}/{row['touches_14d']}/{row['touches_30d']}次")
    actions = data.recommendations.loc[data.recommendations["agent_id"] == row["agent_id"]]
    st.subheader("推荐动作 Top3")
    st.dataframe(actions.loc[actions["rank_no"].between(1, 3), ["rank_no", "action_name", "reason_text", "recommendation_score", "valid_until"]].rename(columns={"rank_no": "排序", "action_name": "动作", "reason_text": "理由", "recommendation_score": "推荐分", "valid_until": "有效期"}), hide_index=True, width="stretch")
    with st.expander("查看被抑制动作及原因"):
        st.dataframe(actions.loc[actions["suppressed_flag"], ["action_name", "suppression_reason"]].rename(columns={"action_name": "动作", "suppression_reason": "抑制原因"}), hide_index=True, width="stretch")


def _tasks(data) -> None:
    manager = st.selectbox("先选择城市经理", sorted(data.agents["manager_name"].unique()))
    agents = data.agents.loc[data.agents["manager_name"] == manager]
    tasks = agents.loc[agents["priority"].isin(["P0", "P1"])].sort_values("priority_score", ascending=False)
    state = st.session_state.setdefault("super_agent_tasks", {})
    skip_reasons = st.session_state.setdefault("super_agent_skip_reasons", {})
    st.caption("演示状态仅在当前会话有效，刷新后可能重置。")
    as_of = data.facts["date"].max()

    def status(row) -> str:
        """Show terminal demo choices or computed expiry/cooldown state."""
        saved = state.get(row["agent_id"])
        if saved:
            return saved
        if row["valid_until"] < as_of:
            return "已过期"
        if pd.notna(row["cooldown_until"]) and row["cooldown_until"].date() > as_of and row["last_action_code"] == row["primary_action_code"]:
            return "冷却中"
        return "待处理"

    task_states = {row["agent_id"]: status(row) for _, row in tasks.iterrows()}
    cols = st.columns(6)
    stats = [("本周P0容量", data.policy["priority"]["p0_capacity_per_manager"]), ("当前P0人数", int(agents["priority"].eq("P0").sum())),
             ("待处理", sum(x == "待处理" for x in task_states.values())),
             ("今日/即将到期", int((tasks["valid_until"] <= as_of + pd.Timedelta(days=3)).sum())),
             ("已执行", sum(x == "已执行" for x in task_states.values())),
             ("跳过", sum(x == "跳过" for x in task_states.values()))]
    for col, (name, value) in zip(cols, stats):
        col.metric(name, value)
    display = tasks[["agent_name", "priority", "primary_action", "valid_until"]].copy()
    display["任务状态"] = tasks["agent_id"].map(task_states)
    st.dataframe(display.rename(columns={"agent_name": "经纪人", "priority": "优先级", "primary_action": "建议动作", "valid_until": "有效期"}), hide_index=True, width="stretch", height=390)
    if tasks.empty:
        st.info("当前经理没有 P0/P1 任务。")
        return
    choice = st.selectbox("选择任务", tasks["agent_name"].tolist())
    row = tasks.loc[tasks["agent_name"] == choice].iloc[0]
    with st.container(border=True):
        st.markdown(f"**{row['priority']}｜{row['agent_name']}｜{row['primary_action']}**")
        detail = f"{row['recommendation_reason']}｜有效至 {row['valid_until']}｜状态：{task_states[row['agent_id']]}"
        if row["agent_id"] in skip_reasons:
            detail += f"｜跳过原因：{skip_reasons[row['agent_id']]}"
        st.caption(detail)
        cols = st.columns([1, 1, 1, 3])
        if cols[0].button("接受", key=f"accept_{row['agent_id']}"):
            state[row["agent_id"]] = "已接受"
            st.rerun()
        if cols[1].button("执行", key=f"execute_{row['agent_id']}"):
            state[row["agent_id"]] = "已执行"
            st.rerun()
        reason = cols[3].selectbox("跳过原因", ["请选择原因", "经纪人暂不可联系", "动作不适用", "资源不可用", "其他"], key=f"skip_reason_{row['agent_id']}")
        if cols[2].button("跳过", key=f"skip_{row['agent_id']}"):
            if reason == "请选择原因":
                st.warning("请先选择跳过原因。")
            else:
                state[row["agent_id"]] = "跳过"
                skip_reasons[row["agent_id"]] = reason
                st.rerun()


def _review(data) -> None:
    k = data.action_kpis
    cols = st.columns(5)
    for col, (name, value) in zip(cols, [("推荐人数", k["recommended_count"]), ("接受人数", k["accepted_count"]),
                                   ("执行人数", k["executed_count"]), ("执行率", fmt_pct(k["action_execution_rate"])),
                                   ("执行后改善率", fmt_pct(k["action_improvement_rate"]))]):
        col.metric(name, value)
    st.write(f"晋级率 {fmt_pct(k['upgrade_rate'])}｜平均晋级周期 {k['mean_upgrade_days'] or '不可用'} 天｜动作成本 {fmt_money(k['action_cost'])}｜单个新增头部成本 {fmt_money(k['cost_per_new_head'])}")
    st.dataframe(pd.DataFrame([{"观察窗口": f"{days}天", "可观察执行数": result["eligible"], "改善数": result["improved"], "改善率": fmt_pct(result["improvement_rate"])} for days, result in k["outcome_windows"].items()]), hide_index=True, width="stretch")
    agents = data.agents.merge(data.campaign_exposure, on="agent_id", validate="one_to_one")
    dates = sorted(data.history["snapshot_date"].unique())
    prior = data.history.loc[data.history["snapshot_date"] == dates[-2], ["agent_id", "stage"]].rename(columns={"stage": "上期阶段"})
    agents = agents.merge(prior, on="agent_id")
    agents["晋级"] = agents["上期阶段"].eq("准头部") & agents["stage"].isin(HEAD)
    experiment = agents.groupby("实验分组").agg(人数=("agent_id", "size"), 活动前准头部=("上期阶段", lambda x: x.eq("准头部").sum()), 活动后晋级=("晋级", "sum"))
    experiment["晋级率"] = [fmt_pct(a / b if b else None) for a, b in zip(experiment["活动后晋级"], experiment["活动前准头部"])]
    st.subheader("模拟活动实验")
    st.dataframe(experiment.reset_index(), hide_index=True, width="stretch")
    rates = experiment["活动后晋级"].div(experiment["活动前准头部"].where(experiment["活动前准头部"].ne(0)))
    st.write("晋级率差异：" + fmt_pct(rates.get("实验组") - rates.get("对照组")))
    st.caption("分组仅为固定规则模拟展示；普通前后对比不能直接证明因果。真实效果需随机分组、曝光记录与成本核算。")


def main() -> None:
    """Render the independent, action-first simulated agent product."""
    configure_page("超级经纪人运营系统", show_heading=False)
    st.markdown("""<style>
    .stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label,
    .stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricLabel"] {
        color: #182230 !important;
    }
    .stApp [data-testid="stCaptionContainer"] p { color: #667085 !important; }
    </style>""", unsafe_allow_html=True)
    st.title("超级经纪人运营系统｜模拟经营Demo")
    st.caption("模拟经营口径 / Demo 数据｜成都、重庆、武汉、西安及经纪人、城市经理均为虚构演示。")
    st.info("当前头部、高潜、准头部等标准均为可配置模拟参数，不代表贝壳真实内部口径。")
    data = _data()
    view = st.radio("产品视图", ["经营总览", "成长漏斗", "经营决策中心", "城市经理工作台", "策略实验与复盘"], horizontal=True)
    {"经营总览": _overview, "成长漏斗": _funnel, "经营决策中心": _decision,
     "城市经理工作台": _tasks, "策略实验与复盘": _review}[view](data)


main()
