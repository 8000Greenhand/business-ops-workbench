"""Canonical field mapping and template persistence."""

from ops_workbench.mapping.field_mapper import InvalidMappingError, apply_mapping
from ops_workbench.mapping.mapping_templates import (
    MappingTemplate,
    list_mappings,
    load_mapping,
    save_mapping,
)
from ops_workbench.mapping.mapping_validator import (
    MappingIssue,
    MappingValidationResult,
    validate_mapping,
)

__all__ = [
    "InvalidMappingError",
    "MappingIssue",
    "MappingTemplate",
    "MappingValidationResult",
    "apply_mapping",
    "list_mappings",
    "load_mapping",
    "save_mapping",
    "validate_mapping",
]
