# YSB M2A anomaly rules

Thresholds are empirical and recomputed from valid historical staging observations, not hard-coded business targets:

- GMV decline: GMV MoM at or below the historical negative-tail threshold `-0.5494`.
- Cash decline: cash-sales MoM at or below `-0.6375`.
- Order decline: order-count MoM at or below `-0.5964`.
- Rank deterioration: rank change at or above the positive-tail threshold `8.00`; positive means a worse rank.
- Low GMV: same-month GMV percentile at or below `0.20`.
- High aftersales: same-month aftersales rate at or above `0.0543`.
- Aftersales worsening: MoM aftersales-rate change at or above `1.6097`.
- Direction divergence: GMV in the decline tail while order count rises above `0.8246`.
- Consecutive decline: three or more consecutive valid monthly GMV decreases.
- Recent missing: latest month lacks GMV or cash amount; this is `DATA_QUALITY_ALERT`.

Each alert stores rule text in `attention_reasons`, plus `severity` and an additive `priority_score` equal to the number of business signals. The score is only a sorting aid, not a black-box health score.
