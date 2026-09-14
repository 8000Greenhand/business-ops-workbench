# Dashboard B B1 数据模型

## 目标与范围

B1 为单个问题商家的日报建立可重复生成、可配置、可审计的数据层。底层金额统一命名为 `purchase_amount`，仅在展示语境中标记为 `GMV candidate / 进货金额`。

本模型不包含 Dashboard B UI，不修改 Dashboard A，不分析活动、价格或流量，也不修改源 Excel。

## 数据流

```text
药师帮日报.xlsx / 订单原始数据
  -> stg_merchant_order_items
  -> mart_merchant_monthly_diagnosis
  -> mart_customer_monthly_contribution
  -> mart_product_monthly_contribution
  -> mart_merchant_data_quality
```

构建入口：

```powershell
.\.venv\Scripts\python.exe scripts\build_ysb_dashboard_b_b1.py
```

订单口径配置：`config/ysb_dashboard_b_order_metric_policy.yaml`。

## Staging

文件：`data/staging/ysb/stg_merchant_order_items.csv`

粒度：一行代表源 Excel `订单原始数据` 中的一条订单商品明细。当前样本 8,810 行。

| 字段 | 定义 |
|---|---|
| `order_date` | 从原始下单时间提取的订单日期 |
| `order_id` | 原始订单 ID，按文本保留 |
| `order_number` | 原始订单编号，按文本保留 |
| `customer_key` | 原始药店编码，按文本保留前导零 |
| `customer_name` | 原始药店全称 |
| `product_key` | 原始商品 ID，作为当前产品主键候选 |
| `product_code` | 原始商品编码，作为辅助映射字段 |
| `product_name` | 原始产品名称，不作为主键 |
| `manufacturer_raw` | 原始厂家文本 |
| `specification_raw` | 原始规格文本 |
| `quantity` | 原始采购量的数值化结果 |
| `unit_purchase_price` | 原始进货价的数值化结果 |
| `purchase_amount` | 原始进货金额；不是财务确认 GMV |
| `order_status_raw` | 原始订单状态 |
| `processing_status_raw` | 原始处理/配送/退款状态 |
| `processing_remark_raw` | 原始处理备注 |
| `settlement_status_raw` | 原始结算状态 |
| `order_type_raw` | 原始订单类型 |
| `policy_purchase_amount` | 当前配置计入月度汇总的文件内进货金额 |
| `order_purchase_amount` | 按订单 ID 汇总的文件内进货金额 |
| `included_in_order_count` | 当前配置下该订单是否计入订单数 |
| `data_quality_flags` | 所有命中的质量规则，分号分隔 |
| `metric_policy_name` | 使用的订单指标策略 |
| `metric_policy_status` | 策略可用性状态 |

Staging 保留独立布尔质量字段，不把缺失、冲突、零金额或未知状态静默修复。

## 月度诊断 mart

文件：`data/marts/ysb/mart_merchant_monthly_diagnosis.csv`

粒度：`month`，当前输出 2025-03 至 2025-06 共 4 行。

指标：

- `purchase_amount`
- `order_count`
- `aov`
- `active_customers`
- `active_products`

每月同时输出日期覆盖、完整性状态、策略名称和策略状态。只有当前月与前一月均为完整自然月时，才生成变化额和变化率；否则 `comparison_quality_status` 为 `INCOMPLETE_PERIOD` 或 `UNAVAILABLE`。

## Customer contribution mart

文件：`data/marts/ysb/mart_customer_monthly_contribution.csv`

粒度：`previous_month + current_month + customer_key`。当前 2025-04 对 2025-05 共 4,150 个 customer key。

客观周期状态：

- `RETAINED`：两个周期均有正金额采购。
- `CURRENT_ONLY`：仅本期有正金额采购。
- `PREVIOUS_ONLY`：仅上期有正金额采购。

`PREVIOUS_ONLY` 只描述两个周期的记录集合，不等同于客户永久流失。

## Product contribution mart

文件：`data/marts/ysb/mart_product_monthly_contribution.csv`

粒度：`previous_month + current_month + product_key`。当前 2025-04 对 2025-05 共 364 个 product key。

客观周期状态：

- `RETAINED_ACTIVE`
- `CURRENT_ONLY_ACTIVE`
- `PREVIOUS_ONLY_ACTIVE`

`mapping_quality_status` 为：

- `VALID`：商品 ID 在样本内只有一个商品编码，且厂家/规格签名唯一。
- `CONFLICT`：商品 ID 对应多个商品编码或多个厂家/规格签名。

商品展示字段通过频次和文本排序确定，金额汇总始终使用 `product_key`；展示字段变化不会改变贡献计算。

## 数据质量 mart

文件：`data/marts/ysb/mart_merchant_data_quality.csv`

输出每条规则的受影响行数、实体数和质量状态。规则覆盖：

- customer key 与名称冲突
- product key 映射冲突
- 订单、客户、商品和金额缺失
- 零金额行与零金额订单
- 新出现且配置未登记的订单、处理和结算状态
- 同订单跨日期
- `purchase_amount` 与 `quantity × unit_purchase_price` 不一致
- 原始状态业务语义尚未确认

状态值分布另存于 `data/marts/ysb/order_status_distribution.csv`，不对值赋予未确认的业务含义。

