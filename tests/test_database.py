"""Tests for protected DuckDB fact-table replacement and round trip."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from ops_workbench.models.database import (
    QualityBlockedError,
    get_fact_row_count,
    get_fact_schema,
    read_fact_business_daily,
    replace_fact_business_daily,
)
from ops_workbench.transforms.standardize import StandardizationResult, standardize
from ops_workbench.validation.data_quality import build_quality_report


def _valid_standardized() -> StandardizationResult:
    return standardize(
        pd.DataFrame(
            {
                "date": ["2025-01-01", "2025/01/02"],
                "business_line": [" 业务线A ", "业务线B"],
                "product": ["产品A", "产品B"],
                "channel": ["渠道A", None],
                "region": ["北区", "南区"],
                "team": ["团队A", "团队B"],
                "salesperson": ["销售001", "销售002"],
                "impressions": [100, 80],
                "leads": [50, 40],
                "valid_leads": [40, 30],
                "contacted_leads": [35, 25],
                "followed_leads": [30, 20],
                "paid_users": [8, 5],
                "paid_orders": [9, 5],
                "gross_revenue": ["1,234.50", "800.10"],
                "refund_users": [1, 0],
                "refund_orders": [1, 0],
                "refund_amount": ["100.20", None],
            }
        )
    )


def test_duckdb_replace_schema_and_round_trip(tmp_path: Path) -> None:
    """Validated rows should replace a correctly typed canonical fact table."""
    database_path = tmp_path / "business_ops.duckdb"
    standardized = _valid_standardized()
    report = build_quality_report(standardized)

    assert report.is_valid
    assert replace_fact_business_daily(
        standardized,
        report,
        database_path=database_path,
    ) == 2
    assert database_path.is_file()
    assert get_fact_row_count(database_path=database_path) == 2

    schema = get_fact_schema(database_path=database_path)
    assert tuple(column.name for column in schema) == CANONICAL_COLUMN_NAMES
    types = {column.name: column.data_type for column in schema}
    assert types["date"] == "DATE"
    assert types["business_line"] == "VARCHAR"
    assert types["leads"] == "BIGINT"
    assert types["gross_revenue"] == "DECIMAL(18,2)"
    assert types["refund_amount"] == "DECIMAL(18,2)"

    restored = read_fact_business_daily(database_path=database_path)
    assert len(restored) == 2
    assert restored.loc[0, "date"] == date(2025, 1, 1)
    assert restored.loc[0, "business_line"] == "业务线A"
    assert pd.isna(restored.loc[1, "channel"])
    assert restored.loc[0, "gross_revenue"] == Decimal("1234.50")
    assert restored.loc[0, "refund_amount"] == Decimal("100.20")
    assert pd.isna(restored.loc[1, "refund_amount"])


def test_quality_errors_block_database_creation(tmp_path: Path) -> None:
    """A blocking report must stop before the database or table is written."""
    database_path = tmp_path / "blocked.duckdb"
    standardized = standardize(
        pd.DataFrame({"date": ["无效日期"], "gross_revenue": ["无效金额"]})
    )
    report = build_quality_report(standardized)
    with pytest.raises(QualityBlockedError):
        replace_fact_business_daily(
            standardized,
            report,
            database_path=database_path,
        )
    assert not database_path.exists()
