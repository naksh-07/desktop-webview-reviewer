"""
Experience Store Data Models and Domain Enums (Architecture H).

Defines structured experience facts, references, provenance envelopes,
and scope contracts (SESSION / PROJECT / GLOBAL).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from core.version import get_version_info
from runtime.errors import DesktopAutomationException


class ScopeValidationException(DesktopAutomationException):
    """Raised when an invalid scope or unauthorized global promotion is attempted."""
    pass


class ExperienceScope(str, Enum):
    """
    Scope boundaries for durable experience records.
    
    SESSION: Scoped to an individual review session transaction.
    PROJECT: Scoped to the active project repository or desktop application.
    GLOBAL: Cross-project knowledge (Promotion semantics disabled in 2.1 Prompt 1).
    """
    SESSION = "SESSION"
    PROJECT = "PROJECT"
    GLOBAL = "GLOBAL"


class RecordKind(str, Enum):
    """
    Epistemic classification of an experience record.
    Distinguishes verifiable ground truth from derived insights or inferences.
    """
    FACT = "FACT"                                  # Direct physical or runtime truth
    OBSERVATION = "OBSERVATION"                    # Formatted or filtered observation snapshot
    INFERENCE = "INFERENCE"                        # Probabilistic deduction or heuristic evaluation
    CANDIDATE_KNOWLEDGE = "CANDIDATE_KNOWLEDGE"    # Proposed pattern for future cross-session learning


class RecordSourceType(str, Enum):
    """Authoritative source category for provenance tracing."""
    RUNTIME = "RUNTIME"
    TRACE_ENGINE = "TRACE_ENGINE"
    EVIDENCE_STORE = "EVIDENCE_STORE"
    DIAGNOSTICS = "DIAGNOSTICS"
    SPECIALIST = "SPECIALIST"
    USER_VERIFICATION = "USER_VERIFICATION"
    AGENT = "AGENT"


def validate_scope_promotion(scope: Union[str, ExperienceScope]) -> ExperienceScope:
    """
    Validates scope assignment.
    Rejects GLOBAL promotion in 2.1 Prompt 1 as governed by Section 8 of contract.
    """
    if isinstance(scope, str):
        try:
            scope = ExperienceScope(scope.upper())
        except ValueError:
            raise ScopeValidationException(f"Invalid experience scope '{scope}'. Allowed: SESSION, PROJECT, GLOBAL.")

    if scope == ExperienceScope.GLOBAL:
        raise ScopeValidationException(
            "Global promotion semantics are not authorized in Milestone 2.1 Prompt 1. "
            "Experience records must be scoped to SESSION or PROJECT."
        )
    return scope


@dataclass(frozen=True)
class ProvenanceRecord:
    """
    Immutable provenance envelope required for all durable experience facts.
    Answers: who, what, when, where, with what confidence, and linked to what evidence.
    """
    source: str
    source_type: RecordSourceType
    session_id: str
    runtime_version: str = field(default_factory=lambda: get_version_info().product_version)
    mission_id: Optional[str] = None
    project_id: Optional[str] = None
    confidence: float = 1.0
    evidence_reference: Optional[str] = None
    trace_reference: Optional[str] = None
    kind: RecordKind = RecordKind.FACT
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["source_type"] = self.source_type.value if isinstance(self.source_type, RecordSourceType) else str(self.source_type)
        d["kind"] = self.kind.value if isinstance(self.kind, RecordKind) else str(self.kind)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProvenanceRecord:
        st = data.get("source_type", RecordSourceType.RUNTIME)
        if isinstance(st, str):
            st = RecordSourceType(st)
        kd = data.get("kind", RecordKind.FACT)
        if isinstance(kd, str):
            kd = RecordKind(kd)

        return cls(
            source=data["source"],
            source_type=st,
            session_id=data["session_id"],
            runtime_version=data.get("runtime_version") or get_version_info().product_version,
            mission_id=data.get("mission_id"),
            project_id=data.get("project_id"),
            confidence=float(data.get("confidence", 1.0)),
            evidence_reference=data.get("evidence_reference"),
            trace_reference=data.get("trace_reference"),
            kind=kd,
            timestamp=float(data.get("timestamp", time.time())),
            iso_timestamp=data.get("iso_timestamp", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class SessionExperienceRecord:
    """Durable record of an automation review session."""
    session_id: str
    created_at: str
    status: str
    runtime_version: str = field(default_factory=lambda: get_version_info().product_version)
    project_id: Optional[str] = None
    completed_at: Optional[str] = None
    target_executable: Optional[str] = None
    target_pid: Optional[int] = None
    target_hwnd: Optional[str] = None
    target_plane: Optional[str] = None
    scope: ExperienceScope = ExperienceScope.SESSION
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scope"] = self.scope.value if isinstance(self.scope, ExperienceScope) else str(self.scope)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SessionExperienceRecord:
        sc = data.get("scope", ExperienceScope.SESSION)
        if isinstance(sc, str):
            sc = ExperienceScope(sc)
        return cls(
            session_id=data["session_id"],
            created_at=data["created_at"],
            status=data["status"],
            runtime_version=data.get("runtime_version") or get_version_info().product_version,
            project_id=data.get("project_id"),
            completed_at=data.get("completed_at"),
            target_executable=data.get("target_executable"),
            target_pid=data.get("target_pid"),
            target_hwnd=data.get("target_hwnd"),
            target_plane=data.get("target_plane"),
            scope=sc,
            metadata=data.get("metadata", {}),
        )


@dataclass
class MissionExperienceRecord:
    """Durable record of an admitted review mission authority."""
    mission_id: str
    session_id: str
    goal: str
    scope: str
    created_at: str
    status: str
    project_id: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MissionExperienceRecord:
        return cls(
            mission_id=data["mission_id"],
            session_id=data["session_id"],
            goal=data["goal"],
            scope=data["scope"],
            created_at=data["created_at"],
            status=data["status"],
            project_id=data.get("project_id"),
            completed_at=data.get("completed_at"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ActionReferenceRecord:
    """Durable correlation reference to a physical or web action."""
    action_id: str
    session_id: str
    action_type: str
    plane: str
    status: str
    provenance: ProvenanceRecord
    target: Optional[str] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ActionReferenceRecord:
        return cls(
            action_id=data["action_id"],
            session_id=data["session_id"],
            action_type=data["action_type"],
            plane=data["plane"],
            status=data["status"],
            provenance=ProvenanceRecord.from_dict(data["provenance"]),
            target=data.get("target"),
            duration_ms=data.get("duration_ms"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TraceReferenceRecord:
    """Durable correlation reference pointing to an authoritative DesktopTraceEvent."""
    event_id: str
    session_id: str
    sequence_monotonic: int
    event_type: str
    plane: str
    provenance: ProvenanceRecord
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TraceReferenceRecord:
        return cls(
            event_id=data["event_id"],
            session_id=data["session_id"],
            sequence_monotonic=int(data["sequence_monotonic"]),
            event_type=data["event_type"],
            plane=data["plane"],
            provenance=ProvenanceRecord.from_dict(data["provenance"]),
            metadata=data.get("metadata", {}),
        )


@dataclass
class EvidenceReferenceRecord:
    """
    Durable correlation reference pointing to an authoritative forensic EvidenceArtifact.
    Contains stable hashes and paths; NEVER stores raw binary screenshot blobs in SQLite.
    """
    evidence_id: str
    session_id: str
    artifact_id: str
    artifact_type: str
    checksum_sha256: str
    relative_path_or_uri: str
    provenance: ProvenanceRecord
    action_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceReferenceRecord:
        return cls(
            evidence_id=data["evidence_id"],
            session_id=data["session_id"],
            artifact_id=data["artifact_id"],
            artifact_type=data["artifact_type"],
            checksum_sha256=data["checksum_sha256"],
            relative_path_or_uri=data["relative_path_or_uri"],
            provenance=ProvenanceRecord.from_dict(data["provenance"]),
            action_id=data.get("action_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class OutcomeRecord:
    """Durable verdict and quality outcome for a review session or milestone."""
    outcome_id: str
    session_id: str
    verdict: str                  # PASS / FAIL / UNVERIFIED
    confidence: float
    provenance: ProvenanceRecord
    error_category: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OutcomeRecord:
        return cls(
            outcome_id=data["outcome_id"],
            session_id=data["session_id"],
            verdict=data["verdict"],
            confidence=float(data["confidence"]),
            provenance=ProvenanceRecord.from_dict(data["provenance"]),
            error_category=data.get("error_category"),
            details=data.get("details", {}),
        )


@dataclass
class ExperienceHealthReport:
    """Health, sizing, and consistency diagnostic for the Experience Store."""
    enabled: bool
    storage_path: str
    database_file: str
    database_size_bytes: int
    schema_version: int
    runtime_version: str
    installation_id: str
    health: str                   # OK / DEGRADED / ERROR
    integrity_check: str          # "ok" from PRAGMA integrity_check or failure text
    last_write: Optional[str] = None
    record_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
