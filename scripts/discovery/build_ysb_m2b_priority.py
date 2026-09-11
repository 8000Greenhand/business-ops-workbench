from __future__ import annotations

import json
from pathlib import Path

from ops_workbench.diagnostics.ysb_priority import ATTENTION, BUSINESS_ALERT, DATA_QUALITY, PRIORITY, WATCHLIST, build_priority_mart
from ops_workbench.diagnostics.ysb_health import build_ysb_health


ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "data" / "staging" / "ysb" / "stg_merchant_monthly_performance.csv"
HEALTH = ROOT / "data" / "marts" / "ysb" / "mart_merchant_monthly_health.csv"
OUT = ROOT / "data" / "marts" / "ysb"
DOC = ROOT / "docs" / "discovery" / "ysb"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True); DOC.mkdir(parents=True, exist_ok=True)
    # Rebuild from persisted staging so the mart is reproducible without trusting a prior process.
    health, _ = build_ysb_health(STAGING)
    frame, thresholds = build_priority_mart(health)
    mart = OUT / "mart_merchant_monthly_priority.csv"
    frame.to_csv(mart, index=False, encoding="utf-8-sig")
    target = frame[frame["month"] == "2026-05"].copy()
    level_order = {PRIORITY: 1, ATTENTION: 2, WATCHLIST: 3}
    scale_order = {"KEY": 1, "MID": 2, "LONG_TAIL": 3, "UNAVAILABLE": 4}
    sample = target[target["priority_level"].isin([PRIORITY, ATTENTION, WATCHLIST])].assign(_level_order=lambda x: x["priority_level"].map(level_order), _scale_order=lambda x: x["merchant_scale"].map(scale_order)).sort_values(["_level_order", "_scale_order", "priority_sort_loss", "diagnostic_dimension_count", "priority_sort_share"], ascending=[True, True, False, False, False]).drop(columns=["_level_order", "_scale_order"]).head(15)
    sample_cols = ["merchant_name", "current_gmv", "previous_gmv", "gmv_mom", "gmv_loss", "previous_gmv_share", "gmv_rank_current", "rank_previous", "order_change", "aftersales_rate", "consecutive_gmv_decline", "merchant_scale", "priority_level", "attention_reasons", "metric_quality_status", "data_quality_status"]
    sample[sample_cols].to_csv(OUT / "YSB_MERCHANT_PRIORITY_SAMPLE.csv", index=False, encoding="utf-8-sig")
    (OUT / "ysb_m2b_thresholds.json").write_text(json.dumps(thresholds, ensure_ascii=False, indent=2), encoding="utf-8")
    (DOC / "YSB_M2B_PRIORITY_RULES.md").write_text(_rules(thresholds), encoding="utf-8")
    (DOC / "YSB_M2B_VALIDATION.md").write_text(_validation(frame, thresholds, mart, sample), encoding="utf-8")
    print(f"mart={mart} rows={len(frame)} target_sample={len(sample)}")
    return 0


def _rules(t: dict[str, float]) -> str:
    return f"""# YSB M2B priority rules

## Pools

- `WATCHLIST`: one independent diagnostic dimension is active.
- `ATTENTION`: at least two independent dimensions are active, but P1 conditions are not met.
- `PRIORITY`: severe Trend plus at least one Scale / Impact or Service condition, or severe Trend with three or more consecutive valid monthly declines.
- `DATA_QUALITY_ALERT`: unresolved merchant or missing current GMV; never ranked by GMV loss.

## Independent dimensions

Trend combines GMV decline and consecutive decline. Scale / Impact combines GMV loss and previous-month regional share. Relative Position combines rank deterioration and low same-month percentile. Order combines order decline and GMV/order divergence. Service combines high aftersales and aftersales worsening. Rules within one dimension are explanatory evidence, not independent priority points.

## Empirical thresholds

- severe GMV MoM: `{t['severe_gmv_mom']:.4f}`
- severe order MoM: `{t['severe_order_mom']:.4f}`
- high GMV loss: `{t['high_loss']:.2f}`
- important previous GMV share: `{t['important_share']:.4f}`
- rank deterioration: `{t['rank_drop']:.2f}` places
- high aftersales: `{t['high_aftersales']:.4f}`
- aftersales worsening: `{t['aftersales_worsening']:.4f}`
- low GMV percentile: `{t['low_percentile']:.2f}`

Thresholds are derived from valid historical staging distributions, not formal company KPI targets.

## Scale

For each month, valid previous GMV is split by empirical quartiles: top quartile `KEY`, middle 50% `MID`, bottom quartile `LONG_TAIL`. Missing/unresolved rows are `UNAVAILABLE`.
"""


def _validation(frame, t, mart, sample) -> str:
    target = frame[frame["month"] == "2026-05"]
    valid = target[target["current_gmv"].notna() & target["previous_gmv"].notna() & (target["mapping_status"] != "UNRESOLVED")]
    current = valid["current_gmv"].sum(); previous = valid["previous_gmv"].sum(); delta = current - previous
    lines = ["# YSB M2B validation", "", f"Mart: `{mart}`", f"Target month: 2026-05; valid shared GMV merchants={len(valid)}.", "", "## 2026-05 regional summary", "", f"- Regional GMV (shared valid population): {current:.2f}", f"- Previous-month GMV (shared valid population): {previous:.2f}", f"- Regional GMV MoM: {(delta / previous):.2%}" if previous else "- Regional GMV MoM: NULL", f"- GMV decline merchants: {(valid['gmv_change_abs'] < 0).sum()}", f"- GMV growth merchants: {(valid['gmv_change_abs'] > 0).sum()}", f"- Aftersales high/worsening merchants: {(target['diagnostic_dimensions'].str.contains('Service', na=False)).sum()}", f"- PRIORITY: {(target['priority_level'] == PRIORITY).sum()}", f"- ATTENTION: {(target['priority_level'] == ATTENTION).sum()}", f"- WATCHLIST: {(target['priority_level'] == WATCHLIST).sum()}", f"- DATA_QUALITY_ALERT: {(target['priority_level'] == DATA_QUALITY).sum()}", "", "## Top GMV loss merchants", "", "| merchant | current_gmv | previous_gmv | gmv_loss | loss_contribution | scale | priority |", "|---|---:|---:|---:|---:|---|---|"]
    for _, r in valid.sort_values("gmv_loss", ascending=False).head(10).iterrows(): lines.append(f"| {r['merchant_name']} | {r['current_gmv']:.2f} | {r['previous_gmv']:.2f} | {r['gmv_loss']:.2f} | {r['regional_gmv_loss_contribution']:.2%} | {r['merchant_scale']} | {r['priority_level']} |" if r['regional_gmv_loss_contribution'] == r['regional_gmv_loss_contribution'] else f"| {r['merchant_name']} | {r['current_gmv']:.2f} | {r['previous_gmv']:.2f} | {r['gmv_loss']:.2f} | NULL | {r['merchant_scale']} | {r['priority_level']} |")
    lines += ["", "## Acceptance checks", "", f"- Priority count is less than M2A business alert pool: {(target['priority_level'] == PRIORITY).sum()} < {(target['business_attention_status'] == BUSINESS_ALERT).sum()}.", f"- Missing/unresolved rows in GMV loss ranking: {len(target[(target['priority_level'] == DATA_QUALITY) & target['gmv_loss'].notna()])}.", f"- Sample rows written: {len(sample)}.", "- Priority reasons are dimension-level and explainable; no composite health score is used."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
