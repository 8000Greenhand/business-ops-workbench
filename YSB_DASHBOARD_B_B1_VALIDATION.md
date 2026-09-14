# Dashboard B B1 验证

## 验证范围

输入：`药师帮日报.xlsx / 订单原始数据`。

策略：`DEFAULT_FILE_INTERNAL_POLICY`。

对比周期：2025-04 与 2025-05。两个周期均覆盖完整自然月；2025-03 和 2025-06 为部分月份，不进入相邻完整周期比较。

## B0 核心数字复现

| 指标 | B0 2025-04 | B1 2025-04 | B0 2025-05 | B1 2025-05 | B1 变化 | 结果 |
|---|---:|---:|---:|---:|---:|---|
| Purchase amount | 426,265.64 | 426,265.64 | 363,033.66 | 363,033.66 | -63,231.98 | 一致 |
| Orders | 2,285 | 2,285 | 2,340 | 2,340 | +55 | 一致 |
| AOV | 186.55 | 186.55 | 155.14 | 155.14 | -31.41 | 一致 |
| Active customers | 2,141 | 2,141 | 2,181 | 2,181 | +40 | 一致 |
| Active products | 268 | 268 | 266 | 266 | -2 | 一致 |

金额变化率为 -14.83%，订单数变化率为 +2.41%，AOV 变化率为 -16.84%。B1 使用 `purchase_amount`，不再把底层金额正式命名为财务 GMV。

## Customer contribution 复现

Top 5 amount decrease 的 customer key、上期金额、本期金额和变化额均与 B0 一致。

| 排名 | customer_key | previous_amount | current_amount | amount_change | period_status |
|---:|---|---:|---:|---:|---|
| 1 | 0000622769 | 5,029.20 | 0.00 | -5,029.20 | PREVIOUS_ONLY |
| 2 | 0000614531 | 2,888.00 | 168.17 | -2,719.83 | RETAINED |
| 3 | 0000611205 | 2,600.00 | 0.00 | -2,600.00 | PREVIOUS_ONLY |
| 4 | 0000638204 | 2,259.60 | 0.00 | -2,259.60 | PREVIOUS_ONLY |
| 5 | 0000638563 | 1,666.52 | 0.00 | -1,666.52 | PREVIOUS_ONLY |

贡献表共有 4,150 个 customer key。`药店编码` 缺失 0 行，customer key 对多个名称冲突 0 个。Customer contribution 在当前文件内部稳定。

## Product contribution 复现

Top 5 amount decrease 的 product key、上期金额、本期金额和变化额均与 B0 一致。

| 排名 | product_key | previous_amount | current_amount | amount_change | period_status | mapping_quality_status |
|---:|---|---:|---:|---:|---|---|
| 1 | 2361484 | 49,797.25 | 387.00 | -49,410.25 | RETAINED_ACTIVE | CONFLICT |
| 2 | 2361487 | 53,951.52 | 10,445.00 | -43,506.52 | RETAINED_ACTIVE | VALID |
| 3 | 2923175 | 19,145.00 | 327.32 | -18,817.68 | RETAINED_ACTIVE | VALID |
| 4 | 2749085 | 19,605.94 | 5,527.63 | -14,078.31 | RETAINED_ACTIVE | CONFLICT |
| 5 | 3289729 | 14,064.65 | 3,134.12 | -10,930.53 | RETAINED_ACTIVE | CONFLICT |

贡献表共有 364 个 product key。金额和排名稳定；辅助商品编码或名称可能因一对多映射而变化，因此所有冲突均通过 `mapping_quality_status` 暴露，展示字段不参与金额分组。

## 数据质量结果

| 规则 | 受影响行 | 受影响实体 | 状态 |
|---|---:|---:|---|
| MISSING_ORDER_ID | 0 | 0 | VALID |
| MISSING_CUSTOMER_KEY | 0 | 0 | VALID |
| CUSTOMER_KEY_NAME_CONFLICT | 0 | 0 | VALID |
| MISSING_PRODUCT_KEY | 0 | 0 | VALID |
| PRODUCT_KEY_MAPPING_CONFLICT | 4,438 | 100 | REVIEW_REQUIRED |
| ZERO_AMOUNT_LINE | 1,059 | 1,059 | REVIEW_REQUIRED |
| ZERO_AMOUNT_ORDER | 967 | 896 | REVIEW_REQUIRED |
| UNRECOGNIZED_ORDER_STATUS | 0 | 0 | VALID |
| UNRECOGNIZED_PROCESSING_STATUS | 0 | 0 | VALID |
| UNRECOGNIZED_SETTLEMENT_STATUS | 0 | 0 | VALID |
| ORDER_CROSS_DATE | 0 | 0 | VALID |
| MISSING_PURCHASE_AMOUNT | 0 | 0 | VALID |
| PURCHASE_AMOUNT_MISMATCH | 0 | 0 | VALID |
| UNCONFIRMED_STATUS_SEMANTICS | 8,810 | 8,050 orders | USABLE_WITH_LIMITATION |

`ZERO_AMOUNT_ORDER` 的 967 是受影响明细行数，896 是唯一订单数。零金额被保留和标记，没有被填充、删除或改写。

## 自动化验证

新增聚焦测试覆盖：

- 正金额订单计数与零金额保留。
- 最近两个相邻完整月份选择。
- Customer 与 Product 的客观周期状态。
- customer 名称冲突、product 映射冲突、跨日期订单和金额不一致的显式质量标记。

聚焦测试结果：4 passed。

## 判定

B1 成功复现 B0 的核心数字与贡献排名。Customer contribution 可作为稳定数据层使用。Product contribution 的金额计算稳定，但展示和“仅某周期活跃”状态必须携带映射质量标记。

当前 BLOCKER 仍是订单、退款、配送和结算状态的业务口径未确认。该问题不阻止进入 B2 生成基于事实的诊断结论，但 B2 必须把金额称为 `purchase_amount`，保留 `USABLE_WITH_LIMITATION`，不得从状态关联推断财务收入、退款归因或客户流失。
