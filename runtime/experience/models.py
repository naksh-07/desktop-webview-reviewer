"""
Experience Store Data Models and Domain Enums (Architecture H).

Defines structured experience facts, references, provenance envelopes,
and scope contracts (SESSION / PROJECT / GLOBAL).
"""

from __future__ import annotations

import json
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
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "INITIALIZING"
    runtime_version: str = field(default_factory=lambda: get_version_info().product_version)
    project_id: Optional[str] = None
    completed_at: Optional[str] = None
    target_executable: Optional[str] = None
    target_pid: Optional[int] = None
    target_hwnd: Optional[str] = None
    target_plane: Optional[str] = None
    scope: ExperienceScope = ExperienceScope.SESSION
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def completion_time(self) -> Optional[str]:
        return self.completed_at

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

    @property
    def execution_status(self) -> str:
        return self.status

    @property
    def completion_time(self) -> Optional[str]:
        return self.completed_at

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

    @property
    def metadata_json(self) -> str:
        return json.dumps(self.metadata)

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

    @property
    def sha256(self) -> str:
        return self.checksum_sha256

    @property
    def relative_path(self) -> str:
        return self.relative_path_or_uri

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
    confidence: float = 1.0
    provenance: Optional[ProvenanceRecord] = None
    error_category: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        outcome_id: str,
        session_id: str,
        verdict: str,
        confidence: float = 1.0,
        provenance: Optional[ProvenanceRecord] = None,
        error_category: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
        iso_timestamp: Optional[str] = None,
        **kwargs: Any,
    ):
        self.outcome_id = outcome_id
        self.session_id = session_id
        self.verdict = verdict
        self.confidence = confidence
        self.error_category = error_category
        self.details = details or {}
        ts = timestamp if timestamp is not None else time.time()
        iso_ts = iso_timestamp or datetime.now(timezone.utc).isoformat()
        self.provenance = provenance or ProvenanceRecord(
            source="VerificationEngine",
            source_type=RecordSourceType.RUNTIME,
            session_id=session_id,
            confidence=confidence,
            timestamp=ts,
            iso_timestamp=iso_ts,
            kind=RecordKind.FACT,
        )

    @property
    def timestamp(self) -> float:
        return self.provenance.timestamp if self.provenance else time.time()

    @property
    def iso_timestamp(self) -> str:
        return self.provenance.iso_timestamp if self.provenance else datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.provenance:
            d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OutcomeRecord:
        prov = ProvenanceRecord.from_dict(data["provenance"]) if "provenance" in data else None
        return cls(
            outcome_id=data["outcome_id"],
            session_id=data["session_id"],
            verdict=data["verdict"],
            confidence=float(data["confidence"]),
            provenance=prov,
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


@dataclass
class NormalizedFailureRecord:
    """
    Durable record of a normalized runtime failure.
    Contains stable failure category, deterministic signature, and non-sensitive context.
    """
    failure_id: str
    session_id: str
    category: str = "UNKNOWN"
    original_classification: str = "UNKNOWN"
    signature: str = ""
    confidence: float = 1.0
    provenance: Optional[ProvenanceRecord] = None
    mission_id: Optional[str] = None
    action_id: Optional[str] = None
    recovery_reference: Optional[str] = None
    trace_reference: Optional[str] = None
    evidence_reference: Optional[str] = None
    safe_context: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __init__(
        self,
        failure_id: str,
        session_id: str,
        category: Optional[str] = None,
        original_classification: str = "UNKNOWN",
        signature: Optional[str] = None,
        confidence: float = 1.0,
        provenance: Optional[ProvenanceRecord] = None,
        mission_id: Optional[str] = None,
        action_id: Optional[str] = None,
        recovery_reference: Optional[str] = None,
        trace_reference: Optional[str] = None,
        evidence_reference: Optional[str] = None,
        safe_context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
        iso_timestamp: Optional[str] = None,
        normalized_category: Optional[str] = None,
        failure_signature: Optional[str] = None,
        action_type: Optional[str] = None,
        plane: Optional[str] = None,
        **kwargs: Any,
    ):
        self.failure_id = failure_id
        self.session_id = session_id
        self.category = category or normalized_category or "UNKNOWN"
        self.original_classification = original_classification
        self.signature = signature or failure_signature or ""
        self.confidence = confidence
        self.mission_id = mission_id
        self.action_id = action_id
        self.recovery_reference = recovery_reference
        self.trace_reference = trace_reference
        self.evidence_reference = evidence_reference
        ctx = dict(safe_context or {})
        if action_type:
            ctx["action_type"] = action_type
        if plane:
            ctx["plane"] = plane
        self.safe_context = ctx
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.iso_timestamp = iso_timestamp or datetime.now(timezone.utc).isoformat()
        self.provenance = provenance or ProvenanceRecord(
            source="FailureNormalizer",
            source_type=RecordSourceType.RUNTIME,
            session_id=self.session_id,
            mission_id=self.mission_id,
            confidence=self.confidence,
            kind=RecordKind.FACT,
        )

    @property
    def normalized_category(self) -> str:
        return self.category

    @property
    def failure_signature(self) -> str:
        return self.signature

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.provenance:
            d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NormalizedFailureRecord:
        prov = ProvenanceRecord.from_dict(data["provenance"]) if isinstance(data.get("provenance"), dict) else data.get("provenance")
        return cls(
            failure_id=data["failure_id"],
            session_id=data["session_id"],
            category=data.get("category", data.get("normalized_category", "UNKNOWN")),
            original_classification=data["original_classification"],
            signature=data.get("signature", data.get("failure_signature", "")),
            confidence=float(data.get("confidence", 1.0)),
            provenance=prov,
            mission_id=data.get("mission_id"),
            action_id=data.get("action_id"),
            recovery_reference=data.get("recovery_reference"),
            trace_reference=data.get("trace_reference"),
            evidence_reference=data.get("evidence_reference"),
            safe_context=data.get("safe_context", {}),
            timestamp=float(data.get("timestamp", time.time())),
            iso_timestamp=data.get("iso_timestamp", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class RecoveryExperienceRecord:
    """
    Durable record of a bounded recovery attempt and its outcome.
    Preserves audit trail linking failure to recovery strategy and final verification.
    """
    recovery_id: str
    session_id: str
    failure_category: str = "UNKNOWN"
    recovery_action: str = "REFRESH_OBSERVATION"
    attempt_number: int = 1
    max_attempts: int = 1
    result: str = "UNKNOWN"
    duration_ms: float = 0.0
    provenance: Optional[ProvenanceRecord] = None
    action_id: Optional[str] = None
    failure_id: Optional[str] = None
    error: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    trace_event_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        recovery_id: str,
        session_id: str,
        failure_category: Optional[str] = None,
        recovery_action: Optional[str] = None,
        attempt_number: int = 1,
        max_attempts: int = 1,
        result: str = "UNKNOWN",
        duration_ms: float = 0.0,
        provenance: Optional[ProvenanceRecord] = None,
        action_id: Optional[str] = None,
        failure_id: Optional[str] = None,
        error: Optional[str] = None,
        evidence_refs: Optional[List[str]] = None,
        trace_event_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        iso_timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        trigger_category: Optional[str] = None,
        action: Optional[str] = None,
        **kwargs: Any,
    ):
        self.recovery_id = recovery_id
        self.session_id = session_id
        self.failure_category = failure_category or trigger_category or "UNKNOWN"
        self.recovery_action = recovery_action or action or "REFRESH_OBSERVATION"
        self.attempt_number = attempt_number
        self.max_attempts = max_attempts
        self.result = result
        self.duration_ms = duration_ms
        self.action_id = action_id
        self.failure_id = failure_id
        self.error = error
        self.evidence_refs = list(evidence_refs or [])
        self.trace_event_id = trace_event_id
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.iso_timestamp = iso_timestamp or datetime.now(timezone.utc).isoformat()
        self.metadata = metadata or {}
        self.provenance = provenance or ProvenanceRecord(
            source="RecoveryEngine",
            source_type=RecordSourceType.RUNTIME,
            session_id=self.session_id,
            kind=RecordKind.FACT,
        )

    @property
    def trigger_category(self) -> str:
        return self.failure_category

    @property
    def action(self) -> str:
        return self.recovery_action

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.provenance:
            d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RecoveryExperienceRecord:
        prov = ProvenanceRecord.from_dict(data["provenance"]) if isinstance(data.get("provenance"), dict) else data.get("provenance")
        return cls(
            recovery_id=data["recovery_id"],
            session_id=data["session_id"],
            failure_category=data.get("failure_category", data.get("trigger_category", "UNKNOWN")),
            recovery_action=data.get("recovery_action", data.get("action", "REFRESH_OBSERVATION")),
            attempt_number=int(data.get("attempt_number", 1)),
            max_attempts=int(data.get("max_attempts", 1)),
            result=data.get("result", "UNKNOWN"),
            duration_ms=float(data.get("duration_ms", 0.0)),
            provenance=prov,
            action_id=data.get("action_id"),
            failure_id=data.get("failure_id"),
            error=data.get("error"),
            evidence_refs=data.get("evidence_refs", []),
            trace_event_id=data.get("trace_event_id"),
            timestamp=float(data.get("timestamp", time.time())),
            iso_timestamp=data.get("iso_timestamp", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class FailureSummaryItem:
    """Historical aggregate metric for a failure category."""
    category: str
    count: int
    latest_timestamp: Optional[str] = None


@dataclass
class FailureSignatureSummary:
    """Historical frequency metric for a deterministic failure signature."""
    signature: str = ""
    category: str = "UNKNOWN"
    count: int = 0
    latest_timestamp: Optional[str] = None
    example_session_id: Optional[str] = None

    def __init__(
        self,
        signature: str = "",
        category: str = "UNKNOWN",
        count: int = 0,
        latest_timestamp: Optional[str] = None,
        example_session_id: Optional[str] = None,
        sample_session: Optional[str] = None,
        failure_signature: Optional[str] = None,
        **kwargs: Any,
    ):
        self.signature = signature or failure_signature or ""
        self.category = category
        self.count = count
        self.latest_timestamp = latest_timestamp
        self.example_session_id = example_session_id or sample_session

    @property
    def sample_session(self) -> Optional[str]:
        return self.example_session_id

    @property
    def failure_signature(self) -> str:
        return self.signature


@dataclass
class RecoveryStatistics:
    """Aggregate statistics for recovery effectiveness."""
    category: Optional[str] = None
    attempt_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    success_rate: float = 0.0
    mean_duration_ms: float = 0.0
    total_attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0
    blocked_attempts: int = 0
    overall_success_rate: float = 0.0
    by_category: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def __init__(
        self,
        category: Optional[str] = None,
        attempt_count: int = 0,
        success_count: int = 0,
        failed_count: int = 0,
        blocked_count: int = 0,
        success_rate: float = 0.0,
        mean_duration_ms: float = 0.0,
        total_attempts: Optional[int] = None,
        successful_attempts: Optional[int] = None,
        failed_attempts: Optional[int] = None,
        blocked_attempts: Optional[int] = None,
        overall_success_rate: Optional[float] = None,
        by_category: Optional[Dict[str, Dict[str, Any]]] = None,
        **kwargs: Any,
    ):
        self.category = category
        self.attempt_count = attempt_count or total_attempts or 0
        self.success_count = success_count or successful_attempts or 0
        self.failed_count = failed_count or failed_attempts or 0
        self.blocked_count = blocked_count or blocked_attempts or 0
        self.success_rate = success_rate if success_rate != 0.0 else (overall_success_rate or 0.0)
        self.mean_duration_ms = mean_duration_ms
        self.total_attempts = self.attempt_count
        self.successful_attempts = self.success_count
        self.failed_attempts = self.failed_count
        self.blocked_attempts = self.blocked_count
        self.overall_success_rate = self.success_rate
        self.by_category = by_category or {}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationDistribution:
    """Distribution of tripartite verification outcomes."""
    pass_count: int = 0
    fail_count: int = 0
    unverified_count: int = 0
    total_outcomes: int = 0
    pass_rate: float = 0.0
    fail_rate: float = 0.0
    unverified_rate: float = 0.0
    total: int = 0

    def __init__(
        self,
        pass_count: int = 0,
        fail_count: int = 0,
        unverified_count: int = 0,
        total_outcomes: Optional[int] = None,
        total: Optional[int] = None,
        pass_rate: float = 0.0,
        fail_rate: float = 0.0,
        unverified_rate: float = 0.0,
        **kwargs: Any,
    ):
        self.pass_count = pass_count
        self.fail_count = fail_count
        self.unverified_count = unverified_count
        tot = total_outcomes if total_outcomes is not None else (total or (pass_count + fail_count + unverified_count))
        self.total_outcomes = tot
        self.total = tot
        self.pass_rate = pass_rate if pass_rate != 0.0 else ((pass_count / tot) if tot > 0 else 0.0)
        self.fail_rate = fail_rate if fail_rate != 0.0 else ((fail_count / tot) if tot > 0 else 0.0)
        self.unverified_rate = unverified_rate if unverified_rate != 0.0 else ((unverified_count / tot) if tot > 0 else 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

