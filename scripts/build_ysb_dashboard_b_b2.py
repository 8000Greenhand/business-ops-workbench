"""Build Dashboard B B2 diagnosis facts from persisted B1 marts."""

from __future__ import annotations

import logging
from pathlib import Path

from ops_workbench.diagnostics.ysb_merchant_b2 import (
    build_diagnosis_facts,
    load_b1_marts,
    load_diagnosis_rules,
)

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Generate the bounded facts mart without reopening the source workbook."""
    mart_dir = ROOT / "data" / "marts" / "ysb"
    rules = load_diagnosis_rules(ROOT / "config" / "ysb_dashboard_b_diagnosis_rules.yaml")
    monthly, customers, products = load_b1_marts(mart_dir)
    facts, diagnostics = build_diagnosis_facts(monthly, customers, products, rules)
    output = mart_dir / "mart_merchant_diagnosis_facts.csv"
    facts.to_csv(output, index=False, encoding="utf-8-sig")
    LOGGER.info("wrote %s rows to %s", len(facts), output)
    LOGGER.info(
        "comparison=%s vs %s core_facts=%s customer_reconciliation_error=%.10f product_reconciliation_error=%.10f",
        diagnostics["previous_period"],
        diagnostics["current_period"],
        int(facts["is_core_fact"].sum()),
        diagnostics["customer"]["reconciliation_error"],
        diagnostics["product"]["reconciliation_error"],
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())

