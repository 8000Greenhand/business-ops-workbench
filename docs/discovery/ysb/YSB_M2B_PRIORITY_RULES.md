# YSB M2B priority rules

## Pools

- `WATCHLIST`: one independent diagnostic dimension is active.
- `ATTENTION`: at least two independent dimensions are active, but P1 conditions are not met.
- `PRIORITY`: severe Trend plus at least one Scale / Impact or Service condition, or severe Trend with three or more consecutive valid monthly declines.
- `DATA_QUALITY_ALERT`: unresolved merchant or missing current GMV; never ranked by GMV loss.

## Independent dimensions

Trend combines GMV decline and consecutive decline. Scale / Impact combines GMV loss and previous-month regional share. Relative Position combines rank deterioration and low same-month percentile. Order combines order decline and GMV/order divergence. Service combines high aftersales and aftersales worsening. Rules within one dimension are explanatory evidence, not independent priority points.

## Empirical thresholds

- severe GMV MoM: `-0.5494`
- severe order MoM: `-0.5964`
- high GMV loss: `53345.74`
- important previous GMV share: `0.0193`
- rank deterioration: `8.00` places
- high aftersales: `0.0543`
- aftersales worsening: `1.6097`
- low GMV percentile: `0.20`

Thresholds are derived from valid historical staging distributions, not formal company KPI targets.

## Scale

For each month, valid previous GMV is split by empirical quartiles: top quartile `KEY`, middle 50% `MID`, bottom quartile `LONG_TAIL`. Missing/unresolved rows are `UNAVAILABLE`.
