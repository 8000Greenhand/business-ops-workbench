# 药师帮 V1 数据模型草案：Dashboard A / Dashboard B 分离

本文件只定义候选边界，不修改正式 schema，不创建数据库表。

## Dashboard A：区域商家经营 / KPI

### staging 事实：stg_merchant_monthly_performance

建议粒度优先为：

`period × merchant_natural_key`

已生成本地 CSV staging：`data/staging/ysb/stg_merchant_monthly_performance.csv`。

字段：

- period
- merchant_natural_key
- merchant_id（未来可选）
- merchant_name_raw
- supplier_id_raw
- region_raw
- owner_raw
- sales_amount_candidate
- gmv_candidate
- order_count
- after_sales_order_count
- merchant_reason_after_sales_rate
- active_sku / active_store_count
- source_file
- source_sheet
- snapshot_version
- mapping_status
- coverage_status
- mom_cash_sales
- mom_gmv
- merchant_rank_cash_sales
- merchant_rank_gmv

V1 允许使用 `merchant_natural_key`：优先供应商 ID，其次标准化供应商名称；必须保留原始字段和未确认标记，不做静默 fuzzy merge。

### dim_region_or_owner_staging

保留供应商省份/城市、运营名称、商务对接人、对应人等原始归属字段。行政区和内部区域不直接合并，直到业务确认。

### fact_kpi_performance_staging

候选粒度：

`period × owner_or_region × metric`

字段：period、owner_or_region、metric、target、actual、source_file、definition_status。当前 target 与 merchant actual 尚未证明可同粒度关联。

## Dashboard B：单商家日报诊断

Dashboard B 按需上传某一家商家的日报，保持独立：

- fact_order_line_candidate
- fact_daily_business_candidate
- activity/product/customer 候选维度

不把日报订单明细扩展成覆盖全区域的 `fact_order_line`，也不要求它与 Dashboard A 自动关联。

## 当前可进入 V1 staging 的指标

Dashboard A：月现金额/销售额候选、月 GMV 候选、订单数、售后订单数/率、运营/商务归属、覆盖月数。

Dashboard B：沿用已有日报订单、客户、商品、活动、流量审计结果。

## 暂不进入正式 schema

- 统一 `merchant_id`
- 商家级 KPI target/achievement
- 区域订单事实仓库
- `fact_merchant_daily` 的正式版本；当前先使用 `month × merchant_natural_key` staging
- 全区域订单、Customer、Product、Activity 统一事实表
