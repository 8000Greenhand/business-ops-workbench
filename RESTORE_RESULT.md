# Business Ops Workbench 恢复结果

检查日期：2026-09-11

## 恢复位置

真正的源码根目录：

`C:\Users\mr\Documents\ChatGPT\Business Ops Workbench\business-ops-workbench`

该目录直接包含 `README.md`、`AGENTS.md`、`pyproject.toml`、`src/`、`tests/`、`docs/`、`config/`，没有重复的 `Business Ops Workbench` 嵌套层级。当前工作区原有的 `outputs/` 和 `work/` 已保留。

## 复制与哈希校验

- 补充包源码文件数：220
- 首次复制：220
- 首次同 SHA-256 跳过：0
- 首次冲突（不同文件且未覆盖）：0
- 首次目标缺失：0
- 最终逐文件比对：220 个源文件均在恢复目录中找到
- 最终相同哈希：218
- 最终不同哈希：2
- 最终源文件缺失：0

最终不同的两个文件是 `src/business_ops_workbench.egg-info/PKG-INFO` 和 `src/business_ops_workbench.egg-info/SOURCES.txt`；它们在执行 editable 安装时由 setuptools 重新生成，未涉及源码或业务数据。复制阶段没有覆盖冲突文件。

## Python 与依赖

`pyproject.toml` 声明：`requires-python = ">=3.12"`。当前解释器为 Python 3.12.7，满足要求。

已在项目根目录创建专用环境：`.venv/`，并执行：

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

依赖安装成功；未复制或恢复原压缩包中的 `.venv`。

## 测试结果

执行命令：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

结果：168 项收集，167 通过，1 失败。

失败项：`tests/test_ui_smoke.py::test_streamlit_workbench_script_starts[script0]`。根因表现为 `src/ops_workbench/ui/app.py` 的 Streamlit `AppTest` 在 15 秒超时；其余测试均通过。未启动外部服务，未执行文档中的后续开发任务。

## 可运行命令

```powershell
.\.venv\Scripts\python.exe -m pytest
streamlit run src/ops_workbench/ui/app.py
python scripts/generate_demo_data.py --seed 42
```

本次仅执行测试，没有生成或推进正式业务指标、看板或业务功能。

## 数据与安全边界

`data/` 存在，包含 demo、staging、marts、exports、raw 分层。未修改原始业务数据，未填写账号、密码、Token 或 API Key。

## 项目关联

当前可用工具不提供把本地目录直接登记为 Codex 全局项目的操作，也不会修改 Codex 内部数据库或全局状态文件。请在应用的本地项目选择器中手动选择：

`C:\Users\mr\Documents\ChatGPT\Business Ops Workbench\business-ops-workbench`

## 迁移后 Streamlit UI smoke test 排查

### 测试结果

- 初始恢复记录中的唯一失败为 `tests/test_ui_smoke.py::test_streamlit_workbench_script_starts[script0]`，表现为 `AppTest.run(timeout=15)` 超时。
- 在恢复后的专用 `.venv` 中单独复现同一用例：通过，耗时约 4.45 秒；未出现应用异常。
- UI smoke 全量重跑：6 项通过，耗时 5.71 秒。
- 全量回归：168 项通过，耗时 129.78 秒。
- 复现及回归期间未修改业务代码、原始业务数据或测试超时设置。

### 启动与环境检查

- 独立执行 `streamlit run src/ops_workbench/ui/app.py --server.port 8501 --server.address 127.0.0.1`，日志显示 Uvicorn 正常启动并提供 `http://127.0.0.1:8501`。
- 启动后 `127.0.0.1:8501` 处于监听状态，访问根 URL 返回 HTTP 200。
- 启动前检查 8500–8510 端口无残留监听；测试结束后无残留 Streamlit/Python 进程。

### 结论

当前证据支持迁移环境中的首次启动/冷启动耗时波动，而不是应用代码或依赖不可用：后续冷启动及完整测试均稳定通过。未进行代码修复，也未通过延长超时或跳过测试掩盖失败。

### 应用页面实际可用性

应用可正常启动并响应本地 HTTP 请求；根页面可用。UI smoke 覆盖的 6 个 Streamlit 脚本均可执行且无 `app.exception`：入口页及数据导入、数据集状态、指标、异常、诊断页面脚本均通过。
