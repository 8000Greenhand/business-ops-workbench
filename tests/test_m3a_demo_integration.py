"""Full Demo ground-truth and alert-noise integration for M3A."""

from pathlib import Path

from ops_workbench.diagnostics import AnomalyEngine
from ops_workbench.ingestion.file_loader import load_source
from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.metrics import MetricEngine
from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report
from scripts.generate_demo_data import generate_demo_data


def test_full_demo_ground_truth_and_noise_are_reasonable(tmp_path: Path) -> None:
    demo = generate_demo_data(tmp_path / "demo", seed=42)
    loaded = load_source(demo.csv_path)
    identity = {field: field for field in CANONICAL_COLUMN_NAMES}
    standardized = standardize(
        apply_mapping(loaded.dataframe, identity),
        source_columns=loaded.metadata.source_columns,
        source_field_mapping=identity,
    )
    report = build_quality_report(standardized)
    database_path = tmp_path / "demo.duckdb"
    replace_fact_business_daily(standardized, report, database_path=database_path)
    scanner = AnomalyEngine(MetricEngine(database_path=database_path))

    results = scanner.scan_range(
        str(demo.metadata["start_date"]),
        str(demo.metadata["end_date"]),
    )
    by_date = {result.date.isoformat(): result for result in results}
    for expected in demo.metadata["injected_anomalies"]:
        matches = [
            event
            for event in by_date[str(expected["date"])].events
            if event.date.isoformat() == expected["date"]
            and event.metric_id == expected["metric"]
            and event.dimension == expected["dimension"]
            and event.dimension_value == expected["value"]
        ]
        assert matches, expected

    events = [event for result in results for event in result.events]
    assert 3 <= len(events) < 1000
    assert max(len(result.events) for result in results) < 20
    assert all(event.evidence for event in events)
