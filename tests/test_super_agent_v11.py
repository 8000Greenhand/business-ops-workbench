"""V1.1 state, configuration and linked outcome regression tests."""

from copy import deepcopy
from datetime import date, timedelta

import pandas as pd
import pytest

from ops_workbench.diagnostics.super_agent import action_guard, action_kpis, load_actions
from ops_workbench.metrics.super_agent import load_policy, transition_stage, validate_actions, validate_policy
from ops_workbench.ui.super_agent_dashboard import (build_dashboard, record_session_event,
    session_progress, task_statuses)


@pytest.mark.parametrize("candidate,high,expected", [
    ("准头部", False, "准头部"), ("活跃", True, "高潜"), ("活跃", False, "活跃")])
def test_head_miss_returns_to_highest_supported_stage(candidate, high, expected):
    policy = load_policy()
    streaks = {"top": 3, "miss": 0}
    row = {"top_met": False, "effective_work_flag": 12, "candidate_stage": candidate,
           "high_potential_candidate": high, "top_progress": 0.8 if candidate == "准头部" else 0.6,
           "potential_percentile": 0.95, "confidence": 0.9}
    assert transition_stage("稳定头部", row, streaks, policy) == ("稳定头部", True)
    assert transition_stage("稳定头部", row, streaks, policy) == (expected, False)


def test_extreme_silence_precedes_top_grace():
    policy = load_policy()
    row = {"top_met": False, "effective_work_flag": 0, "candidate_stage": "无效/沉默",
           "high_potential_candidate": False, "top_progress": 0, "potential_percentile": 0,
           "confidence": 0}
    assert transition_stage("稳定头部", row, {"top": 3}, policy) == ("无效/沉默", False)


@pytest.mark.parametrize("field,value", [
    ("top.operator", "XOR"), ("priority.p0_capacity_per_manager", -1),
    ("lifecycle.near_top_fast_track", 0.1), ("priority.p0_threshold", 20),
    ("confidence.weights.observed_days", -0.1), ("confidence.weights.peer_sample", 0.2)])
def test_policy_fails_fast(field, value):
    policy = deepcopy(load_policy())
    node = policy
    for key in field.split(".")[:-1]:
        node = node[key]
    node[field.split(".")[-1]] = value
    with pytest.raises(ValueError, match=field.split(".")[0]):
        validate_policy(policy)


def test_action_catalog_fails_fast():
    actions = load_actions()
    for alteration, pattern in [({"action_code": "A01"}, "action_code"),
                                ({"eligible_stages": ["不存在"]}, "eligible_stages"),
                                ({"capacity_per_cycle": -1}, "capacity_per_cycle")]:
        changed = deepcopy(actions)
        changed[1].update(alteration)
        with pytest.raises(ValueError, match=pattern):
            validate_actions(changed)


@pytest.fixture(scope="module")
def dashboard():
    return build_dashboard()


def test_confidence_bounds_and_cases(dashboard):
    weights = dashboard.policy["confidence"]["weights"]
    assert sum(weights.values()) == pytest.approx(1)
    assert dashboard.agents["confidence"].between(0, 1).all()
    assert set("ABCDEFGH").issubset(set(dashboard.agents["case"]))
    case_e = dashboard.agents.loc[dashboard.agents["case"] == "E"].iloc[0]
    assert case_e["confidence"] < dashboard.policy["potential"]["confidence_gate"]
    assert case_e["primary_action_code"] == "A10"
    counts = dashboard.agents.groupby("manager_id")["priority"].apply(lambda values: values.eq("P0").sum())
    assert counts.max() <= dashboard.policy["priority"]["p0_capacity_per_manager"]
    assert counts.min() == 0  # Capacity is a ceiling, never a fill target.


