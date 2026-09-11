# YSB M2A metric definitions

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
