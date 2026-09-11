"""Tests for local CSV/XLSX reading and source metadata."""

from pathlib import Path

import pytest

from ops_workbench.ingestion.csv_reader import read_csv
from ops_workbench.ingestion.errors import (
    EmptySourceFileError,
    InvalidSourceFileError,
    SourceFileNotFoundError,
    UnsupportedSourceFormatError,
)
from ops_workbench.ingestion.file_loader import list_sheets, load_source, preview_source

XLSX_FIXTURE = Path(__file__).parent / "fixtures" / "m1b_source.xlsx"


def test_normal_csv_and_chinese_columns_are_read(tmp_path: Path) -> None:
    """UTF-8 CSV should preserve Chinese headers and expose preview metadata."""
    path = tmp_path / "source.csv"
    path.write_text("日期,推广来源,流水\n2026-01-01,渠道A,1200.50\n", encoding="utf-8")

    loaded = preview_source(path, limit=1)

    assert tuple(loaded.dataframe.columns) == ("日期", "推广来源", "流水")
    assert loaded.metadata.file_name == "source.csv"
    assert loaded.metadata.file_type == "csv"
    assert loaded.metadata.row_count is None
    assert loaded.metadata.column_count == 3
    assert loaded.metadata.source_columns == ("日期", "推广来源", "流水")
    assert len(loaded.metadata.preview_rows) == 1


def test_utf8_sig_csv_is_read(tmp_path: Path) -> None:
    """UTF-8-SIG CSV should not retain a BOM in the first column name."""
    path = tmp_path / "source.csv"
    path.write_text("日期,资源数\n2026-01-01,8\n", encoding="utf-8-sig")
    dataframe = read_csv(path)
    assert tuple(dataframe.columns) == ("日期", "资源数")


def test_gb18030_csv_is_read(tmp_path: Path) -> None:
    """GB18030 provides a deterministic fallback for common Chinese CSV files."""
    path = tmp_path / "source.csv"
    path.write_text("日期,销售组\n2026-01-01,一组\n", encoding="gb18030")
    dataframe = read_csv(path)
    assert dataframe.loc[0, "销售组"] == "一组"


def test_empty_and_missing_files_raise_explicit_errors(tmp_path: Path) -> None:
    """Empty and nonexistent paths should never be silently accepted."""
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    with pytest.raises(EmptySourceFileError):
        load_source(empty)
    with pytest.raises(SourceFileNotFoundError):
        load_source(tmp_path / "missing.csv")


def test_unsupported_format_raises_explicit_error(tmp_path: Path) -> None:
    """The unified loader should reject extensions outside CSV and XLSX."""
    path = tmp_path / "source.txt"
    path.write_text("date,value\n2026-01-01,1\n", encoding="utf-8")
    with pytest.raises(UnsupportedSourceFormatError):
        load_source(path)


def test_invalid_xlsx_raises_explicit_error(tmp_path: Path) -> None:
    """A corrupt file with an XLSX extension should produce a reader error."""
    path = tmp_path / "corrupt.xlsx"
    path.write_text("not an XLSX workbook", encoding="utf-8")
    with pytest.raises(InvalidSourceFileError):
        load_source(path)


def test_xlsx_can_list_and_select_sheets() -> None:
    """XLSX reading should list sheets and load one selected sheet."""
    assert list_sheets(XLSX_FIXTURE) == ("业务数据", "备用数据")
    loaded = load_source(XLSX_FIXTURE, sheet_name="备用数据")
    assert loaded.metadata.sheet_name == "备用数据"
    assert loaded.metadata.row_count == 1
    assert tuple(loaded.dataframe.columns) == ("日期", "团队", "流水")
    assert loaded.dataframe.loc[0, "团队"] == "团队02"
