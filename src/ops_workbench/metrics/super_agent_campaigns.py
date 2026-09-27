"""Configurable fictional campaigns, manager selection, and cohort review."""

from __future__ import annotations

from datetime import date, timedelta
import math
from pathlib import Path
import random

import pandas as pd
import yaml

from ops_workbench.metrics.super_agent import HEAD, STAGES, safe_ratio


CAMPAIGN_TYPES = {"成长激励", "晋级激励", "培训辅导"}
GOALS = {"成长改善", "成交提升", "晋级头部", "瓶颈改善"}
STATUSES = {"筹备中", "报名中", "进行中", "已结束"}
BOTTLENECKS = {"resource", "acceptance", "followup", "showing", "closing"}
FIT_COMPONENTS = {"potential", "growth", "confidence", "actionability", "top_progress",
                  "funnel_health", "closing_gap", "business_value"}
DECLINE_REASONS = ("本人意愿不足", "近期状态变化", "不符合城市实际情况", "已参加其他活动", "名额有限", "其他")


def load_campaigns(path: Path | None = None) -> dict:
    """Load and validate the versioned fictional campaign catalog."""
    path = path or Path(__file__).resolve().parents[3] / "config" / "super_agent_campaigns.yaml"
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError("super_agent_campaigns.yaml 语法非法") from exc
    validate_campaigns(config)
    return config


def validate_campaigns(config: dict) -> None:
    """Reject malformed campaign rules before any candidate generation."""
    if not isinstance(config, dict) or config.get("scope_label") != "模拟经营口径":
        raise ValueError("scope_label 必须为模拟经营口径")
    campaigns = config.get("campaigns")
    if not isinstance(campaigns, list) or not campaigns:
        raise ValueError("campaigns 必须为非空列表")
    if not isinstance(config.get("historical_seed"), int):
        raise ValueError("historical_seed 非法")
    if not isinstance(config.get("observation_days"), int) or config["observation_days"] <= 0:
        raise ValueError("observation_days 非法")
    ratio = config.get("min_observed_ratio")
    if not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or not 0 < ratio <= 1:
        raise ValueError("min_observed_ratio 非法")
    seen: set[str] = set()
    for campaign in campaigns:
        if not isinstance(campaign, dict):
            raise ValueError("campaigns 项必须为映射")
        code = campaign.get("campaign_id")
        if not isinstance(code, str) or not code or code in seen:
            raise ValueError(f"campaign_id 重复或非法：{code}")
        seen.add(code)
        for key, valid in (("campaign_type", CAMPAIGN_TYPES), ("goal_type", GOALS), ("status", STATUSES)):
            if campaign.get(key) not in valid:
                raise ValueError(f"{code}.{key} 非法")
        try:
            start = date.fromisoformat(campaign["start_date"])
            end = date.fromisoformat(campaign["end_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{code}.start_date/end_date 非法") from exc
        if start > end:
            raise ValueError(f"{code}.start_date 不得晚于 end_date")
        for key in ("budget", "capacity", "unit_cost"):
            value = campaign.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{code}.{key} 非法")
        if not isinstance(campaign["capacity"], int):
            raise ValueError(f"{code}.capacity 必须为整数")
        rule = campaign.get("rule")
        if not isinstance(rule, dict):
            raise ValueError(f"{code}.rule 缺失")
        stages = rule.get("eligible_stages")
        if not isinstance(stages, list) or not stages or set(stages) - set(STAGES):
            raise ValueError(f"{code}.eligible_stages 非法")
        for key in ("min_top_progress", "max_top_progress", "min_potential_percentile", "min_confidence"):
            value = rule.get(key)
            if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{code}.{key} 非法")
        if (rule.get("min_top_progress") is not None and rule.get("max_top_progress") is not None
                and rule["min_top_progress"] > rule["max_top_progress"]):
            raise ValueError(f"{code}.top_progress 范围非法")
        for key in ("min_potential_score", "min_showings_56d"):
            value = rule.get(key)
            if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0):
                raise ValueError(f"{code}.{key} 非法")
        if rule.get("required_bottleneck") is not None and rule["required_bottleneck"] not in BOTTLENECKS:
            raise ValueError(f"{code}.required_bottleneck 非法")
        excluded = rule.get("excluded_bottlenecks")
        if excluded is not None and (not isinstance(excluded, list) or set(excluded) - BOTTLENECKS):
            raise ValueError(f"{code}.excluded_bottlenecks 非法")
        for key in ("priority_scope", "city_scope"):
            value = rule.get(key)
            if value is not None and not isinstance(value, list):
                raise ValueError(f"{code}.{key} 非法")
        if rule.get("priority_scope") is not None and set(rule["priority_scope"]) - {"P0", "P1", "P2"}:
            raise ValueError(f"{code}.priority_scope 非法")
        weights = rule.get("activity_fit_weights")
        if (not isinstance(weights, dict) or not weights or set(weights) - FIT_COMPONENTS
                or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in weights.values())
                or not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-8)):
            raise ValueError(f"{code}.activity_fit_weights 必须非负且总和为1")


