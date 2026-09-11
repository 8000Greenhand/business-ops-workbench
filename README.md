# Business Ops Workbench

Business Ops Workbench（经营诊断工作台）是一个本地优先、行业无关的经营数据诊断项目。V1 将按 M0 → M4 逐步实现数据导入、指标分析、异常诊断和报告输出。

## 当前里程碑

当前开发里程碑：**M4A-0 Streamlit Operations Workbench Shell**。

v0.1.0 已包含 M1 数据底座、完整 M2 指标层和 M3 诊断层。当前分支增加轻量 Streamlit 运营工作台壳层，尚未实现完整 Dashboard。

## 安装

需要 Python 3.12 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 启动

```powershell
streamlit run src/ops_workbench/ui/app.py
```

## 测试

```powershell
pytest
```

## 生成 Demo 数据

```powershell
python scripts/generate_demo_data.py --seed 42
```

默认输出 `data/demo/business_daily_demo.csv` 和 `data/demo/demo_metadata.json`。

## 标准数据链路

```python
from pathlib import Path

from ops_workbench.ingestion import load_source
from ops_workbench.mapping import apply_mapping, load_mapping
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms import standardize
from ops_workbench.validation import build_quality_report

source = load_source(Path("data/demo/business_daily_demo.csv"))
mapping = load_mapping("demo_business_daily")
mapped = apply_mapping(source.dataframe, mapping.fields)
standardized = standardize(
    mapped,
    source_columns=source.metadata.source_columns,
    source_field_mapping=mapping.fields,
)
quality = build_quality_report(standardized)

if quality.is_valid:
    replace_fact_business_daily(standardized, quality)
```

## 指标计算

```python
from datetime import date

from ops_workbench.metrics import MetricEngine

engine = MetricEngine()
result = engine.calculate_metric(
    "net_revenue",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 1, 31),
    filters={"channel": ["渠道01", "渠道03"]},
)
by_team = engine.calculate_metric_by_dimension("conversion_rate", "team")
```

## 趋势、比较与漏斗

```python
from ops_workbench.metrics import (
    calculate_funnel,
    compare_metric,
    get_metric_series,
    get_rolling_series,
)

trend = get_metric_series(engine, "conversion_rate", "2025-01-01", "2025-01-31")
comparison = compare_metric(
    engine,
    "net_revenue",
    "2025-01-31",
    "2025-01-31",
    comparison="previous_week",
)
rolling = get_rolling_series(engine, "conversion_rate", "2025-01-07", "2025-01-31")
funnel = calculate_funnel(engine, filters={"channel": "渠道03"})
```

滚动比例按窗口内分子、分母分别聚合后重算，不是每日比例的算术平均；加总型指标的滚动值是有效日值的日均。

## 经营异常扫描

```python
from ops_workbench.diagnostics import AnomalyEngine

scanner = AnomalyEngine(engine)
scan = scanner.scan_date("2025-07-19", filters={"business_line": "业务线01"})
event = scan.events[0]
print(event.metric_name, event.current_value, event.baseline_value, event.severity)
```

`AnomalyEvent` 描述指标相对基线的数据偏离；异常不等于已确认根因，event evidence 不作因果判断。

## 算术贡献分析

```python
from ops_workbench.diagnostics import ContributionEngine

contribution = ContributionEngine(engine).analyze_contribution(
    "net_revenue",
    "2025-08-01",
    "2025-08-30",
    "channel",
    comparison="previous_period",
)
largest_movements = contribution.top_movements()
```

Contribution 是对可加总指标变化的算术拆分，不代表因果影响。V1 明确拒绝对 ratio metrics 进行 arithmetic contribution。

## 结构化诊断

```python
from ops_workbench.diagnostics import DiagnosisEngine

event = scanner.scan_date("2025-07-19").events[0]
diagnosis = DiagnosisEngine(engine).diagnose_event(event)
```

Diagnosis 提供结构化证据与下一步检查方向，不是自动化因果结论；当前只执行一层 contribution drilldown。

## 目录简介

- `config/`：后续里程碑使用的配置目录。
- `data/`：本地数据分层目录；真实数据目录默认不提交 Git。
- `docs/`：架构、数据字典、指标字典和使用文档。
- `scripts/`：后续里程碑的命令行脚本目录。
- `src/ops_workbench/`：应用源代码及后续业务模块目录。
- `tests/`：自动化测试及测试夹具。

完整产品范围和里程碑约束见 `SPEC.md` 与 `AGENTS.md`。
