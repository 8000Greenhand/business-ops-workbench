"""Guardrails, capacity and recommendation ordering."""

from datetime import date

import pandas as pd

from ops_workbench.diagnostics.super_agent import action_guard, load_actions, prioritize, recommend
from ops_workbench.metrics.super_agent import load_policy
from ops_workbench.ui.super_agent_dashboard import build_dashboard


def test_a02_a07_cooldown_and_low_confidence():
    data = build_dashboard()
    actions = {x["action_code"]: x for x in load_actions()}
    p = data.policy
    day = data.facts["date"].max()
    c = data.agents.loc[data.agents["case"] == "C"].iloc[0].to_dict()
    assert action_guard(c, actions["A02"], p, day) == ""
    assert action_guard(c, actions["A02"], p, day, used_capacity=actions["A02"]["capacity_per_cycle"]) == "城市动作容量已满"
    c["confidence"] = 0.4
    assert action_guard(c, actions["A02"], p, day) == "置信度不足"
    e = data.agents.loc[data.agents["case"] == "E"].iloc[0].to_dict()
    assert action_guard(e, actions["A02"], p, day) != ""
    b = data.agents.loc[data.agents["case"] == "B"].iloc[0].to_dict()
    inactive = {**p, "campaign": {**p["campaign"], "active": False}}
    assert action_guard(b, actions["A07"], inactive, day) == "无可用活动预算"
    b.update(last_action_at=pd.Timestamp(day), last_action_code="A01")
    assert action_guard(b, actions["A01"], p, day) == "冷却中"


def test_priority_threshold_capacity_fatigue_and_head_defense():
    p = load_policy()
    base = {"stage": "准头部", "top_progress": 0.95, "top_at_risk": False,
            "primary_bottleneck": "none", "confidence": 0.95, "touches_7d": 0, "manager_id": "m"}
    rows = [{**base, "agent_id": str(i)} for i in range(6)]
    ranked = prioritize(pd.DataFrame(rows), p)
    assert ranked["priority"].eq("P0").sum() == 5
    assert ranked["capacity_deferred"].sum() == 1
    rows = [{**base, "agent_id": "low", "top_progress": 0.1}]
    assert prioritize(pd.DataFrame(rows), p).iloc[0]["priority"] != "P0"
    rows = [{**base, "agent_id": "head", "stage": "稳定头部", "top_progress": 0.6, "top_at_risk": True}]
    assert prioritize(pd.DataFrame(rows), p).iloc[0]["priority"] == "P0"
    rows.append({**rows[0], "agent_id": "fatigued", "touches_7d": 3})
    scored = prioritize(pd.DataFrame(rows), p)
    assert scored.loc[scored["agent_id"] == "fatigued", "priority_score"].iloc[0] < scored.loc[scored["agent_id"] == "head", "priority_score"].iloc[0]


def test_top_n_stable_and_suppression_retained():
    data = build_dashboard()
    a = data.agents.head(30)
    first = recommend(a, data.policy, load_actions(), data.facts["date"].max())
    second = recommend(a, data.policy, load_actions(), data.facts["date"].max())
    pd.testing.assert_frame_equal(first, second)
    assert first.loc[~first["suppressed_flag"], "rank_no"].max() <= len(load_actions())
    assert first["suppressed_flag"].any()
