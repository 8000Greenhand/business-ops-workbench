"""Peer-supported bottlenecks, priority and guarded next-best actions."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

from ops_workbench.metrics.super_agent import HEAD, _peer_percentile, safe_ratio, validate_actions


BOTTLENECKS = {"resource": "商机资源", "acceptance": "承接", "followup": "有效跟进", "showing": "带看", "closing": "成交转化"}


def recommendation_reason(agent: dict, code: str, policy: dict) -> str:
    """Explain one simulated recommendation from its measured evidence."""
    progress = f"{agent['top_progress']:.0%}"
    if code == "A02":
        downstream = [agent[key] for key in ("acceptance_rate_pct", "followup_rate_pct", "showing_rate_pct", "closing_rate_pct") if pd.notna(agent[key])]
        efficiency = sum(downstream) / len(downstream) if downstream else float("nan")
        return (f"近28天商机量位于{agent['city']}同群P{agent['resource_peer_pct'] * 100:.0f}，后链路综合位于P{efficiency * 100:.0f}。"
                "当前可评估有限商机微倾斜，执行前仍需城市经理确认资源条件。")
    if code == "A09":
        return (f"上期处于头部，本期头部完成度{progress}，已触发失守风险。"
                f"近期成长趋势分{agent['growth_score']:.0f}，建议优先进行头部风险干预。")
    if code in {"A01", "A07"} and agent["stage"] == "准头部" and agent["primary_bottleneck"] == "none":
        return (f"当前头部完成度{progress}，主漏斗未见持续异常。"
                f"距模拟头部门槛较近，建议{'评估本期晋级激励' if code == 'A07' else '进入本周冲刺触达'}。")
    if code == "A01":
        return (f"当前处于{agent['stage']}，头部完成度{progress}，成长趋势分{agent['growth_score']:.0f}。"
                "建议城市经理触达核实后续经营条件，暂不直接承诺资源。")
    if code == "A08":
        return (f"当前处于新晋头部，头部完成度{progress}。"
                "建议城市经理复核近期作业节奏，巩固稳定性。")
    if code == "A10":
        if agent["confidence"] < policy["potential"]["confidence_gate"]:
            return f"当前置信度{agent['confidence']:.0%}，证据不足以支持高成本资源动作；建议继续观察并补足样本。"
        return f"当前处于{agent['stage']}，头部完成度{progress}；本周期可继续观察，以后续快照复核变化。"
    if agent["primary_bottleneck"] != "none":
        key = agent["primary_bottleneck"]
        return (f"近28天{BOTTLENECKS[key]}指标位于同群P{agent[f'{key}_peer_pct'] * 100:.0f}，满足持续或极端偏低条件。"
                f"建议先进行{BOTTLENECKS[key]}环节辅导，再观察后续表现。")
    return f"当前处于{agent['stage']}，头部完成度{progress}；建议按本期节奏开展{code}对应动作并观察变化。"


def load_actions() -> list[dict]:
    """Read the simulated action catalog from YAML."""
    path = Path(__file__).resolve().parents[3] / "config" / "super_agent_actions.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError("super_agent_actions.yaml 语法非法") from exc
    if not isinstance(document, dict) or "actions" not in document:
        raise ValueError("super_agent_actions.yaml.actions 缺失")
    actions = document["actions"]
    validate_actions(actions)
    return actions


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
    if code == "A01" and row["stage"] == "高潜" and row["top_progress"] < policy["recommendation"]["high_potential_touch_progress_gate"]:
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
    fit_scores = policy["recommendation"]["fit_scores"]
    for agent in frame.sort_values(["priority_score", "agent_id"], ascending=[False, True]).to_dict("records"):
        candidates = []
        for action in actions:
            key = (agent["city"], action["action_code"])
            capacity_used = sum(count for (_, code), count in used.items() if code == "A07") if action["action_code"] == "A07" else used.get(key, 0)
            reason = action_guard(agent, action, policy, as_of, used_capacity=capacity_used)
            code = action["action_code"]
            fit = fit_scores["low_confidence_observation"] if code == "A10" and agent["confidence"] < policy["potential"]["confidence_gate"] else (
                fit_scores["head_risk"] if code == "A09" and agent["top_at_risk"] else
                fit_scores["new_head_retention"] if code == "A08" and agent["stage"] == "新晋头部" else
                fit_scores["bottleneck_match"] if action["target_bottleneck"] == agent["primary_bottleneck"] and agent["primary_bottleneck"] != "none" else
                fit_scores["near_top_incentive"] if code == "A07" and agent["stage"] == "准头部" else
                fit_scores["near_top_touch"] if code == "A01" and agent["stage"] == "准头部" else fit_scores["observation_default"] if code == "A10" else fit_scores["generic"])
            leverage = max(0 if pd.isna(agent["potential_score"]) else agent["potential_score"], agent["top_progress"] * policy["recommendation"]["leverage"]["top_progress_scale"])
            urgency_cfg = policy["recommendation"]["urgency"]
            urgency = urgency_cfg["head_risk"] if agent["top_at_risk"] else min(urgency_cfg["ceiling"], agent["top_progress"] * urgency_cfg["progress_scale"])
            score = (weights["fit"] * fit + weights["leverage"] * leverage + weights["urgency"] * urgency
                     - policy["recommendation"]["cost_penalty"][action["cost_level"]]
                     - policy["recommendation"]["fatigue_penalty_per_touch"] * agent["touches_7d"])
            candidates.append({"recommendation_id": f"{as_of:%Y%m%d}-{agent['agent_id']}-{code}",
                               "agent_id": agent["agent_id"], "city": agent["city"], "action_code": code,
                               "action_name": action["action_name"], "recommendation_score": round(score, 2),
                               "reason_code": "LOW_CONFIDENCE" if code == "A10" else agent["primary_bottleneck"],
                               "reason_text": recommendation_reason(agent, code, policy),
                               "valid_from": as_of, "valid_until": as_of + timedelta(days=action["valid_days"]),
                               "suppressed_flag": bool(reason), "suppression_reason": reason, "capacity_reserved": False})
        candidates.sort(key=lambda x: (-x["recommendation_score"], x["action_code"]))
        rank = 0
        for item in candidates:
            if not item["suppressed_flag"]:
                rank += 1
                item["rank_no"] = rank
                if rank <= policy["recommendation"]["top_n"]:
                    key = (agent["city"], item["action_code"])
                    used[key] = used.get(key, 0) + 1
                    item["capacity_reserved"] = True
            else:
                item["rank_no"] = 0
            rows.append(item)
    return pd.DataFrame(rows)


def prioritize(frame: pd.DataFrame, policy: dict) -> pd.DataFrame:
    """Assign P0 only above threshold and within manager capacity."""
    result = frame.copy()
    w = policy["priority"]["weights"]
    cfg = policy["priority"]
    upgrade = (result["top_progress"].clip(0, 1) * cfg["business_value"]["upgrade_scale"]).where(~result["stage"].isin(HEAD), 0)
    defend = pd.Series(0.0, index=result.index).where(~result["top_at_risk"], cfg["business_value"]["head_risk"])
    value = pd.concat([upgrade, defend], axis=1).max(axis=1)
    actionable = pd.Series(float(cfg["actionability"]["no_bottleneck"]), index=result.index).where(result["primary_bottleneck"].eq("none"), cfg["actionability"]["diagnosed"])
    actionable = actionable.where(result["confidence"] >= policy["potential"]["confidence_gate"], cfg["actionability"]["low_confidence"])
    urgency = (result["top_progress"].clip(0, 1) * cfg["urgency"]["progress_scale"]).where(~result["top_at_risk"], cfg["urgency"]["head_risk"])
    result["priority_score"] = (w["business_value"] * value + w["actionability"] * actionable
                                + w["urgency"] * urgency + w["confidence"] * result["confidence"] * cfg["confidence_scale"]
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
    """Measure one linked historical cohort; exclude missing before/after evidence."""
    if recommendations["recommendation_id"].duplicated().any() or log["recommendation_id"].duplicated().any():
        raise ValueError("recommendation_id 必须唯一")
    if not log["recommendation_id"].isin(recommendations["recommendation_id"]).all():
        raise ValueError("operation_action_log 存在无推荐来源的动作")
    joined = log.merge(recommendations[["recommendation_id", "agent_id", "action_code", "recommended_at"]],
                       on="recommendation_id", suffixes=("", "_recommended"), validate="one_to_one")
    if not (joined["agent_id"] == joined["agent_id_recommended"]).all() or not (joined["action_code"] == joined["action_code_recommended"]).all():
        raise ValueError("operation_action_log 经纪人或动作与推荐不一致")
    for row in joined.itertuples():
        if row.recommended_at != row.recommended_at_recommended or row.status not in {"已推荐", "已接受", "已执行", "跳过", "过期"}:
            raise ValueError(f"{row.recommendation_id} 推荐时间或状态非法")
        if row.status == "已接受" and (pd.isna(row.accepted_at) or row.accepted_at < row.recommended_at):
            raise ValueError(f"{row.recommendation_id} 接受时间非法")
        if row.status == "已执行" and (pd.isna(row.accepted_at) or pd.isna(row.executed_at) or not row.recommended_at <= row.accepted_at <= row.executed_at or row.cost < 0):
            raise ValueError(f"{row.recommendation_id} 推荐→接受→执行时间或成本非法")
        if row.status != "已执行" and (pd.notna(row.executed_at) or row.cost != 0):
            raise ValueError(f"{row.recommendation_id} 未执行不得产生实际成本")
        if row.status in {"已推荐", "跳过", "过期"} and pd.notna(row.accepted_at):
            raise ValueError(f"{row.recommendation_id} 未接受状态不得有接受时间")
        if row.status == "跳过" and not row.skip_reason:
            raise ValueError(f"{row.recommendation_id} 跳过缺少原因")
    recommended = recommendations["agent_id"].nunique()
    accepted = joined.loc[joined["status"].isin(["已接受", "已执行"]), "agent_id"].nunique()
    executed_log = joined.loc[joined["status"] == "已执行"]
    executed = executed_log["agent_id"].nunique()
    skipped = joined.loc[joined["status"] == "跳过", "agent_id"].nunique()
    facts_by_agent = {key: group for key, group in facts.groupby("agent_id")}
    stages_by_agent = {key: group.sort_values("snapshot_date") for key, group in history.groupby("agent_id")}
    expected = {action["action_code"]: action["expected_metric"] for action in load_actions()}
    as_of = facts["date"].max()
    windows = {}
    detailed: list[dict] = []
    for days in policy["windows"]["action_days"]:
        records = []
        for action in executed_log.itertuples():
            if action.executed_at > as_of - timedelta(days=days):
                continue
            agent = facts_by_agent[action.agent_id]
            metric = expected[action.action_code]
            before = agent.loc[(agent["date"] < action.executed_at) & (agent["date"] >= action.executed_at - timedelta(days=days)), ["date", metric]].dropna()
            after = agent.loc[(agent["date"] > action.executed_at) & (agent["date"] <= action.executed_at + timedelta(days=days)), ["date", metric]].dropna()
            enough = min(before["date"].nunique(), after["date"].nunique()) >= days * policy["outcome"]["min_observed_ratio"]
            stage_path = stages_by_agent[action.agent_id]
            stage_before = stage_path.loc[stage_path["snapshot_date"] <= action.executed_at]
            stage_after = stage_path.loc[stage_path["snapshot_date"] <= action.executed_at + timedelta(days=days)]
            if stage_before.empty or stage_after.empty:
                enough = False
            improved = bool(after[metric].sum() > before[metric].sum()) if enough else False
            upgraded = bool(stage_before.iloc[-1]["stage"] not in HEAD and stage_after.iloc[-1]["stage"] in HEAD) if enough else False
            first_head = stage_after.loc[(stage_after["snapshot_date"] > action.executed_at) & stage_after["stage"].isin(HEAD), "snapshot_date"]
            records.append({"agent_id": action.agent_id, "action_code": action.action_code, "recommendation_id": action.recommendation_id,
                            "outcome_status": "可观察" if enough else "样本不足", "improved": improved, "upgraded": upgraded,
                            "cost": action.cost, "executed_at": action.executed_at,
                            "upgrade_days": (first_head.iloc[0] - action.executed_at).days if upgraded and not first_head.empty else None})
        observed = [record for record in records if record["outcome_status"] == "可观察"]
        eligible_people = len({record["agent_id"] for record in records})
        observed_people = len({record["agent_id"] for record in observed})
        improved_people = len({record["agent_id"] for record in observed if record["improved"]})
        upgraded_people = len({record["agent_id"] for record in observed if record["upgraded"]})
        cost = sum(record["cost"] for record in records)
        windows[days] = {"eligible": eligible_people, "observable": observed_people, "insufficient": eligible_people - observed_people,
                         "improved": improved_people, "upgraded": upgraded_people,
                         "improvement_rate": safe_ratio(improved_people, observed_people),
                         "upgrade_rate": safe_ratio(upgraded_people, observed_people), "cost": cost,
                         "cost_per_new_head": safe_ratio(cost, upgraded_people)}
        if days == max(policy["windows"]["action_days"]):
            detailed = records
    main = windows[max(policy["windows"]["action_days"])]
    upgrade_days = [record["upgrade_days"] for record in detailed if record["upgrade_days"] is not None]
    action_rows = []
    for code in sorted(executed_log["action_code"].unique()):
        subset = [record for record in detailed if record["action_code"] == code]
        observed = [record for record in subset if record["outcome_status"] == "可观察"]
        action_rows.append({"action_code": code, "executed": len(subset), "observable": len(observed),
                            "improvement_rate": safe_ratio(sum(record["improved"] for record in observed), len(observed)),
                            "upgrade_rate": safe_ratio(sum(record["upgraded"] for record in observed), len(observed)),
                            "cost": sum(record["cost"] for record in subset)})
    return {"recommended_count": recommended, "accepted_count": accepted, "executed_count": executed, "skipped_count": skipped,
            "action_accept_rate": safe_ratio(accepted, recommended), "action_execution_rate": safe_ratio(executed, accepted),
            "action_improvement_rate": windows.get(7, {}).get("improvement_rate"), "upgrade_rate": main["upgrade_rate"],
            "mean_upgrade_days": sum(upgrade_days) / len(upgrade_days) if upgrade_days else None,
            "action_cost": main["cost"], "cost_per_new_head": main["cost_per_new_head"],
            "outcome_windows": windows, "action_rows": action_rows, "outcome_detail": detailed}
