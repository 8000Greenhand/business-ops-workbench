"""Structured business anomaly outputs."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Mapping

from ops_workbench.alerts.severity import BusinessSeverity
from ops_workbench.metrics.engine import MetricStatus, MetricValue


@dataclass(frozen=True, slots=True)
class AnomalyEvent:
    """One evidence-backed business metric deviation."""

    rule_id: str
    rule_name: str
    metric_id: str
    metric_name: str
    date: date
    dimension: str | None
    dimension_value: str | None
    current_value: MetricValue
    baseline_value: MetricValue
    delta: Decimal
    relative_change: Decimal | None
    percentage_point_change: Decimal | None
    severity: BusinessSeverity
    comparison_type: str
    current_status: MetricStatus
    baseline_status: MetricStatus
    evidence: str
    z_score: Decimal | None = None


@dataclass(frozen=True, slots=True)
class AnomalyScanResult:
    """Business anomaly events and skip counts for one date."""

    date: date
    rules_evaluated: int
    groups_evaluated: int
    events: tuple[AnomalyEvent, ...]
    warning_count: int
    critical_count: int
    info_count: int
    skipped_no_data_count: int
    skipped_low_volume_count: int


class ContributionDirection(StrEnum):
    """Pure arithmetic direction of one segment metric delta."""

    INCREASE = "increase"
    DECREASE = "decrease"
    UNCHANGED = "unchanged"


class ContributionStatus(StrEnum):
    """Availability and reconciliation state of a contribution result."""

    AVAILABLE = "available"
    AVAILABLE_NO_CHANGE = "available_no_change"
    UNAVAILABLE = "unavailable"
    RECONCILIATION_FAILED = "reconciliation_failed"


@dataclass(frozen=True, slots=True)
class ContributionSegment:
    """One dimension member's arithmetic metric change."""

    dimension: str
    dimension_value: str | None
    current_value: Decimal
    baseline_value: Decimal
    delta: Decimal
    net_change_share: Decimal | None
    movement_share: Decimal | None
    direction: ContributionDirection
    rank_by_absolute_change: int
    metric_status: MetricStatus = MetricStatus.AVAILABLE


@dataclass(frozen=True, slots=True)
class ContributionResult:
    """Reconciled arithmetic decomposition of an additive metric change."""

    metric_id: str
    metric_name: str
    dimension: str
    comparison_type: str
    current_start: date
    current_end: date
    baseline_start: date
    baseline_end: date
    overall_current: Decimal | None
    overall_baseline: Decimal | None
    overall_delta: Decimal | None
    net_change_share_available: bool
    segments: tuple[ContributionSegment, ...]
    increase_segments: tuple[ContributionSegment, ...]
    decrease_segments: tuple[ContributionSegment, ...]
    unchanged_segments: tuple[ContributionSegment, ...]
    current_reconciliation_difference: Decimal | None
    baseline_reconciliation_difference: Decimal | None
    reconciliation_difference: Decimal | None
    status: ContributionStatus
    reason: str | None = None

    def top_increases(self, n: int = 5) -> tuple[ContributionSegment, ...]:
        """Return the largest metric increases in descending delta order."""
        _validate_top_n(n)
        return self.increase_segments[:n]

    def top_decreases(self, n: int = 5) -> tuple[ContributionSegment, ...]:
        """Return the largest metric decreases, most negative first."""
        _validate_top_n(n)
        return self.decrease_segments[:n]

    def top_movements(self, n: int = 5) -> tuple[ContributionSegment, ...]:
        """Return the largest absolute metric movements."""
        _validate_top_n(n)
        return self.segments[:n]


def _validate_top_n(n: int) -> None:
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError("n must be a positive integer")


class DiagnosisStatus(StrEnum):
    """Completion state for structured diagnostic orchestration."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED = "unsupported"


class EvidenceKind(StrEnum):
    """Non-overlapping role of one diagnosis evidence item."""

    FACT = "FACT"
    DIAGNOSTIC = "DIAGNOSTIC"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


@dataclass(frozen=True, slots=True)
class ComponentObservation:
    """Current-versus-baseline observation for one recipe component."""

    metric_id: str
    metric_name: str
    current_value: MetricValue | None
    baseline_value: MetricValue | None
    delta: Decimal | None
    relative_change: Decimal | None
    current_status: MetricStatus
    baseline_status: MetricStatus
    comparison_type: str
    direction: ContributionDirection | None


@dataclass(frozen=True, slots=True)
class DrilldownFinding:
    """Bounded one-level contribution summary for one metric and dimension."""

    metric_id: str
    dimension: str
    overall_delta: Decimal
    top_increases: tuple[ContributionSegment, ...]
    top_decreases: tuple[ContributionSegment, ...]
    top_movements: tuple[ContributionSegment, ...]
    reconciliation_status: ContributionStatus
    comparison_type: str
    scope_filters: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SkippedDimension:
    """A contribution candidate skipped with an explicit reason."""

    metric_id: str
    dimension: str
    reason: str


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """A classified, non-probabilistic diagnosis statement."""

    kind: EvidenceKind
    message: str
    supporting_metric_ids: tuple[str, ...]
    supporting_dimension: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosisResult:
    """Structured evidence and bounded inspection guidance for one anomaly."""

    status: DiagnosisStatus
    source_event: AnomalyEvent
    anomaly_comparison_type: str
    diagnostic_comparison_type: str | None
    scope_filters: Mapping[str, object]
    component_observations: tuple[ComponentObservation, ...]
    drilldown_findings: tuple[DrilldownFinding, ...]
    evidence: tuple[EvidenceItem, ...]
    recommended_checks: tuple[str, ...]
    skipped_dimensions: tuple[SkippedDimension, ...]
    limitations: tuple[str, ...]
    reason: str | None = None
