"""Deterministic, entirely fictional agent operating facts."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd


CITIES = ("成都", "重庆", "武汉", "西安")
PROFILES = ("正常稳定", "快速成长", "商机不足但高转化", "承接偏弱", "跟进偏弱", "带看偏弱", "成交转化偏弱", "稳定头部", "头部下滑", "沉默", "低样本高转化", "准头部")
CASE_PROFILES = {"A": "快速成长", "B": "准头部", "C": "商机不足但高转化", "D": "成交转化偏弱", "E": "低样本高转化", "F": "头部下滑", "G": "快速成长", "H": "准头部"}


def simulate_agents(config: dict, *, seed: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return fictional master and daily facts; identical seed yields identical rows."""
    rng = random.Random(config["seed"] if seed is None else seed)
    count = config["simulation"]["agents"]
    days = config["simulation"]["days"]
    start = date(2026, 6, 1)
    master: list[dict] = []
    facts: list[dict] = []
    city_factor = {"成都": 1.10, "重庆": 0.90, "武汉": 1.0, "西安": 0.82}
    for i in range(count):
        city = CITIES[i % 4]
        local = i // 4
        case = "ABCDEFGH"[local] if local < 8 and city == "成都" else ""
        profile = CASE_PROFILES[case] if case else PROFILES[(local + i % 4) % len(PROFILES)]
        manager_no = local % 3 + 1
        agent_id = f"DEMO-{i+1:04d}"
        base = {"正常稳定": 2.2, "快速成长": 2.0, "商机不足但高转化": 0.85,
                "承接偏弱": 3.1, "跟进偏弱": 2.8, "带看偏弱": 2.7,
                "成交转化偏弱": 3.8, "稳定头部": 4.2, "头部下滑": 4.2,
                "沉默": 0.15, "低样本高转化": 0.16, "准头部": 3.2}[profile]
        if case == "A":
            base = 0.85
        elif case == "B":
            base = 1.75
        elif case == "C":
            base = 0.72
        elif case == "E":
            base = 2.8
        elif case == "F":
            base = 2.55
        elif case == "H":
            base = 1.75
        master_row = {"agent_id": agent_id, "agent_name": f"演示经纪人{i+1:04d}", "city": city,
                      "area": f"演示片区{local % 5 + 1}", "manager_id": f"{i % 4 + 1}-{manager_no}",
                      "manager_name": f"{city}演示经理{manager_no}", "profile": profile, "case": case}
        if case == "F":
            master_row["manager_id"] = "1-4"
            master_row["manager_name"] = "成都演示经理4"
        master.append(master_row)
        for d in range(days):
            current = d >= days - 28
            growth = 2.5 if case == "A" and current else 1.85 if profile == "快速成长" and current else 1.0
            decline = 0.0 if case == "F" and d >= days - 7 else 0.12 if profile == "头部下滑" and d >= days - 14 else 1.0
            work = int(rng.random() < (0.06 if profile == "沉默" else 0.70 if profile == "低样本高转化" else 0.86))
            if case == "E" and d < days - 7 and d % 14 != 0:
                continue  # Sparse observed dates remain absent, never converted to zero.
            if case == "E":
                work = 1
            opportunities = max(0, round((base * city_factor[city] * growth * decline + rng.uniform(-1.3, 1.3)) * work))
            acceptance = 0.36 if profile == "承接偏弱" else 0.88 if profile in {"商机不足但高转化", "低样本高转化"} else 0.74
            accepted = sum(rng.random() < acceptance for _ in range(opportunities))
            follow_rate = 0.33 if profile == "跟进偏弱" else 0.94 if profile in {"商机不足但高转化", "低样本高转化"} else 0.77
            followups = sum(rng.random() < follow_rate for _ in range(accepted))
            showing_rate = 0.29 if profile == "带看偏弱" else 0.87 if profile in {"商机不足但高转化", "低样本高转化"} else 0.65
            showings = sum(rng.random() < showing_rate for _ in range(followups))
            closing_rate = (0.045 if profile == "成交转化偏弱" else 0.28 if case == "E" else 0.47 if profile in {"商机不足但高转化", "低样本高转化", "稳定头部", "头部下滑", "准头部"} else 0.28)
            deals = sum(rng.random() < closing_rate for _ in range(showings))
            facts.append({"date": start + timedelta(days=d), "agent_id": agent_id,
                          "opportunity_received": opportunities, "opportunity_accepted": accepted,
                          "valid_followup_count": followups, "showing_count": showings,
                          "deal_count": deals, "deal_gtv": deals * rng.choice((75000, 85000, 95000)),
                          "effective_work_flag": work})
    return pd.DataFrame(master), pd.DataFrame(facts).merge(pd.DataFrame(master).drop(columns=["profile", "case"]), on="agent_id", validate="many_to_one")


def simulated_action_log(master: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Return linked historical recommendation outcomes for fatigue and review."""
    return simulated_action_cohort(master, as_of)[1]


def simulated_action_cohort(master: pd.DataFrame, as_of: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create one traceable, fixed-seed historical recommendation/action cohort."""
    recommended: list[dict] = []
    events: list[dict] = []
    for i, agent in master.iterrows():
        ages = (2, 5, 10) if agent["case"] == "G" or (i % 29 == 0 and not agent["case"]) else (35,) if i % 4 == 0 else (22,) if i % 11 == 0 else ()
        for age in ages:
            code = "A01" if age in (2, 5, 10) else ("A07" if agent["profile"] == "准头部" else "A06" if agent["profile"] == "成交转化偏弱" else "A04" if i % 2 else "A05")
            recommended_at = as_of - timedelta(days=age + 2)
            recommendation_id = f"H-{recommended_at:%Y%m%d}-{agent['agent_id']}-{code}"
            status = ("过期" if i % 19 == 0 and age == 35 else
                      "跳过" if i % 13 == 0 and age == 35 else
                      "已推荐" if i % 7 == 0 and age == 35 else
                      "已接受" if i % 5 == 0 and age == 35 else "已执行")
            accepted_at = recommended_at + timedelta(days=1) if status in {"已接受", "已执行"} else None
            executed_at = recommended_at + timedelta(days=2) if status == "已执行" else None
            cost = (1000 if code == "A07" else 120 if code == "A06" else 80 if code in {"A04", "A05"} else 20) if executed_at else 0
            rec = {"recommendation_id": recommendation_id, "agent_id": agent["agent_id"], "action_code": code,
                   "recommended_at": recommended_at, "recommendation_rank": 1, "recommendation_score": float(60 + i % 30)}
            recommended.append(rec)
            events.append({**rec, "accepted_at": accepted_at, "executed_at": executed_at,
                           "action_at": executed_at, "status": status,
                           "skip_reason": "本周期暂不适用" if status == "跳过" else "", "cost": cost})
    return pd.DataFrame(recommended), pd.DataFrame(events)
