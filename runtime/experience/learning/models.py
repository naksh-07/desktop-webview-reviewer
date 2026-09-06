"""
Data Models, Enums, and Epistemic Contracts for Learning, Governance & Field Intelligence.
Architecture H / Milestone 2.1 Prompt 4.

Defines:
- Observations & Observation Types
- Detected Patterns
- Governed Improvement Candidates & Gate Results
- Governance Records (Human Review Audits)
- Durable Knowledge Representation & Decay States
- Field Intelligence Reports
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from core.version import get_version_info
from runtime.experience.models import (
    ExperienceScope,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    validate_scope_promotion,
)


class ObservationType(str, Enum):
    """Authoritative taxonomy for normalized empirical observations."""
    FAILURE_SIGNATURE = "FAILURE_SIGNATURE"
    RECOVERY_PATTERN = "RECOVERY_PATTERN"
    VERIFICATION_UNKNOWN = "VERIFICATION_UNKNOWN"
    TOOL_PRECEDING_FAILURE = "TOOL_PRECEDING_FAILURE"
    USER_CORRECTION_FOLLOWING_FAILURE = "USER_CORRECTION_FOLLOWING_FAILURE"
    TARGET_RESOLUTION_FAILURE = "TARGET_RESOLUTION_FAILURE"
    ENVIRONMENT_PATTERN = "ENVIRONMENT_PATTERN"


class ObservationStatus(str, Enum):
    """Lifecycle status of an observation."""
    OBSERVED = "OBSERVED"
    RETIRED = "RETIRED"


class PatternType(str, Enum):
    """Categorization of deterministic detected patterns."""
    RECURRING_FAILURE = "RECURRING_FAILURE"
    REPEATED_RECOVERY_REQUIRED = "REPEATED_RECOVERY_REQUIRED"
    AGENT_TOOL_FAILURE_CORRELATION = "AGENT_TOOL_FAILURE_CORRELATION"
    VERIFICATION_AMBIGUITY_CONDITION = "VERIFICATION_AMBIGUITY_CONDITION"
    USER_CORRECTION_SEQUENCE = "USER_CORRECTION_SEQUENCE"
    REPEATED_TARGET_RESOLUTION_FAILURE = "REPEATED_TARGET_RESOLUTION_FAILURE"


class CandidateCategory(str, Enum):
    """Category of system improvement proposed by an Improvement Candidate."""
    RECOVERY_IMPROVEMENT = "RECOVERY_IMPROVEMENT"
    VERIFICATION_STABILITY = "VERIFICATION_STABILITY"
    TARGET_RESOLUTION_ROBUSTNESS = "TARGET_RESOLUTION_ROBUSTNESS"
    TOOL_COORDINATION = "TOOL_COORDINATION"
    ENVIRONMENT_ADAPTATION = "ENVIRONMENT_ADAPTATION"


class RiskLevel(str, Enum):
    """Risk classification associated with an improvement candidate."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CandidateStatus(str, Enum):
    """
    Governed lifecycle state machine for Improvement Candidates:
    OBSERVED -> CANDIDATE -> VALIDATION_REQUIRED -> VALIDATED -> HUMAN_APPROVED -> DURABLE
    Also supports REJECTED, STALE, and SUPERSEDED.
    """
    OBSERVED = "OBSERVED"
    CANDIDATE = "CANDIDATE"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"
    VALIDATED = "VALIDATED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    DURABLE = "DURABLE"
    REJECTED = "REJECTED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class GateStatus(str, Enum):
    """Status result of an evidence threshold gate."""
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class GovernanceDecision(str, Enum):
    """Authoritative decision recorded by human reviewer."""
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    DEPRECATE = "DEPRECATE"


class KnowledgeStatus(str, Enum):
    """Lifecycle and decay status of durable knowledge."""
    DURABLE = "DURABLE"
    REVIEW_DUE = "REVIEW_DUE"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


@dataclass
class GateResult:
    """Individual transparent gate check result for an improvement candidate."""
    gate_name: str
    status: GateStatus
    metric_value: Any
    threshold: Any
    details: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "status": self.status.value if isinstance(self.status, GateStatus) else str(self.status),
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GateResult:
        st = data.get("status", GateStatus.FAIL)
        if isinstance(st, str):
            st = GateStatus(st)
        return cls(
            gate_name=data["gate_name"],
            status=st,
            metric_value=data.get("metric_value"),
            threshold=data.get("threshold"),
            details=data.get("details", ""),
        )


