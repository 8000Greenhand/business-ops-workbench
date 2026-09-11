"""Tests for the standard-library Decimal z-score anomaly method."""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ops_workbench.alerts.rules import AnomalyRuleRegistry
from ops_workbench.alerts.severity import BusinessSeverity
from ops_workbench.diagnostics import AnomalyEngine
from ops_workbench.metrics import MetricEngine
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report


def _scanner(
    tmp_path: Path,
    values: list[int | None],
    *,
    min_history_days: int = 28,
) -> AnomalyEngine:
    dates = [date(2025, 1, 1) + timedelta(days=offset) for offset in range(len(values))]
    standardized = standardize(pd.DataFrame({"date": dates, "leads": values}))
    report = build_quality_report(standardized)
    assert report.is_valid
    database_path = tmp_path / "zscore.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    metric_engine = MetricEngine(database_path=database_path)
    config_path = tmp_path / "alerts.yaml"
    config_path.write_text(
        f"""rules:
  - id: leads_zscore
    name: Leads z-score
    metric_id: leads
    dimension: null
    method: zscore
    direction: increase
    thresholds:
      warning:
        z_score: 2
      critical:
        z_score: 5
    history_window_days: 28
    min_history_days: {min_history_days}
""",
        encoding="utf-8",
    )
    registry = AnomalyRuleRegistry.from_yaml(
        config_path,
        metric_registry=metric_engine.registry,
    )
    return AnomalyEngine(metric_engine, rule_registry=registry)


def test_normal_zscore_value_does_not_alert(tmp_path: Path) -> None:
    history = [99 if index % 2 == 0 else 101 for index in range(28)]
    result = _scanner(tmp_path, history + [100]).scan_date("2025-01-29")
    assert not result.events


def test_extreme_zscore_value_alerts_without_scipy(tmp_path: Path) -> None:
    history = [99 if index % 2 == 0 else 101 for index in range(28)]
    result = _scanner(tmp_path, history + [110]).scan_date("2025-01-29")
    event = result.events[0]
    assert event.severity == BusinessSeverity.CRITICAL
    assert event.z_score is not None and event.z_score >= 5
    assert "z-score" in event.evidence


def test_zero_standard_deviation_does_not_produce_infinity(tmp_path: Path) -> None:
    result = _scanner(tmp_path, [100] * 28 + [150]).scan_date("2025-01-29")
    assert not result.events
    assert result.skipped_no_data_count == 1


def test_insufficient_history_does_not_alert(tmp_path: Path) -> None:
    result = _scanner(tmp_path, [100] * 9 + [150]).scan_date("2025-01-10")
    assert not result.events
    assert result.skipped_no_data_count == 1


def test_null_history_day_is_ignored_not_treated_as_zero(tmp_path: Path) -> None:
    history: list[int | None] = [99 if index % 2 == 0 else 101 for index in range(27)]
    history.insert(10, None)
    result = _scanner(
        tmp_path,
        history + [110],
        min_history_days=27,
    ).scan_date("2025-01-29")
    assert result.critical_count == 1
    assert result.events[0].z_score is not None
