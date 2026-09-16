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
    activity_detail_summary,
    activity_top_contributors,
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

    detail = data.activity_details
    assert detail["activity_id"].dtype.name == "string"
    assert detail["activity_id"].nunique() == 154
    assert detail.groupby("activity_type")["activity_id"].nunique().to_dict() == {
        "拼团": 142,
        "批购包邮": 12,
    }
    assert detail["amount_change"].sum() == pytest.approx(
        data.activities["amount_change"].sum()
    )

    summary = activity_detail_summary(data, "拼团")
    assert summary == pytest.approx(
        {
            "activity_count": 142,
            "negative_count": 85,
            "positive_count": 53,
            "flat_count": 4,
            "top5_loss_concentration": 0.5606184011,
        }
    )
    losses = activity_top_contributors(data, "拼团", positive=False)
    growth = activity_top_contributors(data, "拼团", positive=True)
    assert losses.head(5)["activity_id"].tolist() == [
        "1129859298",
        "974385766",
        "974385814",
        "1165953164",
        "974385821",
    ]
    assert losses.head(5)["amount_change"].tolist() == pytest.approx(
        [-71_601.51, -44_170.80, -43_932.50, -33_279.25, -28_662.90]
    )
    assert growth.head(3)["activity_id"].tolist() == ["1209902830", "1203607570", "1114638780"]
    assert growth.head(3)["amount_change"].tolist() == pytest.approx(
        [22_131.36, 21_924.22, 12_891.12]
    )


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
