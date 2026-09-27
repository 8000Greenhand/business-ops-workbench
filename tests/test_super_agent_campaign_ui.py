"""Six-view campaign workflow and session/history isolation smoke."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


PAGE = Path(__file__).resolve().parents[1] / "src" / "ops_workbench" / "ui" / "pages" / "9_super_agent_ops.py"


def _box(app: AppTest, label: str):
    return next(box for box in app.selectbox if box.label == label)


def _metric(app: AppTest, label: str) -> str:
    return next(metric.value for metric in app.metric if metric.label == label)


def _enrollments(app: AppTest):
    return next(frame.value for frame in app.dataframe if "报名状态" in frame.value.columns)


def test_campaign_center_manager_choice_review_same_session():
    app = AppTest.from_file(str(PAGE), default_timeout=75).run()
    assert not app.exception
    assert len(app.radio[0].options) == 6
    app.radio[0].set_value("活动策略中心").run()
    assert not app.exception
    assert _box(app, "选择活动查看规则与候选").value.startswith("C02")
    assert any("活动规则与资源" == item.value for item in app.subheader)
    assert _metric(app, "当前有效活动") == "3"
    assert _metric(app, "报名中") == "2"
    assert _metric(app, "进行中") == "1"
    assert int(_metric(app, "系统推荐候选人次")) > len(_enrollments(app))
    assert _enrollments(app)["报名状态"].eq("待选择").all()
    app.radio[0].set_value("策略与活动复盘").run()
    assert not app.exception
    historical = {name: _metric(app, name) for name in ("成交单量", "晋级头部人数", "实际成本")}
    assert _metric(app, "本次会话报名") == "0"
    process = next(frame.value for frame in app.dataframe if "环节" in frame.value.columns)
    assert process["环节"].tolist() == ["系统推荐", "城市报名", "确认参与", "活动完成"]
    assert any("成交结果" in item.value for item in app.markdown)
    assert any("晋级结果" in item.value for item in app.markdown)

    app.radio[0].set_value("城市经理工作台").run()
    assert not app.exception
    assert any("模拟角色视图" in caption.value for caption in app.caption)
    assert _box(app, "选择我的活动").value.startswith("C02")
    people = _enrollments(app)["经纪人"].tolist()
    assert len(people) >= 2
    first, second = people[:2]
    _box(app, "选择活动候选人").set_value(first).run()
    next(button for button in app.button if button.label == "报名").click().run()
    assert not app.exception
    assert _enrollments(app).loc[lambda f: f["经纪人"] == first, "报名状态"].iloc[0] == "已报名"
    _box(app, "选择活动候选人").set_value(second).run()
    next(button for button in app.button if button.label == "不参加").click().run()
    assert any("原因" in warning.value for warning in app.warning)
    _box(app, "不参加原因").set_value("本人意愿不足").run()
    next(button for button in app.button if button.label == "不参加").click().run()
    assert not app.exception
    assert _enrollments(app).loc[lambda f: f["经纪人"] == second, "不参加原因"].iloc[0] == "本人意愿不足"

    app.radio[0].set_value("活动策略中心").run()
    center = _enrollments(app)
    assert center.loc[center["经纪人"] == first, "报名状态"].iloc[0] == "已报名"
    assert center.loc[center["经纪人"] == second, "报名状态"].iloc[0] == "不参加"
    assert center.loc[center["经纪人"] == second, "不参加原因"].iloc[0] == "本人意愿不足"
    app.radio[0].set_value("策略与活动复盘").run()
    assert _metric(app, "本次会话报名") == "1"
    assert _metric(app, "本次会话不参加") == "1"
    assert {name: _metric(app, name) for name in historical} == historical
    assert not app.exception
