import pandas as pd

from ops_workbench.diagnostics.ysb_health import build_merchant_monthly_health
from ops_workbench.diagnostics.ysb_priority import DATA_QUALITY, PRIORITY, build_priority_mart


def _health() -> pd.DataFrame:
    rows = []
    values = {"2026-01": {"A": 1000, "B": 500, "C": 100, "D": 50, "E": 40}, "2026-02": {"A": 800, "B": 100, "C": None, "D": 25, "E": 30}, "2026-03": {"A": 700, "B": 80, "C": None, "D": 20, "E": 10}}
    for month, data in values.items():
        for key, gmv in data.items():
            rows.append({"month": month, "merchant_key": f"ID:{key}", "merchant_name_raw": key, "mapping_status": "ID_MATCHED", "coverage_status": "CURRENT", "gmv": gmv, "cash_sales_amount": gmv, "order_count": gmv, "aftersales_order_count": 1, "aftersales_rate": 0.01})
    return build_merchant_monthly_health(pd.DataFrame(rows))


def test_priority_separates_data_quality_and_calculates_loss() -> None:
    mart, _ = build_priority_mart(_health())
    row = mart[(mart["merchant_key"] == "ID:C") & (mart["month"] == pd.Period("2026-03", freq="M"))].iloc[0]
    assert row["priority_level"] == DATA_QUALITY
    assert pd.isna(row["gmv_loss"])

    row = mart[(mart["merchant_key"] == "ID:A") & (mart["month"] == pd.Period("2026-03", freq="M"))].iloc[0]
    assert row["gmv_loss"] == 100
    assert row["previous_gmv"] == 800
    assert row["current_gmv"] == 700


def test_priority_uses_independent_dimensions_and_scale_labels() -> None:
    mart, thresholds = build_priority_mart(_health())
    row = mart[(mart["merchant_key"] == "ID:A") & (mart["month"] == pd.Period("2026-03", freq="M"))].iloc[0]
    assert row["merchant_scale"] in {"KEY", "MID", "LONG_TAIL"}
    assert row["diagnostic_dimension_count"] == len(set(row["diagnostic_dimensions"].split("|")))
    assert "Scale / Impact" in row["diagnostic_dimensions"] or row["priority_level"] != PRIORITY
    assert thresholds["high_loss"] >= 0
