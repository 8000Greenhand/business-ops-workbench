"""Tests for deterministic M1A demo data."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from scripts.generate_demo_data import (
    ANOMALY_CHANNEL,
    ANOMALY_PRODUCT,
    ANOMALY_TEAM,
    DEFAULT_START_DATE,
    DAYS,
    generate_demo_data,
)


@dataclass(slots=True)
class DemoAudit:
    """Compact audit facts collected in one pass over the generated CSV."""

    fieldnames: tuple[str, ...]
    rows: int
    dates: set[date]
    salesperson_teams: dict[str, set[str]]
    product_lines: dict[str, set[str]]
    constraints_hold: bool
    amounts_are_finite: bool
    channel_daily: dict[date, tuple[int, int]]
    team_daily: dict[date, tuple[int, int]]
    product_daily: dict[date, tuple[Decimal, Decimal]]


@pytest.fixture(scope="module")
def generated_demo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, object]]:
    """Generate one shared demo artifact for structural and anomaly tests."""
    output_dir = tmp_path_factory.mktemp("demo")
    result = generate_demo_data(output_dir, seed=42)
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    return result.csv_path, metadata


@pytest.fixture(scope="module")
def demo_audit(generated_demo: tuple[Path, dict[str, object]]) -> DemoAudit:
    """Read the generated CSV once and collect all required audit evidence."""
    csv_path, _ = generated_demo
    dates: set[date] = set()
    salesperson_teams: dict[str, set[str]] = defaultdict(set)
    product_lines: dict[str, set[str]] = defaultdict(set)
    channel_totals: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    team_totals: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    product_totals: dict[date, list[Decimal]] = defaultdict(
        lambda: [Decimal("0"), Decimal("0")]
    )
    constraints_hold = True
    amounts_are_finite = True
    row_count = 0

    with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = tuple(reader.fieldnames or ())
        for row in reader:
            row_count += 1
            row_date = date.fromisoformat(row["date"])
            dates.add(row_date)
            salesperson_teams[row["salesperson"]].add(row["team"])
            product_lines[row["product"]].add(row["business_line"])

            counts = {
                name: int(row[name])
                for name in (
                    "impressions",
                    "leads",
                    "valid_leads",
                    "contacted_leads",
                    "followed_leads",
                    "paid_users",
                    "paid_orders",
                    "refund_users",
                    "refund_orders",
                )
            }
            gross_revenue = Decimal(row["gross_revenue"])
            refund_amount = Decimal(row["refund_amount"])
            amounts_are_finite &= gross_revenue.is_finite() and refund_amount.is_finite()
            constraints_hold &= (
                counts["impressions"] >= counts["leads"] >= counts["valid_leads"]
                and counts["contacted_leads"] <= counts["valid_leads"]
                and counts["followed_leads"] <= counts["valid_leads"]
                and counts["paid_users"] <= counts["valid_leads"]
                and counts["paid_orders"] >= counts["paid_users"]
                and counts["refund_users"] <= counts["paid_users"]
                and counts["refund_orders"] <= counts["paid_orders"]
                and gross_revenue >= 0
                and refund_amount >= 0
                and refund_amount <= gross_revenue
                and (counts["paid_orders"] == 0) == (gross_revenue == 0)
                and (counts["refund_orders"] == 0) == (refund_amount == 0)
            )

            if row["channel"] == ANOMALY_CHANNEL:
                channel_totals[row_date][0] += counts["valid_leads"]
                channel_totals[row_date][1] += counts["leads"]
            if row["team"] == ANOMALY_TEAM:
                team_totals[row_date][0] += counts["paid_users"]
                team_totals[row_date][1] += counts["valid_leads"]
            if row["product"] == ANOMALY_PRODUCT:
                product_totals[row_date][0] += refund_amount
                product_totals[row_date][1] += gross_revenue

    return DemoAudit(
        fieldnames=fieldnames,
        rows=row_count,
        dates=dates,
        salesperson_teams=dict(salesperson_teams),
        product_lines=dict(product_lines),
        constraints_hold=constraints_hold,
        amounts_are_finite=amounts_are_finite,
        channel_daily={key: tuple(value) for key, value in channel_totals.items()},
        team_daily={key: tuple(value) for key, value in team_totals.items()},
        product_daily={key: tuple(value) for key, value in product_totals.items()},
    )


def _rate(numerator: int | Decimal, denominator: int | Decimal) -> float:
    return float(numerator / denominator)


def _same_weekday_baseline(
    daily_totals: dict[date, tuple[int | Decimal, int | Decimal]],
    anomaly_date: date,
) -> float:
    comparison_dates = [
        anomaly_date + timedelta(days=offset)
        for offset in (-28, -21, -14, -7, 7, 14, 21, 28)
    ]
    numerator = sum(daily_totals[item][0] for item in comparison_dates)
    denominator = sum(daily_totals[item][1] for item in comparison_dates)
    return _rate(numerator, denominator)


def test_demo_generation_and_metadata(
    generated_demo: tuple[Path, dict[str, object]], demo_audit: DemoAudit
) -> None:
    """The generator should produce the requested size and metadata."""
    csv_path, metadata = generated_demo
    assert csv_path.is_file()
    assert metadata["seed"] == 42
    assert metadata["rows"] == 109_500 == demo_audit.rows
    assert 100_000 <= demo_audit.rows <= 500_000
    assert metadata["business_lines"] == 5
    assert metadata["products"] == 20
    assert metadata["channels"] == 8
    assert metadata["regions"] >= 1
    assert metadata["teams"] == 6
    assert metadata["salespersons"] == 100
    assert len(metadata["injected_anomalies"]) == 3


def test_same_seed_is_reproducible(
    generated_demo: tuple[Path, dict[str, object]], tmp_path: Path
) -> None:
    """The same seed should produce byte-identical CSV and metadata files."""
    first_csv, first_metadata = generated_demo
    second = generate_demo_data(tmp_path, seed=42)
    first_hash = hashlib.sha256(first_csv.read_bytes()).digest()
    second_hash = hashlib.sha256(second.csv_path.read_bytes()).digest()
    assert first_hash == second_hash
    assert first_metadata == json.loads(second.metadata_path.read_text(encoding="utf-8"))


def test_schema_dates_and_stable_relationships(demo_audit: DemoAudit) -> None:
    """Rows should match the schema, cover 365 days, and retain stable mappings."""
    assert demo_audit.fieldnames == CANONICAL_COLUMN_NAMES
    assert len(demo_audit.dates) == DAYS
    assert min(demo_audit.dates) == DEFAULT_START_DATE
    assert max(demo_audit.dates) == DEFAULT_START_DATE + timedelta(days=DAYS - 1)
    assert all(len(teams) == 1 for teams in demo_audit.salesperson_teams.values())
    assert all(len(lines) == 1 for lines in demo_audit.product_lines.values())


def test_business_constraints_and_amounts(demo_audit: DemoAudit) -> None:
    """Generated counts and monetary values should satisfy basic business rules."""
    assert demo_audit.constraints_hold
    assert demo_audit.amounts_are_finite


def test_injected_anomalies_are_visible(demo_audit: DemoAudit) -> None:
    """All three fixed anomalies should be visible against same-weekday baselines."""
    day_200 = DEFAULT_START_DATE + timedelta(days=199)
    day_250 = DEFAULT_START_DATE + timedelta(days=249)
    day_300 = DEFAULT_START_DATE + timedelta(days=299)

    channel_rate = _rate(*demo_audit.channel_daily[day_200])
    channel_baseline = _same_weekday_baseline(demo_audit.channel_daily, day_200)
    channel_ratio = channel_rate / channel_baseline
    assert 0.70 <= channel_ratio <= 0.90

    team_rate = _rate(*demo_audit.team_daily[day_250])
    team_baseline = _same_weekday_baseline(demo_audit.team_daily, day_250)
    team_ratio = team_rate / team_baseline
    assert 0.55 <= team_ratio <= 0.85

    product_rate = _rate(*demo_audit.product_daily[day_300])
    product_baseline = _same_weekday_baseline(demo_audit.product_daily, day_300)
    assert product_rate >= 0.20
    assert product_rate >= product_baseline * 2.5