def _meets(value: object, threshold: float | None, *, minimum: bool) -> bool:
    return threshold is None or (pd.notna(value) and (value >= threshold if minimum else value <= threshold))


def eligible(row: pd.Series | dict, campaign: dict) -> bool:
    """Apply only the campaign's basic entry rules, independently of Priority."""
    rule = campaign["rule"]
    if row["stage"] not in rule["eligible_stages"]:
        return False
    checks = (("top_progress", "min_top_progress", True), ("top_progress", "max_top_progress", False),
              ("potential_score", "min_potential_score", True), ("potential_percentile", "min_potential_percentile", True),
              ("confidence", "min_confidence", True), ("showings_56d", "min_showings_56d", True))
    if any(not _meets(row[field], rule.get(bound), minimum=minimum) for field, bound, minimum in checks):
        return False
    bottleneck = row["primary_bottleneck"]
    if rule.get("required_bottleneck") is not None and bottleneck != rule["required_bottleneck"]:
        return False
    if bottleneck in (rule.get("excluded_bottlenecks") or []):
        return False
    if rule.get("priority_scope") and row["priority"] not in rule["priority_scope"]:
        return False
    return not rule.get("city_scope") or row["city"] in rule["city_scope"]


def activity_fit(row: pd.Series | dict, campaign: dict) -> float | None:
    """Score the activity objective from available evidence on a 0–100 scale."""
    values = {
        "potential": row["potential_score"], "growth": row["growth_score"],
        "confidence": row["confidence"] * 100 if pd.notna(row["confidence"]) else None,
        "actionability": row["conversion_score"],
        "top_progress": min(100, row["top_progress"] * 100) if pd.notna(row["top_progress"]) else None,
        "funnel_health": row["conversion_score"],
        "closing_gap": 100 * (1 - row["closing_rate_pct"]) if pd.notna(row["closing_rate_pct"]) else None,
        "business_value": min(100, row["top_progress"] * 100) if pd.notna(row["top_progress"]) else None,
    }
    weighted = [(weight, values[key]) for key, weight in campaign["rule"]["activity_fit_weights"].items() if pd.notna(values[key])]
    if not weighted:
        return None
    return round(max(0, min(100, sum(weight * value for weight, value in weighted) / sum(weight for weight, _ in weighted))), 2)


def _reason(row: pd.Series, campaign: dict) -> str:
    progress = f"头部完成度{row['top_progress']:.0%}" if pd.notna(row["top_progress"]) else "头部完成度不可用"
    confidence = f"置信度{row['confidence']:.0%}" if pd.notna(row["confidence"]) else "置信度不可用"
    if campaign["campaign_id"] == "C02":
        return f"当前处于{row['stage']}，{progress}、{confidence}；未见被本活动排除的成交瓶颈，建议城市经理结合实际情况确认报名。"
    if campaign["campaign_id"] == "C03":
        return f"近56天带看{int(row['showings_56d'])}次，成交转化被诊断为持续或极端偏低，{confidence}；建议评估训练营席位。"
    return f"当前处于{row['stage']}，潜力同群百分位{row['potential_percentile']:.0%}，成长分{row['growth_score']:.0f}、{confidence}；建议城市经理复核成长计划适配性。"


def generate_candidates(agents: pd.DataFrame, campaigns: list[dict], recommended_at: date) -> pd.DataFrame:
    """Produce one system decision per campaign and agent; never enroll anyone."""
    rows: list[dict] = []
    for campaign in campaigns:
        code = campaign["campaign_id"]
        for _, agent in agents.iterrows():
            passes = eligible(agent, campaign)
            rows.append({"campaign_id": code, "agent_id": agent["agent_id"], "agent_name": agent["agent_name"],
                         "manager_id": agent["manager_id"], "manager_name": agent["manager_name"], "city": agent["city"],
                         "stage": agent["stage"], "priority": agent.get("priority", "未评估"),
                         "potential_score": agent["potential_score"], "confidence": agent["confidence"],
                         "top_progress": agent["top_progress"], "primary_bottleneck": agent["primary_bottleneck"],
                         "eligible_flag": passes, "activity_fit_score": activity_fit(agent, campaign) if passes else None,
                         "recommendation_reason": _reason(agent, campaign) if passes else "",
                         "recommended_at": recommended_at})
    result = pd.DataFrame(rows)
    result["activity_fit_percentile"] = pd.NA
    result["recommendation_rank"] = pd.NA
    for code, part in result.loc[result["eligible_flag"]].groupby("campaign_id", sort=False):
        ordered = part.sort_values(["activity_fit_score", "agent_id"], ascending=[False, True])
        result.loc[ordered.index, "recommendation_rank"] = range(1, len(ordered) + 1)
        result.loc[ordered.index, "activity_fit_percentile"] = part["activity_fit_score"].rank(pct=True, method="average").loc[ordered.index]
    if result.duplicated(["campaign_id", "agent_id"]).any():
        raise ValueError("campaign_candidate: campaign_id + agent_id 重复")
    return result


