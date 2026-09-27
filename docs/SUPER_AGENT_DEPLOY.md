# 超级经纪人运营系统｜部署准备

Streamlit Community Cloud 推荐配置：

- Repository：`8000Greenhand/business-ops-workbench`
- Branch：`feature/super-agent-ops-v1`（经代码验收后可选正式发布分支）
- Main file path：`src/ops_workbench/ui/super_agent_app.py`

使用 Python 3.12+。仓库 `requirements.txt` 以 `-e .` 安装项目，实际依赖在 `pyproject.toml` 中。工作目录应为仓库根目录，`config/` 必须随仓库提供。入口由文件位置解析配置，无本机绝对路径、外部 API 或真实业务数据依赖。

本轮只完成可部署准备，不创建公网部署。页面持续显示“模拟经营口径 / Demo 数据”；部署前还需按真实业务授权与数据边界复核。
