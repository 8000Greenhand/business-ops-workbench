# Business Ops Workbench — V1 产品与开发规格（SPEC）

## 1. 项目定位

**项目名：** Business Ops Workbench  
**中文名：** 经营诊断工作台  
**V1目标：** 将 Excel / CSV 原始经营数据自动转换为可用于经营判断的信息：

> 数据导入 → 字段映射 → 数据校验 → 标准化 → 指标计算 → 趋势分析 → 异常发现 → 维度下钻 → 贡献诊断 → 经营日报

V1 必须保持行业无关，不能将任何嗨学网专属字段、KPI 或组织结构写死。

## 2. V1 核心原则

1. 配置优先：字段、指标、维度、预警阈值尽量配置化。
2. 行业无关：真实字段通过 mapping 适配标准模型。
3. 本地优先：V1 可完全离线运行。
4. 先诊断、后AI：V1 不接大模型、不做机器学习预测。
5. 数据质量优先：脏数据不得静默进入指标计算。
6. 结果可解释：异常和贡献分析必须说明依据。
7. 小步迭代：严格按 M0 → M4 开发。

## 3. 技术栈

- Python 3.12+
- pandas
- DuckDB
- Streamlit
- Plotly
- PyYAML
- openpyxl
- pytest
- Git

### V1 不使用
- MySQL / PostgreSQL
- React / Vue
- 云服务器
- 外部 LLM API
- 实时流式数据
- 企业微信/飞书机器人
- 权限系统
- 多租户
- CRM
- 机器学习模型

## 4. 项目目录

```text
business-ops-workbench/
│
├── README.md
├── SPEC.md
├── AGENTS.md
├── pyproject.toml
├── .gitignore
├── .env.example
│
├── config/
│   ├── app.yaml
│   ├── dimensions.yaml
│   ├── metrics.yaml
│   ├── alerts.yaml
│   └── mappings/
│       └── demo.yaml
│
├── data/
│   ├── raw/
│   ├── staging/
│   ├── marts/
│   ├── demo/
│   └── exports/
│
├── src/
│   └── ops_workbench/
│       ├── app.py
│       ├── ingestion/
│       │   ├── excel_reader.py
│       │   ├── csv_reader.py
│       │   └── file_loader.py
│       ├── mapping/
│       │   ├── field_mapper.py
│       │   └── mapping_validator.py
│       ├── validation/
│       │   ├── schema_validator.py
│       │   └── data_quality.py
│       ├── transforms/
│       │   ├── standardize.py
│       │   ├── clean.py
│       │   └── aggregate.py
│       ├── models/
│       │   ├── canonical_schema.py
│       │   └── database.py
│       ├── metrics/
│       │   ├── engine.py
│       │   ├── formulas.py
│       │   └── comparisons.py
│       ├── diagnostics/
│       │   ├── trend.py
│       │   ├── anomaly.py
│       │   ├── contribution.py
│       │   └── drilldown.py
│       ├── alerts/
│       │   ├── rules.py
│       │   └── severity.py
│       ├── reports/
│       │   ├── daily_report.py
│       │   ├── weekly_report.py
│       │   └── exporter.py
│       ├── ui/
│       │   ├── overview.py
│       │   ├── funnel.py
│       │   ├── diagnostics.py
│       │   ├── alerts.py
│       │   └── data_manager.py
│       └── utils/
│           ├── dates.py
│           ├── logging.py
│           └── helpers.py
│
├── scripts/
│   ├── generate_demo_data.py
│   ├── run_pipeline.py
│   └── reset_demo.py
│
├── tests/
│   ├── fixtures/
│   ├── test_ingestion.py
│   ├── test_mapping.py
│   ├── test_metrics.py
│   ├── test_anomaly.py
│   └── test_contribution.py
│
└── docs/
    ├── architecture.md
    ├── data_dictionary.md
    ├── metric_dictionary.md
    └── onboarding.md
```

## 5. 核心数据模型

### 5.1 核心事实表

