# Codex M0 启动指令

请在当前工作区建立新的 Python 项目：`business-ops-workbench`。

项目目标和规则已经写在：
- `SPEC.md`
- `AGENTS.md`
- `docs/data_dictionary.md`
- `docs/metric_dictionary.md`

## 当前只执行 M0：工程底座

请严格遵守 `AGENTS.md`，不要提前实现 M1-M4。

### M0 要完成

1. 创建 SPEC 中定义的完整目录骨架。
2. 创建 `pyproject.toml`，要求 Python 3.12+。
3. 创建 `.gitignore`：忽略 Python 临时文件、`.venv`、`.env`，并忽略 `data/raw/`、`data/staging/`、`data/marts/`、`data/exports/` 中的真实数据文件；必要目录使用 `.gitkeep` 保留。
4. 创建 `.env.example`。
5. 创建 `README.md`，至少包括项目定位、当前里程碑、安装、启动、测试、目录简介。
6. 创建 Streamlit 最小启动页：
   - 标题：Business Ops Workbench
   - 副标题：经营诊断工作台
   - 显示“当前版本：M0 工程底座”
   - 不实现任何真实业务功能。
7. 创建基础 logging 工具。
8. 创建 pytest smoke test。
9. 确保项目能通过 `pytest`，并能启动 Streamlit。

## 不允许实现

- Excel/CSV 导入
- DuckDB 业务表
- 字段映射
- 指标计算
- Demo 数据
- 异常检测
- 贡献分析
- 完整 Dashboard
- AI 功能

## 完成后按以下结构汇报

### 完成
### 新增/修改文件
### 启动方式
### 测试结果
### 当前里程碑剩余事项
### 风险或需要确认的问题

不要开始 M1，等待下一条指令。
