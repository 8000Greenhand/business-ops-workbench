"""Evidence-based business diagnostics."""

from ops_workbench.diagnostics.anomaly import AnomalyEngine
from ops_workbench.diagnostics.contribution import (
    ContributionEngine,
    UnsupportedContributionComparison,
    UnsupportedContributionMetric,
    is_contribution_eligible,
)
from ops_workbench.diagnostics.diagnosis import (
    DiagnosisEngine,
    render_diagnosis_summary,
)
from ops_workbench.diagnostics.models import (
    AnomalyEvent,
    AnomalyScanResult,
    ContributionResult,
    ContributionSegment,
    ContributionStatus,
    DiagnosisResult,
    DiagnosisStatus,
    DrilldownFinding,
    EvidenceItem,
    EvidenceKind,
)
from ops_workbench.diagnostics.recipes import (
    DiagnosticRecipe,
    DiagnosticRecipeRegistry,
)

__all__ = [
    "AnomalyEngine",
    "AnomalyEvent",
    "AnomalyScanResult",
    "ContributionEngine",
    "ContributionResult",
    "ContributionSegment",
    "ContributionStatus",
    "DiagnosisEngine",
    "DiagnosisResult",
    "DiagnosisStatus",
    "DiagnosticRecipe",
    "DiagnosticRecipeRegistry",
    "DrilldownFinding",
    "EvidenceItem",
    "EvidenceKind",
    "UnsupportedContributionComparison",
    "UnsupportedContributionMetric",
    "is_contribution_eligible",
    "render_diagnosis_summary",
]
