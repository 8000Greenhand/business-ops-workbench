"""XLSX reader and workbook-sheet discovery."""

from pathlib import Path
from zipfile import BadZipFile

import pandas as pd

from ops_workbench.ingestion._file_checks import validate_source_file
from ops_workbench.ingestion.errors import (
    EmptySourceFileError,
    InvalidSourceFileError,
    SheetNotFoundError,
)


def list_excel_sheets(path: Path) -> tuple[str, ...]:
    """Return workbook sheet names in their stored order."""
    source_path = validate_source_file(path)
    try:
        with pd.ExcelFile(source_path, engine="openpyxl") as workbook:
            sheets = tuple(workbook.sheet_names)
    except (BadZipFile, OSError, ValueError) as exc:
        raise InvalidSourceFileError(
            f"Unable to open XLSX file {source_path}: {exc}"
        ) from exc
    if not sheets:
        raise EmptySourceFileError(f"XLSX workbook has no sheets: {source_path}")
    return sheets


def resolve_sheet_name(path: Path, sheet_name: str | int | None = None) -> str:
    """Resolve a sheet name or zero-based sheet index to a stored sheet name."""
    sheets = list_excel_sheets(path)
    if sheet_name is None:
        return sheets[0]
    if isinstance(sheet_name, int):
        if 0 <= sheet_name < len(sheets):
            return sheets[sheet_name]
        raise SheetNotFoundError(
            f"Sheet index {sheet_name} is outside workbook range 0..{len(sheets) - 1}"
        )
    if sheet_name not in sheets:
        raise SheetNotFoundError(
            f"Sheet {sheet_name!r} does not exist; available sheets: {sheets}"
        )
    return sheet_name


def read_excel(
    path: Path,
    *,
    sheet_name: str | int | None = None,
    nrows: int | None = None,
) -> pd.DataFrame:
    """Read one selected XLSX sheet without coercing canonical data types."""
    source_path = validate_source_file(path)
    selected_sheet = resolve_sheet_name(source_path, sheet_name)
    try:
        dataframe = pd.read_excel(
            source_path,
            sheet_name=selected_sheet,
            nrows=nrows,
            engine="openpyxl",
        )
    except (BadZipFile, OSError, ValueError) as exc:
        raise InvalidSourceFileError(
            f"Unable to read sheet {selected_sheet!r} from {source_path}: {exc}"
        ) from exc
    if dataframe.empty:
        raise EmptySourceFileError(
            f"XLSX sheet {selected_sheet!r} contains no data rows: {source_path}"
        )
    return dataframe
