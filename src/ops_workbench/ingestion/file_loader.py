"""Unified local source-file loading and preview metadata."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ops_workbench.ingestion.csv_reader import read_csv
from ops_workbench.ingestion.errors import UnsupportedSourceFormatError
from ops_workbench.ingestion.excel_reader import (
    list_excel_sheets,
    read_excel,
    resolve_sheet_name,
)

SUPPORTED_FILE_TYPES = {".csv", ".xlsx"}
DEFAULT_PREVIEW_ROWS = 20


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Describe a loaded source without performing data profiling."""

    file_name: str
    file_type: str
    file_size: int
    sheet_name: str | None
    row_count: int | None
    column_count: int
    source_columns: tuple[str, ...]
    preview_rows: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class LoadedSource:
    """Pair a source DataFrame with its file metadata."""

    dataframe: pd.DataFrame
    metadata: SourceMetadata


def _file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_FILE_TYPES:
        raise UnsupportedSourceFormatError(
            f"Unsupported source format {suffix or '<none>'}; expected .csv or .xlsx"
        )
    return suffix.removeprefix(".")


def _read_source(
    path: Path,
    *,
    sheet_name: str | int | None,
    nrows: int | None,
) -> tuple[pd.DataFrame, str | None, str]:
    file_type = _file_type(path)
    if file_type == "csv":
        if sheet_name is not None:
            raise UnsupportedSourceFormatError("sheet_name is only valid for XLSX files")
        return read_csv(path, nrows=nrows), None, file_type

    selected_sheet = resolve_sheet_name(path, sheet_name)
    return (
        read_excel(path, sheet_name=selected_sheet, nrows=nrows),
        selected_sheet,
        file_type,
    )


def _metadata(
    path: Path,
    dataframe: pd.DataFrame,
    *,
    file_type: str,
    sheet_name: str | None,
    row_count: int | None,
    preview_limit: int,
) -> SourceMetadata:
    return SourceMetadata(
        file_name=path.name,
        file_type=file_type,
        file_size=path.stat().st_size,
        sheet_name=sheet_name,
        row_count=row_count,
        column_count=len(dataframe.columns),
        source_columns=tuple(str(column) for column in dataframe.columns),
        preview_rows=tuple(
            dataframe.head(preview_limit).to_dict(orient="records")
        ),
    )


def preview_source(
    path: Path,
    *,
    sheet_name: str | int | None = None,
    limit: int = DEFAULT_PREVIEW_ROWS,
) -> LoadedSource:
    """Read only the first rows of a local CSV or XLSX source."""
    if limit <= 0:
        raise ValueError("Preview limit must be greater than zero")
    source_path = Path(path)
    dataframe, selected_sheet, file_type = _read_source(
        source_path,
        sheet_name=sheet_name,
        nrows=limit,
    )
    return LoadedSource(
        dataframe=dataframe,
        metadata=_metadata(
            source_path,
            dataframe,
            file_type=file_type,
            sheet_name=selected_sheet,
            row_count=None,
            preview_limit=limit,
        ),
    )


def load_source(
    path: Path,
    *,
    sheet_name: str | int | None = None,
    preview_limit: int = DEFAULT_PREVIEW_ROWS,
) -> LoadedSource:
    """Load a complete local CSV or selected XLSX sheet."""
    if preview_limit <= 0:
        raise ValueError("Preview limit must be greater than zero")
    source_path = Path(path)
    dataframe, selected_sheet, file_type = _read_source(
        source_path,
        sheet_name=sheet_name,
        nrows=None,
    )
    return LoadedSource(
        dataframe=dataframe,
        metadata=_metadata(
            source_path,
            dataframe,
            file_type=file_type,
            sheet_name=selected_sheet,
            row_count=len(dataframe),
            preview_limit=preview_limit,
        ),
    )


def list_sheets(path: Path) -> tuple[str, ...]:
    """List XLSX sheets after confirming that the extension is supported."""
    source_path = Path(path)
    if _file_type(source_path) != "xlsx":
        raise UnsupportedSourceFormatError("Sheet listing is only valid for XLSX files")
    return list_excel_sheets(source_path)
