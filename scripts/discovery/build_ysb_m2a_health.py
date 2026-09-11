from __future__ import annotations

import json
from pathlib import Path

from ops_workbench.diagnostics.ysb_health import BUSINESS_ALERT, DATA_QUALITY_ALERT, build_ysb_health


ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "data" / "staging" / "ysb" / "stg_merchant_monthly_performance.csv"
OUT = ROOT / "data" / "marts" / "ysb"
DOC = ROOT / "docs" / "discovery" / "ysb"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    frame, thresholds = build_ysb_health(STAGING)
    mart = OUT / "mart_merchant_monthly_health.csv"
    frame.to_csv(mart, index=False, encoding="utf-8-sig")
    sample_columns = ["month", "merchant_key", "merchant_name", "owner", "gmv", "gmv_mom", "gmv_rank", "gmv_percentile", "cash_sales_amount", "cash_sales_mom", "order_count", "aftersales_order_count", "aftersales_rate", "metric_quality_status", "merchant_mapping_status", "business_attention_status", "data_quality_status", "data_quality_reasons", "severity", "priority_score", "attention_reasons"]
    sample = frame[frame["business_attention_status"] != "NO_ALERT"].sort_values(["month", "priority_score", "gmv_mom"], ascending=[True, False, True]).groupby("month", observed=True).head(15)
    sample[sample_columns].to_csv(OUT / "YSB_MERCHANT_ATTENTION_SAMPLE.csv", index=False, encoding="utf-8-sig")
    (OUT / "ysb_m2a_thresholds.json").write_text(json.dumps(thresholds, ensure_ascii=False, indent=2), encoding="utf-8")
    (DOC / "YSB_M2A_VALIDATION.md").write_text(_validation(frame, thresholds, mart), encoding="utf-8")
    (DOC / "YSB_M2A_METRIC_DEFINITIONS.md").write_text(_metric_definitions(frame), encoding="utf-8")
    (DOC / "YSB_M2A_DATA_QUALITY_RULES.md").write_text(_quality_rules(frame), encoding="utf-8")
    (DOC / "YSB_M2A_ANOMALY_RULES.md").write_text(_anomaly_rules(frame, thresholds), encoding="utf-8")
    print(f"mart={mart} rows={len(frame)} attention_rows={len(sample)}")
    return 0


def _validation(frame, thresholds, mart) -> str:
    months = sorted(str(x) for x in frame["month"].drop_duplicates())
    alerts = frame[frame["business_attention_status"] != "NO_ALERT"]
    lines = ["# YSB M2A validation", "", f"Mart: `{mart}`", f"Grain duplicate count: {frame.duplicated(['month','merchant_key']).sum()}", f"Rows={len(frame)}, merchants={frame['merchant_key'].nunique()}, months={len(months)} ({months[0]}..{months[-1]}).", "", "## Thresholds derived from valid history", "", "```json", json.dumps(thresholds, ensure_ascii=False, indent=2), "```", "", "## Alert counts by month", "", "| month | business_alert | data_quality_alert | total_attention_rows |", "|---|---:|---:|---:|"]
    for m in months:
        part = frame[frame["month"] == m]
        lines.append(f"| {m} | {(part['business_attention_status'] == 'BUSINESS_ALERT').sum()} | {(part['business_attention_status'] == 'DATA_QUALITY_ALERT').sum()} | {(part['business_attention_status'] != 'NO_ALERT').sum()} |")
    complete_month = "2026-05"
    complete_part = frame[frame["month"] == complete_month]
    lines += ["", "## Quality vocabulary", "", "VALID, MISSING, INSUFFICIENT_HISTORY, UNRESOLVED_MERCHANT, UNAVAILABLE_FOR_PERIOD are preserved as distinct states. Missing data and insufficient history never generate a business rule by themselves. Rows that contain both a valid business signal and a data gap expose both `business_attention_status` and `data_quality_status`.", "", f"Observed alerts: {len(alerts)} rows; business alerts={(alerts['business_attention_status'] == BUSINESS_ALERT).sum()}, data quality alerts={(alerts['data_quality_status'] == DATA_QUALITY_ALERT).sum()}.", "", f"Recent relatively complete month for manual review: {complete_month}; business alerts={(complete_part['business_attention_status'] == BUSINESS_ALERT).sum()}, data-quality alerts={(complete_part['data_quality_status'] == DATA_QUALITY_ALERT).sum()}. See `data/marts/ysb/YSB_MERCHANT_ATTENTION_SAMPLE.csv` for up to 15 attention rows per month."]
    return "\n".join(lines) + "\n"


