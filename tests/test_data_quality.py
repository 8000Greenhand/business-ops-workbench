"""Tests for structured, aggregated M1C data-quality reports."""

from pathlib import Path

import pandas as pd

from ops_workbench.ingestion.file_loader import load_source
from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import (
    QualityConfig,
    build_quality_report,
    load_quality_config,
)
from ops_workbench.validation.quality_models import QualityReport, Severity

DIRTY_FIXTURE = Path(__file__).parent / "fixtures" / "m1c_dirty.csv"


def _dirty_report() -> QualityReport:
    loaded = load_source(DIRTY_FIXTURE)
    identity = {column: column for column in CANONICAL_COLUMN_NAMES}
    standardized = standardize(
        apply_mapping(loaded.dataframe, identity),
        source_columns=loaded.metadata.source_columns,
    )
    return build_quality_report(standardized)


def test_dirty_fixture_produces_required_errors_and_warnings() -> None:
    """Dirty values should be reported, not silently repaired or discarded."""
    report = _dirty_report()
    error_codes = {issue.code for issue in report.issues if issue.severity is Severity.ERROR}
    warning_codes = {
        issue.code for issue in report.issues if issue.severity is Severity.WARNING
    }

    assert not report.is_valid
    assert report.blocking_count == 4
    assert report.warning_count == 21
    assert error_codes == {
        "invalid_date",
        "invalid_numeric",
        "non_integer_count",
        "duplicate_canonical_grain",
    }
    assert {
        "mapped_field_nulls",
        "missing_ratio_exceeded",
        "negative_value",
        "impressions_gte_leads",
        "leads_gte_valid_leads",
        "contacted_leads_lte_valid_leads",
        "followed_leads_lte_valid_leads",
        "paid_users_lte_valid_leads",
        "refund_users_lte_paid_users",
        "refund_orders_lte_paid_orders",
        "refund_amount_lte_gross_revenue",
    } <= warning_codes
    assert {
        issue.field
        for issue in report.issues
        if issue.code == "negative_value"
    } == {"impressions", "gross_revenue", "refund_amount"}
    assert report.info_count == 0
    assert report.row_count == 4


def test_quality_configuration_loads_expected_controls() -> None:
    """The checked-in YAML should expose only the four M1C controls."""
    config = load_quality_config()
    assert config == QualityConfig(
        missing_warning_threshold=0.05,
        sample_rows_limit=10,
        duplicate_check_enabled=True,
        consistency_checks_enabled=True,
    )


def test_optional_unmapped_and_null_fields_warn_without_blocking() -> None:
    """Unavailable optional fields and mapped NULLs should remain warnings."""
    standardized = standardize(
        pd.DataFrame({"date": ["2025-01-01", "2025-01-02"], "channel": [None, "A"]})
    )
    report = build_quality_report(standardized)
    assert report.is_valid
    assert any(issue.code == "unmapped_optional_field" for issue in report.issues)
    assert any(
        issue.code == "mapped_field_nulls" and issue.field == "channel"
        for issue in report.issues
    )


def test_empty_data_is_blocking() -> None:
    """A zero-row canonical dataset should produce one empty-data ERROR."""
    report = build_quality_report(standardize(pd.DataFrame(columns=["date"])))
    assert not report.is_valid
    assert any(issue.code == "empty_data" for issue in report.issues)


def test_many_same_errors_create_one_bounded_issue() -> None:
    """Ten thousand bad values should remain one issue with bounded samples."""
    rows = 10_000
    dataframe = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=rows, freq="D"),
            "gross_revenue": ["无效金额"] * rows,
        }
    )
    standardized = standardize(dataframe, sample_rows_limit=3)
    report = build_quality_report(
        standardized,
        QualityConfig(sample_rows_limit=3),
    )
    matching = [
        issue
        for issue in report.issues
        if issue.code == "invalid_numeric" and issue.field == "gross_revenue"
    ]
    assert len(matching) == 1
    assert matching[0].affected_count == rows
    assert len(matching[0].affected_rows) == 3
