"""Build a complete canonical DataFrame from mapped source columns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import pandas as pd

from ops_workbench.models.canonical_schema import (
    CANONICAL_COLUMN_NAMES,
    DATE_FIELD,
    DIMENSION_FIELDS,
    INTEGER_FIELDS,
    MONEY_FIELDS,
)
from ops_workbench.transforms.clean import clean_date, clean_dimension, clean_numeric


@dataclass(frozen=True, slots=True)
class NormalizationIssue:
    """One aggregated value-normalization failure."""

    code: str
    field: str
    message: str
    affected_count: int
    affected_rows: tuple[object, ...]
    sample_values: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class StandardizationResult:
    """Canonical data plus field availability and normalization evidence."""

    dataframe: pd.DataFrame
    mapped_fields: tuple[str, ...]
    unavailable_fields: tuple[str, ...]
    source_columns: tuple[str, ...]
    source_field_mapping: Mapping[str, str]
    row_count: int
    normalization_issues: tuple[NormalizationIssue, ...]


def _issue_from_mask(
    code: str,
    field: str,
    message: str,
    mask: pd.Series,
    source: pd.Series,
    sample_rows_limit: int,
) -> NormalizationIssue | None:
    affected_count = int(mask.sum())
    if not affected_count:
        return None
    affected = source.loc[mask]
    return NormalizationIssue(
        code=code,
        field=field,
        message=message,
        affected_count=affected_count,
        affected_rows=tuple(affected.index[:sample_rows_limit].tolist()),
        sample_values=tuple(affected.drop_duplicates().head(sample_rows_limit).tolist()),
    )


def _null_column(field: str, index: pd.Index) -> pd.Series:
    if field == DATE_FIELD:
        return pd.Series(pd.NaT, index=index, dtype="datetime64[ns]")
    if field in DIMENSION_FIELDS:
        return pd.Series(pd.NA, index=index, dtype="string")
    if field in INTEGER_FIELDS:
        return pd.Series(pd.NA, index=index, dtype="Int64")
    return pd.Series(pd.NA, index=index, dtype="Float64")


def standardize(
    dataframe: pd.DataFrame,
    *,
    source_columns: Sequence[str] | None = None,
    source_field_mapping: Mapping[str, str] | None = None,
    sample_rows_limit: int = 10,
) -> StandardizationResult:
    """Normalize mapped fields and add unavailable canonical fields as NULL."""
    if sample_rows_limit <= 0:
        raise ValueError("sample_rows_limit must be greater than zero")
    if dataframe.columns.has_duplicates:
        raise ValueError("Mapped DataFrame contains duplicate canonical columns")
    unknown_columns = tuple(
        str(column)
        for column in dataframe.columns
        if str(column) not in CANONICAL_COLUMN_NAMES
    )
    if unknown_columns:
        raise ValueError(f"Mapped DataFrame contains non-canonical columns: {unknown_columns}")

    mapped_fields = tuple(
        field for field in CANONICAL_COLUMN_NAMES if field in dataframe.columns
    )
    unavailable_fields = tuple(
        field for field in CANONICAL_COLUMN_NAMES if field not in dataframe.columns
    )
    original_source_columns = tuple(
        source_columns or tuple(str(column) for column in dataframe.columns)
    )
    if source_field_mapping is None:
        resolved_source_mapping = {field: field for field in mapped_fields}
    else:
        mapping_keys = set(source_field_mapping)
        mapped_field_set = set(mapped_fields)
        if mapping_keys != mapped_field_set:
            raise ValueError(
                "source_field_mapping keys must exactly match mapped canonical fields"
            )
        resolved_source_mapping = {
            field: source_field_mapping[field] for field in mapped_fields
        }
        if not all(
            isinstance(source_field, str)
            for source_field in resolved_source_mapping.values()
        ):
            raise ValueError("source_field_mapping values must be strings")
        unknown_source_fields = tuple(
            source_field
            for source_field in resolved_source_mapping.values()
            if source_field not in original_source_columns
        )
        if unknown_source_fields:
            raise ValueError(
                "source_field_mapping references fields outside source_columns: "
                f"{unknown_source_fields}"
            )
    standardized: dict[str, pd.Series] = {}
    issues: list[NormalizationIssue] = []

    for field in CANONICAL_COLUMN_NAMES:
        if field not in dataframe.columns:
            standardized[field] = _null_column(field, dataframe.index)
            continue

        source = dataframe[field]
        if field == DATE_FIELD:
            cleaned = clean_date(source)
            standardized[field] = cleaned.values
            issue = _issue_from_mask(
                "invalid_date",
                field,
                "Non-empty date values could not be parsed",
                cleaned.invalid_mask,
                source,
                sample_rows_limit,
            )
            if issue:
                issues.append(issue)
        elif field in DIMENSION_FIELDS:
            standardized[field] = clean_dimension(source)
        elif field in INTEGER_FIELDS:
            cleaned = clean_numeric(source, integer=True)
            standardized[field] = cleaned.values
            invalid_issue = _issue_from_mask(
                "invalid_numeric",
                field,
                "Non-empty count values could not be parsed",
                cleaned.invalid_mask,
                source,
                sample_rows_limit,
            )
            if invalid_issue:
                issues.append(invalid_issue)
            non_integer_issue = _issue_from_mask(
                "non_integer_count",
                field,
                "Count values must be whole numbers",
                cleaned.non_integer_mask,
                source,
                sample_rows_limit,
            )
            if non_integer_issue:
                issues.append(non_integer_issue)
        elif field in MONEY_FIELDS:
            cleaned = clean_numeric(source, integer=False)
            standardized[field] = cleaned.values
            issue = _issue_from_mask(
                "invalid_numeric",
                field,
                "Non-empty monetary values could not be parsed",
                cleaned.invalid_mask,
                source,
                sample_rows_limit,
            )
            if issue:
                issues.append(issue)

    canonical_dataframe = pd.DataFrame(standardized, index=dataframe.index)
    canonical_dataframe = canonical_dataframe.loc[:, CANONICAL_COLUMN_NAMES]
    return StandardizationResult(
        dataframe=canonical_dataframe,
        mapped_fields=mapped_fields,
        unavailable_fields=unavailable_fields,
        source_columns=original_source_columns,
        source_field_mapping=MappingProxyType(resolved_source_mapping),
        row_count=len(canonical_dataframe),
        normalization_issues=tuple(issues),
    )