@dataclass
class ObservationRecord:
    """
    Normalized empirical observation derived deterministically from raw experience records.
    Contains stable signature, occurrence counts, and verifiable provenance references.
    """
    observation_id: str
    observation_type: ObservationType
    signature: str
    scope: ExperienceScope = ExperienceScope.SESSION
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    occurrence_count: int = 1
    confidence: float = 1.0
    status: ObservationStatus = ObservationStatus.OBSERVED
    first_observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    first_observed_ts: float = field(default_factory=time.time)
    last_observed_ts: float = field(default_factory=time.time)
    source_refs: List[str] = field(default_factory=list)
    provenance: Optional[ProvenanceRecord] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["observation_type"] = self.observation_type.value if isinstance(self.observation_type, ObservationType) else str(self.observation_type)
        d["scope"] = self.scope.value if isinstance(self.scope, ExperienceScope) else str(self.scope)
        d["status"] = self.status.value if isinstance(self.status, ObservationStatus) else str(self.status)
        if self.provenance:
            d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ObservationRecord:
        ot = data.get("observation_type", ObservationType.FAILURE_SIGNATURE)
        if isinstance(ot, str):
            ot = ObservationType(ot)
        sc = data.get("scope", ExperienceScope.SESSION)
        if isinstance(sc, str):
            sc = ExperienceScope(sc)
        st = data.get("status", ObservationStatus.OBSERVED)
        if isinstance(st, str):
            st = ObservationStatus(st)
        prov = ProvenanceRecord.from_dict(data["provenance"]) if isinstance(data.get("provenance"), dict) else data.get("provenance")

        return cls(
            observation_id=data["observation_id"],
            observation_type=ot,
            signature=data["signature"],
            scope=sc,
            project_id=data.get("project_id"),
            session_id=data.get("session_id"),
            occurrence_count=int(data.get("occurrence_count", 1)),
            confidence=float(data.get("confidence", 1.0)),
            status=st,
            first_observed_at=data.get("first_observed_at", datetime.now(timezone.utc).isoformat()),
            last_observed_at=data.get("last_observed_at", datetime.now(timezone.utc).isoformat()),
            first_observed_ts=float(data.get("first_observed_ts", time.time())),
            last_observed_ts=float(data.get("last_observed_ts", time.time())),
            source_refs=list(data.get("source_refs", [])),
            provenance=prov,
            details=data.get("details", {}),
        )


@dataclass
class DetectedPatternRecord:
    """
    Deterministic detected pattern backed by measurable empirical observations.
    Explainable through underlying observation references.
    """
    pattern_id: str
    pattern_type: PatternType
    signature: str
    summary: str
    scope: ExperienceScope = ExperienceScope.PROJECT
    project_id: Optional[str] = None
    occurrence_count: int = 1
    session_count: int = 1
    confidence: float = 1.0
    first_seen_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    first_seen_ts: float = field(default_factory=time.time)
    last_seen_ts: float = field(default_factory=time.time)
    observation_refs: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["pattern_type"] = self.pattern_type.value if isinstance(self.pattern_type, PatternType) else str(self.pattern_type)
        d["scope"] = self.scope.value if isinstance(self.scope, ExperienceScope) else str(self.scope)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DetectedPatternRecord:
        pt = data.get("pattern_type", PatternType.RECURRING_FAILURE)
        if isinstance(pt, str):
            pt = PatternType(pt)
        sc = data.get("scope", ExperienceScope.PROJECT)
        if isinstance(sc, str):
            sc = ExperienceScope(sc)

        return cls(
            pattern_id=data["pattern_id"],
            pattern_type=pt,
            signature=data["signature"],
            summary=data.get("summary", ""),
            scope=sc,
            project_id=data.get("project_id"),
            occurrence_count=int(data.get("occurrence_count", 1)),
            session_count=int(data.get("session_count", 1)),
            confidence=float(data.get("confidence", 1.0)),
            first_seen_at=data.get("first_seen_at", datetime.now(timezone.utc).isoformat()),
            last_seen_at=data.get("last_seen_at", datetime.now(timezone.utc).isoformat()),
            first_seen_ts=float(data.get("first_seen_ts", time.time())),
            last_seen_ts=float(data.get("last_seen_ts", time.time())),
            observation_refs=list(data.get("observation_refs", [])),
            details=data.get("details", {}),
        )


