"""Generate deterministic daily business demo data for M1A."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Sequence

from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from ops_workbench.utils.logging import configure_logging, get_logger

LOGGER = get_logger(__name__)

DEFAULT_SEED = 42
DEFAULT_START_DATE = date(2025, 1, 1)
DAYS = 365
ROUTES_PER_SALESPERSON = 3

BUSINESS_LINES = tuple(f"业务线{i:02d}" for i in range(1, 6))
PRODUCTS = tuple(f"产品{i:02d}" for i in range(1, 21))
CHANNELS = tuple(f"渠道{i:02d}" for i in range(1, 9))
REGIONS = ("北区", "南区", "西区")
TEAMS = tuple(f"团队{i:02d}" for i in range(1, 7))
SALESPERSONS = tuple(f"销售{i:03d}" for i in range(1, 101))

ANOMALY_CHANNEL = CHANNELS[2]
ANOMALY_TEAM = TEAMS[3]
ANOMALY_PRODUCT = PRODUCTS[11]

BUSINESS_LINE_SCALE = (0.72, 0.88, 1.00, 1.16, 1.34)
CHANNEL_LEAD_SCALE = (1.14, 0.92, 1.06, 0.82, 1.20, 0.96, 0.88, 1.10)
CHANNEL_QUALITY_SCALE = (0.80, 0.88, 0.95, 1.02, 1.08, 1.15, 0.91, 1.20)
TEAM_SKILL_SCALE = (0.84, 0.91, 0.97, 1.03, 1.10, 1.17)
WEEKDAY_SCALE = (1.05, 1.03, 1.01, 1.00, 0.98, 0.86, 0.78)

PRODUCT_TO_BUSINESS_LINE = {
    product: BUSINESS_LINES[index // 4] for index, product in enumerate(PRODUCTS)
}
SALESPERSON_TO_TEAM = {
    salesperson: TEAMS[index % len(TEAMS)]
    for index, salesperson in enumerate(SALESPERSONS)
}
SALESPERSON_TO_REGION = {
    salesperson: REGIONS[(index % len(TEAMS)) % len(REGIONS)]
    for index, salesperson in enumerate(SALESPERSONS)
}


@dataclass(frozen=True, slots=True)
class DemoGenerationResult:
    """Paths and metadata produced by one demo generation run."""

    csv_path: Path
    metadata_path: Path
    metadata: dict[str, object]


def _round_money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _bounded_rate(value: float) -> float:
    return min(0.98, max(0.0, value))


def _sample_count(rng: random.Random, total: int, probability: float) -> int:
    """Sample a bounded count using a fast normal approximation to a binomial."""
    if total <= 0 or probability <= 0:
        return 0
    probability = _bounded_rate(probability)
    expected = total * probability
    standard_deviation = math.sqrt(total * probability * (1.0 - probability))
    sampled = round(rng.gauss(expected, standard_deviation))
    return min(total, max(0, sampled))


def _salesperson_routes(salesperson_index: int) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            PRODUCTS[(salesperson_index * 3 + route_index * 7) % len(PRODUCTS)],
            CHANNELS[(salesperson_index + route_index * 3) % len(CHANNELS)],
        )
        for route_index in range(ROUTES_PER_SALESPERSON)
    )


def _build_row(
    rng: random.Random,
    day_number: int,
    business_date: date,
    salesperson_index: int,
    product: str,
    channel: str,
) -> dict[str, object]:
    team = SALESPERSON_TO_TEAM[SALESPERSONS[salesperson_index]]
    region = SALESPERSON_TO_REGION[SALESPERSONS[salesperson_index]]
    business_line = PRODUCT_TO_BUSINESS_LINE[product]

    line_index = BUSINESS_LINES.index(business_line)
    product_index = PRODUCTS.index(product)
    channel_index = CHANNELS.index(channel)
    team_index = TEAMS.index(team)

    annual_seasonality = 1.0 + 0.08 * math.sin(2.0 * math.pi * day_number / DAYS)
    salesperson_scale = 0.90 + (salesperson_index % 11) * 0.02
    impression_mean = (
        260.0
        * BUSINESS_LINE_SCALE[line_index]
        * WEEKDAY_SCALE[business_date.weekday()]
        * annual_seasonality
        * salesperson_scale
    )
    impressions = max(20, round(rng.gauss(impression_mean, impression_mean * 0.10)))

    lead_rate = 0.078 * CHANNEL_LEAD_SCALE[channel_index]
    leads = _sample_count(rng, impressions, lead_rate)

    valid_lead_rate = 0.68 * CHANNEL_QUALITY_SCALE[channel_index]
    if day_number == 200 and channel == ANOMALY_CHANNEL:
        valid_lead_rate *= 0.80
    valid_leads = _sample_count(rng, leads, valid_lead_rate)

    contacted_leads = _sample_count(rng, valid_leads, 0.84)
    followed_leads = _sample_count(rng, valid_leads, 0.73)

    product_conversion_scale = 0.82 + (product_index % 5) * 0.09
    conversion_rate = 0.18 * product_conversion_scale * TEAM_SKILL_SCALE[team_index]
    if day_number == 250 and team == ANOMALY_TEAM:
        conversion_rate *= 0.70
    paid_users = _sample_count(rng, valid_leads, conversion_rate)
    paid_orders = paid_users + _sample_count(rng, paid_users, 0.14)

    base_order_value = 520.0 + product_index * 42.0
    if paid_orders:
        order_value = base_order_value * rng.lognormvariate(0.0, 0.12)
        gross_revenue = _round_money(paid_orders * order_value)
    else:
        gross_revenue = Decimal("0.00")

    refund_users = _sample_count(rng, paid_users, 0.035)
    remaining_orders = paid_orders - refund_users
    refund_orders = refund_users + _sample_count(rng, remaining_orders, 0.015)

    if refund_orders and paid_orders:
        refund_share = refund_orders / paid_orders
        refund_amount = _round_money(
            float(gross_revenue) * refund_share * rng.uniform(0.55, 0.95)
        )
    else:
        refund_amount = Decimal("0.00")

    if day_number == 300 and product == ANOMALY_PRODUCT and paid_orders:
        refund_orders = min(paid_orders, max(refund_orders, round(paid_orders * 0.25), 1))
        if paid_users:
            refund_users = min(paid_users, max(refund_users, round(paid_users * 0.18), 1))
        refund_amount = max(
            refund_amount,
            _round_money(float(gross_revenue) * rng.uniform(0.22, 0.30)),
        )

    return {
        "date": business_date.isoformat(),
        "business_line": business_line,
        "product": product,
        "channel": channel,
        "region": region,
        "team": team,
        "salesperson": SALESPERSONS[salesperson_index],
        "impressions": impressions,
        "leads": leads,
        "valid_leads": valid_leads,
        "contacted_leads": contacted_leads,
        "followed_leads": followed_leads,
        "paid_users": paid_users,
        "paid_orders": paid_orders,
        "gross_revenue": format(gross_revenue, "f"),
        "refund_users": refund_users,
        "refund_orders": refund_orders,
        "refund_amount": format(refund_amount, "f"),
    }


def _build_metadata(seed: int, start_date: date, rows: int) -> dict[str, object]:
    end_date = start_date + timedelta(days=DAYS - 1)
    anomalies = [
        {
            "day": 200,
            "date": (start_date + timedelta(days=199)).isoformat(),
            "dimension": "channel",
            "value": ANOMALY_CHANNEL,
            "metric": "valid_lead_rate",
            "effect": "normal_rate_multiplier",
            "multiplier": 0.80,
        },
        {
            "day": 250,
            "date": (start_date + timedelta(days=249)).isoformat(),
            "dimension": "team",
            "value": ANOMALY_TEAM,
            "metric": "conversion_rate",
            "effect": "normal_rate_multiplier",
            "multiplier": 0.70,
        },
        {
            "day": 300,
            "date": (start_date + timedelta(days=299)).isoformat(),
            "dimension": "product",
            "value": ANOMALY_PRODUCT,
            "metric": "refund_rate_amount",
            "effect": "rate_forced_to_range",
            "range": [0.22, 0.30],
        },
    ]
    return {
        "seed": seed,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "rows": rows,
        "business_lines": len(BUSINESS_LINES),
        "products": len(PRODUCTS),
        "channels": len(CHANNELS),
        "regions": len(REGIONS),
        "teams": len(TEAMS),
        "salespersons": len(SALESPERSONS),
        "routes_per_salesperson_per_day": ROUTES_PER_SALESPERSON,
        "injected_anomalies": anomalies,
    }


def generate_demo_data(
    output_dir: Path,
    seed: int = DEFAULT_SEED,
    start_date: date = DEFAULT_START_DATE,
) -> DemoGenerationResult:
    """Generate canonical demo CSV and its audit metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "business_daily_demo.csv"
    metadata_path = output_dir / "demo_metadata.json"
    rng = random.Random(seed)
    row_count = 0

    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CANONICAL_COLUMN_NAMES)
        writer.writeheader()
        for day_offset in range(DAYS):
            business_date = start_date + timedelta(days=day_offset)
            day_number = day_offset + 1
            for salesperson_index in range(len(SALESPERSONS)):
                for product, channel in _salesperson_routes(salesperson_index):
                    writer.writerow(
                        _build_row(
                            rng,
                            day_number,
                            business_date,
                            salesperson_index,
                            product,
                            channel,
                        )
                    )
                    row_count += 1

    metadata = _build_metadata(seed, start_date, row_count)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return DemoGenerationResult(csv_path, metadata_path, metadata)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "demo",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the demo generator from the command line."""
    args = _parse_args(argv)
    configure_logging()
    result = generate_demo_data(args.output_dir, seed=args.seed)
    LOGGER.info(
        "Generated %s rows in %s; metadata: %s",
        result.metadata["rows"],
        result.csv_path,
        result.metadata_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
