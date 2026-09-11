"""Shared path checks for local source readers."""

from pathlib import Path

from ops_workbench.ingestion.errors import (
    EmptySourceFileError,
    SourceFileNotFoundError,
)


def validate_source_file(path: Path) -> Path:
    """Return a resolved file path or raise an explicit source-file error."""
    source_path = Path(path)
    if not source_path.exists() or not source_path.is_file():
        raise SourceFileNotFoundError(f"Source file does not exist: {source_path}")
    if source_path.stat().st_size == 0:
        raise EmptySourceFileError(f"Source file is empty: {source_path}")
    return source_path.resolve()