def current_enrollments(candidates: pd.DataFrame, events: list[dict]) -> pd.DataFrame:
    """Apply current-session choices to eligible candidates without touching history."""
    frame = candidates.loc[candidates["eligible_flag"]].copy()
    latest = {(event["campaign_id"], event["agent_id"]): event for event in events}
    frame["enrollment_status"] = [latest.get((row.campaign_id, row.agent_id), {}).get("status", "待选择") for row in frame.itertuples()]
    frame["decline_reason"] = [latest.get((row.campaign_id, row.agent_id), {}).get("decline_reason", "") for row in frame.itertuples()]
    frame["selected_at"] = [latest.get((row.campaign_id, row.agent_id), {}).get("event_at") for row in frame.itertuples()]
    frame["session_event_at"] = frame["selected_at"]
    return frame


def record_enrollment(events: list[dict], candidate: pd.Series | dict, campaign: dict,
                      manager_id: str, status: str, event_at: pd.Timestamp,
                      decline_reason: str = "", enrollments: pd.DataFrame | None = None) -> None:
    """Validate one city manager decision, including capacity and budget."""
    if not candidate["eligible_flag"] or candidate["campaign_id"] != campaign["campaign_id"] or candidate["manager_id"] != manager_id:
        raise ValueError("该经理无权处理此活动候选人")
    if campaign["status"] not in {"报名中", "进行中"}:
        raise ValueError("活动当前不可报名")
    if status not in {"已报名", "不参加"}:
        raise ValueError("enrollment_status 非法")
    if any(event["campaign_id"] == candidate["campaign_id"] and event["agent_id"] == candidate["agent_id"] for event in events):
        raise ValueError("该候选人已作出选择，不能重复报名")
    if status == "不参加" and decline_reason not in DECLINE_REASONS:
        raise ValueError("不参加必须选择有效原因")
    if status == "已报名":
        if enrollments is None:
            raise ValueError("报名需提供当前活动报名数据")
        enrolled = int(((enrollments["campaign_id"] == campaign["campaign_id"]) & enrollments["enrollment_status"].eq("已报名")).sum())
        if enrolled >= campaign["capacity"]:
            raise ValueError("活动名额已满")
        if (enrolled + 1) * campaign["unit_cost"] > campaign["budget"]:
            raise ValueError("活动预算不足")
    events.append({"campaign_id": candidate["campaign_id"], "agent_id": candidate["agent_id"],
                   "manager_id": manager_id, "status": status, "event_at": event_at,
                   "decline_reason": decline_reason if status == "不参加" else ""})


