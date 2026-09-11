# YSB staging metric validation V1

| metric | source | calculation | NULL meaning | zero meaning | usable period | coverage | validation_status |
|---|---|---|---|---|---|---|---|
| cash_sales_amount | 销售额统计（按月）/现金额 | direct source value | source absent or merchant-month not present | source explicitly zero | 2026-03..2026-06 | 91 merchants in canonical recent source | VERIFIED |
| gmv | 商业每月GMV/aYYYYMM | unpivot monthly column | source cell absent | source explicitly zero | 2023-01..2026-05 | 112 IDs; non-null coverage varies by month | VERIFIED |
| order_count | 销售额统计（按月）/订单数 | direct source value | source absent | source explicitly zero | 2026-03..2026-06 | 91 merchants | VERIFIED |
| aftersales_order_count | 商业售后情况/当月售后订单数 | direct source value | source absent | source explicitly zero | 2024-12..2026-05 | about 107 IDs in source snapshot | VERIFIED |
| aftersales_rate | 商业售后情况/当月商家原因售后率 | direct source ratio | source absent or not defined | source explicitly zero | 2024-12..2026-05 | about 107 IDs in source snapshot | LIKELY |
