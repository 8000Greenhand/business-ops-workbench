"""Small shared helpers for the Streamlit workbench shell."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import duckdb
import streamlit as st

from ops_workbench.metrics.engine import MetricGroupResult, MetricResult
from ops_workbench.models.database import (
    DEFAULT_DATABASE_PATH,
    DatasetMetadata,
    FieldAvailability,
    get_dataset_metadata,
    get_field_availability,
)

APP_TITLE = "Business Ops Workbench"


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    """Persisted dataset state used by presentation pages."""

    metadata: DatasetMetadata
    availability: tuple[FieldAvailability, ...]
    quality_status: str = "Validated"


def configure_page(title: str) -> None:
    """Apply consistent restrained page metadata and heading."""
    st.set_page_config(page_title=f"{title} | {APP_TITLE}", page_icon="📊")
    st.title(title)
    st.caption(APP_TITLE)


def load_dataset_snapshot(
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> DatasetSnapshot | None:
    """Return current metadata, or None when no readable dataset exists."""
    path = Path(database_path)
    if not path.is_file():
        return None
    try:
        metadata = get_dataset_metadata(database_path=path)
        availability = get_field_availability(database_path=path)
    except (duckdb.Error, LookupError, OSError):
        return None
    return DatasetSnapshot(metadata, availability)


def require_dataset() -> DatasetSnapshot | None:
    """Render the standard empty state and return the current snapshot."""
    snapshot = load_dataset_snapshot()
    if snapshot is None:
        st.info("No dataset loaded")
    return snapshot


def dataset_metadata_rows(snapshot: DatasetSnapshot) -> list[dict[str, object]]:
    """Serialize dataset metadata for a plain Streamlit table."""
    return [
        {
            "dataset_id": snapshot.metadata.dataset_id,
            "loaded_at": snapshot.metadata.loaded_at,
            "row_count": snapshot.metadata.row_count,
            "quality_status": snapshot.quality_status,
        }
    ]


def field_availability_rows(
    snapshot: DatasetSnapshot,
) -> list[dict[str, object]]:
    """Serialize canonical field availability for presentation."""
    return [
        {
            "canonical_field": item.canonical_field,
            "available": item.is_available,
            "source_field": item.source_field,
        }
        for item in snapshot.availability
    ]


def metric_result_row(result: MetricResult) -> dict[str, object]:
    """Serialize a structured metric result without recalculating it."""
    return {
        "metric_id": result.metric_id,
        "name": result.name,
        "value": _display_value(result.value),
        "status": result.status.value,
        "format": result.format,
        "numerator": _display_value(result.numerator_value),
        "denominator": _display_value(result.denominator_value),
        "reason": result.reason,
    }


def grouped_metric_rows(
    results: tuple[MetricGroupResult, ...],
) -> list[dict[str, object]]:
    """Serialize grouped metric results for a plain table."""
    return [
        {
            "dimension": result.dimension,
            "dimension_value": result.dimension_value,
            "metric_id": result.metric_id,
            "value": _display_value(result.value),
            "status": result.status.value,
            "reason": result.reason,
        }
        for result in results
    ]


def _display_value(value: int | Decimal | None) -> int | str | None:
    if isinstance(value, Decimal):
        return str(value)
    return value
