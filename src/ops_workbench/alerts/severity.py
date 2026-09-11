"""Severity values used only for business anomalies."""

from enum import StrEnum


class BusinessSeverity(StrEnum):
    """Business deviation severity, separate from data-quality severity."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