def simulate_historical_campaigns(candidates: pd.DataFrame, campaigns: list[dict], facts: pd.DataFrame,
                                  history: pd.DataFrame, config: dict, started_at: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate past city decisions; derive later business outcomes from dated facts."""
    rng = random.Random(config["historical_seed"])
    days = config["observation_days"]
    end = started_at + timedelta(days=days)
    before = history.loc[history["snapshot_date"] == started_at, ["agent_id", "stage"]].set_index("agent_id")["stage"]
    after = history.loc[history["snapshot_date"] == end, ["agent_id", "stage"]].set_index("agent_id")["stage"]
    daily = facts.loc[(facts["date"] > started_at) & (facts["date"] <= end)].groupby("agent_id").agg(
        observed_days=("date", "nunique"), deal_count=("deal_count", "sum"), deal_gtv=("deal_gtv", "sum"))
    enrollments: list[dict] = []
    outcomes: list[dict] = []
    for campaign in campaigns:
        enrolled = 0
        ordered = candidates.loc[(candidates["campaign_id"] == campaign["campaign_id"]) & candidates["eligible_flag"]].sort_values("recommendation_rank")
        for row in ordered.itertuples():
            choose = rng.random() < 0.78 and enrolled < campaign["capacity"] and (enrolled + 1) * campaign["unit_cost"] <= campaign["budget"]
            if choose:
                enrolled += 1
            participated = choose and rng.random() < 0.86
            completed = participated and rng.random() < 0.88
            observed = daily.loc[row.agent_id] if row.agent_id in daily.index else None
            enough = bool(participated and observed is not None and observed["observed_days"] >= days * config["min_observed_ratio"]
                          and row.agent_id in before.index and row.agent_id in after.index)
            stage_before = before.get(row.agent_id)
            stage_after = after.get(row.agent_id)
            enrollments.append({"campaign_id": campaign["campaign_id"], "agent_id": row.agent_id,
                                "manager_id": row.manager_id, "enrollment_status": "已报名" if choose else "不参加",
                                "selected_at": started_at, "decline_reason": "本人意愿不足" if not choose else "",
                                "session_event_at": None})
            outcomes.append({"campaign_id": campaign["campaign_id"], "agent_id": row.agent_id,
                             "participated": participated, "completed": completed,
                             "deal_count": int(observed["deal_count"]) if enough else None,
                             "deal_gtv": float(observed["deal_gtv"]) if enough else None,
                             "stage_before": stage_before, "stage_after": stage_after,
                             "promoted_to_head": bool(enough and stage_before == "准头部" and stage_after in HEAD),
                             "actual_cost": campaign["unit_cost"] if participated else 0,
                             "observation_status": "可观察" if enough else "样本不足" if participated else "未参与"})
    enrollment_frame = pd.DataFrame(enrollments)
    outcome_frame = pd.DataFrame(outcomes)
    keys = ["campaign_id", "agent_id"]
    if enrollment_frame.duplicated(keys).any() or outcome_frame.duplicated(keys).any():
        raise ValueError("历史活动 cohort 键重复")
    return enrollment_frame, outcome_frame


def campaign_review(candidates: pd.DataFrame, enrollments: pd.DataFrame,
                    outcomes: pd.DataFrame, campaigns: list[dict]) -> pd.DataFrame:
    """Aggregate each campaign's linked historical funnel and resource costs."""
    keys = ["campaign_id", "agent_id"]
    recommended = candidates.loc[candidates["eligible_flag"], keys]
    if (recommended.duplicated(keys).any() or enrollments.duplicated(keys).any() or outcomes.duplicated(keys).any()
            or not enrollments[keys].merge(recommended, on=keys, how="left", indicator=True)["_merge"].eq("both").all()
            or not outcomes[keys].merge(enrollments[keys], on=keys, how="left", indicator=True)["_merge"].eq("both").all()):
        raise ValueError("活动历史 recommendation → enrollment → outcome cohort 不一致")
    linked = outcomes.merge(enrollments[keys + ["enrollment_status"]], on=keys, validate="one_to_one")
    if ((linked["participated"] & linked["enrollment_status"].ne("已报名")).any()
            or (linked["completed"] & ~linked["participated"]).any()):
        raise ValueError("活动历史报名 → 参与 → 完成状态链不一致")
    rows = []
    for campaign in campaigns:
        code = campaign["campaign_id"]
        rec = int((recommended["campaign_id"] == code).sum())
        enr = enrollments.loc[(enrollments["campaign_id"] == code) & enrollments["enrollment_status"].eq("已报名")]
        out = outcomes.loc[outcomes["campaign_id"] == code]
        part = out.loc[out["participated"]]
        done = part.loc[part["completed"]]
        observable = done.loc[done["observation_status"] == "可观察"]
        deals = observable.loc[observable["deal_count"] > 0]
        promoted = deals.loc[deals["promoted_to_head"]]
        cost = float(part["actual_cost"].sum())
        rows.append({"campaign_id": code, "campaign_name": campaign["campaign_name"], "eligible": rec,
                     "recommended": rec, "enrolled": len(enr), "participated": len(part), "completed": len(done),
                     "observable": len(observable), "insufficient": int(part["observation_status"].eq("样本不足").sum()),
                     "deal_agents": len(deals), "deal_count": int(observable["deal_count"].sum()),
                     "deal_gtv": float(observable["deal_gtv"].sum()),
                     "near_top_before": int(observable["stage_before"].eq("准头部").sum()),
                     "promoted": len(promoted), "budget": campaign["budget"], "actual_cost": cost,
                     "budget_usage": safe_ratio(cost, campaign["budget"]),
                     "cost_per_participant": safe_ratio(cost, len(part)),
                     "cost_per_deal_agent": safe_ratio(cost, len(deals)),
                     "cost_per_new_head": safe_ratio(cost, len(promoted)),
                     "upgrade_rate": safe_ratio(len(promoted), int(observable["stage_before"].eq("准头部").sum()))})
    return pd.DataFrame(rows)
