from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.diagnostics.ysb_health import (
    BUSINESS_ALERT,
    DATA_QUALITY_ALERT,
    apply_attention_rules,
    derive_thresholds,
)
from ops_workbench.metrics.ysb_regional import (
    QUALITY_INSUFFICIENT_HISTORY,
    QUALITY_MISSING,
    QUALITY_UNRESOLVED_MERCHANT,
    build_merchant_monthly_health,
    load_ysb_staging,
)


def _frame() -> pd.DataFrame:
    rows = []
    for month, values in (("2026-01", (100, 100, 100)), ("2026-02", (80, None, 70)), ("2026-03", (40, 120, 60))):
        for key, gmv, mapping in (("ID:A", values[0], "ID_MATCHED"), ("ID:B", values[1], "ID_MATCHED"), ("NAME:C", values[2], "UNRESOLVED")):
            rows.append({"month": month, "merchant_key": key, "merchant_name_raw": key, "mapping_status": mapping, "coverage_status": "CURRENT", "gmv": gmv, "cash_sales_amount": gmv, "order_count": gmv, "aftersales_order_count": 1, "aftersales_rate": 0.1})
    return pd.DataFrame(rows)


def test_quality_gate_preserves_missing_and_history_states() -> None:
    health = build_merchant_monthly_health(_frame())
    first = health[(health["merchant_key"] == "ID:A") & (health["month"] == pd.Period("2026-01", freq="M"))].iloc[0]
    missing = health[(health["merchant_key"] == "ID:B") & (health["month"] == pd.Period("2026-02", freq="M"))].iloc[0]
    unresolved = health[(health["merchant_key"] == "NAME:C") & (health["month"] == pd.Period("2026-03", freq="M"))].iloc[0]
    assert first["gmv_mom_quality_status"] == QUALITY_INSUFFICIENT_HISTORY
    assert pd.isna(first["gmv_mom"])
    assert missing["gmv_quality_status"] == QUALITY_MISSING
    assert pd.isna(missing["gmv"])
    assert unresolved["gmv_mom_quality_status"] == QUALITY_UNRESOLVED_MERCHANT
    assert pd.isna(unresolved["gmv_mom"])


def test_quality_gap_is_not_business_alert() -> None:
    health = build_merchant_monthly_health(_frame())
    health.loc[(health["merchant_key"] == "ID:B") & (health["month"] == pd.Period("2026-02", freq="M")), "aftersales_rate"] = pd.NA
    thresholds = derive_thresholds(health)
    result = apply_attention_rules(health, thresholds)
    row = result[(result["merchant_key"] == "ID:B") & (result["month"] == pd.Period("2026-02", freq="M"))].iloc[0]
    assert row["business_attention_status"] == DATA_QUALITY_ALERT or row["business_attention_status"] == "NO_ALERT"
    assert "GMV" not in row["attention_reasons"]


def test_unresolved_merchant_has_no_trend_or_business_alert() -> None:
    health = build_merchant_monthly_health(_frame())
    result = apply_attention_rules(health, derive_thresholds(health))
    unresolved = result[result["merchant_key"] == "NAME:C"]
    assert unresolved["gmv_mom"].isna().all()
    assert (unresolved["business_attention_status"] != BUSINESS_ALERT).all()


def test_loader_rejects_duplicate_grain(tmp_path: Path) -> None:
    path = tmp_path / "staging.csv"
    frame = _frame().iloc[:2].copy()
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="grain"):
        load_ysb_staging(path)
