# Dashboard B B2 验证

## 验证范围

- 输入仅为 B1 的 monthly、customer contribution 和 product contribution marts。
- 样本为 2025-04 与 2025-05。
- 未重读 `药师帮日报.xlsx`，未读取历史 57 文件。
- 未修改 Dashboard A，未开发 UI，未分析活动、价格或流量。

## Result 一致性

| 指标 | B1 | B2 | 结果 |
|---|---:|---:|---|
| 2025-04 purchase_amount | 426,265.64 | 426,265.64 | 一致 |
| 2025-05 purchase_amount | 363,033.66 | 363,033.66 | 一致 |
| purchase_amount change | -63,231.98 | -63,231.98 | 一致 |
| Orders change | +55 / +2.41% | +55 / +2.41% | 一致 |
| AOV change | -31.41 / -16.84% | -31.41 / -16.84% | 一致 |

对称两因素分解得到订单效应 +9,396.53、AOV 效应 -72,628.51，合计 -63,231.98；浮点误差约 `-3.6e-11` 元。Result 分类为 `AOV_DRIVEN`。

## Contribution reconciliation

| 观察维度 | contribution 合计 | 整体变化 | reconciliation error | 结果 |
|---|---:|---:|---:|---|
| Customer | -63,231.98 | -63,231.98 | 0.0000000001 | PASS |
| Product | -63,231.98 | -63,231.98 | 0.0000000001 | PASS |

两个 bridge 分别与整体变化核对，不互相加总。

## Facts mart 验证

生成文件：`data/marts/ysb/mart_merchant_diagnosis_facts.csv`。

- 共 11 条记录：5 条 `FACT` 核心事实、1 条 `LIMITATION`、5 条 `DO_NOT_INFER`。
- 核心事实数为 5，未超过配置上限。
- Result fact 为 `LIMITED`，携带 `ORDER_STATUS_SEMANTICS_UNCONFIRMED`。
- Customer 两条 fact 为 `HIGH`，reconciliation 通过。
- Product 两条 fact 为 `MEDIUM`，均携带 `PRODUCT_MAPPING_LIMITATION`。
- Product 冲突记录保留在贡献计算中，没有删除或静默修正。
- Customer 与 Product 状态均使用客观周期措辞，没有把 `CURRENT_ONLY` / `PREVIOUS_ONLY` 写成新增、流失、新品或永久退出。
- 核心事实未出现财务收入、永久流失、涨价导致、缺货导致或退款导致等越界因果结论。

## 自动化验证

B2 聚焦测试覆盖：

- 两因素分解精确回加和驱动分类。
- Customer contribution bridge reconciliation。
- Product contribution bridge reconciliation。
- 核心事实不超过 5 条。
- Product mapping limitation 向事实传播。
- `FACT`、`LIMITATION`、`DO_NOT_INFER` 三类输出齐备。
- 禁止因果措辞不进入核心事实。

聚焦测试结果：4 passed。

项目全量测试结果：176 passed（139.84s）。

## 判定

B2 已能从 B1 marts 稳定生成可解释、可排序、带证据等级和质量标记的诊断事实。当前 blocker 不在计算回加，而在订单状态业务语义和商品映射质量；未来 UI 必须展示这些限制，不能把 `purchase_amount` 改称财务收入或把周期状态解释为永久新增/流失。
