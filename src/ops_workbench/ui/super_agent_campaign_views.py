"""Six-view demo presentation for fictional campaign decisions and review."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ops_workbench.metrics.super_agent_campaigns import (DECLINE_REASONS, current_enrollments,
    record_enrollment)
from ops_workbench.ui.super_agent_dashboard import fmt_money, fmt_pct


DISCLAIMER = "活动名称、预算、名额、奖励和结果均为模拟配置，不代表任何平台真实内部活动机制。"
BOTTLENECK_LABELS = {"none": "无", "resource": "商机资源", "acceptance": "承接", "followup": "有效跟进",
                     "showing": "带看", "closing": "成交转化"}
FIT_LABELS = {"potential": "潜力", "growth": "成长趋势", "confidence": "置信度", "actionability": "可经营性",
              "top_progress": "头部完成度", "funnel_health": "漏斗健康度", "closing_gap": "成交差距",
              "business_value": "经营价值"}


def _optional(value, *, percentage: bool = False) -> str:
    """Format a nullable campaign rule for Chinese display."""
    if value is None or (isinstance(value, (int, float)) and pd.isna(value)):
        return "不限"
    return fmt_pct(value) if percentage else str(value)


def _catalog(data) -> list[dict]:
    """Recover compact campaign records from the dashboard's validated tables."""
    rules = data.campaign_rules.set_index("campaign_id").to_dict("index")
    return [{**row, "rule": rules[row["campaign_id"]]} for row in data.campaigns.to_dict("records")]


def _current(data, events: list[dict]) -> pd.DataFrame:
    """Return the present-session enrollment state for current candidates."""
    return current_enrollments(data.campaign_candidates, events)


def campaign_center(data, events: list[dict]) -> None:
    """Show strategy rules, resources, candidates, and city decisions."""
    st.caption(DISCLAIMER)
    campaigns = _catalog(data)
    current = _current(data, events)
    active = [campaign for campaign in campaigns if campaign["status"] == "进行中"]
    total_budget = sum(campaign["budget"] for campaign in campaigns)
    total_capacity = sum(campaign["capacity"] for campaign in campaigns)
    enrolled = int(current["enrollment_status"].eq("已报名").sum())
    cols = st.columns(6)
    for col, (name, value) in zip(cols, [("进行中活动", len(active)), ("总预算", fmt_money(total_budget)),
                                   ("总名额", total_capacity), ("系统推荐候选", len(current)),
                                   ("城市已报名", enrolled), ("剩余名额", total_capacity - enrolled)]):
        col.metric(name, value)
    st.subheader("本月活动规划")
    for campaign in campaigns:
        code = campaign["campaign_id"]
        subset = current.loc[current["campaign_id"] == code]
        chosen = int(subset["enrollment_status"].eq("已报名").sum())
        with st.container(border=True):
            st.markdown(f"**{code}｜{campaign['campaign_name']}**　{campaign['campaign_type']} · {campaign['status']}")
            st.write(f"{campaign['start_date']} ～ {campaign['end_date']}｜目标：{campaign['goal_type']}｜预算 {fmt_money(campaign['budget'])}｜名额 {campaign['capacity']}")
            st.caption(f"系统推荐 {len(subset)}｜城市报名 {chosen}｜剩余名额 {campaign['capacity'] - chosen}")
    labels = [f"{campaign['campaign_id']}｜{campaign['campaign_name']}" for campaign in campaigns]
    selected = st.selectbox("选择活动查看规则与候选", labels, index=1)
    campaign = campaigns[labels.index(selected)]
    rule = campaign["rule"]
    st.subheader("活动规则与资源")
    st.write(f"{campaign['description']} 奖励说明：{campaign['reward_description']}。")
    st.write(f"生命周期：{'、'.join(rule['eligible_stages'])}｜头部完成度：{_optional(rule['min_top_progress'], percentage=True)} ～ {_optional(rule['max_top_progress'], percentage=True)}")
    st.write(f"潜力分门槛：{_optional(rule['min_potential_score'])}｜潜力百分位：{_optional(rule['min_potential_percentile'], percentage=True)}｜置信度：{_optional(rule['min_confidence'], percentage=True)}")
    required = _optional(rule["required_bottleneck"])
    st.write(f"必需瓶颈：{BOTTLENECK_LABELS.get(required, required)}｜排除瓶颈：{'、'.join(BOTTLENECK_LABELS.get(item, item) for item in rule['excluded_bottlenecks'] or []) or '无'}｜城市范围：{'、'.join(rule['city_scope'] or []) or '全部'}")
    st.write(f"预算 {fmt_money(campaign['budget'])}｜名额 {campaign['capacity']}｜单人预算占用 {fmt_money(campaign['unit_cost'])}｜匹配分权重：{', '.join(f'{FIT_LABELS.get(key, key)} {fmt_pct(weight)}' for key, weight in rule['activity_fit_weights'].items())}")
    st.subheader("系统候选池与城市选择")
    pool = current.loc[current["campaign_id"] == campaign["campaign_id"]].sort_values("recommendation_rank")
    table = pd.DataFrame({"经纪人": pool["agent_name"], "城市": pool["city"], "城市经理": pool["manager_name"],
                          "生命周期": pool["stage"], "优先级": pool["priority"],
                          "潜力分": pool["potential_score"].map(lambda x: "不可用" if pd.isna(x) else f"{x:.1f}"),
                          "置信度": pool["confidence"].map(fmt_pct), "头部完成度": pool["top_progress"].map(fmt_pct),
                          "主瓶颈": pool["primary_bottleneck"].map(lambda x: BOTTLENECK_LABELS.get(x, x)), "活动匹配分": pool["activity_fit_score"].map(lambda x: f"{x:.1f}"),
                          "推荐原因": pool["recommendation_reason"], "报名状态": pool["enrollment_status"],
                          "不参加原因": pool["decline_reason"]})
    st.dataframe(table, hide_index=True, width="stretch", height=370)
    st.caption("系统推荐只表示满足模拟活动规则；报名由城市经理选择，推荐不等于报名或实际参加。")


