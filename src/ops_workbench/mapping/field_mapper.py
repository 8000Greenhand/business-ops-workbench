"""Apply validated canonical-to-source field mappings to DataFrames."""

import pandas as pd

from ops_workbench.mapping.mapping_validator import (
    FieldMapping,
    MappingValidationResult,
    mapping_items,
    validate_mapping,
)
from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES


class InvalidMappingError(ValueError):
    """Raised when mapping application receives an invalid structure."""

    def __init__(self, result: MappingValidationResult) -> None:
        self.result = result
        codes = ", ".join(issue.code for issue in result.errors)
        super().__init__(f"Field mapping is invalid: {codes}")


def apply_mapping(dataframe: pd.DataFrame, fields: FieldMapping) -> pd.DataFrame:
    """Select and rename mapped columns in canonical schema order."""
    source_columns = tuple(str(column) for column in dataframe.columns)
    result = validate_mapping(fields, source_columns)
    if not result.is_valid:
        raise InvalidMappingError(result)

    fields_by_canonical = dict(mapping_items(fields))
    output_columns = tuple(
        column for column in CANONICAL_COLUMN_NAMES if column in fields_by_canonical
    )
    source_selection = tuple(fields_by_canonical[column] for column in output_columns)
    mapped = dataframe.loc[:, source_selection].copy()
    mapped.columns = output_columns
    return mapped
