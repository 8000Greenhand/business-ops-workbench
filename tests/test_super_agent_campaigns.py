"""Campaign rule, cohort, resource, and concept-separation regression tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pandas as pd
import pytest

from ops_workbench.metrics.super_agent_campaigns import (activity_fit, campaign_review,
    campaign_overview, current_enrollments, eligible, generate_candidates, load_campaigns,
    matched_campaigns_for_agent, record_enrollment, simulate_historical_campaigns,
    validate_campaigns)
from ops_workbench.ui.super_agent_dashboard import build_dashboard


@pytest.fixture(scope="module")
def demo():
    return build_dashboard()


def _campaign(code: str) -> dict:
    return next(item for item in load_campaigns()["campaigns"] if item["campaign_id"] == code)


def test_three_configured_campaigns_and_fail_fast_validation():
    config = load_campaigns()
    assert [item["campaign_id"] for item in config["campaigns"]] == ["C01", "C02", "C03"]
    for campaign in config["campaigns"]:
        assert sum(campaign["rule"]["activity_fit_weights"].values()) == pytest.approx(1)
    mutations = [
        (lambda c: c["campaigns"][1].update(campaign_id="C01"), "campaign_id"),
        (lambda c: c["campaigns"][0].update(end_date="2026-01-01"), "start_date"),
        (lambda c: c["campaigns"][0]["rule"].update(eligible_stages=["非法"]), "eligible_stages"),
        (lambda c: c["campaigns"][0].update(budget=-1), "budget"),
        (lambda c: c["campaigns"][0].update(capacity=-1), "capacity"),
        (lambda c: c["campaigns"][0]["rule"].update(activity_fit_weights={"growth": .5}), "activity_fit_weights"),
        (lambda c: c["campaigns"][0]["rule"].update(min_confidence=1.1), "min_confidence"),
    ]
    for mutate, field in mutations:
        invalid = deepcopy(config)
        mutate(invalid)
        with pytest.raises(ValueError, match=field):
            validate_campaigns(invalid)


def test_candidate_gates_fit_and_stable_rank(demo):
    agents = demo.agents
    before = agents[["stage", "potential_score", "priority_score", "priority"]].copy(deep=True)
    campaigns = load_campaigns()["campaigns"]
    candidates = generate_candidates(agents, campaigns, demo.facts["date"].max())
    pd.testing.assert_frame_equal(before, agents[["stage", "potential_score", "priority_score", "priority"]])
    assert not candidates.duplicated(["campaign_id", "agent_id"]).any()
    pd.testing.assert_frame_equal(candidates, generate_candidates(agents, campaigns, demo.facts["date"].max()))
    chosen = candidates.loc[candidates["eligible_flag"]]
    assert chosen["activity_fit_score"].between(0, 100).all()
    assert chosen["manager_id"].notna().all()
    assert chosen["recommendation_rank"].notna().all()
    assert chosen["activity_fit_percentile"].between(0, 1).all()
    for _, part in chosen.groupby("campaign_id"):
        ordered = part.sort_values(["activity_fit_score", "agent_id"], ascending=[False, True])
        assert ordered["recommendation_rank"].tolist() == list(range(1, len(part) + 1))
    ids = set(chosen["agent_id"])
    for priority in ("P0", "P1"):
        assert demo.agents.loc[demo.agents["priority"] == priority, "agent_id"].isin(ids).any()
    assert (~demo.agents.loc[demo.agents["priority"] == "P0", "agent_id"].isin(ids)).any()
    assert set(chosen["priority"]) >= {"P0", "P1", "P2"}


def test_multiple_campaign_matches_are_preserved_without_cross_campaign_winner(demo):
    current = demo.campaign_candidates.loc[demo.campaign_candidates["eligible_flag"]]
    overlap = current.groupby("agent_id").size().loc[lambda counts: counts >= 2]
    if overlap.empty:
        first = current.loc[current["campaign_id"] == "C01"].iloc[0].copy()
        second = first.copy()
        second["campaign_id"] = "C03"
        first["activity_fit_score"], first["activity_fit_percentile"] = 82.0, 0.80
        second["activity_fit_score"], second["activity_fit_percentile"] = 78.0, 0.95
        sample = pd.DataFrame([first, second])
    else:
        sample = current.loc[current["agent_id"] == overlap.index[0]].copy()
    original = demo.agents[["stage", "potential_score", "priority_score", "priority"]].copy(deep=True)
    matched = matched_campaigns_for_agent(sample, demo.campaigns, sample.iloc[0]["agent_id"])
    assert len(matched) >= 2
    assert set(matched["campaign_id"]) == set(sample["campaign_id"])
    assert matched["activity_fit_percentile"].tolist() == sorted(matched["activity_fit_percentile"], reverse=True)
    assert "activity_fit_score" not in demo.agents.columns
    assert "activity_recommendation" not in demo.agents.columns
    if overlap.empty:
        assert matched["campaign_id"].tolist() == ["C03", "C01"]
        assert matched["activity_fit_score"].tolist() == [78.0, 82.0]
    pd.testing.assert_frame_equal(original, demo.agents[["stage", "potential_score", "priority_score", "priority"]])


def test_current_status_budget_and_cross_campaign_person_times(demo):
    current = current_enrollments(demo.campaign_candidates, [])
    summary = campaign_overview(demo.campaigns, current)
    statuses = demo.campaigns["status"]
    active = demo.campaigns.loc[statuses.isin(["报名中", "进行中"])]
    assert summary["current_campaigns"] == len(active) == 3
    assert summary["accepting"] == statuses.eq("报名中").sum() == 2
    assert summary["running"] == statuses.eq("进行中").sum() == 1
    assert summary["budget"] == active["budget"].sum()
    assert summary["recommended_person_times"] == len(current) == int(demo.campaign_candidates["eligible_flag"].sum())
    assert summary["enrolled_person_times"] == 0
    synthetic_campaigns = pd.DataFrame([
        {"campaign_id": "A", "status": "报名中", "budget": 100, "capacity": 2},
        {"campaign_id": "B", "status": "进行中", "budget": 200, "capacity": 2},
        {"campaign_id": "C", "status": "筹备中", "budget": 300, "capacity": 2},
        {"campaign_id": "D", "status": "已结束", "budget": 400, "capacity": 2},
    ])
    choices = pd.DataFrame([
        {"campaign_id": "A", "agent_id": "same", "enrollment_status": "已报名"},
        {"campaign_id": "B", "agent_id": "same", "enrollment_status": "已报名"},
        {"campaign_id": "C", "agent_id": "other", "enrollment_status": "待选择"},
    ])
    separate = campaign_overview(synthetic_campaigns, choices)
    assert separate["current_campaigns"] == 2
    assert separate["budget"] == 300
    assert separate["recommended_person_times"] == 2
    assert separate["enrolled_person_times"] == 2  # One person, two campaign enrollments.


def test_eligibility_stage_confidence_progress_and_closing_sample(demo):
    candidates = demo.campaign_candidates
    for code in ("C01", "C02", "C03"):
        campaign = _campaign(code)
        person = candidates.loc[(candidates["campaign_id"] == code) & candidates["eligible_flag"]].iloc[0]
        row = demo.agents.loc[demo.agents["agent_id"] == person["agent_id"]].iloc[0].copy()
        assert eligible(row, campaign)
        assert activity_fit(row, campaign) == pytest.approx(person["activity_fit_score"])
        row["stage"] = "稳定头部"
        assert not eligible(row, campaign)
        row = demo.agents.loc[demo.agents["agent_id"] == person["agent_id"]].iloc[0].copy()
        row["confidence"] = 0.01
        assert not eligible(row, campaign)
        if code == "C02":
            row["confidence"] = 0.99
            row["top_progress"] = 0.84
            assert not eligible(row, campaign)
        if code == "C03":
            row["confidence"] = 0.99
            row["showings_56d"] = 0
            assert not eligible(row, campaign)
            row["showings_56d"] = 20
            row["primary_bottleneck"] = "none"
            assert not eligible(row, campaign)
    c02 = candidates.loc[(candidates["campaign_id"] == "C02") & candidates["eligible_flag"]]
    assert c02["stage"].eq("准头部").all()
    assert c02["top_progress"].ge(.85).all()


def test_city_choice_status_reason_capacity_and_budget(demo):
    candidates = demo.campaign_candidates
    campaign = _campaign("C02")
    row = candidates.loc[(candidates["campaign_id"] == "C02") & candidates["eligible_flag"]].iloc[0]
    events: list[dict] = []
    current = current_enrollments(candidates, events)
    assert current["enrollment_status"].eq("待选择").all()
    with pytest.raises(ValueError, match="无权"):
        record_enrollment(events, row, campaign, "other-manager", "已报名", pd.Timestamp.now(), enrollments=current)
    with pytest.raises(ValueError, match="原因"):
        record_enrollment(events, row, campaign, row["manager_id"], "不参加", pd.Timestamp.now(), enrollments=current)
    full = deepcopy(campaign)
    full["capacity"] = 0
    with pytest.raises(ValueError, match="名额已满"):
        record_enrollment(events, row, full, row["manager_id"], "已报名", pd.Timestamp.now(), enrollments=current)
    broke = deepcopy(campaign)
    broke["budget"] = 0
    with pytest.raises(ValueError, match="预算不足"):
        record_enrollment(events, row, broke, row["manager_id"], "已报名", pd.Timestamp.now(), enrollments=current)
    record_enrollment(events, row, campaign, row["manager_id"], "已报名", pd.Timestamp.now(), enrollments=current)
    assert current_enrollments(candidates, events).loc[lambda f: (f.campaign_id == "C02") & (f.agent_id == row.agent_id), "enrollment_status"].iloc[0] == "已报名"
    with pytest.raises(ValueError, match="不能重复"):
        record_enrollment(events, row, campaign, row["manager_id"], "已报名", pd.Timestamp.now(), enrollments=current_enrollments(candidates, events))
    another = candidates.loc[(candidates["campaign_id"] == "C02") & candidates["eligible_flag"] & candidates["agent_id"].ne(row["agent_id"])].iloc[0]
    record_enrollment(events, another, campaign, another["manager_id"], "不参加", pd.Timestamp.now(), "本人意愿不足", current)
    declined = current_enrollments(candidates, events).loc[lambda f: (f.campaign_id == "C02") & (f.agent_id == another.agent_id)].iloc[0]
    assert declined["enrollment_status"] == "不参加"
    assert declined["decline_reason"] == "本人意愿不足"
    assert len(events) == 2


def test_historical_campaign_cohort_and_factual_outcomes(demo):
    candidates = demo.historical_campaign_candidates
    enrollments = demo.historical_campaign_enrollments
    outcomes = demo.historical_campaign_outcomes
    keys = ["campaign_id", "agent_id"]
    assert not candidates.duplicated(keys).any()
    assert not enrollments.duplicated(keys).any()
    assert not outcomes.duplicated(keys).any()
    assert set(map(tuple, outcomes[keys].to_numpy())).issubset(set(map(tuple, enrollments[keys].to_numpy())))
    assert set(map(tuple, enrollments[keys].to_numpy())).issubset(set(map(tuple, candidates.loc[candidates.eligible_flag, keys].to_numpy())))
    review = campaign_review(candidates, enrollments, outcomes, load_campaigns()["campaigns"])
    assert (review["recommended"] >= review["enrolled"]).all()
    assert (review["enrolled"] >= review["participated"]).all()
    assert (review["participated"] >= review["completed"]).all()
    assert (review["completed"] >= review["deal_agents"]).all()
    assert review["deal_count"].gt(0).all()
    assert review.loc[review["campaign_id"] == "C02", "promoted"].iloc[0] > 0
    assert pd.isna(review.loc[review["promoted"] == 0, "cost_per_new_head"]).all()
    sampled = outcomes.loc[outcomes["observation_status"] == "可观察"].iloc[0]
    started = demo.facts["date"].max() - timedelta(days=42)
    after = demo.facts.loc[(demo.facts.agent_id == sampled.agent_id) & (demo.facts.date > started) &
                           (demo.facts.date <= started + timedelta(days=28))]
    assert sampled.deal_count == after.deal_count.sum()
    assert sampled.deal_gtv == after.deal_gtv.sum()
    broken = outcomes.copy()
    broken.loc[broken.index[0], "campaign_id"] = "INVALID"
    with pytest.raises(ValueError, match="cohort"):
        campaign_review(candidates, enrollments, broken, load_campaigns()["campaigns"])
    impossible = outcomes.copy()
    declined = enrollments.loc[enrollments["enrollment_status"] == "不参加"].iloc[0]
    mismatch = (impossible["campaign_id"] == declined["campaign_id"]) & (impossible["agent_id"] == declined["agent_id"])
    impossible.loc[mismatch, "participated"] = True
    with pytest.raises(ValueError, match="状态链"):
        campaign_review(candidates, enrollments, impossible, load_campaigns()["campaigns"])


def test_historical_simulation_deterministic_and_missing_not_zero(demo):
    config = load_campaigns()
    started = demo.facts["date"].max() - timedelta(days=42)
    first = simulate_historical_campaigns(demo.historical_campaign_candidates, config["campaigns"],
                                           demo.facts, demo.history, config, started)
    second = simulate_historical_campaigns(demo.historical_campaign_candidates, config["campaigns"],
                                            demo.facts, demo.history, config, started)
    pd.testing.assert_frame_equal(first[0], second[0])
    pd.testing.assert_frame_equal(first[1], second[1])
    _, no_facts = simulate_historical_campaigns(demo.historical_campaign_candidates, config["campaigns"],
                                                 demo.facts.iloc[0:0], demo.history, config, started)
    observed = no_facts.loc[no_facts["participated"]]
    assert observed["observation_status"].eq("样本不足").all()
    assert observed["deal_count"].isna().all()
    assert observed["deal_gtv"].isna().all()


def test_campaign_deal_and_promotion_are_parallel_outcomes():
    candidates = pd.DataFrame([
        {"campaign_id": "C02", "agent_id": agent_id, "eligible_flag": True}
        for agent_id in ("deal-only", "promotion-only")])
    enrollments = pd.DataFrame([
        {"campaign_id": "C02", "agent_id": agent_id, "enrollment_status": "已报名"}
        for agent_id in ("deal-only", "promotion-only")])
    outcomes = pd.DataFrame([
        {"campaign_id": "C02", "agent_id": "deal-only", "participated": True, "completed": True,
         "observation_status": "可观察", "deal_count": 1, "deal_gtv": 1000,
         "stage_before": "准头部", "promoted_to_head": False, "actual_cost": 100},
        {"campaign_id": "C02", "agent_id": "promotion-only", "participated": True, "completed": True,
         "observation_status": "可观察", "deal_count": 0, "deal_gtv": 0,
         "stage_before": "准头部", "promoted_to_head": True, "actual_cost": 100},
    ])
    result = campaign_review(candidates, enrollments, outcomes, [_campaign("C02")]).iloc[0]
    assert result["deal_agents"] == 1
    assert result["deal_count"] == 1
    assert result["promoted"] == 1
    assert result["near_top_before"] == 2
    assert result["upgrade_rate"] == pytest.approx(0.5)
    assert result["cost_per_new_head"] == 200
