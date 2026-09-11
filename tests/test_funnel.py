"""Tests for configured funnel loading and calculation."""

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.metrics import MetricEngine, MetricStatus
from ops_workbench.metrics.funnel import (
    DEFAULT_FUNNELS_PATH,
    FunnelRegistry,
    calculate_funnel,
)
from ops_workbench.metrics.registry import DuplicateKeyError
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report


def _engine(tmp_path: Path, *, include_impressions: bool = True) -> MetricEngine:
    data: dict[str, list[object]] = {
        "date": ["2025-01-01", "2025-01-02"],
        "channel": ["渠道A", "渠道B"],
        "leads": [4, 100],
        "valid_leads": [2, 90],
        "contacted_leads": [1, 81],
        "followed_leads": [1, 70],
        "paid_users": [1, 9],
        "gross_revenue": ["100.00", "900.00"],
        "refund_amount": ["10.00", "90.00"],
    }
    if include_impressions:
        data["impressions"] = [8, 200]
    standardized = standardize(pd.DataFrame(data))
    report = build_quality_report(standardized)
    assert report.is_valid
    database_path = tmp_path / f"funnel-{include_impressions}.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    return MetricEngine(database_path=database_path)


def test_default_funnel_config_loads() -> None:
    definition = FunnelRegistry.from_yaml(DEFAULT_FUNNELS_PATH).get("business_funnel")
    assert definition.stages == (
        "impressions",
        "leads",
        "valid_leads",
        "contacted_leads",
        "followed_leads",
        "paid_users",
    )
    assert len(definition.step_rates) == 4
    assert definition.outcomes == ("gross_revenue", "refund_amount", "net_revenue")


def test_funnel_stage_step_and_outcome_values(tmp_path: Path) -> None:
    result = calculate_funnel(_engine(tmp_path))
    stages = {item.metric_id: item for item in result.stages}
    outcomes = {item.metric_id: item for item in result.outcomes}
    steps = {(item.from_stage, item.to_stage): item for item in result.step_rates}

    assert stages["impressions"].value == 208
    assert stages["paid_users"].value == 10
    assert steps[("impressions", "leads")].value == Decimal(104) / Decimal(208)
    assert steps[("valid_leads", "paid_users")].value == Decimal(10) / Decimal(92)
    assert outcomes["gross_revenue"].value == Decimal("1000.00")
    assert outcomes["refund_amount"].value == Decimal("100.00")
    assert outcomes["net_revenue"].value == Decimal("900.00")


def test_missing_stage_only_affects_related_step(tmp_path: Path) -> None:
    result = calculate_funnel(_engine(tmp_path, include_impressions=False))
    stages = {item.metric_id: item for item in result.stages}
    steps = {(item.from_stage, item.to_stage): item for item in result.step_rates}

    assert stages["impressions"].status == MetricStatus.UNAVAILABLE_MISSING_FIELD
    assert stages["leads"].status == MetricStatus.AVAILABLE
    assert steps[("impressions", "leads")].status == MetricStatus.UNAVAILABLE_MISSING_FIELD
    assert steps[("leads", "valid_leads")].status == MetricStatus.AVAILABLE


def test_funnel_reuses_engine_filters_and_date_range(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    channel = calculate_funnel(engine, filters={"channel": "渠道A"})
    date_range = calculate_funnel(
        engine, start_date="2025-01-02", end_date="2025-01-02"
    )
    assert {item.metric_id: item.value for item in channel.stages}["leads"] == 4
    assert {item.metric_id: item.value for item in date_range.stages}["leads"] == 100


def test_unknown_metric_in_funnel_config_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "funnels.yaml"
    path.write_text(
        """funnels:
  broken:
    name: Broken
    stages: [unknown_metric]
    step_rates: []
    outcomes: [gross_revenue]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown metric"):
        FunnelRegistry.from_yaml(path)


def test_duplicate_funnel_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "funnels.yaml"
    path.write_text(
        """funnels:
  duplicate:
    name: First
    stages: [leads]
    step_rates: []
    outcomes: [gross_revenue]
  duplicate:
    name: Second
    stages: [leads]
    step_rates: []
    outcomes: [gross_revenue]
""",
        encoding="utf-8",
    )
    with pytest.raises(DuplicateKeyError):
        FunnelRegistry.from_yaml(path)


def test_funnel_config_rejects_arbitrary_formula(tmp_path: Path) -> None:
    path = tmp_path / "funnels.yaml"
    path.write_text(
        """funnels:
  unsafe:
    name: Unsafe
    stages: [leads]
    step_rates:
      - numerator: leads
        denominator: impressions
        formula: __import__('os').system('echo unsafe')
    outcomes: [gross_revenue]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="allow only numerator and denominator"):
        FunnelRegistry.from_yaml(path)


def test_funnel_filter_values_remain_parameterized(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    result = calculate_funnel(
        engine,
        filters={"channel": "渠道A' OR 1=1 --"},
    )
    assert all(item.status == MetricStatus.UNAVAILABLE_NO_DATA for item in result.stages)
