"""End-to-end M1C integration test using the full reproducible Demo size."""

from pathlib import Path

import pandas as pd

from ops_workbench.ingestion.file_loader import load_source
from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES, MONEY_FIELDS
from ops_workbench.models.database import (
    get_dataset_metadata,
    get_fact_row_count,
    get_field_availability,
    read_fact_business_daily,
    replace_fact_business_daily,
)
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report
from scripts.generate_demo_data import generate_demo_data


def test_full_demo_pipeline_round_trip(tmp_path: Path) -> None:
    """All 109,500 Demo rows should pass quality and round-trip through DuckDB."""
    demo = generate_demo_data(tmp_path / "demo", seed=42)
    loaded = load_source(demo.csv_path)
    identity = {column: column for column in CANONICAL_COLUMN_NAMES}
    standardized = standardize(
        apply_mapping(loaded.dataframe, identity),
        source_columns=loaded.metadata.source_columns,
        source_field_mapping=identity,
    )
    report = build_quality_report(standardized)
    database_path = tmp_path / "business_ops.duckdb"

    assert standardized.row_count == 109_500
    assert report.is_valid
    assert report.blocking_count == 0
    assert report.warning_count == 0
    assert replace_fact_business_daily(
        standardized,
        report,
        database_path=database_path,
    ) == 109_500
    assert get_fact_row_count(database_path=database_path) == 109_500
    assert get_dataset_metadata(database_path=database_path).row_count == 109_500
    availability = get_field_availability(database_path=database_path)
    assert len(availability) == 18
    assert all(item.is_available for item in availability)
    assert all(
        item.source_field == item.canonical_field for item in availability
    )

    restored = read_fact_business_daily(database_path=database_path)
    assert tuple(restored.columns) == CANONICAL_COLUMN_NAMES
    assert len(restored) == 109_500
    assert restored.groupby("salesperson")["team"].nunique().max() == 1
    assert restored.groupby("product")["business_line"].nunique().max() == 1
    for field in MONEY_FIELDS:
        pd.testing.assert_series_equal(
            restored[field].astype(float).reset_index(drop=True),
            standardized.dataframe[field].round(2).astype(float).reset_index(drop=True),
            check_names=False,
            atol=0.001,
            rtol=0,
        )
