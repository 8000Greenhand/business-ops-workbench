"""Presentation-ready assembly for the independent simulated agent demo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import random

import pandas as pd

from ops_workbench.diagnostics.super_agent import (action_kpis, attach_touch_history,
    diagnose, load_actions, prioritize, recommend)
from ops_workbench.metrics.super_agent import build_snapshots, load_policy, transition_kpis
from ops_workbench.metrics.super_agent_campaigns import (campaign_review, generate_candidates,
    load_campaigns, simulate_historical_campaigns)
from ops_workbench.simulation.super_agent import simulate_agents, simulated_action_cohort


@dataclass(frozen=True)
class Dashboard:
    """All derived demo tables used by the six views."""

    agents: pd.DataFrame
    facts: pd.DataFrame
    history: pd.DataFrame
    recommendations: pd.DataFrame
    historical_recommendations: pd.DataFrame
    action_log: pd.DataFrame
    campaign_exposure: pd.DataFrame
    kpis: dict
    action_kpis: dict
    policy: dict
    campaigns: pd.DataFrame
    campaign_rules: pd.DataFrame
    campaign_candidates: pd.DataFrame
    historical_campaign_candidates: pd.DataFrame
    historical_campaign_enrollments: pd.DataFrame
    historical_campaign_outcomes: pd.DataFrame
    campaign_kpis: pd.DataFrame


def build_dashboard() -> Dashboard:
    """Assemble deterministic facts, snapshots, diagnostics and actions."""
    policy = load_policy()
    master, facts = simulate_agents(policy)
    agents, history = build_snapshots(master, facts, policy)
    agents = diagnose(agents, policy)
    as_of = facts["date"].max()
    historical_recommendations, log = simulated_action_cohort(master, as_of)
    agents = attach_touch_history(agents, log, as_of)
    agents = prioritize(agents, policy)
    recommendations = recommend(agents, policy, load_actions(), as_of)
    primary = recommendations.loc[recommendations["rank_no"] == 1, ["agent_id", "recommendation_id", "action_code", "action_name", "reason_text", "valid_until"]]
    agents = agents.merge(primary.rename(columns={"action_code": "primary_action_code", "action_name": "primary_action", "reason_text": "recommendation_reason"}), on="agent_id", how="left", validate="one_to_one")
    # Case letters identify observed examples in the fixed-seed output, not rule overrides.
    agents["case"] = ""
    selectors = {
        "A": agents[(agents["stage"] == "高潜") & (agents["top_progress"] < 0.72)].sort_values("growth_score", ascending=False),
        "B": agents[(agents["stage"] == "准头部") & (agents["primary_bottleneck"] == "none") & (agents["primary_action_code"].isin(["A01", "A07"]))].sort_values("top_progress", ascending=False),
        "C": agents[(agents["primary_bottleneck"] == "resource") & (agents["primary_action_code"] == "A02")],
        "D": agents[(agents["primary_bottleneck"] == "closing") & (agents["primary_action_code"] == "A06")],
        "E": agents[(agents["confidence"] < policy["potential"]["confidence_gate"]) & (agents["growth_score"] > 80) & (agents["observed_days_56d"] < 20)].sort_values("potential_score", ascending=False),
        "F": agents[(agents["stage"] == "稳定头部") & agents["top_at_risk"] & (agents["priority"] == "P0") & (agents["primary_action_code"] == "A09")],
        "G": agents[agents["agent_id"].isin(recommendations.loc[recommendations["suppression_reason"].isin(["冷却中", "触达频率上限"]), "agent_id"])].sort_values("touches_7d", ascending=False),
        "H": agents[(agents["priority"] == "P1") & agents["capacity_deferred"] & (agents["stage"] == "准头部")].sort_values("top_progress", ascending=False),
    }
    used_cases = set()
    for label, candidates in selectors.items():
        candidate = next((idx for idx in candidates.index if idx not in used_cases), None)
        if candidate is not None:
            agents.at[candidate, "case"] = label
            used_cases.add(candidate)
    kpis = transition_kpis(history)
    kpis["p0_count"] = int(agents["priority"].eq("P0").sum())
    ids = agents["agent_id"].tolist()
    random.Random(policy["seed"]).shuffle(ids)
    exposure = pd.DataFrame({"agent_id": ids, "实验分组": ["实验组" if i % 2 == 0 else "对照组" for i in range(len(ids))]})
    campaign_config = load_campaigns()
    campaign_list = campaign_config["campaigns"]
    current_candidates = generate_candidates(agents, campaign_list, as_of)
    historical_at = as_of - timedelta(days=42)
    historical_agents, _ = build_snapshots(master, facts.loc[facts["date"] <= historical_at], policy)
    historical_agents = diagnose(historical_agents, policy)
    historical_candidates = generate_candidates(historical_agents, campaign_list, historical_at)
    historical_enrollments, historical_outcomes = simulate_historical_campaigns(
        historical_candidates, campaign_list, facts, history, campaign_config, historical_at)
    return Dashboard(
        agents=agents, facts=facts, history=history, recommendations=recommendations,
        historical_recommendations=historical_recommendations, action_log=log,
        campaign_exposure=exposure, kpis=kpis,
        action_kpis=action_kpis(historical_recommendations, log, history, facts, policy), policy=policy,
        campaigns=pd.DataFrame([{key: value for key, value in campaign.items() if key != "rule"} for campaign in campaign_list]),
        campaign_rules=pd.DataFrame([{"campaign_id": campaign["campaign_id"], **campaign["rule"]} for campaign in campaign_list]),
        campaign_candidates=current_candidates,
        historical_campaign_candidates=historical_candidates,
        historical_campaign_enrollments=historical_enrollments,
        historical_campaign_outcomes=historical_outcomes,
        campaign_kpis=campaign_review(historical_candidates, historical_enrollments, historical_outcomes, campaign_list),
    )


def fmt_pct(value: float | None) -> str:
    """Show a percent or an explicit unavailable label."""
    return "不可用" if pd.isna(value) else f"{value:.1%}"


def fmt_money(value: float | None) -> str:
    """Show renminbi with Chinese-friendly units."""
    if pd.isna(value):
        return "不可用"
    return f"¥{value / 10000:,.1f}万" if abs(value) >= 10000 else f"¥{value:,.0f}"


BOTTLENECK_FILTER_OPTIONS = {"全部": None, "商机资源": "resource", "商机承接": "acceptance",
                             "有效跟进": "followup", "带看转化": "showing", "成交转化": "closing"}
BOTTLENECK_UI_LABELS = {code: label for label, code in BOTTLENECK_FILTER_OPTIONS.items() if code is not None}
BOTTLENECK_UI_LABELS["none"] = "未见持续异常"


def task_statuses(agents: pd.DataFrame, events: list[dict], as_of) -> dict[str, str]:
    """Resolve shared current-session task states by recommendation identity."""
    latest = {event["recommendation_id"]: event for event in events}
    statuses = {}
    for row in agents.itertuples():
        event = latest.get(row.recommendation_id) if isinstance(row.recommendation_id, str) else None
        if event:
            status = event["status"]
        elif row.valid_until < as_of:
            status = "已过期"
        elif pd.notna(row.cooldown_until) and row.cooldown_until.date() > as_of and row.last_action_code == row.primary_action_code:
            status = "冷却中"
        else:
            status = "待处理"
        statuses[row.agent_id] = status
    return statuses


def record_session_event(events: list[dict], row: pd.Series | dict, status: str, event_at, skip_reason: str = "") -> None:
    """Append one session event after checking task transition and skip reason."""
    if status not in {"已接受", "已执行", "跳过"}:
        raise ValueError("status 非法")
    if status == "跳过" and not skip_reason:
        raise ValueError("跳过必须填写原因")
    previous = next((event["status"] for event in reversed(events) if event["recommendation_id"] == row["recommendation_id"]), "待处理")
    if (status == "已接受" and previous != "待处理") or (status == "已执行" and previous != "已接受") or (status == "跳过" and previous not in {"待处理", "已接受"}):
        raise ValueError("任务状态迁移非法")
    events.append({"agent_id": row["agent_id"], "recommendation_id": row["recommendation_id"],
                   "action_code": row["primary_action_code"], "status": status,
                   "event_at": event_at, "skip_reason": skip_reason})


def session_progress(events: list[dict]) -> dict[str, int]:
    """Count session accept/execute/skip events without historical effects."""
    return {status: len({event["recommendation_id"] for event in events if event["status"] == status})
            for status in ("已接受", "已执行", "跳过")}


def decision_table(agents: pd.DataFrame, statuses: dict[str, str] | None = None) -> pd.DataFrame:
    """Return a readable Chinese action table without raw decimal ratios."""
    return pd.DataFrame({
        "经纪人": agents["agent_name"], "验收案例": agents["case"].map(lambda x: f"案例{x}" if x else ""),
        "城市": agents["city"], "负责人": agents["manager_name"],
        "生命周期": agents["stage"], "头部完成度": agents["top_progress"].map(fmt_pct),
        "头部差距维度": agents["top_gap_dimension"].map({"deal_count": "成交量", "deal_gtv": "成交额"}),
        "潜力分": agents["potential_score"].map(lambda x: "不可用" if pd.isna(x) else f"{x:.1f}"),
        "同群潜力百分位": agents["potential_percentile"].map(fmt_pct),
        "置信度": agents["confidence"].map(lambda x: "高" if x >= 0.8 else "中" if x >= 0.65 else "低"),
        "趋势": agents["growth_score"].map(lambda x: "上行" if x >= 60 else "平稳" if x >= 40 else "转弱"),
        "主瓶颈": agents["primary_bottleneck"].map(BOTTLENECK_UI_LABELS),
        "优先级": agents["priority"], "容量状态": agents["capacity_deferred"].map(lambda x: "容量递延" if x else ""),
        "首选动作": agents["primary_action"].fillna("继续观察"),
        "推荐原因": agents["recommendation_reason"].fillna("样本不足，继续观察"),
        "有效期": agents["valid_until"].astype(str),
        "最近触达": agents["last_action_at"].dt.strftime("%Y-%m-%d").fillna("无"),
        "任务状态": agents["agent_id"].map(statuses or {}).fillna("待处理"),
    })
