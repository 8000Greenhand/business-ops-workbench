"""Tests for the canonical daily business schema."""

from datetime import date
from decimal import Decimal

from ops_workbench.models.canonical_schema import (
    CANONICAL_COLUMN_NAMES,
    COLUMN_METADATA,
    FACT_BUSINESS_DAILY_SCHEMA,
)


def test_canonical_schema_order_and_types() -> None:
    """The canonical schema should expose stable order and reusable metadata."""
    assert CANONICAL_COLUMN_NAMES == tuple(
        column.name for column in FACT_BUSINESS_DAILY_SCHEMA
    )
    assert CANONICAL_COLUMN_NAMES[0] == "date"
    assert CANONICAL_COLUMN_NAMES[-1] == "refund_amount"
    assert COLUMN_METADATA["date"].python_type is date
    assert COLUMN_METADATA["date"].nullable is False
    assert COLUMN_METADATA["business_line"].nullable is True
    assert COLUMN_METADATA["leads"].python_type is int
    assert COLUMN_METADATA["gross_revenue"].python_type is Decimal
    assert all(
        COLUMN_METADATA[name].nullable
        for name in CANONICAL_COLUMN_NAMES[1:]
    )
