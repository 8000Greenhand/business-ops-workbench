"""Build Dashboard B B1 staging and monthly diagnostic marts."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ops_workbench.diagnostics.ysb_merchant_b1 import (
    apply_order_policy,
    build_customer_contribution,
    build_monthly_diagnosis,
    build_product_contribution,
    build_quality_summary,
    latest_complete_pair,
    load_order_metric_policy,
    observed_status_distribution,
    read_order_items,
)

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Build persisted B1 outputs from the single merchant workbook."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "药师帮日报.xlsx")
    parser.add_argument("--policy", type=Path, default=ROOT / "config" / "ysb_dashboard_b_order_metric_policy.yaml")
    args = parser.parse_args()

    policy = load_order_metric_policy(args.policy)
    staged = apply_order_policy(read_order_items(args.source), policy)
    monthly = build_monthly_diagnosis(staged)
    previous, current = latest_complete_pair(monthly)
    customers = build_customer_contribution(staged, previous, current)
    products = build_product_contribution(staged, previous, current)
    quality = build_quality_summary(staged)
    statuses = observed_status_distribution(staged)

    staging_dir = ROOT / "data" / "staging" / "ysb"
    mart_dir = ROOT / "data" / "marts" / "ysb"
    staging_dir.mkdir(parents=True, exist_ok=True)
    mart_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        staging_dir / "stg_merchant_order_items.csv": staged,
        mart_dir / "mart_merchant_monthly_diagnosis.csv": monthly,
        mart_dir / "mart_customer_monthly_contribution.csv": customers,
        mart_dir / "mart_product_monthly_contribution.csv": products,
        mart_dir / "mart_merchant_data_quality.csv": quality,
        mart_dir / "order_status_distribution.csv": statuses,
    }
    for path, frame in outputs.items():
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        LOGGER.info("wrote %s rows to %s", len(frame), path)
    LOGGER.info("comparison period: %s vs %s", previous, current)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())

