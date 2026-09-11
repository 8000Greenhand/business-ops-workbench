"""CSV reader with a small, explicit encoding fallback strategy."""

from pathlib import Path

import pandas as pd

from ops_workbench.ingestion._file_checks import validate_source_file
from ops_workbench.ingestion.errors import EmptySourceFileError, InvalidSourceFileError

CSV_ENCODINGS = ("utf-8-sig", "gb18030")


def read_csv(path: Path, *, nrows: int | None = None) -> pd.DataFrame:
    """Read a CSV using UTF-8 first and GB18030 as the Chinese fallback."""
    source_path = validate_source_file(path)
    decoding_errors: list[str] = []

    for encoding in CSV_ENCODINGS:
        try:
            dataframe = pd.read_csv(source_path, encoding=encoding, nrows=nrows)
        except UnicodeDecodeError as exc:
            decoding_errors.append(f"{encoding}: {exc}")
            continue
        except pd.errors.EmptyDataError as exc:
            raise EmptySourceFileError(
                f"CSV contains no columns or data: {source_path}"
            ) from exc
        except (pd.errors.ParserError, OSError, ValueError) as exc:
            raise InvalidSourceFileError(
                f"Unable to parse CSV file {source_path}: {exc}"
            ) from exc

        if dataframe.empty:
            raise EmptySourceFileError(f"CSV contains no data rows: {source_path}")
        return dataframe

    details = "; ".join(decoding_errors)
    raise InvalidSourceFileError(
        f"Unable to decode CSV file {source_path} with {CSV_ENCODINGS}: {details}"
    )