表名：`fact_business_daily`

推荐粒度：

> date × business_line × product × channel × region × team × salesperson

允许部分维度为空，但不得把不同粒度的数据混入同一事实表而不做标记。

### 5.2 标准字段

维度字段：
- date
- business_line
- product
- channel
- region
- team
- salesperson

原子经营字段：
- impressions
- leads
- valid_leads
- contacted_leads
- followed_leads
- paid_users
- paid_orders
- gross_revenue
- refund_users
- refund_orders
- refund_amount

### 5.3 缺失字段原则

真实数据不存在某字段时：
- 标准化结果保留该字段；
- 值使用 NULL；
- 依赖该字段的指标标记为 unavailable；
- 页面不得伪造 0；
- 不得以 0 替代未知值。

## 6. 字段映射系统

真实源字段必须通过 YAML 映射到标准模型。

```yaml
mapping_name: demo_sales
source_type: excel
fields:
  date: 日期
  business_line: 项目
  product: 班型
  channel: 推广来源
  region: 区域
  team: 销售组
  salesperson: 咨询师
  leads: 资源数
  valid_leads: 有效资源
  paid_users: 成交人数
  gross_revenue: 流水
  refund_amount: 退费
```

要求：
1. 映射文件可保存。
2. 同类文件再次上传可复用映射。
3. 必填字段缺失时明确阻断。
4. 可选字段缺失时给出提示，不阻断。
5. 未识别字段可保留在 staging，不进入标准事实表。

## 7. 数据质量规则

### 阻断级错误
- date 无法解析
- gross_revenue 存在非法类型
- 核心粒度完全无法识别
- 同一文件出现无法解释的重复行
- 数据文件为空

### 警告级
- salesperson 缺失
- refund_amount 缺失
- 关键字段缺失比例超过阈值
- 负值
- 极端异常值
- 维度值前后空格/大小写不一致

输出示例：

```text
✓ 日期字段解析成功
✓ 共 105,321 行
⚠ refund_amount 缺失 2.1%
⚠ salesperson 为空 27 行
✕ gross_revenue 存在 8 个无法解析值
```

## 8. 指标引擎

指标必须由 `config/metrics.yaml` 驱动。

V1 至少支持：
- leads
- valid_leads
- valid_lead_rate
- contacted_leads
- contact_rate
- paid_users
- paid_orders
- conversion_rate
- gross_revenue
- avg_order_value
- refund_users
- refund_orders
- refund_amount
- refund_rate_amount
- net_revenue
- revenue_per_lead

指标计算要求：
1. 分母为 0 时返回 NULL。
2. 缺失依赖字段时返回 unavailable。
3. 每个派生指标必须带依赖项。
4. 支持按任意标准维度聚合。
5. 比例类指标必须先聚合分子分母再重算，禁止简单平均。

## 9. 时间比较

V1 支持：
- 环比
- 上周同期
- 7 日移动平均
- 30 日趋势
- 变化量
- 变化率

比例类指标要区分百分点变化（pct）和相对变化率。

## 10. 异常检测 V1

不使用机器学习。

支持：
1. 相对 7 日均值偏离
2. 相对上周同期偏离
3. 简单 z-score
4. 连续 N 天低于/高于阈值
5. 固定业务阈值

Severity：INFO / WARNING / CRITICAL

阈值放在 `config/alerts.yaml`。

## 11. 贡献分析

目标：解释“总指标变化由谁贡献”。

维度顺序：
1. business_line
2. product
3. channel
4. region
5. team
6. salesperson

输出：
- 各成员绝对变化量
- 对整体变化的贡献比例
- Top positive / Top negative
- 支持继续下钻

V1 的贡献只描述算术贡献，不自动宣称因果关系。

## 12. 诊断流程

```text
目标指标异常
→ 判断变化类型
→ 指标拆解
→ 一级维度贡献
→ 二级维度下钻
→ 找到主要异常节点
→ 生成“建议检查方向”
```

