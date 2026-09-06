"""
Learning, Governance & Field Intelligence Subsystem.
Architecture H / Milestone 2.1 Prompt 4.

Exports:
- Domain models and enums
- LearningSafetyGate (10 Non-Bypassable Invariants)
- LearningObservationEngine
- DeterministicPatternDetector
- ImprovementCandidateGenerator
- GovernanceEngine
- KnowledgeDecayEngine
- FieldIntelligenceEngine
"""

from runtime.experience.learning.models import (
    CandidateCategory,
    CandidateStatus,
    DetectedPatternRecord,
    DurableKnowledgeRecord,
    FieldIntelligenceReport,
    GateResult,
    GateStatus,
    GovernanceDecision,
    GovernanceRecord,
    ImprovementCandidateRecord,
    KnowledgeStatus,
    ObservationRecord,
    ObservationStatus,
    ObservationType,
    PatternType,
    RiskLevel,
)
from runtime.experience.learning.safety_gate import (
    LearningSafetyException,
    LearningSafetyGate,
)
from runtime.experience.learning.observation_engine import LearningObservationEngine
from runtime.experience.learning.pattern_detector import DeterministicPatternDetector
from runtime.experience.learning.candidate_generator import ImprovementCandidateGenerator
from runtime.experience.learning.governance import (
    GovernanceEngine,
    GovernanceException,
)
from runtime.experience.learning.decay import KnowledgeDecayEngine
from runtime.experience.learning.field_intelligence import FieldIntelligenceEngine

__all__ = [
    "CandidateCategory",
    "CandidateStatus",
    "DetectedPatternRecord",
    "DeterministicPatternDetector",
    "DurableKnowledgeRecord",
    "FieldIntelligenceEngine",
    "FieldIntelligenceReport",
    "GateResult",
    "GateStatus",
    "GovernanceDecision",
    "GovernanceEngine",
    "GovernanceException",
    "GovernanceRecord",
    "ImprovementCandidateGenerator",
    "ImprovementCandidateRecord",
    "KnowledgeDecayEngine",
    "KnowledgeStatus",
    "LearningObservationEngine",
    "LearningSafetyException",
    "LearningSafetyGate",
    "ObservationRecord",
    "ObservationStatus",
    "ObservationType",
    "PatternType",
    "RiskLevel",
]
