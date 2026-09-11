# Metric Dictionary — V1 指标字典

## 1. 原则

指标必须明确：公式、依赖字段、聚合逻辑、0 分母处理、缺失字段处理，并允许真实口径确认后通过配置调整。

## 2. 原子指标

| 指标ID | 中文名 | 字段 | 聚合 |
|---|---|---|---|
| impressions | 曝光 | impressions | SUM |
| leads | 线索 | leads | SUM |
| valid_leads | 有效线索 | valid_leads | SUM |
| contacted_leads | 已联系线索 | contacted_leads | SUM |
| followed_leads | 已跟进线索 | followed_leads | SUM |
| paid_users | 支付用户 | paid_users | SUM |
| paid_orders | 支付订单 | paid_orders | SUM |
| gross_revenue | 支付金额 | gross_revenue | SUM |
| refund_users | 退款用户 | refund_users | SUM |
| refund_orders | 退款订单 | refund_orders | SUM |
| refund_amount | 退款金额 | refund_amount | SUM |

## 3. 派生指标

### valid_lead_rate｜有效线索率
`valid_leads / leads`

### contact_rate｜联系率
`contacted_leads / valid_leads`

### follow_rate｜跟进率
`followed_leads / valid_leads`

### conversion_rate｜支付转化率
默认：`paid_users / valid_leads`

> 真实公司可能用支付人数/线索、支付人数/接通人数等，必须确认。

### avg_order_value｜客单价
默认：`gross_revenue / paid_users`

> 若实际按订单计算，则改为 gross_revenue / paid_orders。

### refund_rate_amount｜金额退款率
`refund_amount / gross_revenue`

### refund_rate_users｜用户退款率
`refund_users / paid_users`

### refund_rate_orders｜订单退款率
`refund_orders / paid_orders`

### net_revenue｜净收入
默认：`gross_revenue - refund_amount`

> 若存在撤单、坏账、调整项、手续费等，必须调整。

### revenue_per_lead｜单线索收入
`net_revenue / leads`

### target_completion_rate｜目标完成率
`net_revenue / revenue_target`

仅目标数据存在时启用。

## 4. 聚合逻辑

正确：

```text
conversion_rate = SUM(paid_users) / SUM(valid_leads)
```

错误：

```text
AVG(每个销售的 conversion_rate)
```

除非业务明确要求算术平均。

## 5. 时间比较

### 变化量
`delta = current - baseline`

### 变化率
`change_rate = (current - baseline) / baseline`

baseline = 0 时返回 NULL。

### 比例类指标百分点变化
`change_pct_point = current_rate - baseline_rate`

展示示例：转化率 15.2%，较上周 +1.8pct，相对提升 +13.4%。

## 6. 比较基准

| compare_id | 定义 |
|---|---|
| previous_period | 上一等长周期 |
| previous_week | 当前区间整体前移 7 天 |
| rolling_7d_average | 单日前 7 个日粒度指标的平均经营水平 |

`rolling_7d_average` 对原子指标和 difference 指标取有效日值的日均，缺失日和全 NULL 日不作为 0；对 ratio 指标先汇总窗口内 numerator 和 denominator，再重新相除，禁止平均每日比例。M2B 的滚动比较只支持单日 current，滚动序列只支持 7 日窗口。

## 7. 指标可用性

- available
- unavailable_missing_field
- unavailable_zero_denominator
- unavailable_insufficient_history

UI 必须显示合理原因。

## 8. 建议的 metrics.yaml 结构

```yaml
metrics:
  net_revenue:
    name: 净收入
    type: derived
    formula: gross_revenue - refund_amount
    dependencies:
      - gross_revenue
      - refund_amount
    format: currency
    higher_is_better: true

  conversion_rate:
    name: 支付转化率
    type: ratio
    numerator: paid_users
    denominator: valid_leads
    format: percentage
    higher_is_better: true

  refund_rate_amount:
    name: 金额退款率
    type: ratio
    numerator: refund_amount
    denominator: gross_revenue
    format: percentage
    higher_is_better: false
```

V1 优先使用结构化 numerator/denominator，不做任意字符串执行。

## 9. 默认核心指标

经营总览默认：
1. net_revenue
2. gross_revenue
3. refund_amount
4. conversion_rate
5. refund_rate_amount
6. target_completion_rate（如可用）

诊断中心默认目标指标：`net_revenue`

## 10. 真实业务接入前必须确认

1. 净收入是否等于流水减退款？
2. 转化率分母是什么？
3. 客单价按用户还是订单？
4. 退款率按金额、订单还是用户？
5. 退款归属成交日还是退款日？
6. 是否存在跨期退款？
7. 目标完成率以流水还是净收入为分子？
8. 是否计算毛利/利润？
9. 营销成本如何归因？
10. 多渠道触点如何归因？
