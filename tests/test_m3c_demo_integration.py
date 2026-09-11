"""End-to-end M3C scan-to-diagnosis validation using Demo metadata."""

from pathlib import Path

from ops_workbench.diagnostics import (
    AnomalyEngine,
    DiagnosisEngine,
    DiagnosisStatus,
    render_diagnosis_summary,
)
from ops_workbench.diagnostics.models import ContributionDirection
from ops_workbench.ingestion.file_loader import load_source
from ops_workbench.mapping.field_mapper import apply_mapping
from ops_workbench.metrics import MetricEngine
from ops_workbench.models.canonical_schema import CANONICAL_COLUMN_NAMES
from ops_workbench.models.database import replace_fact_business_daily
from ops_workbench.transforms.standardize import standardize
from ops_workbench.validation.data_quality import build_quality_report
from scripts.generate_demo_data import generate_demo_data


def test_demo_anomalies_produce_bounded_noncausal_diagnoses(tmp_path: Path) -> None:
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
    metric_engine = MetricEngine(database_path=database_path)
    anomaly_engine = AnomalyEngine(metric_engine)
    diagnosis_engine = DiagnosisEngine(metric_engine)

    for expected in demo.metadata["injected_anomalies"]:
        scan = anomaly_engine.scan_date(str(expected["date"]))
        event = next(
            item
            for item in scan.events
            if item.metric_id == expected["metric"]
            and item.dimension == expected["dimension"]
            and item.dimension_value == expected["value"]
        )
        result = diagnosis_engine.diagnose_event(event)
        metric_definition = metric_engine.registry.get(event.metric_id)
        numerator = metric_definition.numerator
        numerator_observation = next(
            item
            for item in result.component_observations
            if item.metric_id == numerator
        )

        assert result.status == DiagnosisStatus.COMPLETE
        assert result.anomaly_comparison_type == event.comparison_type
        assert result.diagnostic_comparison_type == "previous_week"
        assert result.scope_filters[event.dimension] == event.dimension_value
        assert result.drilldown_findings
        assert all(
            finding.metric_id != event.metric_id
            for finding in result.drilldown_findings
        )
        assert all(
            len(finding.top_increases) <= 3
            and len(finding.top_decreases) <= 3
            and len(finding.top_movements) <= 3
            for finding in result.drilldown_findings
        )
        expected_direction = (
            ContributionDirection.INCREASE
            if event.delta > 0
            else ContributionDirection.DECREASE
        )
        assert numerator_observation.direction == expected_direction
        built_in_text = render_diagnosis_summary(result) + "\n" + "\n".join(
            item.message for item in result.evidence
        )
        for forbidden in ("导致", "造成", "证明", "根因是", "一定是"):
            assert forbidden not in built_in_text
