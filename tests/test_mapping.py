"""Tests for mapping validation, application, and YAML persistence."""

from pathlib import Path

import pandas as pd
import pytest

from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.mapping.mapping_templates import (
    UnsafeMappingNameError,
    list_mappings,
    load_mapping,
    save_mapping,
)
from ops_workbench.mapping.mapping_validator import MappingValidationResult, validate_mapping


def _error_codes(result: MappingValidationResult) -> set[str]:
    return {issue.code for issue in result.errors}


def test_valid_mapping_and_optional_unmapped_fields() -> None:
    """A partial mapping with date should pass and warn about optional fields."""
    result = validate_mapping(
        {"date": "日期", "channel": "推广来源", "gross_revenue": "流水"},
        ("日期", "推广来源", "流水", "备注"),
    )
    assert result.is_valid
    assert result.mapped_fields == ("date", "channel", "gross_revenue")
    assert result.unmapped_source_fields == ("备注",)
    assert "product" in result.unmapped_canonical_fields
    assert {warning.code for warning in result.warnings} == {
        "unmapped_source_fields",
        "unmapped_optional_canonical_fields",
    }


@pytest.mark.parametrize(
    ("fields", "source_columns", "expected_code"),
    [
        ({"date": "日期", "not_canonical": "项目"}, ("日期", "项目"), "unknown_canonical_field"),
        ({"date": "日期", "channel": "不存在"}, ("日期", "渠道"), "missing_source_field"),
        ({"date": "日期", "channel": "日期"}, ("日期",), "duplicate_source_field"),
        ({"channel": "渠道"}, ("渠道",), "missing_required_date"),
        ([('date', '日期'), ('date', '统计日期')], ("日期", "统计日期"), "duplicate_canonical_field"),
    ],
)
def test_invalid_mapping_structures_are_reported(
    fields: object,
    source_columns: tuple[str, ...],
    expected_code: str,
) -> None:
    """Each structural mapping defect should have a stable machine-readable code."""
    result = validate_mapping(fields, source_columns)
    assert not result.is_valid
    assert expected_code in _error_codes(result)


def test_apply_mapping_preserves_null_and_canonical_order() -> None:
    """Mapping should select only mapped fields without coercing nulls or dtypes."""
    source = pd.DataFrame(
        {
            "流水": [1200.5, None],
            "未映射": ["保留在源数据", "不进入结果"],
            "日期": ["2026-01-01", "2026-01-02"],
            "推广来源": ["渠道A", None],
        }
    )
    mapped = apply_mapping(
        source,
        {"gross_revenue": "流水", "date": "日期", "channel": "推广来源"},
    )
    assert tuple(mapped.columns) == ("date", "channel", "gross_revenue")
    assert mapped.loc[0].to_dict() == {
        "date": "2026-01-01",
        "channel": "渠道A",
        "gross_revenue": 1200.5,
    }
    assert pd.isna(mapped.loc[1, "channel"])
    assert pd.isna(mapped.loc[1, "gross_revenue"])
    assert "未映射" not in mapped.columns


def test_mapping_persistence_round_trip_and_listing(tmp_path: Path) -> None:
    """Saved YAML should load unchanged and appear in the mapping list."""
    fields = {"date": "日期", "leads": "资源数"}
    path = save_mapping("daily_demo", "csv", fields, mapping_dir=tmp_path)
    loaded = load_mapping("daily_demo", mapping_dir=tmp_path)
    assert path.is_file()
    assert loaded.mapping_name == "daily_demo"
    assert loaded.version == 1
    assert loaded.source_file_type == "csv"
    assert loaded.fields == fields
    assert list_mappings(mapping_dir=tmp_path) == ("daily_demo",)


@pytest.mark.parametrize("mapping_name", ("../escape", "nested/path", "..", "C:\\escape"))
def test_mapping_name_cannot_escape_directory(
    tmp_path: Path,
    mapping_name: str,
) -> None:
    """Unsafe mapping names must be rejected before any file is written."""
    with pytest.raises(UnsafeMappingNameError):
        save_mapping(mapping_name, "csv", {"date": "日期"}, mapping_dir=tmp_path)
    assert not any(tmp_path.iterdir())