def test_action_reservation_is_not_actual_cost(dashboard):
    actions = {action["action_code"]: action for action in load_actions()}
    recs = dashboard.recommendations
    assert recs.loc[recs["capacity_reserved"], "rank_no"].between(1, dashboard.policy["recommendation"]["top_n"]).all()
    assert recs.loc[recs["suppressed_flag"], "capacity_reserved"].eq(False).all()
    c = dashboard.agents.loc[dashboard.agents["case"] == "C"].iloc[0].to_dict()
    day = dashboard.facts["date"].max()
    assert action_guard(c, actions["A02"], dashboard.policy, day, used_capacity=actions["A02"]["capacity_per_cycle"]) == "城市动作容量已满"
    b = dashboard.agents.loc[dashboard.agents["case"] == "B"].iloc[0].to_dict()
    assert action_guard(b, actions["A07"], dashboard.policy, day, used_capacity=dashboard.policy["campaign"]["capacity"]) == "活动容量已满"
    budgetless = deepcopy(dashboard.policy)
    budgetless["campaign"]["budget"] = 0
    assert action_guard(b, actions["A07"], budgetless, day) == "无可用活动预算"


def test_historical_recommendation_execution_cohort(dashboard):
    rec = dashboard.historical_recommendations
    log = dashboard.action_log
    assert rec["recommendation_id"].is_unique and log["recommendation_id"].is_unique
    assert set(log["recommendation_id"]) == set(rec["recommendation_id"])
    assert (log.loc[log["status"] != "已执行", "cost"] == 0).all()
    assert log.loc[log["status"] == "跳过", "skip_reason"].ne("").all()
    assert dashboard.action_kpis["recommended_count"] == rec["agent_id"].nunique()
    assert dashboard.action_kpis["executed_count"] == log.loc[log["status"] == "已执行", "agent_id"].nunique()
    assert dashboard.action_kpis["outcome_windows"][28]["insufficient"] >= 1
    assert set(dashboard.action_kpis["outcome_detail"][0]) >= {"recommendation_id", "outcome_status", "improved", "upgraded"}
    broken = log.copy()
    broken.loc[broken.index[0], "recommendation_id"] = "missing"
    with pytest.raises(ValueError, match="无推荐来源"):
        action_kpis(rec, broken, dashboard.history, dashboard.facts, dashboard.policy)


def test_missing_before_after_excluded_from_improvement(dashboard):
    rec = dashboard.historical_recommendations.head(1).copy()
    log = dashboard.action_log.loc[dashboard.action_log["recommendation_id"].isin(rec["recommendation_id"])].copy()
    log.loc[:, "status"] = "已执行"
    day = dashboard.facts["date"].max() - timedelta(days=35)
    log.loc[:, "recommended_at"] = day - timedelta(days=2)
    log.loc[:, "accepted_at"] = day - timedelta(days=1)
    log.loc[:, "executed_at"] = day
    log.loc[:, "action_at"] = day
    log.loc[:, "cost"] = 20
    rec.loc[:, "recommended_at"] = day - timedelta(days=2)
    facts = dashboard.facts.loc[(dashboard.facts["agent_id"] != log.iloc[0]["agent_id"]) | (dashboard.facts["date"] <= day)].copy()
    outcome = action_kpis(rec, log, dashboard.history, facts, dashboard.policy)["outcome_windows"][7]
    assert outcome["eligible"] == 1 and outcome["observable"] == 0
    assert outcome["insufficient"] == 1 and outcome["improvement_rate"] is None


def test_session_state_is_shared_but_excluded_from_history(dashboard):
    row = dashboard.agents.loc[dashboard.agents["priority"] == "P0"].iloc[0]
    events: list[dict] = []
    as_of = dashboard.facts["date"].max()
    baseline = dashboard.action_kpis["executed_count"]
    record_session_event(events, row, "已接受", pd.Timestamp.now())
    assert task_statuses(dashboard.agents, events, as_of)[row["agent_id"]] == "已接受"
    record_session_event(events, row, "已执行", pd.Timestamp.now())
    assert task_statuses(dashboard.agents, events, as_of)[row["agent_id"]] == "已执行"
    assert session_progress(events) == {"已接受": 1, "已执行": 1, "跳过": 0}
    assert dashboard.action_kpis["executed_count"] == baseline
    another = dashboard.agents.loc[(dashboard.agents["priority"] == "P0") & (dashboard.agents["agent_id"] != row["agent_id"])].iloc[0]
    record_session_event(events, another, "跳过", pd.Timestamp.now(), "经纪人暂不可联系")
    assert events[-1]["skip_reason"] == "经纪人暂不可联系"
    assert task_statuses(dashboard.agents, events, as_of)[another["agent_id"]] == "跳过"
