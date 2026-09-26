"""Diagnosis needs persistence or extremity plus usable samples."""

from ops_workbench.diagnostics.super_agent import diagnose
from ops_workbench.metrics.super_agent import load_policy
from ops_workbench.ui.super_agent_dashboard import build_dashboard


def test_pressure_guardrails_and_representative_bottlenecks():
    data = build_dashboard()
    agents = data.agents
    cases = agents.set_index("case")
    assert set("ABCDEFGH").issubset(set(cases.index))
    assert cases.loc["A", "stage"] == "高潜" and cases.loc["A", "top_progress"] < 0.72
    assert cases.loc["B", "stage"] == "准头部" and cases.loc["B", "primary_action_code"] in {"A01", "A07"}
    assert cases.loc["C", "primary_bottleneck"] == "resource" and cases.loc["C", "primary_action_code"] == "A02"
    assert cases.loc["D", "primary_bottleneck"] == "closing" and cases.loc["D", "primary_action_code"] == "A06"
    assert cases.loc["E", "potential_score"] >= 65 and cases.loc["E", "confidence"] < 0.65
    assert cases.loc["E", "observed_days_56d"] < 20
    assert cases.loc["F", "top_at_risk"] and cases.loc["F", "priority"] == "P0"
    g = cases.loc["G"]
    assert g["touches_7d"] >= 2
    assert data.recommendations.loc[data.recommendations["agent_id"] == g["agent_id"], "suppression_reason"].isin(["冷却中", "触达频率上限"]).any()
    assert cases.loc["H", "priority"] == "P1" and cases.loc["H", "capacity_deferred"]
    assert agents.loc[(agents["manager_id"] == cases.loc["H", "manager_id"]) & (agents["priority"] == "P0")].shape[0] == data.policy["priority"]["p0_capacity_per_manager"]
    assert (agents["primary_bottleneck"] == "none").sum() > len(agents) * 0.2
    assert agents["stage"].eq("高潜").sum() < agents["stage"].ne("无效/沉默").sum() / 2
    assert agents["primary_action_code"].nunique() >= 3
    assert agents.loc[agents["priority"] == "P0"].groupby("manager_id").size().max() <= data.policy["priority"]["p0_capacity_per_manager"]


def test_resource_requires_downstream_evidence_and_random_low_is_not_enough():
    policy = load_policy()
    data = build_dashboard()
    row = data.agents.loc[data.agents["case"] == "C"].iloc[0].copy()
    assert row["resource_flag"]
    row["opportunity_received"] = 0
    row["previous_opportunity_received"] = 100
    row["acceptance_rate_pct"] = 0.1
    row["followup_rate_pct"] = 0.1
    row["showing_rate_pct"] = 0.1
    row["closing_rate_pct"] = 0.1
    modified = data.agents.copy()
    for key in row.index:
        modified.at[row.name, key] = row[key]
    result = diagnose(modified, policy)
    assert not result.at[row.name, "resource_flag"]


def test_closing_needs_56_day_sample():
    data = build_dashboard()
    row = data.agents.loc[data.agents["case"] == "D"].iloc[0]
    assert row["showings_56d"] >= data.policy["bottleneck"]["min_showings_56d"]
    assert row["closing_flag"]
    modified = data.agents.copy()
    modified.at[row.name, "showings_56d"] = 1
    assert not diagnose(modified, data.policy).at[row.name, "closing_flag"]
