"""Schema-level checks for standardized canonical datasets."""

from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES, DATE_FIELD
from ops_workbench.transforms.standardize import StandardizationResult
from ops_workbench.validation.quality_models import QualityIssue, Severity


def validate_standardized_schema(
    result: StandardizationResult,
) -> tuple[QualityIssue, ...]:
    """Return blocking issues for schema, empty data, and normalization failures."""
    issues: list[QualityIssue] = []
    actual_columns = tuple(str(column) for column in result.dataframe.columns)
    if actual_columns != CANONICAL_COLUMN_NAMES:
        issues.append(
            QualityIssue(
                code="invalid_canonical_schema",
                severity=Severity.ERROR,
                field=None,
                message="Standardized columns do not match the canonical schema order",
                affected_rows=(),
                affected_count=1,
                sample_values=(actual_columns,),
            )
        )
    if result.row_count == 0:
        issues.append(
            QualityIssue(
                code="empty_data",
                severity=Severity.ERROR,
                field=None,
                message="The standardized dataset contains no rows",
                affected_rows=(),
                affected_count=0,
                sample_values=(),
            )
        )
    if DATE_FIELD in result.unavailable_fields:
        issues.append(
            QualityIssue(
                code="missing_required_date",
                severity=Severity.ERROR,
                field=DATE_FIELD,
                message="The required canonical date field was not mapped",
                affected_rows=(),
                affected_count=result.row_count,
                sample_values=(),
            )
        )
    issues.extend(
        QualityIssue(
            code=normalization_issue.code,
            severity=Severity.ERROR,
            field=normalization_issue.field,
            message=normalization_issue.message,
            affected_rows=normalization_issue.affected_rows,
            affected_count=normalization_issue.affected_count,
            sample_values=normalization_issue.sample_values,
        )
        for normalization_issue in result.normalization_issues
    )
    return tuple(issues)
