"""Core simulated agent metric and lifecycle invariants."""

from datetime import date

import pandas as pd
import pytest

from ops_workbench.metrics.super_agent import (aggregate_period, build_snapshots,
    load_policy, safe_ratio, top_completion, transition_kpis, transition_stage, _peer_scope)
from ops_workbench.simulation.super_agent import simulate_agents


@pytest.fixture(scope="module")
def demo():
    policy = load_policy()
    master, facts = simulate_agents(policy)
    return policy, master, facts


def test_seed_is_repeatable(demo):
    policy, master, facts = demo
    again_master, again_facts = simulate_agents(policy)
    pd.testing.assert_frame_equal(master, again_master)
    pd.testing.assert_frame_equal(facts, again_facts)
    assert len(master) >= 1200
    assert facts["date"].nunique() >= 90


def test_ratios_from_atomic_sums_and_nulls():
    assert safe_ratio(3, 0) is None
    assert safe_ratio(3, None) is None
    rows = pd.DataFrame({"agent_id": ["x", "x"], "date": [date(2026, 1, 1), date(2026, 1, 2)],
        "opportunity_received": [1, 9], "opportunity_accepted": [1, 0],
        "valid_followup_count": [1, 0], "showing_count": [1, 0], "deal_count": [1, 0],
        "deal_gtv": [100, 0], "effective_work_flag": [1, 1]})
    output = aggregate_period(rows, date(2026, 1, 2), 2, pd.Index(["x"], name="agent_id"))
    assert output.loc["x", "acceptance_rate"] == pytest.approx(0.1)


def test_top_and_or_paths(demo):
    policy = demo[0]
    row = {"deal_count": 9, "deal_gtv": 460800}
    progress, gap, met = top_completion(row, policy)
    assert progress == pytest.approx(0.72) and gap == "deal_gtv" and not met
    alternate = {**policy, "top": {**policy["top"], "operator": "OR"}}
    progress, gap, met = top_completion(row, alternate)
    assert progress > 1 and gap == "deal_count" and met


def test_transition_confirmation_and_grace(demo):
    p = demo[0]
    state = {}
    row = {"top_met": True, "effective_work_flag": 20, "candidate_stage": "新晋头部",
           "high_potential_candidate": False, "top_progress": 1.1, "potential_percentile": 0.4, "confidence": 0.9}
    stage, risk = transition_stage("活跃", row, state, p)
    assert (stage, risk) == ("新晋头部", False)
    for _ in range(p["lifecycle"]["stable_top_confirm_periods"] - 1):
        stage, _ = transition_stage(stage, row, state, p)
    assert stage == "稳定头部"
    row["top_met"] = False
    row["candidate_stage"] = "准头部"
    stage, risk = transition_stage(stage, row, state, p)
    assert stage == "稳定头部" and risk
    stage, risk = transition_stage(stage, row, state, p)
    assert stage != "稳定头部" and not risk
    state = {}
    row.update(candidate_stage="活跃", high_potential_candidate=True, top_progress=0.4)
    stage, _ = transition_stage("活跃", row, state, p)
    assert stage == "活跃"
    stage, _ = transition_stage(stage, row, state, p)
    assert stage == "高潜"


def test_peer_fallback_and_snapshot_exclusivity(demo):
    p, master, facts = demo
    tiny = pd.DataFrame({"agent_id": ["a", "b", "c"], "city": ["成都", "成都", "重庆"],
                         "candidate_stage": ["活跃", "准头部", "活跃"]})
    scope, size = _peer_scope(tiny, {**p, "peer": {"min_sample_size": 2}})
    assert scope.iloc[0] == "同城市×相邻成长阶段" and size.iloc[0] == 2
    latest, history = build_snapshots(master, facts, p)
    assert not history.duplicated(["agent_id", "snapshot_date"]).any()
    assert latest["stage"].nunique() >= 4
    assert latest["high_potential_candidate"].sum() < latest["candidate_stage"].eq("活跃").sum() / 2
    high = latest.loc[latest["high_potential_candidate"]]
    assert (high["potential_percentile"] >= p["potential"]["percentile_gate"]).all()
    assert (high["confidence"] >= p["potential"]["confidence_gate"]).all()


def test_transition_kpis_cohorts():
    history = pd.DataFrame({"snapshot_date": [date(2026, 1, 1)] * 4 + [date(2026, 1, 8)] * 4,
        "agent_id": ["a", "b", "c", "d"] * 2,
        "stage": ["准头部", "稳定头部", "新晋头部", "活跃", "新晋头部", "活跃", "稳定头部", "活跃"]})
    k = transition_kpis(history)
    assert k["head_count"] == 2 and k["net_new_head"] == 0
    assert k["head_retention_rate"] == pytest.approx(0.5)
    assert k["near_top_to_head_upgrade_rate"] == pytest.approx(1)
