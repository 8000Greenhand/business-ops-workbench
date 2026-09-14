from pathlib import Path

import pandas as pd

from ops_workbench.diagnostics.ysb_merchant_b2 import (
    build_contribution_summary,
    build_diagnosis_facts,
    decompose_result,
    load_diagnosis_rules,
)

ROOT = Path(__file__).resolve().parents[1]
RULES = load_diagnosis_rules(ROOT / "config" / "ysb_dashboard_b_diagnosis_rules.yaml")


def _monthly() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"month": "2025-04", "previous_month": pd.NA, "purchase_amount": 100.0, "order_count": 10, "aov": 10.0, "purchase_amount_change": pd.NA, "purchase_amount_change_rate": pd.NA, "order_count_change": pd.NA, "order_count_change_rate": pd.NA, "aov_change": pd.NA, "aov_change_rate": pd.NA, "comparison_quality_status": "UNAVAILABLE"},
            {"month": "2025-05", "previous_month": "2025-04", "purchase_amount": 80.0, "order_count": 12, "aov": 80 / 12, "purchase_amount_change": -20.0, "purchase_amount_change_rate": -0.2, "order_count_change": 2, "order_count_change_rate": 0.2, "aov_change": 80 / 12 - 10, "aov_change_rate": (80 / 12) / 10 - 1, "comparison_quality_status": "VERIFIED"},
        ]
    )


def _customers() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"previous_month": "2025-04", "current_month": "2025-05", "customer_key": "C1", "customer_name": "Customer 1", "previous_amount": 60.0, "current_amount": 50.0, "amount_change": -10.0, "period_status": "RETAINED"},
            {"previous_month": "2025-04", "current_month": "2025-05", "customer_key": "C2", "customer_name": "Customer 2", "previous_amount": 0.0, "current_amount": 30.0, "amount_change": 30.0, "period_status": "CURRENT_ONLY"},
            {"previous_month": "2025-04", "current_month": "2025-05", "customer_key": "C3", "customer_name": "Customer 3", "previous_amount": 40.0, "current_amount": 0.0, "amount_change": -40.0, "period_status": "PREVIOUS_ONLY"},
        ]
    )


def _products() -> pd.DataFrame:
    frame = _customers().rename(columns={"customer_key": "product_key", "customer_name": "product_name"})
    frame["period_status"] = frame["period_status"].map(
        {"RETAINED": "RETAINED_ACTIVE", "CURRENT_ONLY": "CURRENT_ONLY_ACTIVE", "PREVIOUS_ONLY": "PREVIOUS_ONLY_ACTIVE"}
    )
    frame["mapping_quality_status"] = ["CONFLICT", "VALID", "VALID"]
    return frame


def test_symmetric_decomposition_is_exact_and_aov_driven() -> None:
    monthly = _monthly()
    result = decompose_result(monthly.iloc[0], monthly.iloc[1])
    assert abs(result["decomposition_error"]) < 0.01
    assert result["driver_classification"] == "AOV_DRIVEN"
    assert result["order_effect"] > 0
    assert result["aov_effect"] < 0


def test_contribution_bridge_reconciles_to_result() -> None:
    result = build_contribution_summary(
        _customers(), ("RETAINED", "CURRENT_ONLY", "PREVIOUS_ONLY"), -20.0, 5
    )
    assert abs(result["reconciliation_error"]) < 0.01
    assert result["bridge"]["amount_change"].sum() == -20.0


def test_fact_generation_is_bounded_and_propagates_product_limitation() -> None:
    facts, diagnostics = build_diagnosis_facts(_monthly(), _customers(), _products(), RULES)
    core = facts[facts["is_core_fact"]]
    product = core[core["diagnosis_dimension"].eq("PRODUCT")]
    assert len(core) <= 5
    assert diagnostics["result"]["driver_classification"] == "AOV_DRIVEN"
    assert product["quality_flags"].str.contains("PRODUCT_MAPPING_LIMITATION").all()
    assert (product["evidence_level"] == "MEDIUM").all()
    assert {"FACT", "LIMITATION", "DO_NOT_INFER"}.issubset(set(facts["output_type"]))


def test_generated_text_does_not_cross_causal_boundary() -> None:
    facts, _ = build_diagnosis_facts(_monthly(), _customers(), _products(), RULES)
    core_text = " ".join(facts.loc[facts["is_core_fact"], "fact_text"])
    forbidden = ("财务收入下降", "客户永久流失", "涨价导致", "缺货导致", "退款导致")
    assert not any(term in core_text for term in forbidden)

