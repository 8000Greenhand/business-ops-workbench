"""YAML persistence for canonical-to-source field mapping templates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ops_workbench.mapping.field_mapper import InvalidMappingError
from ops_workbench.mapping.mapping_validator import FieldMapping, mapping_items, validate_mapping

DEFAULT_MAPPING_DIR = Path(__file__).resolve().parents[3] / "config" / "mappings"
SAFE_MAPPING_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SUPPORTED_MAPPING_FILE_TYPES = {"csv", "xlsx"}


class MappingTemplateError(ValueError):
    """Base class for invalid mapping templates."""


class UnsafeMappingNameError(MappingTemplateError):
    """Raised when a mapping name is unsafe for use as a file name."""


class MappingTemplateNotFoundError(MappingTemplateError):
    """Raised when a named mapping template does not exist."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise MappingTemplateError(f"Duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class MappingTemplate:
    """Persisted canonical-to-source mapping configuration."""

    mapping_name: str
    version: int
    source_file_type: str
    fields: dict[str, str]


def _mapping_path(mapping_name: str, mapping_dir: Path) -> Path:
    if not SAFE_MAPPING_NAME.fullmatch(mapping_name):
        raise UnsafeMappingNameError(
            "mapping_name must use 1-64 ASCII letters, numbers, underscores, or hyphens"
        )
    directory = Path(mapping_dir).resolve()
    path = directory / f"{mapping_name}.yaml"
    if path.resolve(strict=False).parent != directory:
        raise UnsafeMappingNameError("mapping_name escapes the mappings directory")
    return path


def save_mapping(
    mapping_name: str,
    source_file_type: str,
    fields: FieldMapping,
    *,
    mapping_dir: Path = DEFAULT_MAPPING_DIR,
    version: int = 1,
) -> Path:
    """Validate and save one mapping template below the mappings directory."""
    path = _mapping_path(mapping_name, mapping_dir)
    if source_file_type not in SUPPORTED_MAPPING_FILE_TYPES:
        raise MappingTemplateError("source_file_type must be 'csv' or 'xlsx'")
    if version < 1:
        raise MappingTemplateError("version must be at least 1")

    items = mapping_items(fields)
    validation = validate_mapping(items, tuple(source for _, source in items))
    if not validation.is_valid:
        raise InvalidMappingError(validation)

    payload = {
        "mapping_name": mapping_name,
        "version": version,
        "source": {"file_type": source_file_type},
        "fields": dict(items),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def load_mapping(
    mapping_name: str,
    *,
    mapping_dir: Path = DEFAULT_MAPPING_DIR,
) -> MappingTemplate:
    """Load and validate one mapping template by safe mapping name."""
    path = _mapping_path(mapping_name, mapping_dir)
    if not path.is_file():
        raise MappingTemplateNotFoundError(f"Mapping template does not exist: {mapping_name}")
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise MappingTemplateError(f"Invalid mapping YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise MappingTemplateError("Mapping template root must be an object")

    source = payload.get("source")
    fields = payload.get("fields")
    if (
        payload.get("mapping_name") != mapping_name
        or not isinstance(payload.get("version"), int)
        or not isinstance(source, dict)
        or source.get("file_type") not in SUPPORTED_MAPPING_FILE_TYPES
        or not isinstance(fields, dict)
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in fields.items())
    ):
        raise MappingTemplateError("Mapping template structure is invalid")

    validation = validate_mapping(fields, tuple(fields.values()))
    if not validation.is_valid:
        raise InvalidMappingError(validation)
    return MappingTemplate(
        mapping_name=mapping_name,
        version=payload["version"],
        source_file_type=source["file_type"],
        fields=dict(fields),
    )


def list_mappings(*, mapping_dir: Path = DEFAULT_MAPPING_DIR) -> tuple[str, ...]:
    """List safe mapping template names in filename order."""
    directory = Path(mapping_dir).resolve()
    if not directory.exists():
        return ()
    return tuple(
        path.stem
        for path in sorted(directory.glob("*.yaml"))
        if path.is_file() and SAFE_MAPPING_NAME.fullmatch(path.stem)
    )
