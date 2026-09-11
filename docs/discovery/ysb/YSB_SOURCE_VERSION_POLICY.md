# YSB source version policy for Dashboard A

## Canonical selection

1. Select one source per metric family and grain.
2. Prefer the version with the latest covered period, then the largest complete row/column structure, then the latest trustworthy export time.
3. Do not select by filename sort order or `(1)/(2)` suffix.
4. A source snapshot enters staging only once; superseded versions remain inventory evidence.
5. Reconcile every selected source to staging totals before release.

## Current policy

- `cash_sales_amount`, `order_count`: `销售额统计 (5).xlsx / 销售额统计（按月）`, the 91-merchant, 4-month long table.
- `gmv`: the 2026-05-25 full `商业每月GMV` wide table, because it has the broadest historical complete structure; later files are subsets and are not mixed in.
- `aftersales_*`: the 2026-05-25 `商业售后情况` table.
- Later versions are reserved for a future replacement only after coverage and reconciliation checks.