输出必须区分：
- Fact：数据事实
- Diagnostic：结构性定位
- Hypothesis：可能原因
- Recommendation：建议检查方向

## 13. UI 页面

V1 仅做 5 页：

### Page 1 — 经营总览
- net_revenue
- gross_revenue
- refund_amount
- conversion_rate
- refund_rate_amount
- target_completion_rate（若有目标数据）
- 7日/30日趋势
- Top positive / negative
- 当前异常摘要

### Page 2 — 经营漏斗
默认节点：
- impressions
- leads
- valid_leads
- contacted_leads
- paid_users
- paid_orders
- gross_revenue / net_revenue

字段不存在时自动隐藏。

### Page 3 — 诊断中心
- 选择目标指标
- 选择比较区间
- 一级贡献
- 自动/手动下钻
- 诊断摘要

### Page 4 — 异常中心
- severity
- 指标
- 维度
- 当前值
- 基准值
- 偏离幅度
- 异常规则
- 状态

### Page 5 — 数据管理
- 上传 XLSX / CSV
- 预览
- 字段映射
- 数据质量检查
- 导入
- 刷新
- 历史数据概览
- 映射模板管理

## 14. 自动日报

V1 使用规则模板生成 Markdown，不调用 AI。

必须包含：
- 核心经营结果
- 核心变化
- 主要异常
- 正/负贡献
- 今日重点关注

必须支持导出 `.md`。V1 可选支持 `.xlsx`，暂不要求 PDF。

## 15. Demo 数据

`scripts/generate_demo_data.py` 必须生成可复现模拟数据：
- 365 天
- 5 个业务线
- 20 个产品
- 8 个渠道
- 6 个团队
- 100 个销售

必须注入：
- Day 200：某渠道 valid_lead_rate 下跌约 20%
- Day 250：某团队 conversion_rate 下跌约 30%
- Day 300：某产品 refund_rate_amount 显著上升

测试必须验证这些异常可被识别。

## 16. 里程碑

### M0 — 工程底座
只做：目录、pyproject.toml、README、AGENTS、Streamlit 最小页、pytest、基础 logging、启动命令。

**不得实现 M1-M4。**

### M1 — 数据层
Demo 数据、Excel/CSV 导入、字段映射、校验、标准化、DuckDB。

### M2 — 指标层
metrics.yaml、指标引擎、聚合、环比、周同比、7日均值。

### M3 — 诊断层
异常检测、贡献分析、下钻。

### M4 — 产品层
5 个页面、日报、导出、完整测试、文档。

## 17. V1 验收标准

### 数据
- XLSX/CSV 可导入
- 字段映射可保存/复用
- 数据质量问题可见
- 阻断错误能阻断

### 指标
至少正确支持：leads、valid_leads、valid_lead_rate、conversion_rate、gross_revenue、refund_amount、refund_rate_amount、net_revenue、avg_order_value。

### 分析
- 环比
- 周同比
- 7日均值
- Top/Bottom
- 维度下钻
- 贡献分析
- 异常检测

### UI
- 5 个页面可正常使用
- 缺失指标有降级逻辑
- 错误不能导致整页崩溃

### 工程
- pytest 全部通过
- 核心公式有单测
- Demo 可自动生成
- 一条命令启动
- 无互联网可运行
- README 包含安装、启动、测试命令

## 18. V1 明确不做

- AI Agent
- LLM 自动分析
- 预测模型
- 用户画像模型
- 权限
- 多租户
- 云部署
- 实时数据
- API 接入
- CRM
- 企业微信/飞书
- 自动消息发送
- 数据仓库

任何新增需求先判断是否属于 V1；若不属于，记录到 Future Backlog。

## 19. Future Backlog

- 真实数据库连接
- Power BI 数据输出
- AI 经营摘要
- 异常根因候选排序
- 退款风险模型
- 线索价值分层
- 目标/预算模块
- 用户生命周期
- 自动周报/PPT
- 企业微信/飞书推送
- 权限与审计