@dataclass
class ImprovementCandidateRecord:
    """
    Formal proposal representing enough repeated evidence to investigate a possible improvement.
    Not an instruction; not automatically applied. Subject to strict governance.
    """
    candidate_id: str
    category: CandidateCategory
    affected_subsystem: str
    rationale_summary: str
    pattern_id: Optional[str] = None
    scope: ExperienceScope = ExperienceScope.PROJECT
    project_id: Optional[str] = None
    evidence_count: int = 1
    session_count: int = 1
    confidence: float = 1.0
    risk_level: RiskLevel = RiskLevel.MEDIUM
    status: CandidateStatus = CandidateStatus.OBSERVED
    first_seen_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    gate_results: Dict[str, GateResult] = field(default_factory=dict)
    provenance: Optional[ProvenanceRecord] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value if isinstance(self.category, CandidateCategory) else str(self.category)
        d["scope"] = self.scope.value if isinstance(self.scope, ExperienceScope) else str(self.scope)
        d["risk_level"] = self.risk_level.value if isinstance(self.risk_level, RiskLevel) else str(self.risk_level)
        d["status"] = self.status.value if isinstance(self.status, CandidateStatus) else str(self.status)
        d["gate_results"] = {k: v.to_dict() for k, v in self.gate_results.items()}
        if self.provenance:
            d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ImprovementCandidateRecord:
        cat = data.get("category", CandidateCategory.RECOVERY_IMPROVEMENT)
        if isinstance(cat, str):
            cat = CandidateCategory(cat)
        sc = data.get("scope", ExperienceScope.PROJECT)
        if isinstance(sc, str):
            sc = ExperienceScope(sc)
        rl = data.get("risk_level", RiskLevel.MEDIUM)
        if isinstance(rl, str):
            rl = RiskLevel(rl)
        st = data.get("status", CandidateStatus.OBSERVED)
        if isinstance(st, str):
            st = CandidateStatus(st)

        gates = {}
        for k, v in data.get("gate_results", {}).items():
            if isinstance(v, dict):
                gates[k] = GateResult.from_dict(v)
            elif isinstance(v, GateResult):
                gates[k] = v

        prov = ProvenanceRecord.from_dict(data["provenance"]) if isinstance(data.get("provenance"), dict) else data.get("provenance")

        return cls(
            candidate_id=data["candidate_id"],
            category=cat,
            affected_subsystem=data.get("affected_subsystem", "runtime"),
            rationale_summary=data.get("rationale_summary", ""),
            pattern_id=data.get("pattern_id"),
            scope=sc,
            project_id=data.get("project_id"),
            evidence_count=int(data.get("evidence_count", 1)),
            session_count=int(data.get("session_count", 1)),
            confidence=float(data.get("confidence", 1.0)),
            risk_level=rl,
            status=st,
            first_seen_at=data.get("first_seen_at", datetime.now(timezone.utc).isoformat()),
            last_seen_at=data.get("last_seen_at", datetime.now(timezone.utc).isoformat()),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            gate_results=gates,
            provenance=prov,
            metadata=data.get("metadata", {}),
        )


