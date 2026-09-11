"""Structural validation for canonical-to-source field mappings."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES

FieldMapping = Mapping[str, str] | Sequence[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class MappingIssue:
    """One structured mapping error or warning."""

    code: str
    message: str
    canonical_field: str | None = None
    source_field: str | None = None


@dataclass(frozen=True, slots=True)
class MappingValidationResult:
    """Structured result of validating mapping shape and field references."""

    is_valid: bool
    errors: tuple[MappingIssue, ...]
    warnings: tuple[MappingIssue, ...]
    mapped_fields: tuple[str, ...]
    unmapped_source_fields: tuple[str, ...]
    unmapped_canonical_fields: tuple[str, ...]


def mapping_items(fields: FieldMapping) -> tuple[tuple[str, str], ...]:
    """Return mapping entries without discarding duplicate canonical keys."""
    if isinstance(fields, Mapping):
        return tuple(fields.items())
    return tuple(fields)


def validate_mapping(
    fields: FieldMapping,
    source_columns: Sequence[str],
) -> MappingValidationResult:
    """Validate mapping structure without inspecting or coercing row values."""
    items = mapping_items(fields)
    source_column_set = set(source_columns)
    canonical_set = set(CANONICAL_COLUMN_NAMES)
    canonical_counts = Counter(canonical for canonical, _ in items)
    source_counts = Counter(source for _, source in items)
    errors: list[MappingIssue] = []

    for canonical_field, count in canonical_counts.items():
        if count > 1:
            errors.append(
                MappingIssue(
                    "duplicate_canonical_field",
                    f"Canonical field {canonical_field!r} appears {count} times",
                    canonical_field=canonical_field,
                )
            )

    for canonical_field, source_field in items:
        if canonical_field not in canonical_set:
            errors.append(
                MappingIssue(
                    "unknown_canonical_field",
                    f"Canonical field does not exist: {canonical_field!r}",
                    canonical_field=canonical_field,
                    source_field=source_field,
                )
            )
        if source_field not in source_column_set:
            errors.append(
                MappingIssue(
                    "missing_source_field",
                    f"Source field does not exist: {source_field!r}",
                    canonical_field=canonical_field,
                    source_field=source_field,
                )
            )

    for source_field, count in source_counts.items():
        if count > 1:
            errors.append(
                MappingIssue(
                    "duplicate_source_field",
                    f"Source field {source_field!r} maps to {count} canonical fields",
                    source_field=source_field,
                )
            )

    if canonical_counts["date"] == 0:
        errors.append(
            MappingIssue(
                "missing_required_date",
                "The required canonical field 'date' is not mapped",
                canonical_field="date",
            )
        )

    valid_pairs = {
        canonical_field: source_field
        for canonical_field, source_field in items
        if canonical_counts[canonical_field] == 1
        and source_counts[source_field] == 1
        and canonical_field in canonical_set
        and source_field in source_column_set
    }
    mapped_fields = tuple(
        field for field in CANONICAL_COLUMN_NAMES if field in valid_pairs
    )
    mapped_source_fields = set(valid_pairs.values())
    unmapped_source_fields = tuple(
        field for field in source_columns if field not in mapped_source_fields
    )
    unmapped_canonical_fields = tuple(
        field for field in CANONICAL_COLUMN_NAMES if field not in valid_pairs
    )
    warnings: list[MappingIssue] = []
    if unmapped_source_fields:
        warnings.append(
            MappingIssue(
                "unmapped_source_fields",
                "Unmapped source fields remain outside the canonical output",
            )
        )
    optional_unmapped = tuple(
        field for field in unmapped_canonical_fields if field != "date"
    )
    if optional_unmapped:
        warnings.append(
            MappingIssue(
                "unmapped_optional_canonical_fields",
                "Optional canonical fields may remain unmapped",
            )
        )

    return MappingValidationResult(
        is_valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        mapped_fields=mapped_fields,
        unmapped_source_fields=unmapped_source_fields,
        unmapped_canonical_fields=unmapped_canonical_fields,
    )
