"""Tests for atomic dataset availability metadata persistence."""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import ops_workbench.models.database as database_module
from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from ops_workbench.models.database import (
    CURRENT_DATASET_ID,
    QualityBlockedError,
    get_dataset_metadata,
    get_fact_schema,
    get_field_availability,
    read_fact_business_daily,
    replace_fact_business_daily,
)
from ops_workbench.transforms.standardize import StandardizationResult, standardize
from ops_workbench.validation.data_quality import build_quality_report


def _standardize_source(
    source: pd.DataFrame,
    mapping: dict[str, str],
) -> StandardizationResult:
    mapped = apply_mapping(source, mapping)
    return standardize(
        mapped,
        source_columns=tuple(str(column) for column in source.columns),
        source_field_mapping=mapping,
    )


def _initial_partial_dataset() -> StandardizationResult:
    return _standardize_source(
        pd.DataFrame(
            {
                "日期": ["2025-01-01"],
                "项目": ["业务线A"],
                "资源数": [12],
                "流水": [None],
            }
        ),
        {
            "date": "日期",
            "business_line": "项目",
            "leads": "资源数",
            "gross_revenue": "流水",
        },
    )


def _replace(result: StandardizationResult, database_path: Path) -> None:
    report = build_quality_report(result)
    assert report.is_valid
    replace_fact_business_daily(result, report, database_path=database_path)


def test_partial_mapping_persists_complete_field_availability(tmp_path: Path) -> None:
    """Availability must distinguish mapped-all-NULL from completely unmapped."""
    database_path = tmp_path / "metadata.duckdb"
    result = _initial_partial_dataset()
    _replace(result, database_path)

    metadata = get_dataset_metadata(database_path=database_path)
    availability = get_field_availability(database_path=database_path)
    by_field = {item.canonical_field: item for item in availability}

    assert metadata.dataset_id == CURRENT_DATASET_ID
    assert metadata.row_count == 1
    assert len(availability) == len(CANONICAL_COLUMN_NAMES) == 18
    assert tuple(item.canonical_field for item in availability) == CANONICAL_COLUMN_NAMES
    assert by_field["date"].is_available
    assert by_field["date"].source_field == "日期"
    assert by_field["gross_revenue"].is_available
    assert by_field["gross_revenue"].source_field == "流水"
    assert result.dataframe["gross_revenue"].isna().all()
    assert not by_field["refund_amount"].is_available
    assert by_field["refund_amount"].source_field is None
    assert (
        tuple(column.name for column in get_fact_schema(database_path=database_path))
        == CANONICAL_COLUMN_NAMES
    )


def test_second_replace_updates_fact_and_metadata_together(tmp_path: Path) -> None:
    """A later replace should fully replace current metadata rather than append."""
    database_path = tmp_path / "second_replace.duckdb"
    _replace(_initial_partial_dataset(), database_path)
    initial_metadata = get_dataset_metadata(database_path=database_path)
    second = _standardize_source(
        pd.DataFrame(
            {
                "统计日期": ["2025-02-01", "2025-02-02"],
                "支付人数": [None, None],
            }
        ),
        {"date": "统计日期", "paid_users": "支付人数"},
    )
    _replace(second, database_path)

    metadata = get_dataset_metadata(database_path=database_path)
    by_field = {
        item.canonical_field: item
        for item in get_field_availability(database_path=database_path)
    }
    assert metadata.row_count == 2
    assert metadata.loaded_at > initial_metadata.loaded_at
    assert len(read_fact_business_daily(database_path=database_path)) == 2
    assert by_field["paid_users"].is_available
    assert by_field["paid_users"].source_field == "支付人数"
    assert not by_field["business_line"].is_available
    assert by_field["business_line"].source_field is None


def test_quality_error_preserves_existing_fact_and_metadata(tmp_path: Path) -> None:
    """Quality blocking must leave every current table unchanged."""
    database_path = tmp_path / "quality_gate.duckdb"
    _replace(_initial_partial_dataset(), database_path)
    original_fact = read_fact_business_daily(database_path=database_path)
    original_metadata = get_dataset_metadata(database_path=database_path)
    original_availability = get_field_availability(database_path=database_path)

    invalid = _standardize_source(
        pd.DataFrame({"日期": ["无效日期"], "退款": [10]}),
        {"date": "日期", "refund_amount": "退款"},
    )
    report = build_quality_report(invalid)
    assert not report.is_valid
    with pytest.raises(QualityBlockedError):
        replace_fact_business_daily(invalid, report, database_path=database_path)

    pd.testing.assert_frame_equal(
        read_fact_business_daily(database_path=database_path),
        original_fact,
    )
    assert get_dataset_metadata(database_path=database_path) == original_metadata
    assert get_field_availability(database_path=database_path) == original_availability


def test_transaction_failure_rolls_back_all_three_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after fact replacement must roll back fact and metadata changes."""
    database_path = tmp_path / "transaction.duckdb"
    _replace(_initial_partial_dataset(), database_path)
    original_fact = read_fact_business_daily(database_path=database_path)
    original_metadata = get_dataset_metadata(database_path=database_path)
    original_availability = get_field_availability(database_path=database_path)
    replacement = _standardize_source(
        pd.DataFrame({"日期": ["2025-03-01", "2025-03-02"]}),
        {"date": "日期"},
    )
    replacement_report = build_quality_report(replacement)
    assert replacement_report.is_valid

    def fail_after_fact(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated metadata write failure")

    monkeypatch.setattr(database_module, "_replace_dataset_metadata", fail_after_fact)
    with pytest.raises(RuntimeError, match="simulated metadata write failure"):
        replace_fact_business_daily(
            replacement,
            replacement_report,
            database_path=database_path,
        )

    pd.testing.assert_frame_equal(
        read_fact_business_daily(database_path=database_path),
        original_fact,
    )
    assert get_dataset_metadata(database_path=database_path) == original_metadata
    assert get_field_availability(database_path=database_path) == original_availability
