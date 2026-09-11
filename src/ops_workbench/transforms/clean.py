"""Vectorized column cleaning helpers for canonical standardization."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class CleanedColumn:
    """A cleaned pandas Series and masks describing rejected source values."""

    values: pd.Series
    invalid_mask: pd.Series
    non_integer_mask: pd.Series | None = None


def clean_dimension(series: pd.Series) -> pd.Series:
    """Trim dimension strings and convert empty strings to pandas NULL."""
    cleaned = series.astype("string").str.strip()
    return cleaned.mask(cleaned.eq(""), pd.NA)


def clean_date(series: pd.Series) -> CleanedColumn:
    """Parse common text, datetime, timestamp, and Excel serial dates."""
    text = series.astype("string").str.strip()
    provided = (series.notna() & text.ne("")).fillna(False).astype(bool)

    numeric = pd.to_numeric(text, errors="coerce")
    excel_serial = (
        provided & numeric.between(1, 132_320, inclusive="both")
    ).fillna(False).astype(bool)
    text_dates = pd.to_datetime(
        series.mask(excel_serial, pd.NA),
        format="mixed",
        errors="coerce",
    ).astype("datetime64[ns]")
    excel_dates = pd.to_datetime(
        numeric,
        unit="D",
        origin="1899-12-30",
        errors="coerce",
    ).astype("datetime64[ns]")
    parsed = text_dates.copy()
    serial_positions = excel_serial.to_numpy(dtype=bool)
    parsed.iloc[serial_positions] = excel_dates.iloc[serial_positions].to_numpy()

    invalid = provided & parsed.isna()
    return CleanedColumn(parsed.dt.normalize(), invalid)


def clean_numeric(series: pd.Series, *, integer: bool) -> CleanedColumn:
    """Parse common numeric text while preserving invalid values as issues."""
    text = series.astype("string").str.strip()
    provided = (series.notna() & text.ne("")).fillna(False)
    normalized = text.str.replace(r"[,\s¥￥]", "", regex=True)
    parsed = pd.to_numeric(normalized, errors="coerce")
    finite = ~parsed.isin([float("inf"), float("-inf")])
    invalid = provided & (parsed.isna() | ~finite)
    parsed = parsed.mask(~finite, pd.NA).astype("Float64")

    if not integer:
        return CleanedColumn(parsed, invalid)

    non_integer = provided & parsed.notna() & ((parsed % 1).abs() > 1e-9)
    integer_values = parsed.mask(non_integer, pd.NA).astype("Int64")
    return CleanedColumn(integer_values, invalid, non_integer)
