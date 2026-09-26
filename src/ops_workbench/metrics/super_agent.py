"""Snapshot metrics, peer comparisons and simulated lifecycle transitions."""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml


STAGES = ("无效/沉默", "活跃", "高潜", "准头部", "新晋头部", "稳定头部")
HEAD = {"新晋头部", "稳定头部"}
COUNTS = ("opportunity_received", "opportunity_accepted", "valid_followup_count", "showing_count", "deal_count", "deal_gtv", "effective_work_flag")
RATES = {"acceptance_rate": ("opportunity_accepted", "opportunity_received"),
         "followup_rate": ("valid_followup_count", "opportunity_accepted"),
         "showing_rate": ("showing_count", "valid_followup_count"),
         "closing_rate": ("deal_count", "showing_count")}


def load_policy() -> dict:
    """Read versioned, explicitly simulated operating parameters."""
    path = Path(__file__).resolve().parents[3] / "config" / "super_agent_ops.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Return NULL on zero denominator and unavailable on missing inputs."""
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return None
    return float(numerator / denominator)


def top_completion(row: pd.Series | dict, policy: dict) -> tuple[float, str, bool]:
    """Compute the limiting AND path or best OR path from configured metrics."""
    parts = {name: float(row[name]) / threshold for name, threshold in policy["top"]["metrics"].items()}
    operator = policy["top"]["operator"].upper()
    if operator == "AND":
        gap = min(parts, key=parts.get)
        return parts[gap], gap, all(value >= 1 for value in parts.values())
    if operator == "OR":
        gap = max(parts, key=parts.get)
        return parts[gap], gap, any(value >= 1 for value in parts.values())
    raise ValueError("top.operator must be AND or OR")


def aggregate_period(facts: pd.DataFrame, end: date, days: int, agent_ids: pd.Index) -> pd.DataFrame:
    """Sum atomic daily facts before deriving any conversion rate."""
    selected = facts.loc[(facts["date"] <= end) & (facts["date"] > end - timedelta(days=days))]
    totals = selected.groupby("agent_id", sort=False)[list(COUNTS)].sum(min_count=1).reindex(agent_ids)
    for rate, (num, den) in RATES.items():
        totals[rate] = totals[num].div(totals[den].where(totals[den].ne(0)))
    return totals


def _peer_percentile(frame: pd.DataFrame, field: str, policy: dict) -> pd.Series:
    """Rank within exact peers, then adjacent city stages, same stage or global."""
    min_size = policy["peer"]["min_sample_size"]
    exact = frame.groupby(["city", "candidate_stage"])[field]
    exact_size = exact.transform("count")
    exact_rank = exact.rank(pct=True)
    same = frame.groupby("candidate_stage")[field]
    same_size = same.transform("count")
    same_rank = same.rank(pct=True)
    global_rank = frame[field].rank(pct=True)
    result = exact_rank.where(exact_size >= min_size, same_rank.where(same_size >= min_size, global_rank))
    order = ("无效/沉默", "活跃", "准头部", "新晋头部")
    for (city, stage), group in frame.loc[exact_size < min_size].groupby(["city", "candidate_stage"]):
        at = order.index(stage)
        neighbors = order[max(0, at - 1): min(len(order), at + 2)]
        pool = frame.loc[(frame["city"] == city) & frame["candidate_stage"].isin(neighbors), field].dropna().sort_values().to_numpy()
        if len(pool) >= min_size:
            result.loc[group.index] = group[field].map(lambda value: float((pool <= value).sum() / len(pool)) if pd.notna(value) else float("nan"))
    return result


def _peer_scope(frame: pd.DataFrame, policy: dict) -> tuple[pd.Series, pd.Series]:
    """Report the actual fallback population size and scope for each row."""
    min_size = policy["peer"]["min_sample_size"]
    exact = frame.groupby(["city", "candidate_stage"])["agent_id"].transform("size")
    same = frame.groupby("candidate_stage")["agent_id"].transform("size")
    scope = pd.Series("全局可比较人群", index=frame.index)
    size = pd.Series(len(frame), index=frame.index)
    scope.loc[same >= min_size] = "全城市×同成长阶段"
    size.loc[same >= min_size] = same.loc[same >= min_size]
    order = ("无效/沉默", "活跃", "准头部", "新晋头部")
    for (city, stage), group in frame.loc[exact < min_size].groupby(["city", "candidate_stage"]):
        at = order.index(stage)
        neighbors = order[max(0, at - 1): min(len(order), at + 2)]
        count = int(((frame["city"] == city) & frame["candidate_stage"].isin(neighbors)).sum())
        if count >= min_size:
            scope.loc[group.index] = "同城市×相邻成长阶段"
            size.loc[group.index] = count
    scope.loc[exact >= min_size] = "同城市×同生命周期候选阶段"
    size.loc[exact >= min_size] = exact.loc[exact >= min_size]
    return scope, size


