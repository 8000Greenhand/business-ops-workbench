"""Five-view local Streamlit smoke and readable derived data."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from ops_workbench.ui.super_agent_dashboard import build_dashboard, decision_table, fmt_pct


PAGE = Path(__file__).resolve().parents[1] / "src" / "ops_workbench" / "ui" / "pages" / "9_super_agent_ops.py"


def test_dashboard_and_chinese_formats():
    data = build_dashboard()
    table = decision_table(data.agents.head(2))
    assert len(table) == 2
    assert table["头部完成度"].str.endswith("%").all()
    assert fmt_pct(None) == "不可用"
    assert data.kpis["head_count"] == data.kpis["new_head_count"] + data.kpis["stable_head_count"]
    assert data.agents.loc[data.agents["stage"].isin(["新晋头部", "稳定头部"]), "potential_score"].isna().all()
    deferred = data.agents.loc[data.agents["capacity_deferred"]].head(1)
    assert decision_table(deferred)["容量状态"].iloc[0] == "容量递延"


def test_five_views_smoke():
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not app.exception
    assert any(item.value == "城市经营对比" for item in app.subheader)
    for name, marker in [("成长漏斗", "成长阶段"), ("经营决策中心", "推荐动作 Top3"),
                         ("城市经理工作台", "先选择城市经理"), ("策略实验与复盘", "模拟活动实验")]:
        app.radio[0].set_value(name).run()
        assert not app.exception, name
        labels = [item.value for item in app.subheader] + [item.label for item in app.selectbox]
        assert marker in labels, name
