"""Structured result types for data-quality validation."""

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    """Data-quality severity; ERROR blocks fact-table replacement."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    """One aggregated data-quality issue for a field or rule."""

    code: str
    severity: Severity
    field: str | None
    message: str
    affected_rows: tuple[object, ...]
    affected_count: int
    sample_values: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Summary and structured issues for one standardized dataset."""

    is_valid: bool
    blocking_count: int
    warning_count: int
    info_count: int
    row_count: int
    issues: tuple[QualityIssue, ...]