def manager_campaigns(data, events: list[dict], manager_id: str) -> None:
    """Show only one fictional manager's candidates and record their decisions."""
    st.caption(DISCLAIMER)
    campaigns = [campaign for campaign in _catalog(data) if campaign["status"] in {"报名中", "进行中"}]
    current = _current(data, events)
    mine = current.loc[current["manager_id"] == manager_id]
    st.subheader("我的活动")
    for campaign in campaigns:
        subset = mine.loc[mine["campaign_id"] == campaign["campaign_id"]]
        with st.container(border=True):
            st.markdown(f"**{campaign['campaign_name']}**｜{campaign['status']}")
            st.caption(f"系统推荐 {len(subset)}｜已报名 {int(subset['enrollment_status'].eq('已报名').sum())}｜待选择 {int(subset['enrollment_status'].eq('待选择').sum())}｜不参加 {int(subset['enrollment_status'].eq('不参加').sum())}")
    labels = [f"{campaign['campaign_id']}｜{campaign['campaign_name']}" for campaign in campaigns]
    selected = st.selectbox("选择我的活动", labels, index=1)
    campaign = campaigns[labels.index(selected)]
    pool = mine.loc[mine["campaign_id"] == campaign["campaign_id"]].sort_values("recommendation_rank")
    if pool.empty:
        st.info("该经理本期没有此活动候选人。")
        return
    display = pool[["agent_name", "stage", "priority", "activity_fit_score", "enrollment_status", "decline_reason", "recommendation_reason"]].rename(
        columns={"agent_name": "经纪人", "stage": "生命周期", "priority": "优先级", "activity_fit_score": "活动匹配分",
                 "enrollment_status": "报名状态", "decline_reason": "不参加原因", "recommendation_reason": "推荐原因"})
    st.dataframe(display, hide_index=True, width="stretch", height=300)
    choice = st.selectbox("选择活动候选人", pool["agent_name"].tolist())
    row = pool.loc[pool["agent_name"] == choice].iloc[0]
    st.write(f"{choice}｜{row['stage']}｜活动匹配分 {row['activity_fit_score']:.1f}｜当前状态：{row['enrollment_status']}")
    st.caption(row["recommendation_reason"])
    if row["decline_reason"]:
        st.caption("不参加原因：" + row["decline_reason"])
    if row["enrollment_status"] != "待选择":
        return
    reason = st.selectbox("不参加原因", ["请选择原因", *DECLINE_REASONS])
    left, right = st.columns(2)
    for col, label, status in ((left, "报名", "已报名"), (right, "不参加", "不参加")):
        if col.button(label, key=f"campaign_{status}_{campaign['campaign_id']}_{row['agent_id']}"):
            try:
                record_enrollment(events, row, campaign, manager_id, status, pd.Timestamp.now(),
                                  reason if reason != "请选择原因" else "", current)
            except ValueError as exc:
                st.warning(str(exc))
            else:
                st.rerun()


