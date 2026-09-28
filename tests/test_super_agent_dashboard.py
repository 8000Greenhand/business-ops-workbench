"""Six-view local Streamlit smoke and readable derived data."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from ops_workbench.ui.super_agent_dashboard import (BOTTLENECK_FILTER_OPTIONS, BOTTLENECK_UI_LABELS,
    build_dashboard, decision_table, fmt_pct)


PAGE = Path(__file__).resolve().parents[1] / "src" / "ops_workbench" / "ui" / "pages" / "9_super_agent_ops.py"


def test_dashboard_and_chinese_formats():
    data = build_dashboard()
    table = decision_table(data.agents.head(2))
    assert len(table) == 2
    assert table["头部完成度"].str.endswith("%").all()
    assert fmt_pct(None) == "不可用"
    assert table.columns.get_loc("潜力分") + 1 == table.columns.get_loc("同群潜力百分位")
    assert table.columns.get_loc("同群潜力百分位") + 1 == table.columns.get_loc("置信度")
    sample = data.agents.loc[data.agents["potential_percentile"].notna()].head(1)
    assert decision_table(sample)["同群潜力百分位"].iloc[0] == fmt_pct(sample["potential_percentile"].iloc[0])
    missing = data.agents.loc[data.agents["potential_percentile"].isna()].head(1)
    assert decision_table(missing)["同群潜力百分位"].iloc[0] == "不可用"
    assert decision_table(missing)["潜力分"].iloc[0] == "不可用"
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


def test_decision_bottleneck_filter_uses_chinese_labels_and_raw_codes():
    assert list(BOTTLENECK_FILTER_OPTIONS) == ["全部", "商机资源", "商机承接", "有效跟进", "带看转化", "成交转化"]
    assert BOTTLENECK_FILTER_OPTIONS["商机资源"] == "resource"
    assert BOTTLENECK_FILTER_OPTIONS["成交转化"] == "closing"
    assert BOTTLENECK_UI_LABELS["acceptance"] == "商机承接"
    assert BOTTLENECK_UI_LABELS["showing"] == "带看转化"
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    app.radio[0].set_value("经营决策中心").run()
    box = next(item for item in app.selectbox if item.label == "主瓶颈")
    assert box.options == list(BOTTLENECK_FILTER_OPTIONS)
    data = build_dashboard()
    for label in ("成交转化", "商机资源"):
        box.set_value(label).run()
        assert not app.exception
        shown = app.dataframe[0].value
        assert not shown.empty
        expected = data.agents.loc[data.agents["priority"].isin(["P0", "P1"]) &
                                   data.agents["primary_bottleneck"].eq(BOTTLENECK_FILTER_OPTIONS[label]), "agent_name"]
        assert set(shown["经纪人"]).issubset(set(expected))
        assert shown["主瓶颈"].eq(label).all()
        box = next(item for item in app.selectbox if item.label == "主瓶颈")


def test_decision_detail_explains_potential_percentile_and_confidence():
    data = build_dashboard()
    candidate = data.agents.loc[data.agents["priority"].isin(["P0", "P1"]) &
                                data.agents["potential_percentile"].notna()].iloc[0]
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    app.radio[0].set_value("经营决策中心").run()
    table = app.dataframe[0].value
    assert table.columns[4:7].tolist() == ["潜力分", "同群潜力百分位", "置信度"]
    next(item for item in app.selectbox if item.label == "查看经纪人详情").set_value(candidate["agent_name"]).run()
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["潜力分"] == f"{candidate['potential_score']:.1f}"
    assert metrics["同群潜力百分位"] == fmt_pct(candidate["potential_percentile"])
    assert metrics["置信度"] in {"高", "中", "低"}
    assert any("比较同群：" in item.value and "样本" in item.value for item in app.markdown)
    head = data.agents.loc[data.agents["priority"].isin(["P0", "P1"]) &
                           data.agents["potential_score"].isna()].iloc[0]
    next(item for item in app.selectbox if item.label == "查看经纪人详情").set_value(head["agent_name"]).run()
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["潜力分"] == "不可用"
    assert metrics["同群潜力百分位"] == "不可用"
    assert not app.exception


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
