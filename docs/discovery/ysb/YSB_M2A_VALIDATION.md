# YSB M2A validation

Mart: `C:\Users\NPC-003\Documents\ChatGPT\Business Ops Workbench\business-ops-workbench\data\marts\ysb\mart_merchant_monthly_health.csv`
Grain duplicate count: 0
Rows=4956, merchants=118, months=42 (2023-01..2026-06).

## Thresholds derived from valid history

```json
{
  "gmv_decline": -0.5493570518529791,
  "cash_decline": -0.6375096003377129,
  "order_decline": -0.5964104553239495,
  "rank_drop": 8.0,
  "aftersales_high": 0.05425803457477658,
  "aftersales_worsening": 1.6096983795925097,
  "low_gmv_percentile": 0.2,
  "order_rise_for_divergence": 0.8246005639097744
}
```

## Alert counts by month

| month | business_alert | data_quality_alert | total_attention_rows |
|---|---:|---:|---:|
| 2023-01 | 0 | 6 | 6 |
| 2023-02 | 8 | 6 | 14 |
| 2023-03 | 1 | 6 | 7 |
| 2023-04 | 10 | 6 | 16 |
| 2023-05 | 12 | 6 | 18 |
| 2023-06 | 15 | 6 | 21 |
| 2023-07 | 9 | 6 | 15 |
| 2023-08 | 9 | 6 | 15 |
| 2023-09 | 7 | 6 | 13 |
| 2023-10 | 45 | 6 | 51 |
| 2023-11 | 46 | 6 | 52 |
| 2023-12 | 45 | 6 | 51 |
| 2024-01 | 47 | 6 | 53 |
| 2024-02 | 52 | 6 | 58 |
| 2024-03 | 37 | 6 | 43 |
| 2024-04 | 41 | 6 | 47 |
| 2024-05 | 38 | 6 | 44 |
| 2024-06 | 42 | 6 | 48 |
| 2024-07 | 32 | 6 | 38 |
| 2024-08 | 32 | 6 | 38 |
| 2024-09 | 31 | 6 | 37 |
| 2024-10 | 33 | 6 | 39 |
| 2024-11 | 31 | 6 | 37 |
| 2024-12 | 39 | 6 | 45 |
| 2025-01 | 44 | 6 | 50 |
| 2025-02 | 46 | 6 | 52 |
| 2025-03 | 42 | 6 | 48 |
| 2025-04 | 47 | 6 | 53 |
| 2025-05 | 51 | 6 | 57 |
| 2025-06 | 48 | 6 | 54 |
| 2025-07 | 38 | 6 | 44 |
| 2025-08 | 42 | 6 | 48 |
| 2025-09 | 38 | 6 | 44 |
| 2025-10 | 42 | 6 | 48 |
| 2025-11 | 34 | 6 | 40 |
| 2025-12 | 42 | 6 | 48 |
| 2026-01 | 44 | 6 | 50 |
| 2026-02 | 36 | 6 | 42 |
| 2026-03 | 31 | 6 | 37 |
| 2026-04 | 38 | 6 | 44 |
| 2026-05 | 38 | 6 | 44 |
| 2026-06 | 13 | 105 | 118 |

## Quality vocabulary

VALID, MISSING, INSUFFICIENT_HISTORY, UNRESOLVED_MERCHANT, UNAVAILABLE_FOR_PERIOD are preserved as distinct states. Missing data and insufficient history never generate a business rule by themselves. Rows that contain both a valid business signal and a data gap expose both `business_attention_status` and `data_quality_status`.

Observed alerts: 1727 rows; business alerts=1376, data quality alerts=364.

Recent relatively complete month for manual review: 2026-05; business alerts=38, data-quality alerts=6. See `data/marts/ysb/YSB_MERCHANT_ATTENTION_SAMPLE.csv` for up to 15 attention rows per month.
