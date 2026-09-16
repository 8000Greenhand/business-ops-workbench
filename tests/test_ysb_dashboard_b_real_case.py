from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.diagnostics.ysb_merchant_case import (
    HAS_ACTIVITY,
    HAS_CUSTOMER,
    HAS_PRODUCT,
    HAS_TRAFFIC,
    detect_case_capabilities,
)
from ops_workbench.ui.ysb_dashboard_b import (
    core_facts,
    current_metrics,
    has_capability,
    load_public_demo_dashboard_b,
    result_decomposition,
)

ROOT = Path(__file__).resolve().parents[1]


def _case():
    return load_public_demo_dashboard_b(ROOT / "demo_data" / "ysb_dashboard_b")


def test_zhongende_core_result_and_product_contribution() -> None:
    data = _case()
    april, may = data.monthly.iloc[0], current_metrics(data)
    assert april["purchase_amount"] == pytest.approx(476_865.08)
    assert may["purchase_amount"] == pytest.approx(124_226.34)
    assert (april["order_count"], may["order_count"]) == (1932, 1059)
    assert (april["aov"], may["aov"]) == pytest.approx((246.8245756, 117.3053258))
    assert may["purchase_amount_change_rate"] == pytest.approx(-0.7394937369)
    assert result_decomposition(data)["driver_classification"] == "MIXED"

    products = data.products.sort_values("amount_change")
    assert products["amount_change"].sum() == pytest.approx(-352_638.74)
    assert "HEM-7121" in products.iloc[0]["product_name"]
    assert products.iloc[0]["amount_change"] == pytest.approx(-100_040.70)


def test_zhongende_traffic_and_activity_layers() -> None:
    data = _case()
    traffic = data.traffic.set_index("metric")
    assert traffic.loc["曝光", "own_change_rate"] == pytest.approx(-0.4259249)
    assert traffic.loc["点击", "own_change_rate"] == pytest.approx(-0.4775463)
    assert traffic.loc["访客", "own_change_rate"] == pytest.approx(-0.4995010)
    assert traffic.loc["曝光", "peer_change_rate"] == pytest.approx(-0.0516082)
    assert traffic.loc["点击", "peer_change_rate"] == pytest.approx(-0.1184174)
    assert traffic.loc["访客", "peer_change_rate"] == pytest.approx(-0.1307190)

    activities = data.activities.set_index("activity_type")
    assert activities.loc["拼团", "previous_amount"] == pytest.approx(430_627.12)
    assert activities.loc["拼团", "current_amount"] == pytest.approx(123_115.64)
    assert activities.loc["拼团", "negative_contribution"] == pytest.approx(0.8720298)
    assert activities.loc["批购包邮", "amount_change"] == pytest.approx(-45_127.26)
    assert data.activity_mapping_rate == pytest.approx(1.0)


def test_capabilities_make_customer_unavailable_without_fabrication() -> None:
    data = _case()
    assert has_capability(data, HAS_TRAFFIC)
    assert has_capability(data, HAS_ACTIVITY)
    assert has_capability(data, HAS_PRODUCT)
    assert not has_capability(data, HAS_CUSTOMER)
    assert data.customers.empty
    assert "不包含药店标识" in str(data.customer_unavailable_reason)
    assert len(core_facts(data)) == 5

    sparse = pd.DataFrame({"商品编码": ["P1"], "产品名称": ["商品"], "进货金额": [1.0]})
    assert detect_case_capabilities(sparse) == frozenset({HAS_PRODUCT})