@dataclass
class GovernanceRecord:
    """
    Immutable audit record of a human governance review decision on an improvement candidate.
    """
    governance_id: str
    candidate_id: str
    decision: GovernanceDecision
    decision_scope: ExperienceScope
    reviewer: str
    rationale: str
    decision_timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def reviewer_id(self) -> str:
        return self.reviewer

    @property
    def record_id(self) -> str:
        return self.governance_id

    @property
    def reviewer_notes(self) -> str:
        return self.rationale

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value if isinstance(self.decision, GovernanceDecision) else str(self.decision)
        d["decision_scope"] = self.decision_scope.value if isinstance(self.decision_scope, ExperienceScope) else str(self.decision_scope)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GovernanceRecord:
        dec = data.get("decision", GovernanceDecision.APPROVE)
        if isinstance(dec, str):
            dec = GovernanceDecision(dec)
        sc = data.get("decision_scope", ExperienceScope.PROJECT)
        if isinstance(sc, str):
            sc = ExperienceScope(sc)

        return cls(
            governance_id=data["governance_id"],
            candidate_id=data["candidate_id"],
            decision=dec,
            decision_scope=sc,
            reviewer=data.get("reviewer", "human_operator"),
            rationale=data.get("rationale", ""),
            decision_timestamp=float(data.get("decision_timestamp", time.time())),
            iso_timestamp=data.get("iso_timestamp", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DurableKnowledgeRecord:
    """
    Governed, explicitly approved durable knowledge item.
    Includes template statement, supporting evidence references, expiry/review due date,
    and decay tracking metrics.
    """
    knowledge_id: str
    normalized_statement: str
    version: int = 1
    scope: ExperienceScope = ExperienceScope.PROJECT
    project_id: Optional[str] = None
    candidate_id: Optional[str] = None
    supporting_evidence_refs: List[str] = field(default_factory=list)
    validation_metadata: Dict[str, Any] = field(default_factory=dict)
    approval_metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    status: KnowledgeStatus = KnowledgeStatus.DURABLE
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    review_due_at: Optional[str] = None
    last_confirmed_at: Optional[str] = None
    last_used_at: Optional[str] = None
    superseded_by: Optional[str] = None
    contradiction_count: int = 0
    provenance: Optional[ProvenanceRecord] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["scope"] = self.scope.value if isinstance(self.scope, ExperienceScope) else str(self.scope)
        d["status"] = self.status.value if isinstance(self.status, KnowledgeStatus) else str(self.status)
        if self.provenance:
            d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DurableKnowledgeRecord:
        sc = data.get("scope", ExperienceScope.PROJECT)
        if isinstance(sc, str):
            sc = ExperienceScope(sc)
        st = data.get("status", KnowledgeStatus.DURABLE)
        if isinstance(st, str):
            st = KnowledgeStatus(st)
        prov = ProvenanceRecord.from_dict(data["provenance"]) if isinstance(data.get("provenance"), dict) else data.get("provenance")

        return cls(
            knowledge_id=data["knowledge_id"],
            normalized_statement=data["normalized_statement"],
            version=int(data.get("version", 1)),
            scope=sc,
            project_id=data.get("project_id"),
            candidate_id=data.get("candidate_id"),
            supporting_evidence_refs=list(data.get("supporting_evidence_refs", [])),
            validation_metadata=data.get("validation_metadata", {}),
            approval_metadata=data.get("approval_metadata", {}),
            confidence=float(data.get("confidence", 1.0)),
            status=st,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            review_due_at=data.get("review_due_at"),
            last_confirmed_at=data.get("last_confirmed_at"),
            last_used_at=data.get("last_used_at"),
            superseded_by=data.get("superseded_by"),
            contradiction_count=int(data.get("contradiction_count", 0)),
            provenance=prov,
        )


@dataclass
class FieldIntelligenceReport:
    """
    Descriptive, provenance-backed aggregate summary of accumulated field intelligence.
    Uses 'associated with' rather than speculative causal claims.
    """
    top_recurring_failures: List[Dict[str, Any]] = field(default_factory=list)
    failures_by_action_type: List[Dict[str, Any]] = field(default_factory=list)
    recovery_success_by_strategy: List[Dict[str, Any]] = field(default_factory=list)
    verification_distribution: Dict[str, Any] = field(default_factory=dict)
    agent_tool_failures: List[Dict[str, Any]] = field(default_factory=list)
    user_corrections: List[Dict[str, Any]] = field(default_factory=list)
    frequent_candidates: List[Dict[str, Any]] = field(default_factory=list)
    candidate_validation_status: Dict[str, int] = field(default_factory=dict)
    knowledge_due_for_review: List[Dict[str, Any]] = field(default_factory=list)
    stale_or_superseded_knowledge: List[Dict[str, Any]] = field(default_factory=list)
    experience_volume_by_scope: Dict[str, Any] = field(default_factory=dict)
    emerging_patterns: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
