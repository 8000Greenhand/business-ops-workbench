"""Tests for business anomaly thresholds, availability, dimensions, and events."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

import ops_workbench.diagnostics.anomaly as anomaly_module
from ops_workbench.alerts.rules import AnomalyRuleRegistry
from ops_workbench.alerts.severity import BusinessSeverity
from ops_workbench.diagnostics import AnomalyEngine
from ops_workbench.metrics import MetricEngine, MetricStatus
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report


def _metric_engine(tmp_path: Path, dataframe: pd.DataFrame) -> MetricEngine:
    standardized = standardize(dataframe)
    report = build_quality_report(standardized)
    assert report.is_valid
    database_path = tmp_path / "anomaly.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    return MetricEngine(database_path=database_path)


def _rule_registry(tmp_path: Path, engine: MetricEngine, body: str) -> AnomalyRuleRegistry:
    path = tmp_path / "alerts.yaml"
    path.write_text(body, encoding="utf-8")
    return AnomalyRuleRegistry.from_yaml(path, metric_registry=engine.registry)


def _comparison_rule(
    *,
    metric_id: str = "leads",
    dimension: str | None = None,
    direction: str = "decrease",
    measure: str = "relative_change",
    warning: str = "-0.10",
    critical: str | None = "-0.30",
    comparison: str = "rolling_7d_average",
    extra: str = "",
) -> str:
    dimension_value = "null" if dimension is None else dimension
    critical_yaml = (
        "" if critical is None else f"      critical:\n        {measure}: {critical}\n"
    )
    return f"""rules:
  - id: test_rule
    name: Test rule
    metric_id: {metric_id}
    dimension: {dimension_value}
    method: comparison
    comparison: {comparison}
    direction: {direction}
    thresholds:
      warning:
        {measure}: {warning}
{critical_yaml}{extra}"""


def _daily_frame(current_leads: int) -> pd.DataFrame:
    dates = [date(2025, 1, 1) + timedelta(days=offset) for offset in range(8)]
    return pd.DataFrame(
        {
            "date": dates,
            "leads": [100] * 7 + [current_leads],
            "valid_leads": [80] * 7 + [50],
            "paid_users": [20] * 7 + [10],
            "gross_revenue": ["1000.00"] * 7 + ["800.00"],
        }
    )


def _scanner(tmp_path: Path, dataframe: pd.DataFrame, rule_yaml: str) -> AnomalyEngine:
    engine = _metric_engine(tmp_path, dataframe)
    registry = _rule_registry(tmp_path, engine, rule_yaml)
    return AnomalyEngine(engine, rule_registry=registry)


def test_relative_decrease_warning_and_event_fields(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path, _daily_frame(80), _comparison_rule())
    result = scanner.scan_date("2025-01-08")

    assert result.rules_evaluated == result.groups_evaluated == 1
    assert result.warning_count == 1
    event = result.events[0]
    assert event.severity == BusinessSeverity.WARNING
    assert event.current_value == 80
    assert event.baseline_value == Decimal(100)
    assert event.delta == Decimal(-20)
    assert event.relative_change == Decimal("-0.2")
    assert event.percentage_point_change is None
    assert event.current_status == event.baseline_status == MetricStatus.AVAILABLE
    assert event.evidence
    assert "导致" not in event.evidence


def test_relative_decrease_critical(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path, _daily_frame(60), _comparison_rule())
    result = scanner.scan_date("2025-01-08")
    assert result.critical_count == 1
    assert result.events[0].severity == BusinessSeverity.CRITICAL


def test_increase_and_direction_mismatch(tmp_path: Path) -> None:
    increase_rule = _comparison_rule(
        direction="increase", warning="0.20", critical="0.40"
    )
    increase = _scanner(tmp_path, _daily_frame(130), increase_rule)
    assert increase.scan_date("2025-01-08").warning_count == 1

    mismatch_path = tmp_path / "mismatch"
    mismatch_path.mkdir()
    decrease = _scanner(mismatch_path, _daily_frame(130), _comparison_rule())
    assert not decrease.scan_date("2025-01-08").events


def test_both_direction_uses_configured_magnitude(tmp_path: Path) -> None:
    rule = _comparison_rule(
        direction="both",
        warning="0.10",
        critical="0.30",
    )
    scanner = _scanner(tmp_path, _daily_frame(80), rule)
    assert scanner.scan_date("2025-01-08").warning_count == 1


def test_info_threshold_and_count(tmp_path: Path) -> None:
    rule = """rules:
  - id: info_rule
    name: Info rule
    metric_id: leads
    dimension: null
    method: comparison
    comparison: rolling_7d_average
    direction: decrease
    thresholds:
      info:
        relative_change: -0.03
      warning:
        relative_change: -0.10
