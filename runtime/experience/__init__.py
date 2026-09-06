"""
Experience Store Subsystem for Desktop WebView Reviewer 2.0 / 2.1 (Architecture H).

Provides local, durable, structured historical persistence of reviewer facts,
references, tripartite outcomes, provenance, and privacy enforcement.
"""

from runtime.experience.config import (
    ExperienceConfig,
    get_default_experience_dir,
    resolve_experience_dir,
)
from runtime.experience.models import (
    ActionReferenceRecord,
    EvidenceReferenceRecord,
    ExperienceHealthReport,
    ExperienceScope,
    FailureSignatureSummary,
    FailureSummaryItem,
    MissionExperienceRecord,
    NormalizedFailureRecord,
    OutcomeRecord,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    RecoveryExperienceRecord,
    RecoveryStatistics,
    ScopeValidationException,
    SessionExperienceRecord,
    TraceReferenceRecord,
    VerificationDistribution,
    validate_scope_promotion,
)
from runtime.experience.normalization import (
    FailureNormalizer,
)
from runtime.experience.privacy import (
    PrivacyEnforcer,
    PrivacyViolationException,
)
from runtime.experience.schema import (
    CURRENT_SCHEMA_VERSION,
    apply_migrations,
)
from runtime.experience.store import (
    ExperiencePersistenceException,
    ExperienceStore,
)
from runtime.experience.adapter import (
    ExperienceIntegrationAdapter,
    SIGNIFICANT_TRACE_EVENTS,
)
from runtime.experience.antigravity import (
    AgentArtifactRecord,
    AgentCorrectionRecord,
    AgentDwrCorrelationRecord,
    AgentEventEnvelope,
    AgentEventSanitizer,
    AgentEventType,
    AgentSessionRecord,
    AgentSubagentRecord,
    AgentToolCallRecord,
    AgentTurnRecord,
    AntigravityBridgeStatus,
    AntigravityCorrelationBridge,
    AntigravityHookAdapter,
    CorrelationConfidence,
    UserCorrectionType,
)

__all__ = [
    "ExperienceConfig",
    "get_default_experience_dir",
    "resolve_experience_dir",
    "ExperienceScope",
    "RecordKind",
    "RecordSourceType",
    "ProvenanceRecord",
    "SessionExperienceRecord",
    "MissionExperienceRecord",
    "ActionReferenceRecord",
    "TraceReferenceRecord",
    "EvidenceReferenceRecord",
    "OutcomeRecord",
    "NormalizedFailureRecord",
    "RecoveryExperienceRecord",
    "FailureSummaryItem",
    "FailureSignatureSummary",
    "RecoveryStatistics",
    "VerificationDistribution",
    "ExperienceHealthReport",
    "ScopeValidationException",
    "validate_scope_promotion",
    "PrivacyEnforcer",
    "PrivacyViolationException",
    "CURRENT_SCHEMA_VERSION",
    "apply_migrations",
    "ExperienceStore",
    "ExperiencePersistenceException",
    "FailureNormalizer",
    "ExperienceIntegrationAdapter",
    "SIGNIFICANT_TRACE_EVENTS",
    "AntigravityCorrelationBridge",
    "AgentEventEnvelope",
    "AgentEventType",
    "CorrelationConfidence",
    "UserCorrectionType",
    "AgentSessionRecord",
    "AgentTurnRecord",
    "AgentToolCallRecord",
    "AgentSubagentRecord",
    "AgentArtifactRecord",
    "AgentCorrectionRecord",
    "AgentDwrCorrelationRecord",
    "AntigravityBridgeStatus",
    "AgentEventSanitizer",
    "AntigravityHookAdapter",
]