def _metric_definitions(frame) -> str:
    return """# YSB M2A metric definitions

| metric | definition | quality gate |
|---|---|---|
| gmv | source GMV value by month and merchant key | source value present and merchant not unresolved |
| gmv_mom | current GMV / prior-month GMV - 1 | both periods valid and prior value non-zero |
| gmv_rank | descending rank within month among valid GMV values | same-month valid GMV population |
| gmv_percentile | ascending percentile within month among valid GMV values | same-month valid GMV population |
| cash_sales_amount | source cash amount, independent from GMV | source value present |
| cash_sales_mom | current cash amount / prior month - 1 | both periods valid and prior non-zero |
| order_count | source monthly order count | source value present |
| aftersales_order_count | source monthly aftersales order count | source value present |
| aftersales_rate | source monthly merchant-reason aftersales rate | source value present; denominator semantics not redefined |
| coverage_status | source coverage state from staging | data-quality context, not a business signal |

GMV and cash sales remain separate metrics. No formal KPI target achievement is included.
"""


def _quality_rules(frame) -> str:
    return """# YSB M2A data quality rules

- `VALID`: current metric value exists and the merchant mapping is resolved.
- `MISSING`: current metric is NULL for the merchant-month.
- `INSUFFICIENT_HISTORY`: current value exists but the prior period required for a change is absent or invalid.
- `UNRESOLVED_MERCHANT`: staging merchant key is a name fallback without a verified ID mapping; cross-period changes are not calculated.
- `UNAVAILABLE_FOR_PERIOD`: reserved for a metric that is not supplied for the selected source period; it is not treated as zero.

Rules:

1. `month + merchant_key` must be unique.
2. NULL remains NULL; only explicit source zero remains 0.
3. MoM requires valid current and prior values; first observed month has no synthetic MoM.
4. Unresolved merchants remain in the mart but do not generate trend signals.
5. Coverage gaps are `DATA_QUALITY_ALERT`, never `BUSINESS_ALERT` by themselves.
6. Quality states must be visible beside every metric used for diagnosis.
"""


def _anomaly_rules(frame, thresholds) -> str:
    return f"""# YSB M2A anomaly rules

Thresholds are empirical and recomputed from valid historical staging observations, not hard-coded business targets:

- GMV decline: GMV MoM at or below the historical negative-tail threshold `{thresholds['gmv_decline']:.4f}`.
- Cash decline: cash-sales MoM at or below `{thresholds['cash_decline']:.4f}`.
- Order decline: order-count MoM at or below `{thresholds['order_decline']:.4f}`.
- Rank deterioration: rank change at or above the positive-tail threshold `{thresholds['rank_drop']:.2f}`; positive means a worse rank.
- Low GMV: same-month GMV percentile at or below `{thresholds['low_gmv_percentile']:.2f}`.
- High aftersales: same-month aftersales rate at or above `{thresholds['aftersales_high']:.4f}`.
- Aftersales worsening: MoM aftersales-rate change at or above `{thresholds['aftersales_worsening']:.4f}`.
- Direction divergence: GMV in the decline tail while order count rises above `{thresholds['order_rise_for_divergence']:.4f}`.
- Consecutive decline: three or more consecutive valid monthly GMV decreases.
- Recent missing: latest month lacks GMV or cash amount; this is `DATA_QUALITY_ALERT`.

Each alert stores rule text in `attention_reasons`, plus `severity` and an additive `priority_score` equal to the number of business signals. The score is only a sorting aid, not a black-box health score.
"""


if __name__ == "__main__":
    raise SystemExit(main())
