# Dashboard B B1 指标口径

## 命名

底层正式金额字段为 `purchase_amount`，来源是订单明细的 `进货金额`。

允许的展示别名：`GMV candidate / 进货金额`。

禁止在业务定义未确认前将其命名为财务 GMV、确认收入、支付金额或结算金额。

## 实际状态字段与分布

### `order_status_raw`

| 值 | 行数 |
|---|---:|
| 交易完成 | 7,273 |
| 待收货 | 1,537 |

### `processing_status_raw`

| 值 | 行数 |
|---|---:|
| 配送完成 | 7,365 |
| 已退款 | 967 |
| 药品已出库 | 446 |
| 待处理 | 13 |
| 订单已接受 | 10 |
| 无法配送退款中 | 9 |

### `settlement_status_raw`

| 值 | 行数 |
|---|---:|
| 已结算 | 7,254 |
| 未结算 | 1,555 |
| 结算中 | 1 |

### 其他保留字段

- `processing_remark_raw`：35 个观察值（含空值）；空值 7,792 行。该字段包含退款原因、配送问题、资质或缺货等自由文本，不作为自动过滤条件。
- `order_type_raw`：样本全部为 `商家直供`，8,810 行。

以上只是源值分布，不代表已确认状态之间的业务关系。

## DEFAULT_FILE_INTERNAL_POLICY

策略状态：`USABLE_WITH_LIMITATION`。

### Purchase amount

- 所有可解析的 `purchase_amount` 均计入文件内部金额汇总。
- 当前不按订单、处理、退款或结算状态过滤。
- 零金额作为真实零保留并标记。
- 缺失或非数值金额不转为零，标记后保持不可用。

### Order count

- 先按 `order_id` 汇总已纳入的 `purchase_amount`。
- 订单汇总金额大于 0 时，计入 `order_count`。
- 订单汇总金额等于 0 时，不计入 `order_count`，并标记 `ZERO_AMOUNT_ORDER`。
- 该规则是为了复现 B0 文件内口径，不是唯一业务定义。

### AOV

`aov = purchase_amount / order_count`

当 `order_count` 为 0 时返回 NULL，不返回无穷值，也不把 NULL 变为 0。

### Active entities

- `active_customers`：当期至少有一条正 `purchase_amount` 的唯一 `customer_key` 数。
- `active_products`：当期至少有一条正 `purchase_amount` 的唯一 `product_key` 数。

### Period status

Customer：`RETAINED`、`CURRENT_ONLY`、`PREVIOUS_ONLY`。

Product：`RETAINED_ACTIVE`、`CURRENT_ONLY_ACTIVE`、`PREVIOUS_ONLY_ACTIVE`。

这些状态只描述相邻两个完整周期内是否存在正金额采购，不自动解释为新增客户、客户流失、永久上架或永久下架。

## 未确认语义

尚未确认：

- `交易完成` 是否等同财务确认收入。
- `待收货` 的正金额是否应计入正式经营额或订单数。
- `已退款` 与 `进货金额=0` 是否覆盖所有退款场景。
- `配送完成` 是否足以判断订单已经履约。
- `已结算`、`未结算`、`结算中` 应如何影响经营指标。
- 自由文本备注是否存在需要结构化处理的业务规则。

因此，新出现的未登记状态会触发 `UNRECOGNIZED_*` 数据质量规则；已登记状态仍统一标记为 `UNCONFIRMED` 语义，不据此猜测收入或退款归属。