"""
    scanner = _scanner(tmp_path, _daily_frame(95), rule)
    result = scanner.scan_date("2025-01-08")
    assert result.info_count == 1
    assert result.events[0].severity == BusinessSeverity.INFO


def test_percentage_point_threshold_is_distinct(tmp_path: Path) -> None:
    rule = _comparison_rule(
        metric_id="valid_lead_rate",
        measure="percentage_point_change",
        warning="-0.10",
        critical="-0.40",
    )
    scanner = _scanner(tmp_path, _daily_frame(100), rule)
    event = scanner.scan_date("2025-01-08").events[0]

    assert event.severity == BusinessSeverity.WARNING
    assert event.current_value == Decimal("0.5")
    assert event.baseline_value == Decimal("0.8")
    assert event.percentage_point_change == Decimal("-0.3")
    assert event.relative_change == Decimal("-0.375")


@pytest.mark.parametrize(
    ("dimension", "normal_value", "changed_value"),
    [
        ("channel", "渠道B", "渠道A"),
        ("team", "团队B", "团队A"),
        ("product", "产品B", "产品A"),
    ],
)
def test_dimension_scans_find_the_changed_member(
    tmp_path: Path,
    dimension: str,
    normal_value: str,
    changed_value: str,
) -> None:
    rows: list[dict[str, object]] = []
    for offset in range(8):
        current_date = date(2025, 1, 1) + timedelta(days=offset)
        rows.extend(
            [
                {"date": current_date, dimension: changed_value, "leads": 50 if offset == 7 else 100},
                {"date": current_date, dimension: normal_value, "leads": 100},
            ]
        )
    scanner = _scanner(
        tmp_path,
        pd.DataFrame(rows),
        _comparison_rule(dimension=dimension),
    )
    result = scanner.scan_date("2025-01-08")

    assert result.groups_evaluated == 2
    assert len(result.events) == 1
    assert result.events[0].dimension == dimension
    assert result.events[0].dimension_value == changed_value


def test_overall_rule_and_previous_week(tmp_path: Path) -> None:
    scanner = _scanner(
        tmp_path,
        _daily_frame(80),
        _comparison_rule(comparison="previous_week"),
    )
    event = scanner.scan_date("2025-01-08").events[0]
    assert event.dimension is None
    assert event.dimension_value is None
    assert event.comparison_type == "previous_week"


def test_filter_coexists_with_rule_dimension(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    for offset in range(8):
        current_date = date(2025, 1, 1) + timedelta(days=offset)
        rows.extend(
            [
                {
                    "date": current_date,
                    "channel": "渠道A",
                    "team": "团队东",
                    "leads": 50 if offset == 7 else 100,
                },
                {
                    "date": current_date,
                    "channel": "渠道B",
                    "team": "团队西",
                    "leads": 50 if offset == 7 else 100,
                },
            ]
        )
    scanner = _scanner(
        tmp_path,
        pd.DataFrame(rows),
        _comparison_rule(dimension="channel"),
    )
    result = scanner.scan_date("2025-01-08", filters={"team": "团队东"})
    assert result.groups_evaluated == 1
    assert [event.dimension_value for event in result.events] == ["渠道A"]


def test_current_missing_field_and_baseline_no_data_are_skipped(tmp_path: Path) -> None:
    missing_rule = _comparison_rule(metric_id="refund_amount")
    missing = _scanner(tmp_path, _daily_frame(80), missing_rule)
    missing_result = missing.scan_date("2025-01-08")
    assert not missing_result.events
    assert missing_result.skipped_no_data_count == 1

    baseline_path = tmp_path / "baseline"
    baseline_path.mkdir()
    baseline = _scanner(
        baseline_path,
        _daily_frame(80),
        _comparison_rule(),
    )
    baseline_result = baseline.scan_date("2025-01-01")
    assert not baseline_result.events
    assert baseline_result.skipped_no_data_count == 1


def test_zero_denominator_is_skipped(tmp_path: Path) -> None:
    dataframe = _daily_frame(0)
    dataframe.loc[7, "valid_leads"] = 0
    scanner = _scanner(
        tmp_path,
        dataframe,
        _comparison_rule(metric_id="valid_lead_rate"),
    )
    result = scanner.scan_date("2025-01-08")
    assert not result.events
    assert result.skipped_no_data_count == 1


def test_low_denominator_is_counted_separately(tmp_path: Path) -> None:
    dataframe = _daily_frame(100)
    dataframe.loc[7, "valid_leads"] = 2
    dataframe.loc[7, "paid_users"] = 0
    rule = _comparison_rule(
        metric_id="conversion_rate",
        extra="    min_denominator: 100\n",
    )
    scanner = _scanner(tmp_path, dataframe, rule)
    result = scanner.scan_date("2025-01-08")
    assert not result.events
    assert result.skipped_low_volume_count == 1
    assert result.skipped_no_data_count == 0


def test_minimum_baseline_value_protects_small_scale(tmp_path: Path) -> None:
    rule = _comparison_rule(extra="    min_baseline_value: 1000\n")
    scanner = _scanner(tmp_path, _daily_frame(80), rule)
    result = scanner.scan_date("2025-01-08")
    assert not result.events
    assert result.skipped_low_volume_count == 1


def test_consecutive_days_gate(tmp_path: Path) -> None:
    dates = [date(2025, 1, 1) + timedelta(days=offset) for offset in range(10)]
    dataframe = pd.DataFrame({"date": dates, "leads": [100] * 7 + [80, 80, 80]})
    rule = _comparison_rule(
        comparison="previous_week",
        extra="    consecutive_days: 3\n",
    )
    scanner = _scanner(tmp_path, dataframe, rule)

    assert not scanner.scan_date("2025-01-09").events
    result = scanner.scan_date("2025-01-10")
    assert len(result.events) == 1
    assert result.events[0].date == date(2025, 1, 10)


def test_dimension_range_scan_uses_one_series_query_per_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "date": date(2025, 1, 1) + timedelta(days=offset),
            "channel": channel,
            "leads": 50 if offset == 7 and channel == "渠道A" else 100,
        }
        for offset in range(8)
        for channel in ("渠道A", "渠道B")
    ]
    scanner = _scanner(
        tmp_path,
        pd.DataFrame(rows),
        _comparison_rule(dimension="channel"),
    )
    original = anomaly_module.get_metric_series_by_dimension
    call_count = 0

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(anomaly_module, "get_metric_series_by_dimension", counted)
    scanner.scan_range("2025-01-01", "2025-01-08")
    assert call_count == 1
