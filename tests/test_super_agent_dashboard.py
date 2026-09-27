"""Six-view local Streamlit smoke and readable derived data."""

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


def test_v1_fixed_seed_priority_regression():
    data = build_dashboard()
    assert data.agents["priority"].value_counts().to_dict() == {"P0": 60, "P1": 814, "P2": 326}
    assert int(data.agents["priority_score"].ge(data.policy["priority"]["p0_threshold"]).sum()) == 167
    assert int(data.agents["capacity_deferred"].sum()) == 107
    assert data.agents["stage"].nunique() == 6
    assert data.agents.groupby("manager_id")["priority"].apply(lambda values: values.eq("P0").sum()).max() <= 5


def test_six_views_smoke():
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not app.exception
    assert any(item.value == "城市经营对比" for item in app.subheader)
    for name, marker in [("成长漏斗", "成长阶段"), ("经营决策中心", "推荐动作 Top3"),
                         ("活动策略中心", "选择活动查看规则与候选"),
                         ("城市经理工作台", "先选择城市经理"), ("策略与活动复盘", "模拟活动实验")]:
        app.radio[0].set_value(name).run()
        assert not app.exception, name
        labels = [item.value for item in app.subheader] + [item.label for item in app.selectbox]
        assert marker in labels, name


def test_p0_task_session_sync_without_historical_effects():
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    app.radio[0].set_value("策略与活动复盘").run()
    historical = [metric.value for metric in app.metric if metric.label == "执行人数"][0]
    app.radio[0].set_value("城市经理工作台").run()
    assert app.radio[1].value == "P0 本周重点"
    assert not app.exception
    next(button for button in app.button if button.label == "接受").click().run()
    assert not app.exception
    app.radio[0].set_value("经营决策中心").run()
    assert "已接受" in app.dataframe[0].value["任务状态"].tolist()
    app.radio[0].set_value("城市经理工作台").run()
    next(button for button in app.button if button.label == "执行").click().run()
    assert not app.exception
    assert any(metric.label == "已执行" and metric.value == "1" for metric in app.metric)
    app.radio[1].set_value("已处理").run()
    assert any("状态：已执行" in item.value for item in app.caption)
    app.radio[1].set_value("P0 本周重点").run()
    skip_name = next(box for box in app.selectbox if box.label == "选择任务").value
    next(box for box in app.selectbox if box.label == "跳过原因").set_value("动作不适用").run()
    next(button for button in app.button if button.label == "跳过").click().run()
    app.radio[1].set_value("已处理").run()
    next(box for box in app.selectbox if box.label == "选择任务").set_value(skip_name).run()
    assert any("跳过原因：动作不适用" in item.value for item in app.caption)
    app.radio[0].set_value("策略与活动复盘").run()
    assert [metric.value for metric in app.metric if metric.label == "执行人数"][0] == historical
    assert any(metric.label == "已执行" and metric.value == "1" for metric in app.metric)
    assert any(metric.label == "跳过" and metric.value == "1" for metric in app.metric)
