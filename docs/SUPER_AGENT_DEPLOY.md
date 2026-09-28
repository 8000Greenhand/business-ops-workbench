# 超级经纪人运营系统｜独立 Demo 部署

Streamlit Community Cloud 配置：

- Repository：`8000Greenhand/business-ops-workbench`
- Main file path：`src/ops_workbench/ui/super_agent_app.py`
- Python version：`3.12`

| App | Branch | URL |
| --- | --- | --- |
| V1 模拟经营 Demo | `feature/super-agent-ops-v1` | <https://gaoyun-agent-growth-ops.streamlit.app/> |
| V2.1 独立预览（Preview） | `feature/super-agent-ops-v2-campaigns` | <https://gaoyun-agent-growth-ops-v2.streamlit.app/> |

两个 App 分别连接各自分支。V2.1 为模拟经营预览，不代表正式生产系统。

仓库 `requirements.txt` 以 `-e .` 安装项目，实际依赖在 `pyproject.toml` 中。工作目录为仓库根目录，`config/` 随仓库提供。入口由文件位置解析配置，无本机绝对路径、外部 API 或真实业务数据依赖。

页面持续显示“模拟经营口径 / Demo 数据”。此 App 使用固定种子的虚构数据和模拟规则，不代表真实业务口径；接入真实数据前须另行确认授权与数据边界。
