# Data Dictionary — 标准数据字典

## 1. 目的

定义 Business Ops Workbench V1 的标准数据模型。真实业务数据必须通过字段映射进入标准模型。

原则：源字段名称可以不同，业务含义必须先确认，再映射。

## 2. 核心事实表

**表名：** `fact_business_daily`

**推荐粒度：**

`date × business_line × product × channel × region × team × salesperson`

一行数据必须代表一个可明确解释的经营单元。

## 3. 维度字段

| 标准字段 | 中文名 | 类型 | 必填 | 示例 | 说明 |
|---|---|---|---|---|---|
| date | 日期 | DATE | 是 | 2026-09-04 | 业务发生日期 |
| business_line | 业务线 | STRING | 否 | 业务线A | 一级业务分类 |
| product | 产品 | STRING | 否 | 产品A-标准版 | 产品/SKU/课程/服务包 |
| channel | 渠道 | STRING | 否 | 渠道A | 获客/销售/流量来源 |
| region | 区域 | STRING | 否 | 成都 | 地区或经营区域 |
| team | 团队 | STRING | 否 | 业务二组 | 组织单元 |
| salesperson | 人员 | STRING | 否 | 员工001 | 业务人员标识 |

## 4. 原子指标字段

| 标准字段 | 中文名 | 类型 | 单位 | 聚合 | 允许负值 | 说明 |
|---|---|---:|---|---|---|---|
| impressions | 曝光 | INTEGER | 次/人 | SUM | 否 | 上游曝光量 |
| leads | 线索 | INTEGER | 个 | SUM | 否 | 原始线索数 |
| valid_leads | 有效线索 | INTEGER | 个 | SUM | 否 | 有效线索 |
| contacted_leads | 已联系线索 | INTEGER | 个 | SUM | 否 | 已完成首次有效联系 |
| followed_leads | 已跟进线索 | INTEGER | 个 | SUM | 否 | 进入跟进流程 |
| paid_users | 支付用户 | INTEGER | 人 | SUM | 否 | 发生支付的用户数 |
| paid_orders | 支付订单 | INTEGER | 单 | SUM | 否 | 支付订单数 |
| gross_revenue | 支付金额 | DECIMAL | 元 | SUM | 原则否 | 流水/支付金额 |
| refund_users | 退款用户 | INTEGER | 人 | SUM | 否 | 退款用户数 |
| refund_orders | 退款订单 | INTEGER | 单 | SUM | 否 | 退款订单数 |
| refund_amount | 退款金额 | DECIMAL | 元 | SUM | 原则否 | 退款金额 |

## 5. 可扩展目标字段

| 字段 | 中文名 | 类型 | 用途 |
|---|---|---|---|
| revenue_target | 收入目标 | DECIMAL | 目标完成率 |
| leads_target | 线索目标 | INTEGER | 线索完成率 |
| cost | 成本 | DECIMAL | 后续 ROI/利润 |
| marketing_cost | 营销成本 | DECIMAL | 获客效率 |
| new_users | 新用户 | INTEGER | 新增用户 |
| repeat_users | 复购用户 | INTEGER | 复购分析 |

只有在真实口径确认后才能进入正式计算。

## 6. 数据类型规则

### 日期
接受 YYYY-MM-DD、YYYY/MM/DD、Excel 日期序列、可明确解析的 datetime。标准化输出 YYYY-MM-DD。

### 数值
- 金额使用 decimal / float 计算。
- 人数、订单原则为非负整数。
- 千分位、货币符号在 ingestion 阶段清洗。

### 文本
- 去除首尾空格。
- 空字符串标准化为 NULL。
- 不擅自合并同义维度值。

## 7. NULL 与 0

0 = 已知且为零。  
NULL = 未提供、无法确认或当前粒度不适用。

没有退款字段 ≠ 退款金额为 0。

## 8. 主键与重复

推荐逻辑键：date、business_line、product、channel、region、team、salesperson。

如源数据重复：
1. 判断是否可安全聚合；
2. 无法确认则报警；
3. 不得静默去重。

## 9. 字段映射示例

```yaml
fields:
  date: 日期
  business_line: 项目
  product: 班型
  channel: 推广来源
  team: 销售组
  salesperson: 咨询师
  leads: 资源数
  valid_leads: 有效资源
  paid_users: 成交人数
  gross_revenue: 流水
  refund_amount: 退费
```

## 10. 数据质量最低要求

### Schema
- 存在 date
- 至少存在一个可计算经营结果的原子指标

### Completeness
- NULL 比例
- 关键字段缺失

### Validity
- 日期合法
- 数值可解析
- 人数非负
- 金额异常值提示

### Consistency
例如：
- valid_leads > leads 时报警
- paid_users > valid_leads 时报警
- refund_amount > gross_revenue 时报警

这些是数据一致性提示，不自动等于业务错误。

## 11. 真实业务接入时必须确认

1. 流水口径是什么？
2. 退款按申请日还是实际退款日？
3. 支付人数是否去重？
4. 线索是否跨日重复？
5. 一个用户能否对应多个业务人员？
6. 一个订单能否跨产品？
7. 团队/人员组织关系是否历史变化？
8. 渠道归因口径是什么？
9. 是否有目标数据？
10. 是否存在取消、撤单、部分退款？

未确认前不得把假设写死。
