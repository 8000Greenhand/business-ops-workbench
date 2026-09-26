"""Peer-supported bottlenecks, priority and guarded next-best actions."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

from ops_workbench.metrics.super_agent import HEAD, _peer_percentile, safe_ratio


BOTTLENECKS = {"resource": "商机资源", "acceptance": "承接", "followup": "有效跟进", "showing": "带看", "closing": "成交转化"}


def load_actions() -> list[dict]:
    """Read the simulated action catalog from YAML."""
    path = Path(__file__).resolve().parents[3] / "config" / "super_agent_actions.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["actions"]


def diagnose(frame: pd.DataFrame, policy: dict) -> pd.DataFrame:
    """Flag sustained or extreme peer gaps only when denominators support them."""
    result = frame.copy()
    cfg = policy["bottleneck"]
    specs = (("resource", "opportunity_received", "opportunity_received", 0),
             ("acceptance", "acceptance_rate", "opportunity_received", cfg["min_opportunities"]),
             ("followup", "followup_rate", "opportunity_accepted", cfg["min_accepted"]),
             ("showing", "showing_rate", "valid_followup_count", cfg["min_followups"]),
             ("closing", "closing_rate", "showings_56d", cfg["min_showings_56d"]))
    for key, metric, denominator, minimum in specs:
        result[f"{key}_peer_pct"] = _peer_percentile(result, metric, policy)
        previous = f"previous_{metric}"
        result[f"{key}_previous_pct"] = _peer_percentile(result.assign(**{previous: result[previous]}), previous, policy)
        enough = result[denominator] >= minimum
        persistent = ((result[f"{key}_peer_pct"] <= cfg["persistent_current_percentile"])
                      & (result[f"{key}_previous_pct"] <= cfg["persistent_previous_percentile"]))
        extreme = result[f"{key}_peer_pct"] <= cfg["extreme_percentile"]
        if key == "closing":
            result["closing_56d_peer_pct"] = _peer_percentile(result, "closing_56d", policy)
            persistent = persistent & (result["showing_count"] >= minimum / 2) & (result["previous_showings_28d"] >= minimum / 2)
            extreme = result["closing_56d_peer_pct"] <= cfg["extreme_percentile"]
        if key == "resource":
            downstream = result[["acceptance_rate_pct", "followup_rate_pct", "showing_rate_pct", "closing_rate_pct"]].mean(axis=1)
            enough = downstream.notna() & (result["showings_56d"] >= minimum + 5)
            persistent = persistent & (downstream >= cfg["downstream_good_percentile"])
            extreme = extreme & (downstream >= cfg["downstream_good_percentile"])
        result[f"{key}_flag"] = enough & (persistent | extreme)
        result[f"{key}_gap"] = (cfg["persistent_current_percentile"] - result[f"{key}_peer_pct"]).clip(lower=0)
        if key == "closing":
            result[f"{key}_gap"] = (cfg["persistent_current_percentile"] - result[[f"{key}_peer_pct", "closing_56d_peer_pct"]].min(axis=1)).clip(lower=0)
        result.loc[~enough, f"{key}_gap"] = 0.0
    flags = [f"{key}_flag" for key in BOTTLENECKS]
    gaps = [f"{key}_gap" for key in BOTTLENECKS]
    result["primary_bottleneck"] = "none"
    result["secondary_bottleneck"] = "none"
    active = result[flags].any(axis=1)
    ranked = result[gaps].where(result[flags].set_axis(gaps, axis=1), -1)
    order = ranked.apply(lambda row: row.sort_values(ascending=False, kind="stable").index.tolist(), axis=1)
    result.loc[active, "primary_bottleneck"] = order.loc[active].map(lambda x: x[0].removesuffix("_gap"))
    for idx in result.index[active]:
        keys = [name.removesuffix("_gap") for name in order.at[idx] if ranked.at[idx, name] >= 0]
        if len(keys) > 1:
            result.at[idx, "secondary_bottleneck"] = keys[1]
    result["diagnostic_status"] = "未见持续异常"
    result.loc[active, "diagnostic_status"] = "同群持续或极端偏低"
    result.loc[(result["showings_56d"] < cfg["min_showings_56d"]) & ~active, "diagnostic_status"] = "样本不足"
    return result


def attach_touch_history(frame: pd.DataFrame, log: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Add last touch, 7/14/30-day frequency and cooldown inputs."""
    result = frame.copy()
    log = log.loc[log["status"] == "已执行"]
    result["last_action_at"] = pd.NaT
    result["last_action_code"] = ""
    for days in (7, 14, 30):
        recent = log.loc[(log["action_at"] <= as_of) & (log["action_at"] > as_of - timedelta(days=days))]
        result[f"touches_{days}d"] = result["agent_id"].map(recent.groupby("agent_id").size()).fillna(0).astype(int)
    if not log.empty:
        last = log.sort_values("action_at").drop_duplicates("agent_id", keep="last").set_index("agent_id")
        result["last_action_at"] = pd.to_datetime(result["agent_id"].map(last["action_at"]))
        result["last_action_code"] = result["agent_id"].map(last["action_code"]).fillna("")
    cooldowns = {action["action_code"]: action["cooldown_days"] for action in load_actions()}
    result["cooldown_until"] = result["last_action_at"] + pd.to_timedelta(result["last_action_code"].map(cooldowns).fillna(0), unit="D")
    return result


