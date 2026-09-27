"""Five action-first views for a fully simulated agent operating demo."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ops_workbench.metrics.super_agent import HEAD
from ops_workbench.diagnostics.super_agent import BOTTLENECKS, load_actions
from ops_workbench.ui.super_agent_dashboard import (build_dashboard, decision_table, fmt_money, fmt_pct,
    record_session_event, session_progress, task_statuses)
from ops_workbench.ui.components.common import configure_page


@st.cache_resource(show_spinner="正在生成固定种子模拟数据…")
def _data():
    return build_dashboard()


def _events() -> list[dict]:
    return st.session_state.setdefault("super_agent_action_events", [])


def _overview(data) -> None:
    k = data.kpis
    cols = st.columns(6)
    for col, (name, value) in zip(cols, [("头部人数", k["head_count"]), ("头部净新增", k["net_new_head"]),
                                   ("准头部晋级率", fmt_pct(k["near_top_to_head_upgrade_rate"])),
                                   ("头部留存率", fmt_pct(k["head_retention_rate"])),
                                   ("高潜池人数", k["high_potential_count"]), ("P0重点经营人数", k["p0_count"])]):
        col.metric(name, value)
    st.subheader("本周经营摘要")
    priority = data.agents.loc[data.agents["priority"] == "P0"]
    cities = data.agents.loc[data.agents["stage"] == "准头部"].groupby("city").size().sort_values(ascending=False)
    city_name = cities.index[0] if not cities.empty else "演示城市"
    near_count = int(cities.iloc[0]) if not cities.empty else 0
    city_p0 = int(((priority["city"] == city_name) & priority["stage"].eq("准头部")).sum())
    issue_counts = priority.loc[priority["primary_bottleneck"] != "none", "primary_bottleneck"].value_counts()
    issue = BOTTLENECKS[issue_counts.index[0]] if not issue_counts.empty else "暂无集中异常"
    risks = int((data.agents["stage"].eq("稳定头部") & data.agents["top_at_risk"]).sum())
    st.write(f"{city_name}当前有 {near_count} 名准头部，其中 {city_p0} 名进入P0；本周重点对象的主要瓶颈为{issue}；{risks} 名稳定头部出现失守风险。以上均为模拟观察。")
    st.subheader("成长结构")
    st.write("活跃 → 高潜 → 准头部 → 新晋头部 → 稳定头部；各阶段人数请查看成长漏斗。")
    st.subheader("本周期新增与流失头部")
    st.write(f"新增头部 {k['entered_head_count']} 人；退出头部 {k['exited_head_count']} 人；净新增 {k['net_new_head']} 人；头部留存 {fmt_pct(k['head_retention_rate'])}。迁移按相邻周快照计算。")
    st.subheader("城市经营对比")
    city = data.agents.groupby("city").agg(头部人数=("stage", lambda x: x.isin(HEAD).sum()),
        高潜人数=("stage", lambda x: x.eq("高潜").sum()), 待经营高优任务=("priority", lambda x: x.eq("P0").sum())).reset_index().rename(columns={"city": "城市"})
    st.dataframe(city, hide_index=True, width="stretch")
    st.subheader("本周执行负荷")
    load = data.agents.loc[data.agents["priority"] == "P0"].groupby("manager_name").size().rename("待处理").reset_index().rename(columns={"manager_name": "城市经理"})
    st.dataframe(load, hide_index=True, width="stretch")


def _funnel(data) -> None:
    order = ["活跃", "高潜", "准头部", "新晋头部", "稳定头部"]
    count = data.agents["stage"].value_counts()
    st.subheader("成长阶段")
    dates = sorted(data.history["snapshot_date"].unique())
    prior = data.history.loc[data.history["snapshot_date"] == dates[-2], ["agent_id", "stage"]].rename(columns={"stage": "上周"})
    now = data.history.loc[data.history["snapshot_date"] == dates[-1], ["agent_id", "stage"]].rename(columns={"stage": "本周"})
    moves = prior.merge(now, on="agent_id")
    ladder = {name: index for index, name in enumerate(["无效/沉默", *order])}
    stage_rows = []
    for stage in order:
        inbound = moves.loc[(moves["本周"] == stage) & (moves["上周"] != stage)]
        outbound = moves.loc[(moves["上周"] == stage) & (moves["本周"] != stage)]
        stage_rows.append({"阶段": stage, "本周人数": int(count.get(stage, 0)), "本周进入": len(inbound), "本周流出": len(outbound),
                           "晋级": int(inbound["上周"].map(ladder).lt(ladder[stage]).sum()),
                           "回落": int(inbound["上周"].map(ladder).gt(ladder[stage]).sum())})
    st.dataframe(pd.DataFrame(stage_rows), hide_index=True, width="stretch")
    st.subheader("阶段迁移与晋级回落")
    st.dataframe(moves.groupby(["上周", "本周"]).size().rename("人数").reset_index(), hide_index=True, width="stretch")
    hist = data.history.sort_values(["agent_id", "snapshot_date"]).copy()
    hist["change"] = hist["stage"].ne(hist.groupby("agent_id")["stage"].shift())
    hist["run"] = hist.groupby("agent_id")["change"].cumsum()
    runs = hist.groupby(["agent_id", "run", "stage"]).size().rename("周期").reset_index()
    st.subheader("近8周观测期内平均连续停留周数")
    st.dataframe(runs.groupby("stage")["周期"].mean().round(1).rename("平均周数").reset_index().rename(columns={"stage": "阶段"}), hide_index=True, width="stretch")


def _decision(data) -> None:
    frame = data.agents
    cols = st.columns(6)
    for col, (label, field) in zip(cols, [("城市", "city"), ("城市经理", "manager_name"), ("生命周期", "stage"),
                                          ("优先级", "priority"), ("主瓶颈", "primary_bottleneck"), ("置信度", "confidence")]):
        values = (["P0/P1", "P0", "P1", "P2", "全部"] if field == "priority" else
                  ["全部"] + (["低", "中", "高"] if field == "confidence" else sorted(frame[field].dropna().unique().tolist())))
        chosen = col.selectbox(label, values, key=f"filter_{field}")
        if chosen == "P0/P1":
            frame = frame.loc[frame["priority"].isin(["P0", "P1"])]
        elif chosen != "全部":
            if field == "confidence":
                frame = frame.loc[frame["confidence"].map(lambda x: "高" if x >= 0.8 else "中" if x >= 0.65 else "低") == chosen]
            else:
                frame = frame.loc[frame[field] == chosen]
    frame = frame.sort_values(["priority", "priority_score"], ascending=[True, False])
    st.caption("默认优先显示 P0 / P1；P2 可从优先级筛选查看。主瓶颈只由持续或极端同群偏低信号触发。")
    statuses = task_statuses(data.agents, _events(), data.facts["date"].max())
    table = decision_table(frame, statuses)
    first = ["优先级", "经纪人", "生命周期", "头部完成度", "潜力分", "置信度", "主瓶颈", "趋势", "首选动作", "推荐原因", "负责人", "任务状态"]
    st.dataframe(table[first], hide_index=True, width="stretch", height=470)
    if frame.empty:
        st.info("当前筛选没有经纪人。")
        return
    case_options = ["自由选择"] + [f"案例{x}" for x in "ABCDEFGH" if frame["case"].eq(x).any()]
    case_choice = st.selectbox("代表案例快速查看", case_options)
    choice = st.selectbox("查看经纪人详情", frame["agent_name"].tolist()) if case_choice == "自由选择" else frame.loc[frame["case"] == case_choice[-1], "agent_name"].iloc[0]
    row = frame.loc[frame["agent_name"] == choice].iloc[0]
    st.subheader("为什么现在关注")
    st.write(f"{row['priority']}｜{row['stage']}｜{row['recommendation_reason']} 当前任务：{statuses[row['agent_id']]}。")
    st.subheader("离模拟头部还有多远")
    st.write(f"头部完成度 {fmt_pct(row['top_progress'])}；主要差距维度：{ {'deal_count': '成交量', 'deal_gtv': '成交额'}.get(row['top_gap_dimension'], '不可用') }。")
    st.subheader("主问题与数据证据")
    st.markdown(f"**事实｜{choice}：近28天成交 {int(row['deal_count'])} 单，成交额 {fmt_money(row['deal_gtv'])}；近56天带看 {int(row['showings_56d'])} 次，观测 {int(row['observed_days_56d'])} 天。**")
    gap = {"deal_count": "成交量", "deal_gtv": "成交额"}.get(row["top_gap_dimension"], "不可用")
    confidence_label = "高" if row["confidence"] >= 0.8 else "中" if row["confidence"] >= 0.65 else "低"
    st.write(f"同群：{row['peer_scope']}（样本 {int(row['peer_sample_size'])}）；潜力百分位 {fmt_pct(row['potential_percentile'])}；置信度 {confidence_label}；头部差距 {gap}。")
    ratios = pd.DataFrame({"环节": ["商机→承接", "承接→跟进", "跟进→带看", "带看→成交（56天）"],
        "本人": [fmt_pct(row[x]) for x in ("acceptance_rate", "followup_rate", "showing_rate", "closing_56d")],
        "同群百分位": [fmt_pct(row[x]) for x in ("acceptance_rate_pct", "followup_rate_pct", "showing_rate_pct", "closing_rate_pct")]})
    st.dataframe(ratios, hide_index=True, width="stretch")
    if pd.isna(row["potential_score"]):
        st.write("潜力分不适用：当前处于头部阶段，或缺少可计算证据。")
    else:
        st.write("潜力拆解：" + "｜".join(f"{label} {row[key]:.1f}" if pd.notna(row[key]) else f"{label} 不可用" for label, key in [("成长", "growth_score"), ("转化", "conversion_score"), ("稳定", "stability_score"), ("可经营空间", "headroom_score")]))
    st.write(f"诊断｜{row['diagnostic_status']}；主瓶颈 {BOTTLENECKS.get(row['primary_bottleneck'], '无')}；次瓶颈 {BOTTLENECKS.get(row['secondary_bottleneck'], '无')}。")
    if row["top_at_risk"]:
        st.warning("头部风险：当前周期未达到模拟头部标准，正处于保留阶段。")
    if row["capacity_deferred"]:
        st.info("容量递延：达到理论 P0 门槛，但本周期城市经理 P0 容量已满，列为 P1。")
    actions = data.recommendations.loc[data.recommendations["agent_id"] == row["agent_id"]]
    st.subheader("推荐动作 Top3")
    st.dataframe(actions.loc[actions["rank_no"].between(1, 3), ["rank_no", "action_name", "reason_text", "recommendation_score", "valid_until"]].rename(columns={"rank_no": "排序", "action_name": "动作", "reason_text": "理由", "recommendation_score": "推荐分", "valid_until": "有效期"}), hide_index=True, width="stretch")
    last_touch = str(row["last_action_at"].date()) if pd.notna(row["last_action_at"]) else "无"
    st.write(f"最近触达：{last_touch}；近7/14/30天：{row['touches_7d']}/{row['touches_14d']}/{row['touches_30d']}次")
    st.write("历史阶段：" + " → ".join(data.history.loc[data.history["agent_id"] == row["agent_id"], "stage"].tolist()))
    with st.expander("查看被抑制动作及原因"):
        st.dataframe(actions.loc[actions["suppressed_flag"], ["action_name", "suppression_reason"]].rename(columns={"action_name": "动作", "suppression_reason": "抑制原因"}), hide_index=True, width="stretch")


def _tasks(data) -> None:
    manager = st.selectbox("先选择城市经理", sorted(data.agents["manager_name"].unique()))
    agents = data.agents.loc[data.agents["manager_name"] == manager]
    tasks = agents.loc[agents["priority"].isin(["P0", "P1"])].sort_values("priority_score", ascending=False)
    st.caption("演示状态仅在当前会话有效，刷新后可能重置。")
    as_of = data.facts["date"].max()
    task_states = task_statuses(tasks, _events(), as_of)
    cols = st.columns(7)
    stats = [("本周P0容量", data.policy["priority"]["p0_capacity_per_manager"]), ("当前P0任务", int(agents["priority"].eq("P0").sum())),
             ("P1待排期", int(agents["priority"].eq("P1").sum())),
             ("容量递延", int(agents["capacity_deferred"].sum())),
             ("已接受", sum(x == "已接受" for x in task_states.values())),
             ("已执行", sum(x == "已执行" for x in task_states.values())),
             ("已跳过", sum(x == "跳过" for x in task_states.values()))]
    for col, (name, value) in zip(cols, stats):
        col.metric(name, value)
    view = st.radio("任务视图", ["P0 本周重点", "P1 待排期", "已处理"], horizontal=True)
    if view == "P0 本周重点":
        visible = tasks.loc[(tasks["priority"] == "P0") & tasks["agent_id"].map(task_states).isin(["待处理", "已接受"])]
    elif view == "P1 待排期":
        visible = tasks.loc[(tasks["priority"] == "P1") & tasks["agent_id"].map(task_states).isin(["待处理", "已接受"])]
    else:
        visible = tasks.loc[tasks["agent_id"].map(task_states).isin(["已执行", "跳过", "已过期", "冷却中"])]
    display = decision_table(visible, task_states)
    st.dataframe(display[["优先级", "经纪人", "生命周期", "主瓶颈", "首选动作", "推荐原因", "有效期", "任务状态", "容量状态"]], hide_index=True, width="stretch", height=390)
    if visible.empty:
        st.info("当前视图没有任务。P1 属于待排期人群，本周优先处理 P0。")
        return
    choice = st.selectbox("选择任务", visible["agent_name"].tolist())
    row = visible.loc[visible["agent_name"] == choice].iloc[0]
    status = task_states[row["agent_id"]]
    with st.container(border=True):
        st.markdown(f"**{row['priority']}｜{row['agent_name']}｜{row['stage']}｜{row['primary_action']}**")
        st.write(f"为什么现在处理：{row['recommendation_reason']}")
        st.caption(f"主瓶颈：{BOTTLENECKS.get(row['primary_bottleneck'], '未见持续异常')}｜有效至 {row['valid_until']}｜状态：{status}" + ("｜本周期容量递延" if row["capacity_deferred"] else ""))
        last_event = next((event for event in reversed(_events()) if event["recommendation_id"] == row["recommendation_id"]), None)
        if last_event and last_event["skip_reason"]:
            st.caption("跳过原因：" + last_event["skip_reason"])
        if row["priority"] == "P1":
            st.info("P1 待排期：本周期暂不占用 P0 执行容量。" + ("本周期容量递延。" if row["capacity_deferred"] else ""))
            return
        if status not in {"待处理", "已接受"}:
            return
        cols = st.columns([1, 1, 1, 3])
        if cols[0].button("接受", key=f"accept_{row['agent_id']}", disabled=status != "待处理"):
            record_session_event(_events(), row, "已接受", pd.Timestamp.now())
            st.rerun()
        if cols[1].button("执行", key=f"execute_{row['agent_id']}", disabled=status != "已接受"):
            record_session_event(_events(), row, "已执行", pd.Timestamp.now())
            st.rerun()
        reason = cols[3].selectbox("跳过原因", ["请选择原因", "经纪人暂不可联系", "动作不适用", "资源不可用", "其他"], key=f"skip_reason_{row['agent_id']}")
        if cols[2].button("跳过", key=f"skip_{row['agent_id']}"):
            if reason == "请选择原因":
                st.warning("请先选择跳过原因。")
            else:
                record_session_event(_events(), row, "跳过", pd.Timestamp.now(), reason)
                st.rerun()


def _review(data) -> None:
    k = data.action_kpis
    st.subheader("本次会话执行进度")
    st.caption("当前会话刚执行的动作尚无未来结果，不计入历史改善或晋级率。")
    progress = session_progress(_events())
    cols = st.columns(3)
    for col, label in zip(cols, ("已接受", "已执行", "跳过")):
        col.metric(label, progress[label])
    st.subheader("历史模拟策略效果")
    st.caption("以下推荐、接受、执行和观察均来自同一批历史模拟 recommendation_id。观察关系不能证明动作导致晋级。")
    main_window = k["outcome_windows"][max(k["outcome_windows"])]
    cols = st.columns(6)
    for col, (name, value) in zip(cols, [("推荐人数", k["recommended_count"]), ("接受人数", k["accepted_count"]),
                                   ("执行人数", k["executed_count"]), ("可观察人数", main_window["observable"]),
                                   ("改善人数", main_window["improved"]), ("晋级头部人数", main_window["upgraded"]) ]):
        col.metric(name, value)
    st.write(f"接受率 {fmt_pct(k['action_accept_rate'])}｜执行率 {fmt_pct(k['action_execution_rate'])}｜跳过人数 {k['skipped_count']}｜样本不足人数 {main_window['insufficient']}")
    mean_days = "不可用" if k["mean_upgrade_days"] is None else f"{k['mean_upgrade_days']:.1f}天"
    st.write(f"执行后改善率 {fmt_pct(main_window['improvement_rate'])}｜执行对象晋级率 {fmt_pct(main_window['upgrade_rate'])}｜平均观察到晋级天数 {mean_days}｜同期动作实际成本 {fmt_money(main_window['cost'])}")
    st.metric("每名观察期内晋级经纪人成本（模拟观察口径）", fmt_money(main_window["cost_per_new_head"]))
    st.caption("该成本指标只能描述观察关系，不能证明动作导致晋级；未执行的推荐不产生实际成本。")
    st.dataframe(pd.DataFrame([{"观察窗口": f"{days}天", "执行对象": result["eligible"], "可观察": result["observable"], "样本不足": result["insufficient"], "改善": result["improved"], "改善率": fmt_pct(result["improvement_rate"]), "晋级头部": result["upgraded"], "晋级率": fmt_pct(result["upgrade_rate"])} for days, result in k["outcome_windows"].items()]), hide_index=True, width="stretch")
    st.subheader("按动作复盘（28天观察窗）")
    names = {action["action_code"]: action["action_name"] for action in load_actions()}
    st.dataframe(pd.DataFrame([{"动作": names.get(row["action_code"], row["action_code"]), "执行次数": row["executed"], "可观察次数": row["observable"], "改善率": fmt_pct(row["improvement_rate"]), "晋级率": fmt_pct(row["upgrade_rate"]), "实际成本": fmt_money(row["cost"])} for row in k["action_rows"]]), hide_index=True, width="stretch")
    agents = data.agents.merge(data.campaign_exposure, on="agent_id", validate="one_to_one")
    dates = sorted(data.history["snapshot_date"].unique())
    prior = data.history.loc[data.history["snapshot_date"] == dates[-2], ["agent_id", "stage"]].rename(columns={"stage": "上期阶段"})
    agents = agents.merge(prior, on="agent_id")
    agents["晋级"] = agents["上期阶段"].eq("准头部") & agents["stage"].isin(HEAD)
    experiment = agents.groupby("实验分组").agg(人数=("agent_id", "size"), 活动前准头部=("上期阶段", lambda x: x.eq("准头部").sum()), 活动后晋级=("晋级", "sum"))
    experiment["晋级率"] = [fmt_pct(a / b if b else None) for a, b in zip(experiment["活动后晋级"], experiment["活动前准头部"])]
    st.subheader("模拟活动实验")
    st.caption("固定分组仅供演示。普通前后对比不能证明因果；真实增量效果需随机分组、曝光记录和预算核算。")
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
