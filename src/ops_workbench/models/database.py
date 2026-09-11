"""Local DuckDB persistence for validated canonical business data."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from ops_workbench.models.canonical_schema import (
    CANONICAL_COLUMN_NAMES,
    DATE_FIELD,
    DIMENSION_FIELDS,
    FACT_BUSINESS_DAILY_TABLE,
    INTEGER_FIELDS,
    MONEY_FIELDS,
)
from ops_workbench.transforms.standardize import StandardizationResult
from ops_workbench.validation.quality_models import QualityReport

DEFAULT_DATABASE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "marts" / "business_ops.duckdb"
)
_REGISTERED_RELATION = "standardized_fact_input"
DATASET_METADATA_TABLE = "dataset_metadata"
FIELD_AVAILABILITY_TABLE = "dataset_field_availability"
CURRENT_DATASET_ID = "current"


class QualityBlockedError(ValueError):
    """Raised before persistence when a quality report contains ERROR issues."""

    def __init__(self, report: QualityReport) -> None:
        self.report = report
        super().__init__(
            f"Quality report contains {report.blocking_count} blocking issue(s)"
        )


@dataclass(frozen=True, slots=True)
class DatabaseColumn:
    """One DuckDB fact-table column description."""

    name: str
    data_type: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class DatasetMetadata:
    """Persisted metadata for the current dataset; loaded_at is UTC."""

    dataset_id: str
    row_count: int
    loaded_at: datetime


@dataclass(frozen=True, slots=True)
class FieldAvailability:
    """Persisted source availability for one canonical field."""

    dataset_id: str
    canonical_field: str
    is_available: bool
    source_field: str | None


def _select_expressions() -> tuple[str, ...]:
    expressions: list[str] = []
    for field in CANONICAL_COLUMN_NAMES:
        if field == DATE_FIELD:
            data_type = "DATE"
        elif field in DIMENSION_FIELDS:
            data_type = "VARCHAR"
        elif field in INTEGER_FIELDS:
            data_type = "BIGINT"
        elif field in MONEY_FIELDS:
            data_type = "DECIMAL(18,2)"
        else:
            raise ValueError(f"No DuckDB type is defined for canonical field {field}")
        expressions.append(f'CAST("{field}" AS {data_type}) AS "{field}"')
    return tuple(expressions)


def _replace_fact_table(
    connection: duckdb.DuckDBPyConnection,
    select_sql: str,
) -> None:
    connection.execute(
        f'''CREATE OR REPLACE TABLE "{FACT_BUSINESS_DAILY_TABLE}" AS
            SELECT
                {select_sql}
            FROM "{_REGISTERED_RELATION}"'''
    )


def _replace_dataset_metadata(
    connection: duckdb.DuckDBPyConnection,
    *,
    row_count: int,
    loaded_at: datetime,
) -> None:
    connection.execute(
        f'''CREATE OR REPLACE TABLE "{DATASET_METADATA_TABLE}" (
            dataset_id VARCHAR,
            row_count BIGINT,
            loaded_at TIMESTAMP
        )'''
    )
    connection.execute(
        f'''INSERT INTO "{DATASET_METADATA_TABLE}"
            (dataset_id, row_count, loaded_at) VALUES (?, ?, ?)''',
        [CURRENT_DATASET_ID, row_count, loaded_at],
    )


def _replace_field_availability(
    connection: duckdb.DuckDBPyConnection,
    result: StandardizationResult,
) -> None:
    connection.execute(
        f'''CREATE OR REPLACE TABLE "{FIELD_AVAILABILITY_TABLE}" (
            dataset_id VARCHAR,
            canonical_field VARCHAR,
            is_available BOOLEAN,
            source_field VARCHAR
        )'''
    )
    mapped_field_set = set(result.mapped_fields)
    rows = [
        (
            CURRENT_DATASET_ID,
            field,
            field in mapped_field_set,
            result.source_field_mapping.get(field),
        )
        for field in CANONICAL_COLUMN_NAMES
    ]
    connection.executemany(
        f'''INSERT INTO "{FIELD_AVAILABILITY_TABLE}"
            (dataset_id, canonical_field, is_available, source_field)
            VALUES (?, ?, ?, ?)''',
        rows,
    )


def replace_fact_business_daily(
    result: StandardizationResult,
    report: QualityReport,
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> int:
    """Replace the canonical fact table only when quality validation passed."""
    if not report.is_valid:
        raise QualityBlockedError(report)
    if report.row_count != result.row_count:
        raise ValueError("Quality report row count does not match standardized data")

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    select_sql = ",\n                ".join(_select_expressions())
    loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with duckdb.connect(str(path)) as connection:
        connection.register(_REGISTERED_RELATION, result.dataframe)
        try:
            connection.execute("BEGIN TRANSACTION")
            _replace_fact_table(connection, select_sql)
            _replace_dataset_metadata(
                connection,
                row_count=result.row_count,
                loaded_at=loaded_at,
            )
            _replace_field_availability(connection, result)
            row_count = connection.execute(
                f'SELECT COUNT(*) FROM "{FACT_BUSINESS_DAILY_TABLE}"'
            ).fetchone()[0]
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.unregister(_REGISTERED_RELATION)
    return int(row_count)


def get_dataset_metadata(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> DatasetMetadata:
    """Return metadata for the current persisted dataset."""
    with duckdb.connect(str(database_path), read_only=True) as connection:
        row = connection.execute(
            f'''SELECT dataset_id, row_count, loaded_at
                FROM "{DATASET_METADATA_TABLE}"
                WHERE dataset_id = ?''',
            [CURRENT_DATASET_ID],
        ).fetchone()
    if row is None:
        raise LookupError("Current dataset metadata does not exist")
    return DatasetMetadata(
        dataset_id=str(row[0]),
        row_count=int(row[1]),
        loaded_at=row[2],
    )


def get_field_availability(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> tuple[FieldAvailability, ...]:
    """Return current availability for every canonical field in schema order."""
    with duckdb.connect(str(database_path), read_only=True) as connection:
        rows = connection.execute(
            f'''SELECT dataset_id, canonical_field, is_available, source_field
                FROM "{FIELD_AVAILABILITY_TABLE}"
                WHERE dataset_id = ?''',
            [CURRENT_DATASET_ID],
        ).fetchall()
    by_field = {
        str(row[1]): FieldAvailability(
            dataset_id=str(row[0]),
            canonical_field=str(row[1]),
            is_available=bool(row[2]),
            source_field=None if row[3] is None else str(row[3]),
        )
        for row in rows
    }
    missing_fields = tuple(
        field for field in CANONICAL_COLUMN_NAMES if field not in by_field
    )
    if missing_fields:
        raise LookupError(
            f"Field availability metadata is incomplete: {missing_fields}"
        )
    return tuple(by_field[field] for field in CANONICAL_COLUMN_NAMES)


def get_fact_row_count(*, database_path: Path = DEFAULT_DATABASE_PATH) -> int:
    """Return the current canonical fact-table row count."""
    with duckdb.connect(str(database_path), read_only=True) as connection:
        value = connection.execute(
            f'SELECT COUNT(*) FROM "{FACT_BUSINESS_DAILY_TABLE}"'
        ).fetchone()[0]
    return int(value)


def get_fact_schema(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> tuple[DatabaseColumn, ...]:
    """Return fact-table columns in physical order."""
    with duckdb.connect(str(database_path), read_only=True) as connection:
        rows = connection.execute(
            f"PRAGMA table_info('{FACT_BUSINESS_DAILY_TABLE}')"
        ).fetchall()
    return tuple(
        DatabaseColumn(name=row[1], data_type=row[2], nullable=not bool(row[3]))
        for row in rows
    )


def read_fact_business_daily(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    limit: int | None = None,
) -> pd.DataFrame:
    """Read canonical fact rows with Decimal values preserved by DuckDB."""
    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than zero")
    columns_sql = ", ".join(f'"{column}"' for column in CANONICAL_COLUMN_NAMES)
    query = f'SELECT {columns_sql} FROM "{FACT_BUSINESS_DAILY_TABLE}"'
    parameters: tuple[int, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        parameters = (limit,)
    with duckdb.connect(str(database_path), read_only=True) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return pd.DataFrame(rows, columns=CANONICAL_COLUMN_NAMES)