def action_guard(row: pd.Series | dict, action: dict, policy: dict, as_of: date, *,
                 used_capacity: int = 0) -> str:
    """Return a suppression reason or empty string for an eligible action."""
    code = action["action_code"]
    if not action["enabled"] or row["stage"] not in action["eligible_stages"]:
        return "阶段不适用"
    if row["confidence"] < policy["potential"]["confidence_gate"] and code != "A10":
        return "置信度不足"
    if action["target_bottleneck"] != "any" and row["primary_bottleneck"] != action["target_bottleneck"]:
        return "主瓶颈不匹配"
    if code == "A02":
        if pd.isna(row["conversion_score"]) or row["conversion_score"] < policy["recommendation"]["resource_conversion_gate"]:
            return "后链路效率不足"
        if row["confidence"] < policy["recommendation"]["resource_confidence_gate"]:
            return "资源动作置信度不足"
    if code == "A07":
        if row["top_progress"] < policy["recommendation"]["incentive_progress_gate"] or row["primary_bottleneck"] != "none":
            return "尚不适合晋级激励"
        if not policy["campaign"]["active"] or policy["campaign"]["budget"] < policy["campaign"]["unit_cost"]:
            return "无可用活动预算"
        if used_capacity >= min(policy["campaign"]["capacity"], policy["campaign"]["budget"] // policy["campaign"]["unit_cost"]):
            return "活动容量已满"
    if code == "A09" and not row["top_at_risk"]:
        return "未触发头部风险"
    if code == "A08" and row["top_at_risk"]:
        return "优先处理头部风险"
    if code == "A01" and row["stage"] == "高潜" and row["top_progress"] < 0.4:
        return "尚非冲刺阶段"
    last = row["last_action_at"]
    if pd.notna(last) and row["last_action_code"] == code:
        age = (pd.Timestamp(as_of) - pd.Timestamp(last)).days
        if age < action["cooldown_days"]:
            return "冷却中"
    if row["touches_30d"] >= action["max_frequency_30d"]:
        return "触达频率上限"
    if used_capacity >= action["capacity_per_cycle"]:
        return "城市动作容量已满"
    return ""


def recommend(frame: pd.DataFrame, policy: dict, actions: list[dict], as_of: date) -> pd.DataFrame:
    """Rank Top-N actions and retain all suppressed candidates for explanation."""
    rows = []
    used: dict[tuple[str, str], int] = {}
    weights = policy["recommendation"]["weights"]
    for agent in frame.sort_values(["priority_score", "agent_id"], ascending=[False, True]).to_dict("records"):
        candidates = []
        for action in actions:
            key = (agent["city"], action["action_code"])
            capacity_used = sum(count for (_, code), count in used.items() if code == "A07") if action["action_code"] == "A07" else used.get(key, 0)
            reason = action_guard(agent, action, policy, as_of, used_capacity=capacity_used)
            code = action["action_code"]
            fit = 100 if code == "A10" and agent["confidence"] < policy["potential"]["confidence_gate"] else (
                95 if code == "A09" and agent["top_at_risk"] else
                90 if code == "A08" and agent["stage"] == "新晋头部" else
                85 if action["target_bottleneck"] == agent["primary_bottleneck"] and agent["primary_bottleneck"] != "none" else
                80 if code == "A07" and agent["stage"] == "准头部" else
                68 if code == "A01" and agent["stage"] == "准头部" else 45 if code == "A10" else 35)
            leverage = max(0 if pd.isna(agent["potential_score"]) else agent["potential_score"], agent["top_progress"] * 70)
            urgency = 100 if agent["top_at_risk"] else min(100, agent["top_progress"] * 100)
            score = (weights["fit"] * fit + weights["leverage"] * leverage + weights["urgency"] * urgency
                     - policy["recommendation"]["cost_penalty"][action["cost_level"]]
                     - policy["recommendation"]["fatigue_penalty_per_touch"] * agent["touches_7d"])
            candidates.append({"agent_id": agent["agent_id"], "city": agent["city"], "action_code": code,
                               "action_name": action["action_name"], "recommendation_score": round(score, 2),
                               "reason_code": "LOW_CONFIDENCE" if code == "A10" else agent["primary_bottleneck"],
                               "reason_text": "补足样本后再评估" if code == "A10" else f"{agent['stage']}；主瓶颈：{BOTTLENECKS.get(agent['primary_bottleneck'], '未见持续异常')}；同群证据仅支持经营判断",
                               "valid_from": as_of, "valid_until": as_of + timedelta(days=action["valid_days"]),
                               "suppressed_flag": bool(reason), "suppression_reason": reason})
        candidates.sort(key=lambda x: (-x["recommendation_score"], x["action_code"]))
        rank = 0
        for item in candidates:
            if not item["suppressed_flag"]:
                rank += 1
                item["rank_no"] = rank
                if rank <= policy["recommendation"]["top_n"]:
                    key = (agent["city"], item["action_code"])
                    used[key] = used.get(key, 0) + 1
            else:
                item["rank_no"] = 0
            rows.append(item)
    return pd.DataFrame(rows)


def prioritize(frame: pd.DataFrame, policy: dict) -> pd.DataFrame:
    """Assign P0 only above threshold and within manager capacity."""
    result = frame.copy()
    w = policy["priority"]["weights"]
    upgrade = (result["top_progress"].clip(0, 1) * 100).where(~result["stage"].isin(HEAD), 0)
    defend = pd.Series(0.0, index=result.index).where(~result["top_at_risk"], 100.0)
    value = pd.concat([upgrade, defend], axis=1).max(axis=1)
    actionable = pd.Series(25.0, index=result.index).where(result["primary_bottleneck"].eq("none"), 85.0)
    actionable = actionable.where(result["confidence"] >= policy["potential"]["confidence_gate"], 10)
    urgency = (result["top_progress"].clip(0, 1) * 80).where(~result["top_at_risk"], 100)
    result["priority_score"] = (w["business_value"] * value + w["actionability"] * actionable
                                + w["urgency"] * urgency + w["confidence"] * result["confidence"] * 100
                                - policy["priority"]["fatigue_penalty_per_touch"] * result["touches_7d"])
    result["priority"] = "P2"
    result.loc[result["priority_score"] >= policy["priority"]["p1_threshold"], "priority"] = "P1"
    result["capacity_deferred"] = False
    eligible = result[result["priority_score"] >= policy["priority"]["p0_threshold"]].sort_values(["priority_score", "agent_id"], ascending=[False, True])
    rank = eligible.groupby("manager_id").cumcount() + 1
    winners = eligible.index[rank <= policy["priority"]["p0_capacity_per_manager"]]
    result.loc[winners, "priority"] = "P0"
    result.loc[eligible.index.difference(winners), "capacity_deferred"] = True
    return result


def action_kpis(recommendations: pd.DataFrame, log: pd.DataFrame, history: pd.DataFrame,
                facts: pd.DataFrame, policy: dict) -> dict:
    """Summarize historical simulated actions and observed 7/14/28-day changes."""
    primary = recommendations.loc[recommendations["rank_no"] == 1]
    recommended = len(primary)
    executed = log.loc[log["status"] == "已执行", "agent_id"].nunique()
    accepted = log.loc[log["status"].isin(["已接受", "已执行"]), "agent_id"].nunique()
    latest = history.loc[history["snapshot_date"] == history["snapshot_date"].max()]
    prior = history.loc[history["snapshot_date"] == sorted(history["snapshot_date"].unique())[-2]]
    upgrades = prior.set_index("agent_id")["stage"].eq("准头部") & latest.set_index("agent_id")["stage"].isin(HEAD)
    windows = {}
    as_of = facts["date"].max()
    expected = {action["action_code"]: action["expected_metric"] for action in load_actions()}
    for days in policy["windows"]["action_days"]:
        eligible = log.loc[(log["status"] == "已执行") & (log["action_at"] <= as_of - timedelta(days=days))]
        better = 0
        for action in eligible.itertuples():
            agent = facts.loc[facts["agent_id"] == action.agent_id]
            metric = expected[action.action_code]
            before = agent.loc[(agent["date"] < action.action_at) & (agent["date"] >= action.action_at - timedelta(days=days)), metric].sum()
            after = agent.loc[(agent["date"] > action.action_at) & (agent["date"] <= action.action_at + timedelta(days=days)), metric].sum()
            better += int(after > before)
        windows[days] = {"eligible": len(eligible), "improved": better,
                         "improvement_rate": safe_ratio(better, len(eligible))}
    cost = float(log["cost"].sum()) if not log.empty else 0.0
    durations = []
    for _, path in history.sort_values("snapshot_date").groupby("agent_id"):
        stages = path["stage"].tolist()
        dates = path["snapshot_date"].tolist()
        for i in range(1, len(stages)):
            if stages[i] in HEAD and stages[i - 1] == "准头部":
                start = i - 1
                while start > 0 and stages[start - 1] == "准头部":
                    start -= 1
                durations.append((dates[i] - dates[start]).days)
    return {"recommended_count": recommended, "accepted_count": accepted, "executed_count": executed,
            "action_accept_rate": safe_ratio(accepted, recommended), "action_execution_rate": safe_ratio(executed, accepted),
            "action_improvement_rate": windows.get(7, {}).get("improvement_rate"), "upgrade_rate": safe_ratio(int(upgrades.sum()), int(prior["stage"].eq("准头部").sum())),
            "mean_upgrade_days": sum(durations) / len(durations) if durations else None, "action_cost": cost,
            "cost_per_new_head": safe_ratio(cost, int(upgrades.sum())), "outcome_windows": windows}