def campaign_review_view(data, events: list[dict]) -> None:
    """Render current session progress separately from historical activity outcomes."""
    st.subheader("本次会话活动选择")
    st.caption("本次会话报名或不参加只记录城市经理选择，不立即产生参与、成交、晋级或成本。")
    cols = st.columns(2)
    cols[0].metric("本次会话报名", sum(event["status"] == "已报名" for event in events))
    cols[1].metric("本次会话不参加", sum(event["status"] == "不参加" for event in events))
    st.subheader("历史模拟活动复盘")
    st.caption("下列推荐、报名、参与、完成与结果来自同一 campaign_id + agent_id 历史 cohort；普通前后对比不能证明活动产生因果增量。")
    labels = [f"{row.campaign_id}｜{row.campaign_name}" for row in data.campaign_kpis.itertuples()]
    selected = st.selectbox("选择历史活动", labels, index=1)
    k = data.campaign_kpis.iloc[labels.index(selected)]
    st.markdown("**成交**")
    cols = st.columns(4)
    for col, (label, value) in zip(cols, [("参与经纪人数", k["participated"]), ("产生成交人数", k["deal_agents"]),
                                    ("成交单量", k["deal_count"]), ("成交金额", fmt_money(k["deal_gtv"]))]):
        col.metric(label, value)
    st.markdown("**头部晋级**")
    cols = st.columns(3)
    for col, (label, value) in zip(cols, [("活动前准头部人数", k["near_top_before"]), ("晋级头部人数", k["promoted"]),
                                    ("晋级率", fmt_pct(k["upgrade_rate"]))]):
        col.metric(label, value)
    st.subheader("活动执行漏斗")
    st.dataframe(pd.DataFrame([{"环节": label, "人数": int(k[field])} for label, field in
                               (("系统推荐", "recommended"), ("城市报名", "enrolled"), ("确认参与", "participated"),
                                ("活动完成", "completed"), ("产生成交", "deal_agents"), ("晋级头部", "promoted"))]),
                 hide_index=True, width="stretch")
    st.caption(f"可观察 {k['observable']} 人｜样本不足 {k['insufficient']} 人。未参与和观察不足不当作零成交。")
    st.subheader("资源效率")
    cols = st.columns(3)
    for col, (label, value) in zip(cols, [("活动预算", fmt_money(k["budget"])), ("实际成本", fmt_money(k["actual_cost"])),
                                    ("预算使用率", fmt_pct(k["budget_usage"]))]):
        col.metric(label, value)
    cols = st.columns(3)
    for col, (label, value) in zip(cols, [("人均成本", fmt_money(k["cost_per_participant"])),
                                    ("每成交经纪人成本", fmt_money(k["cost_per_deal_agent"])),
                                    ("每新增头部成本", fmt_money(k["cost_per_new_head"]))]):
        col.metric(label, value)
    st.caption("以上成本是历史模拟观察口径。固定 Seed 实验分组仅供展示；真实增量效果仍需随机分组、曝光记录和预算核算。")
