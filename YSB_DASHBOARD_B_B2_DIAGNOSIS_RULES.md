# Dashboard B B2 诊断事实规则

## 范围与输入

B2 只读取 B1 已生成的以下数据集：

- `mart_merchant_monthly_diagnosis`
- `mart_customer_monthly_contribution`
- `mart_product_monthly_contribution`

不读取源 Excel，不新增基础指标，不分析活动、价格或流量。所有金额均称为 `purchase_amount / 进货金额`，不解释为财务收入或正式 GMV。

规则配置位于 `config/ysb_dashboard_b_diagnosis_rules.yaml`，当前版本为 `DASHBOARD_B_B2_FACT_RULES_V1`。核心事实最多 5 条，reconciliation 容差为 0.01 元。

## Result 两因素分解

基础恒等式：

`purchase_amount = Orders × AOV`

采用对称两因素分解：

```text
Order effect = (Orders_current - Orders_previous)
             × (AOV_previous + AOV_current) / 2

AOV effect   = (AOV_current - AOV_previous)
             × (Orders_previous + Orders_current) / 2

purchase_amount change = Order effect + AOV effect
```

该公式精确分配交互项，不依赖因素排列顺序。分类采用方向一致性：

- `ORDER_DRIVEN`：只有订单效应与总变化方向一致。
- `AOV_DRIVEN`：只有 AOV 效应与总变化方向一致。
- `MIXED`：两项均与总变化同向、总变化近似为零，或不能由单一方向因素解释。

由于订单、退款、配送和结算状态的业务语义尚未确认，Result 事实保留 `ORDER_STATUS_SEMANTICS_UNCONFIRMED`，evidence level 为 `LIMITED`。

## Customer contribution bridge

按以下客观周期状态汇总实体数、上期金额、本期金额和变化额：

- `RETAINED`：两期持续活跃药店。
- `CURRENT_ONLY`：本期活跃、上期未活跃药店。
- `PREVIOUS_ONLY`：上期活跃、本期未活跃药店。

Customer bridge 的全部 `amount_change` 必须独立回加至整体进货金额变化。误差超过 0.01 元时，事实降为 `LIMITED` 并标记 `CUSTOMER_RECONCILIATION_ERROR`。

Top loss / growth 按 `amount_change` 排序。Loss concentration 定义为：

`abs(Top 5 negative amount_change) / abs(all negative amount_change)`

`CURRENT_ONLY` 不解释为新增客户，`PREVIOUS_ONLY` 不解释为永久流失客户。

## Product contribution bridge

按以下客观周期状态汇总：

- `RETAINED_ACTIVE`：两期持续活跃商品。
- `CURRENT_ONLY_ACTIVE`：本期活跃、上期未活跃商品。
- `PREVIOUS_ONLY_ACTIVE`：上期活跃、本期未活跃商品。

Product bridge 同样必须独立回加至整体进货金额变化。Customer bridge 和 Product bridge 是两个观察维度，不得相互加总。

存在商品映射冲突时，贡献金额仍保留，但相关事实标记 `PRODUCT_MAPPING_LIMITATION`，evidence level 降为 `MEDIUM`。不得使用“新品”“彻底退出”等永久性或因果措辞。

## 核心事实选择与证据等级

系统按解释层次而不是触发数量选择最多 5 条核心事实：

1. Result：进货金额、Orders、AOV 及两因素分解。
2. Customer：三类状态 bridge。
3. Customer：Top 5 负向集中度及最大正负变化实体。
4. Product：三类状态 bridge。
5. Product：Top 5 负向集中度及最大正负变化实体。

证据等级：

- `HIGH`：由已验证的金额、药店贡献和 reconciliation 直接证明。
- `MEDIUM`：商品贡献成立，但展示映射存在质量限制。
- `LIMITED`：依赖尚未确认的订单状态业务语义，或 reconciliation 失败。

## 输出类型与推断边界

- `FACT`：数据直接证明的描述。
- `LIMITATION`：状态语义或映射质量限制。
- `DO_NOT_INFER`：明确禁止从当前数据推出的结论。

当前拒绝推断：财务收入下降、客户永久流失、涨价导致销量下降、缺货导致商品采购下降、退款导致进货金额下降。