def snapshot_metrics(master: pd.DataFrame, facts: pd.DataFrame, end: date, policy: dict) -> pd.DataFrame:
    """Build one weekly candidate snapshot with peer-based potential and confidence."""
    ids = pd.Index(master["agent_id"], name="agent_id")
    current = aggregate_period(facts, end, policy["windows"]["current_days"], ids)
    previous = aggregate_period(facts, end - timedelta(days=policy["windows"]["current_days"]), policy["windows"]["current_days"], ids)
    closing = aggregate_period(facts, end, policy["windows"]["closing_days"], ids)
    trend = policy["windows"]["trend_days"]
    recent = aggregate_period(facts, end, trend, ids)
    earlier = aggregate_period(facts, end - timedelta(days=trend), trend, ids)
    frame = master.set_index("agent_id").join(current).reset_index()
    completion = frame.apply(lambda row: top_completion(row, policy), axis=1)
    frame["top_progress"] = completion.map(lambda x: x[0])
    frame["top_gap_dimension"] = completion.map(lambda x: x[1])
    frame["top_met"] = completion.map(lambda x: x[2])
    active = ((frame["effective_work_flag"] >= policy["active"]["min_effective_days"])
              & (frame["opportunity_received"] >= policy["active"]["min_opportunities"]))
    frame["candidate_stage"] = "活跃"
    frame.loc[~active, "candidate_stage"] = "无效/沉默"
    frame.loc[frame["top_progress"] >= policy["lifecycle"]["near_top_progress"], "candidate_stage"] = "准头部"
    frame.loc[frame["top_met"], "candidate_stage"] = "新晋头部"
    scope, size = _peer_scope(frame, policy)
    frame["peer_scope"], frame["peer_sample_size"] = scope, size
    growth_parts = []
    for field, weight in policy["potential"]["growth_weights"].items():
        values = pd.Series((recent[field].map(math.log1p) - earlier[field].map(math.log1p)).to_numpy(), index=frame.index)
        key = f"growth_{field}_pct"
        frame[key] = _peer_percentile(frame.assign(**{key: values}), key, policy)
        growth_parts.append(frame[key] * weight)
    frame["growth_score"] = sum(growth_parts) * 100
    conv_sum = pd.Series(0.0, index=frame.index)
    conv_weight = pd.Series(0.0, index=frame.index)
    for rate, weight in policy["potential"]["conversion_weights"].items():
        num, den = RATES[rate]
        source = closing if rate == "closing_rate" else current
        values = pd.Series(source[rate].to_numpy(), index=frame.index)
        key = f"{rate}_pct"
        frame[key] = _peer_percentile(frame.assign(**{key: values}), key, policy)
        valid = pd.Series((source[den] >= policy["potential"]["min_denominators"][rate]).to_numpy(), index=frame.index)
        conv_sum += frame[key].fillna(0) * weight * valid
        conv_weight += weight * valid
    frame["conversion_score"] = 100 * conv_sum.div(conv_weight.where(conv_weight.ne(0)))
    frame["computable_funnel_ratio"] = conv_weight / sum(policy["potential"]["conversion_weights"].values())
    work_pct = _peer_percentile(frame, "effective_work_flag", policy)
    current_days = policy["windows"]["current_days"]
    frequency = policy["snapshot"]["frequency_days"]
    weekly = facts.loc[(facts["date"] <= end) & (facts["date"] > end - timedelta(days=current_days))].copy()
    weekly["week"] = (pd.to_datetime(weekly["date"]) - pd.Timestamp(end - timedelta(days=current_days - 1))).dt.days // frequency
    week_columns = list(range((current_days + frequency - 1) // frequency))
    weeks = weekly.groupby(["agent_id", "week"])["deal_count"].sum(min_count=1).unstack().reindex(index=ids, columns=week_columns)
    work_weeks = weekly.groupby(["agent_id", "week"])["effective_work_flag"].sum(min_count=1).unstack().reindex(index=ids, columns=week_columns)
    observed_weeks = weeks.notna().sum(axis=1)
    concentration = weeks.max(axis=1).div(weeks.sum(axis=1).where(weeks.sum(axis=1).ne(0)))
    concentration = concentration.where(weeks.sum(axis=1).ne(0), 1).where(observed_weeks.ne(0))
    volatility = weeks.std(axis=1).div(weeks.mean(axis=1).where(weeks.mean(axis=1).ne(0)))
    volatility = volatility.fillna(2).where(observed_weeks.ne(0))
    trailing_active = work_weeks.gt(0).iloc[:, ::-1].cumprod(axis=1).sum(axis=1)
    consecutive = trailing_active.div(len(week_columns)).where(work_weeks.notna().any(axis=1)).to_numpy()
    frame["stability_score"] = (35 * work_pct + 25 * consecutive + 20 * (1 - concentration.to_numpy()) + 20 * (1 - volatility.clip(upper=2).to_numpy() / 2)).clip(0, 100)
    near_gate = policy["lifecycle"]["near_top_progress"]
    frame["headroom_score"] = (100 * frame["top_progress"].clip(0, near_gate) / near_gate).clip(0, 100)
    weights = policy["potential"]["weights"]
    available_weight = sum(frame[f"{name}_score"].notna() * weight for name, weight in weights.items())
    weighted_score = sum(frame[f"{name}_score"].fillna(0) * weight for name, weight in weights.items())
    frame["potential_score"] = weighted_score.div(available_weight.where(available_weight.ne(0)))
    frame.loc[frame["top_met"], "potential_score"] = float("nan")
    frame["potential_percentile"] = _peer_percentile(frame, "potential_score", policy)
    observed_facts = facts.loc[(facts["date"] <= end) & (facts["date"] > end - timedelta(days=policy["windows"]["closing_days"]))]
    observed_rows = observed_facts.groupby("agent_id").size().reindex(ids, fill_value=0)
    frame["observed_days_56d"] = observed_rows.to_numpy()
    completeness = pd.Series((observed_rows / policy["windows"]["closing_days"]).clip(0, 1).to_numpy(), index=frame.index)
    value_completeness = observed_facts.assign(completeness=observed_facts[list(COUNTS)].notna().mean(axis=1)).groupby("agent_id")["completeness"].mean().reindex(ids, fill_value=0)
    frame["confidence"] = (0.35 * completeness + 0.05 * value_completeness.to_numpy()
                           + 0.05 * (frame["opportunity_received"] / policy["confidence"]["opportunity_target"]).fillna(0).clip(0, 1)
                           + 0.10 * (closing["showing_count"].to_numpy() / policy["confidence"]["showing_target"]).clip(0, 1)
                           + 0.20 * frame["computable_funnel_ratio"]
                           + 0.15 * (frame["peer_sample_size"] / policy["peer"]["min_sample_size"]).clip(0, 1)).clip(0, 1)
    frame["high_potential_candidate"] = (active & ~frame["top_met"]
        & (frame["top_progress"] < policy["lifecycle"]["near_top_progress"])
        & (frame["potential_score"] >= policy["potential"]["quality_gate"])
        & (frame["potential_percentile"] >= policy["potential"]["percentile_gate"])
        & (frame["confidence"] >= policy["potential"]["confidence_gate"]))
    frame["closing_56d"] = closing["closing_rate"].to_numpy()
    frame["showings_56d"] = closing["showing_count"].to_numpy()
    for field in ("opportunity_received", "deal_count", *RATES):
        frame[f"previous_{field}"] = previous[field].to_numpy()
    frame["previous_showings_28d"] = previous["showing_count"].to_numpy()
    return frame


def transition_stage(previous: str, row: pd.Series | dict, streaks: dict, policy: dict) -> tuple[str, bool]:
    """Apply confirmation, top grace and immediate top entry to one agent."""
    cfg = policy["lifecycle"]
    met = bool(row["top_met"])
    streaks["top"] = streaks.get("top", 0) + 1 if met else 0
    streaks["miss"] = 0 if met else streaks.get("miss", 0) + 1
    if met:
        stage = "稳定头部" if streaks["top"] >= cfg["stable_top_confirm_periods"] else "新晋头部"
        return stage, False
    if previous in HEAD and streaks["miss"] <= cfg["top_grace_periods"]:
        return previous, True
    if previous in HEAD and streaks["miss"] < cfg["downgrade_confirm_periods"]:
        return previous, True
    if row["effective_work_flag"] <= policy["active"]["extreme_silent_days"]:
        return "无效/沉默", False
    near = row["candidate_stage"] == "准头部"
    high = bool(row["high_potential_candidate"])
    streaks["near"] = streaks.get("near", 0) + 1 if near else 0
    streaks["high"] = streaks.get("high", 0) + 1 if high else 0
    supported = near if previous == "准头部" else high if previous == "高潜" else True
    streaks["ordinary_miss"] = 0 if supported else streaks.get("ordinary_miss", 0) + 1
    if near and (streaks["near"] >= cfg["near_top_confirm_periods"] or row["top_progress"] >= cfg["near_top_fast_track"]):
        return "准头部", False
    if high and (streaks["high"] >= cfg["high_potential_confirm_periods"] or
                 (row["potential_percentile"] >= policy["potential"]["fast_percentile_gate"] and row["confidence"] >= policy["potential"]["fast_confidence_gate"])):
        return "高潜", False
    if previous in {"准头部", "高潜"} and streaks["ordinary_miss"] < cfg["downgrade_confirm_periods"]:
        return previous, False
    return "活跃" if row["candidate_stage"] != "无效/沉默" else "无效/沉默", False


def build_snapshots(master: pd.DataFrame, facts: pd.DataFrame, policy: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return latest decision metrics and mutually exclusive weekly lifecycle history."""
    end = facts["date"].max()
    frequency = policy["snapshot"]["frequency_days"]
    dates = [end - timedelta(days=frequency * n) for n in range(policy["snapshot"]["history_periods"] - 1, -1, -1)]
    states: dict[str, tuple[str, dict]] = {}
    history = []
    latest = pd.DataFrame()
    for day in dates:
        latest = snapshot_metrics(master, facts, day, policy)
        stage_rows = []
        for row in latest.to_dict("records"):
            previous, streaks = states.get(row["agent_id"], ("活跃", {}))
            stage, risk = transition_stage(previous, row, streaks, policy)
            states[row["agent_id"]] = (stage, streaks)
            stage_rows.append((stage, risk))
            history.append({"snapshot_date": day, "agent_id": row["agent_id"], "stage": stage, "top_at_risk": risk})
        latest["stage"] = [x[0] for x in stage_rows]
        latest["top_at_risk"] = [x[1] for x in stage_rows]
        latest.loc[latest["stage"].isin(HEAD), ["potential_score", "potential_percentile"]] = float("nan")
    return latest, pd.DataFrame(history)


def transition_kpis(history: pd.DataFrame) -> dict[str, float | int | None]:
    """Calculate current head counts and prior-snapshot cohort transitions."""
    dates = sorted(history["snapshot_date"].unique())
    now = history.loc[history["snapshot_date"] == dates[-1]].set_index("agent_id")
    prior = history.loc[history["snapshot_date"] == dates[-2]].set_index("agent_id")
    was_head, is_head = prior["stage"].isin(HEAD), now["stage"].isin(HEAD)
    entered = int((~was_head & is_head).sum())
    exited = int((was_head & ~is_head).sum())
    near = prior["stage"].eq("准头部")
    return {"head_count": int(is_head.sum()), "new_head_count": int(now["stage"].eq("新晋头部").sum()),
            "stable_head_count": int(now["stage"].eq("稳定头部").sum()), "net_new_head": entered - exited,
            "entered_head_count": entered, "exited_head_count": exited,
            "near_top_to_head_upgrade_rate": safe_ratio(int((near & is_head).sum()), int(near.sum())),
            "head_retention_rate": safe_ratio(int((was_head & is_head).sum()), int(was_head.sum())),
            "high_potential_count": int(now["stage"].eq("高潜").sum())}
