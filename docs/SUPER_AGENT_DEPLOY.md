# 超级经纪人运营系统｜公网部署

Streamlit Community Cloud 推荐配置：

- Repository：`8000Greenhand/business-ops-workbench`
- Branch：`feature/super-agent-ops-v1`
- Main file path：`src/ops_workbench/ui/super_agent_app.py`
- App URL：<https://gaoyun-agent-growth-ops.streamlit.app/>
- Python version：`3.12`

仓库 `requirements.txt` 以 `-e .` 安装项目，实际依赖在 `pyproject.toml` 中。工作目录为仓库根目录，`config/` 随仓库提供。入口由文件位置解析配置，无本机绝对路径、外部 API 或真实业务数据依赖。

页面持续显示“模拟经营口径 / Demo 数据”。此 App 使用固定种子的虚构数据和模拟规则，不代表真实业务口径；接入真实数据前须另行确认授权与数据边界。
