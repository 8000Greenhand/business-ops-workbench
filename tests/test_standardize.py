"""Tests for canonical DataFrame standardization."""

from datetime import date
from pathlib import Path

import pandas as pd

from ops_workbench.ingestion.file_loader import load_source
from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.models.canonical_schema import (
    CANONICAL_COLUMN_NAMES,
    INTEGER_FIELDS,
)
from ops_workbench.transforms.standardize import StandardizationResult, standardize

DIRTY_FIXTURE = Path(__file__).parent / "fixtures" / "m1c_dirty.csv"


def _dirty_result() -> StandardizationResult:
    loaded = load_source(DIRTY_FIXTURE)
    identity = {column: column for column in CANONICAL_COLUMN_NAMES}
    mapped = apply_mapping(loaded.dataframe, identity)
    return standardize(mapped, source_columns=loaded.metadata.source_columns)


def test_standardization_builds_complete_canonical_frame() -> None:
    """Missing canonical fields should be typed NULL columns in canonical order."""
    mapped = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025/01/02"],
            "channel": [" 渠道A ", ""],
            "leads": ["1,234", None],
        }
    )
    result = standardize(mapped, source_columns=("日期", "渠道", "资源数"))

    assert tuple(result.dataframe.columns) == CANONICAL_COLUMN_NAMES
    assert result.row_count == 2
    assert result.mapped_fields == ("date", "channel", "leads")
    assert "refund_amount" in result.unavailable_fields
    assert result.source_columns == ("日期", "渠道", "资源数")
    assert result.dataframe["refund_amount"].isna().all()
    assert not result.dataframe["refund_amount"].eq(0).any()
    assert result.dataframe.loc[0, "channel"] == "渠道A"
    assert pd.isna(result.dataframe.loc[1, "channel"])
    assert result.dataframe.loc[0, "leads"] == 1234
    assert pd.isna(result.dataframe.loc[1, "leads"])
    assert all(str(result.dataframe[field].dtype) == "Int64" for field in INTEGER_FIELDS)


def test_dates_and_dirty_numeric_values_are_normalized_with_issues() -> None:
    """Mixed dates and money text should parse while bad values remain visible."""
    result = _dirty_result()
    dataframe = result.dataframe

    assert dataframe.loc[0, "date"].date() == date(2025, 1, 1)
    assert dataframe.loc[1, "date"].date() == date(2025, 1, 2)
    assert pd.isna(dataframe.loc[2, "date"])
    assert dataframe.loc[0, "business_line"] == "业务线01"
    assert dataframe.loc[0, "region"] == "北区"
    assert pd.isna(dataframe.loc[1, "channel"])
    assert dataframe.loc[0, "gross_revenue"] == 1234.5
    assert pd.isna(dataframe.loc[1, "gross_revenue"])
    assert pd.isna(dataframe.loc[1, "leads"])
    assert pd.isna(dataframe.loc[1, "paid_users"])

    issue_keys = {(issue.code, issue.field) for issue in result.normalization_issues}
    assert ("invalid_date", "date") in issue_keys
    assert ("invalid_numeric", "gross_revenue") in issue_keys
    assert ("non_integer_count", "leads") in issue_keys


def test_excel_serial_and_timestamp_dates_are_supported() -> None:
    """Excel serial dates and pandas timestamps should normalize to dates."""
    result = standardize(
        pd.DataFrame({"date": [45_658, pd.Timestamp("2025-01-02 13:45:00")]})
    )
    assert result.dataframe.loc[0, "date"].date() == date(2025, 1, 1)
    assert result.dataframe.loc[1, "date"].date() == date(2025, 1, 2)
    assert not result.normalization_issues
