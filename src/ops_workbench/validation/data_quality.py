"""Vectorized, configuration-backed data-quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from ops_workbench.models.canonical_schema import (
    DATE_FIELD,
    DIMENSION_FIELDS,
    INTEGER_FIELDS,
    MONEY_FIELDS,
)
from ops_workbench.transforms.standardize import StandardizationResult
from ops_workbench.validation.quality_models import QualityIssue, QualityReport, Severity
from ops_workbench.validation.schema_validator import validate_standardized_schema

DEFAULT_QUALITY_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "data_quality.yaml"
)


@dataclass(frozen=True, slots=True)
class QualityConfig:
    """Small set of generic data-quality controls."""

    missing_warning_threshold: float = 0.05
    sample_rows_limit: int = 10
    duplicate_check_enabled: bool = True
    consistency_checks_enabled: bool = True


def load_quality_config(path: Path = DEFAULT_QUALITY_CONFIG_PATH) -> QualityConfig:
    """Load and validate the simple data-quality YAML configuration."""
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Data-quality configuration must be a YAML object")
    config = QualityConfig(**payload)
    if not 0 <= config.missing_warning_threshold <= 1:
        raise ValueError("missing_warning_threshold must be between 0 and 1")
    if config.sample_rows_limit <= 0:
        raise ValueError("sample_rows_limit must be greater than zero")
    return config


def _sample_rows(mask: pd.Series, limit: int) -> tuple[object, ...]:
    return tuple(mask.index[mask][:limit].tolist())


def _sample_values(series: pd.Series, mask: pd.Series, limit: int) -> tuple[object, ...]:
    return tuple(series.loc[mask].drop_duplicates().head(limit).tolist())


def _field_issue(
    *,
    code: str,
    severity: Severity,
    field: str,
    message: str,
    mask: pd.Series,
    series: pd.Series,
    limit: int,
) -> QualityIssue | None:
    affected_count = int(mask.sum())
    if not affected_count:
        return None
    return QualityIssue(
        code=code,
        severity=severity,
        field=field,
        message=message,
        affected_rows=_sample_rows(mask, limit),
        affected_count=affected_count,
        sample_values=_sample_values(series, mask, limit),
    )


def _unavailable_field_issues(result: StandardizationResult) -> list[QualityIssue]:
    return [
        QualityIssue(
            code="unmapped_optional_field",
            severity=Severity.WARNING,
            field=field,
            message="Optional canonical field was not mapped and remains unavailable",
            affected_rows=(),
            affected_count=result.row_count,
            sample_values=(),
        )
        for field in result.unavailable_fields
        if field != DATE_FIELD
    ]


def _missing_value_issues(
    result: StandardizationResult,
    config: QualityConfig,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if not result.row_count:
        return issues
    for field in result.mapped_fields:
        series = result.dataframe[field]
        mask = series.isna()
        issue = _field_issue(
            code="mapped_field_nulls",
            severity=Severity.WARNING,
            field=field,
            message="Mapped field contains NULL values",
            mask=mask,
            series=series,
            limit=config.sample_rows_limit,
        )
        if issue:
            issues.append(issue)
            if issue.affected_count / result.row_count > config.missing_warning_threshold:
                issues.append(
                    QualityIssue(
                        code="missing_ratio_exceeded",
                        severity=Severity.WARNING,
                        field=field,
                        message=(
                            "Mapped field NULL ratio exceeds the configured warning threshold"
                        ),
                        affected_rows=issue.affected_rows,
                        affected_count=issue.affected_count,
                        sample_values=(),
                    )
                )
    return issues


def _negative_value_issues(
    result: StandardizationResult,
    config: QualityConfig,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    fields = tuple(INTEGER_FIELDS) + tuple(MONEY_FIELDS)
    for field in fields:
        if field not in result.mapped_fields:
            continue
        series = result.dataframe[field]
        mask = series.notna() & series.lt(0)
        issue = _field_issue(
            code="negative_value",
            severity=Severity.WARNING,
            field=field,
            message="Negative values are preserved and require business review",
            mask=mask,
            series=series,
            limit=config.sample_rows_limit,
        )
        if issue:
            issues.append(issue)
    return issues


def _duplicate_issue(
    result: StandardizationResult,
    config: QualityConfig,
) -> QualityIssue | None:
    if not config.duplicate_check_enabled or not result.row_count:
        return None
    available_dimensions = tuple(
        field for field in DIMENSION_FIELDS if field in result.mapped_fields
    )
    grain = (DATE_FIELD, *available_dimensions)
    if DATE_FIELD not in result.mapped_fields:
        return None
    mask = result.dataframe.duplicated(subset=list(grain), keep=False)
    affected_count = int(mask.sum())
    if not affected_count:
        return None
    samples = tuple(
        result.dataframe.loc[mask, list(grain)]
        .head(config.sample_rows_limit)
        .itertuples(index=False, name=None)
    )
    return QualityIssue(
        code="duplicate_canonical_grain",
        severity=Severity.ERROR,
        field=None,
        message=f"Duplicate rows share canonical grain fields: {grain}",
        affected_rows=_sample_rows(mask, config.sample_rows_limit),
        affected_count=affected_count,
        sample_values=samples,
    )


CONSISTENCY_RULES = (
    ("impressions", "leads", "impressions_gte_leads"),
    ("leads", "valid_leads", "leads_gte_valid_leads"),
    ("valid_leads", "contacted_leads", "contacted_leads_lte_valid_leads"),
    ("valid_leads", "followed_leads", "followed_leads_lte_valid_leads"),
    ("valid_leads", "paid_users", "paid_users_lte_valid_leads"),
    ("paid_users", "refund_users", "refund_users_lte_paid_users"),
    ("paid_orders", "refund_orders", "refund_orders_lte_paid_orders"),
    ("gross_revenue", "refund_amount", "refund_amount_lte_gross_revenue"),
)


def _consistency_issues(
    result: StandardizationResult,
    config: QualityConfig,
) -> list[QualityIssue]:
    if not config.consistency_checks_enabled:
        return []
    issues: list[QualityIssue] = []
    for upper_field, lower_field, code in CONSISTENCY_RULES:
        if upper_field not in result.mapped_fields or lower_field not in result.mapped_fields:
            continue
        upper = result.dataframe[upper_field]
        lower = result.dataframe[lower_field]
        mask = upper.notna() & lower.notna() & lower.gt(upper)
        affected_count = int(mask.sum())
        if not affected_count:
            continue
        samples = tuple(
            result.dataframe.loc[mask, [upper_field, lower_field]]
            .head(config.sample_rows_limit)
            .itertuples(index=False, name=None)
        )
        issues.append(
            QualityIssue(
                code=code,
                severity=Severity.WARNING,
                field=lower_field,
                message=(
                    "Consistency warning based on a general relationship; "
                    "it is not a confirmed business error"
                ),
                affected_rows=_sample_rows(mask, config.sample_rows_limit),
                affected_count=affected_count,
                sample_values=samples,
            )
        )
    return issues


def build_quality_report(
    result: StandardizationResult,
    config: QualityConfig | None = None,
) -> QualityReport:
    """Run all M1C checks and return one structured quality report."""
    active_config = config or load_quality_config()
    issues: list[QualityIssue] = list(validate_standardized_schema(result))
    issues.extend(_unavailable_field_issues(result))
    issues.extend(_missing_value_issues(result, active_config))
    issues.extend(_negative_value_issues(result, active_config))
    duplicate_issue = _duplicate_issue(result, active_config)
    if duplicate_issue:
        issues.append(duplicate_issue)
    issues.extend(_consistency_issues(result, active_config))

    blocking_count = sum(issue.severity is Severity.ERROR for issue in issues)
    warning_count = sum(issue.severity is Severity.WARNING for issue in issues)
    info_count = sum(issue.severity is Severity.INFO for issue in issues)
    return QualityReport(
        is_valid=blocking_count == 0,
        blocking_count=blocking_count,
        warning_count=warning_count,
        info_count=info_count,
        row_count=result.row_count,
        issues=tuple(issues),
    )
