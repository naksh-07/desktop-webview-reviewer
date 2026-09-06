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
    MissionExperienceRecord,
    OutcomeRecord,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    ScopeValidationException,
    SessionExperienceRecord,
    TraceReferenceRecord,
    validate_scope_promotion,
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
    "ExperienceHealthReport",
    "ScopeValidationException",
    "validate_scope_promotion",
    "PrivacyEnforcer",
    "PrivacyViolationException",
    "CURRENT_SCHEMA_VERSION",
    "apply_migrations",
    "ExperienceStore",
    "ExperiencePersistenceException",
]
