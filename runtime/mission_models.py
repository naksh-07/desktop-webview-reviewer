"""
Canonical Review Mission Domain Models, Lifecycle & Result Contracts (Phases 17–18).
Defines the authoritative ReviewMission, DiscoveryCandidate, ReviewPlan,
and ReviewMissionResult models.
Enforces mission authority immutability and the Anti-God-Agent boundary:
The controlling agent decides WHAT and WHY; Reviewer decides HOW.
"""

from __future__ import annotations
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Any

from runtime.specialist_contracts import SpecialistRole
from runtime.errors import DesktopAutomationException


class MissionAuthorityMutatedException(DesktopAutomationException):
    """Raised when an unauthorized attempt is made to mutate mission authority."""
    pass


class InvalidMissionTransitionException(DesktopAutomationException):
    """Raised when an invalid mission lifecycle transition is attempted."""
    pass


class MissionLifecycleState(str, Enum):
    """Deterministic lifecycle states of a canonical ReviewMission."""
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    ADMITTED = "ADMITTED"
    DISCOVERING = "DISCOVERING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COLLECTING_EVIDENCE = "COLLECTING_EVIDENCE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    REJECTED = "REJECTED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            MissionLifecycleState.COMPLETED,
            MissionLifecycleState.FAILED,
            MissionLifecycleState.UNVERIFIED,
            MissionLifecycleState.CANCELLED,
            MissionLifecycleState.TIMED_OUT,
            MissionLifecycleState.REJECTED,
        )


# Valid state transitions matrix
ALLOWED_MISSION_TRANSITIONS: Dict[MissionLifecycleState, Set[MissionLifecycleState]] = {
    MissionLifecycleState.CREATED: {
        MissionLifecycleState.VALIDATING,
        MissionLifecycleState.CANCELLED,
        MissionLifecycleState.REJECTED,
    },
    MissionLifecycleState.VALIDATING: {
        MissionLifecycleState.ADMITTED,
        MissionLifecycleState.REJECTED,
        MissionLifecycleState.CANCELLED,
    },
    MissionLifecycleState.ADMITTED: {
        MissionLifecycleState.DISCOVERING,
        MissionLifecycleState.CANCELLED,
        MissionLifecycleState.TIMED_OUT,
        MissionLifecycleState.FAILED,
    },
    MissionLifecycleState.DISCOVERING: {
        MissionLifecycleState.PLANNING,
        MissionLifecycleState.COMPLETED,  # Bounded discovery found no relevant targets -> settle cleanly
        MissionLifecycleState.UNVERIFIED,
        MissionLifecycleState.CANCELLED,
        MissionLifecycleState.TIMED_OUT,
        MissionLifecycleState.FAILED,
    },
    MissionLifecycleState.PLANNING: {
        MissionLifecycleState.EXECUTING,
        MissionLifecycleState.UNVERIFIED,
        MissionLifecycleState.CANCELLED,
        MissionLifecycleState.TIMED_OUT,
        MissionLifecycleState.FAILED,
    },
    MissionLifecycleState.EXECUTING: {
        MissionLifecycleState.VERIFYING,
        MissionLifecycleState.COLLECTING_EVIDENCE,
        MissionLifecycleState.COMPLETED,
        MissionLifecycleState.FAILED,
        MissionLifecycleState.UNVERIFIED,
        MissionLifecycleState.CANCELLED,
        MissionLifecycleState.TIMED_OUT,
    },
    MissionLifecycleState.VERIFYING: {
        MissionLifecycleState.COLLECTING_EVIDENCE,
        MissionLifecycleState.EXECUTING,  # Re-execute step if recovery occurred
        MissionLifecycleState.COMPLETED,
        MissionLifecycleState.FAILED,
        MissionLifecycleState.UNVERIFIED,
        MissionLifecycleState.CANCELLED,
        MissionLifecycleState.TIMED_OUT,
    },
    MissionLifecycleState.COLLECTING_EVIDENCE: {
        MissionLifecycleState.COMPLETED,
        MissionLifecycleState.FAILED,
        MissionLifecycleState.UNVERIFIED,
        MissionLifecycleState.CANCELLED,
        MissionLifecycleState.TIMED_OUT,
    },
    # Terminal states have no outbound transitions
    MissionLifecycleState.COMPLETED: set(),
    MissionLifecycleState.FAILED: set(),
    MissionLifecycleState.UNVERIFIED: set(),
    MissionLifecycleState.CANCELLED: set(),
    MissionLifecycleState.TIMED_OUT: set(),
    MissionLifecycleState.REJECTED: set(),
}


@dataclass
class ReviewMission:
    """
    Canonical Review Mission authority object.
    Represents explicit authority granted by the controlling agent (Antigravity / TeamPreview).
    Immutable once admitted: Reviewer cannot alter objective, scope, criteria, surfaces,
    specialist roles, or budgets.
    """
    session_id: str
    objective: str
    declared_scope: List[str]
    allowed_surfaces: List[str]
    prohibited_surfaces: List[str]
    acceptance_criteria: List[str]
    mission_id: str = field(default_factory=lambda: f"msn_{uuid.uuid4().hex[:12]}")
    app_identity: Dict[str, Any] = field(default_factory=dict)
    authorized_specialist_roles: List[SpecialistRole] = field(default_factory=lambda: [
        SpecialistRole.EXPLORER,
        SpecialistRole.TESTER,
        SpecialistRole.REALITY_INSPECTOR,
        SpecialistRole.DEBUGGER,
        SpecialistRole.EVIDENCE_SPECIALIST,
    ])
    max_duration_sec: float = 120.0
    max_actions: int = 20
    max_delegations: int = 10
    max_recoveries: int = 3
    evidence_requirements: List[str] = field(default_factory=lambda: ["manifest", "screenshot", "trace"])
    stopping_conditions: List[str] = field(default_factory=lambda: ["acceptance_criteria_satisfied", "budget_exhausted", "unrecoverable_failure"])
    orchestrator_identity: str = "antigravity"
    correlation_metadata: Dict[str, Any] = field(default_factory=dict)
    lifecycle_status: MissionLifecycleState = MissionLifecycleState.CREATED
    is_admitted: bool = False
    created_at: float = field(default_factory=time.time)
    admitted_at: Optional[float] = None
    completed_at: Optional[float] = None
    lifecycle_history: List[Dict[str, Any]] = field(default_factory=list)
    _authority_digest: Optional[str] = None

    def __post_init__(self) -> None:
        # Convert any string roles to SpecialistRole enum
        cleaned_roles: List[SpecialistRole] = []
        for r in self.authorized_specialist_roles:
            if isinstance(r, SpecialistRole):
                cleaned_roles.append(r)
            elif isinstance(r, str) and r in SpecialistRole._value2member_map_:
                cleaned_roles.append(SpecialistRole(r))
            else:
                cleaned_roles.append(SpecialistRole(str(r)))
        self.authorized_specialist_roles = cleaned_roles

        if not self.lifecycle_history:
            self.lifecycle_history.append({
                "from_state": None,
                "to_state": self.lifecycle_status.value,
                "timestamp": self.created_at,
                "reason": "Mission created",
            })

    def compute_authority_hash(self) -> str:
        """Computes a SHA-256 digest of immutable authority fields."""
        payload = {
            "mission_id": self.mission_id,
            "session_id": self.session_id,
            "objective": self.objective,
            "declared_scope": sorted(self.declared_scope),
            "allowed_surfaces": sorted(self.allowed_surfaces),
            "prohibited_surfaces": sorted(self.prohibited_surfaces),
            "acceptance_criteria": sorted(self.acceptance_criteria),
            "authorized_specialist_roles": sorted([r.value for r in self.authorized_specialist_roles]),
            "max_duration_sec": self.max_duration_sec,
            "max_actions": self.max_actions,
            "max_delegations": self.max_delegations,
            "max_recoveries": self.max_recoveries,
            "stopping_conditions": sorted(self.stopping_conditions),
            "orchestrator_identity": self.orchestrator_identity,
        }
        raw = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def seal_authority(self) -> None:
        """Seals the authority fields at admission gate."""
        self._authority_digest = self.compute_authority_hash()
        self.is_admitted = True
        self.admitted_at = time.time()

    def verify_authority_integrity(self) -> bool:
        """
        Verifies that Reviewer has not mutated authority fields during execution.
        Raises MissionAuthorityMutatedException if modified.
        """
        if self._authority_digest is None:
            return True  # Not yet admitted
        current = self.compute_authority_hash()
        if current != self._authority_digest:
            raise MissionAuthorityMutatedException(
                f"Constitutional violation: Mission {self.mission_id} authority fields were mutated during execution! "
                f"Expected digest {self._authority_digest[:8]}, current digest {current[:8]}"
            )
        return True

    def transition_to(self, new_state: MissionLifecycleState, reason: Optional[str] = None) -> None:
        """
        Performs a deterministic, validated lifecycle state transition.
        Enforces state transition graph and verifies authority integrity.
        """
        self.verify_authority_integrity()
        current_state = self.lifecycle_status

        allowed = ALLOWED_MISSION_TRANSITIONS.get(current_state, set())
        if new_state not in allowed:
            raise InvalidMissionTransitionException(
                f"Invalid mission lifecycle transition for {self.mission_id}: "
                f"{current_state.value} -> {new_state.value} is not permitted."
            )

        now = time.time()
        self.lifecycle_status = new_state
        if new_state.is_terminal:
            self.completed_at = now

        self.lifecycle_history.append({
            "from_state": current_state.value,
            "to_state": new_state.value,
            "timestamp": now,
            "reason": reason or f"Transition to {new_state.value}",
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "session_id": self.session_id,
            "app_identity": self.app_identity,
            "objective": self.objective,
            "declared_scope": list(self.declared_scope),
            "allowed_surfaces": list(self.allowed_surfaces),
            "prohibited_surfaces": list(self.prohibited_surfaces),
            "acceptance_criteria": list(self.acceptance_criteria),
            "authorized_specialist_roles": [r.value for r in self.authorized_specialist_roles],
            "max_duration_sec": self.max_duration_sec,
            "max_actions": self.max_actions,
            "max_delegations": self.max_delegations,
            "max_recoveries": self.max_recoveries,
            "evidence_requirements": list(self.evidence_requirements),
            "stopping_conditions": list(self.stopping_conditions),
            "orchestrator_identity": self.orchestrator_identity,
            "correlation_metadata": self.correlation_metadata,
            "lifecycle_status": self.lifecycle_status.value,
            "is_admitted": self.is_admitted,
            "created_at": self.created_at,
            "admitted_at": self.admitted_at,
            "completed_at": self.completed_at,
            "lifecycle_history": self.lifecycle_history,
            "authority_digest": self._authority_digest,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReviewMission:
        status_val = data.get("lifecycle_status", MissionLifecycleState.CREATED.value)
        status = MissionLifecycleState(status_val) if status_val in MissionLifecycleState._value2member_map_ else MissionLifecycleState(status_val)
        roles = [
            SpecialistRole(r) if r in SpecialistRole._value2member_map_ else SpecialistRole(str(r))
            for r in data.get("authorized_specialist_roles", [])
        ]
        mission = cls(
            mission_id=data.get("mission_id", f"msn_{uuid.uuid4().hex[:12]}"),
            session_id=data["session_id"],
            app_identity=data.get("app_identity", {}),
            objective=data["objective"],
            declared_scope=data.get("declared_scope", []),
            allowed_surfaces=data.get("allowed_surfaces", []),
            prohibited_surfaces=data.get("prohibited_surfaces", []),
            acceptance_criteria=data.get("acceptance_criteria", []),
            authorized_specialist_roles=roles or [
                SpecialistRole.EXPLORER,
                SpecialistRole.TESTER,
                SpecialistRole.REALITY_INSPECTOR,
                SpecialistRole.DEBUGGER,
                SpecialistRole.EVIDENCE_SPECIALIST,
            ],
            max_duration_sec=float(data.get("max_duration_sec", 120.0)),
            max_actions=int(data.get("max_actions", 20)),
            max_delegations=int(data.get("max_delegations", 10)),
            max_recoveries=int(data.get("max_recoveries", 3)),
            evidence_requirements=data.get("evidence_requirements", ["manifest", "screenshot", "trace"]),
            stopping_conditions=data.get("stopping_conditions", ["acceptance_criteria_satisfied", "budget_exhausted"]),
            orchestrator_identity=data.get("orchestrator_identity", "antigravity"),
            correlation_metadata=data.get("correlation_metadata", {}),
            lifecycle_status=status,
            is_admitted=data.get("is_admitted", False),
            created_at=data.get("created_at", time.time()),
            admitted_at=data.get("admitted_at"),
            completed_at=data.get("completed_at"),
            lifecycle_history=data.get("lifecycle_history", []),
            _authority_digest=data.get("authority_digest"),
        )
        return mission

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass(frozen=True)
class DiscoveryCandidate:
    """
    Provenance-backed review candidate identified by bounded discovery.
    Every candidate MUST trace directly back to an authorized mission acceptance criterion and scope.
    """
    candidate_id: str
    mission_id: str
    scope_reference: str
    acceptance_criterion_reference: str
    technical_rationale: str
    required_specialist: SpecialistRole
    estimated_action_cost: int
    risk: str  # "LOW", "MEDIUM", "HIGH"
    required_evidence: List[str]
    action_type: str = "assert"
    target_ref: Optional[str] = None
    target_name: Optional[str] = None
    assertion_details: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "mission_id": self.mission_id,
            "scope_reference": self.scope_reference,
            "acceptance_criterion_reference": self.acceptance_criterion_reference,
            "technical_rationale": self.technical_rationale,
            "required_specialist": self.required_specialist.value,
            "estimated_action_cost": self.estimated_action_cost,
            "risk": self.risk,
            "required_evidence": list(self.required_evidence),
            "action_type": self.action_type,
            "target_ref": self.target_ref,
            "target_name": self.target_name,
            "assertion_details": self.assertion_details,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DiscoveryCandidate:
        role_val = data["required_specialist"]
        role = SpecialistRole(role_val) if role_val in SpecialistRole._value2member_map_ else SpecialistRole(str(role_val))
        return cls(
            candidate_id=data["candidate_id"],
            mission_id=data["mission_id"],
            scope_reference=data["scope_reference"],
            acceptance_criterion_reference=data["acceptance_criterion_reference"],
            technical_rationale=data["technical_rationale"],
            required_specialist=role,
            estimated_action_cost=int(data.get("estimated_action_cost", 1)),
            risk=data.get("risk", "LOW"),
            required_evidence=data.get("required_evidence", []),
            action_type=data.get("action_type", "assert"),
            target_ref=data.get("target_ref"),
            target_name=data.get("target_name"),
            assertion_details=data.get("assertion_details", {}),
            parameters=data.get("parameters", {}),
        )


@dataclass
class ReviewPlanStep:
    """An individual execution step in a subordinate ReviewPlan."""
    step_id: str
    mission_id: str
    candidate_id: str
    acceptance_criterion: str
    specialist_role: SpecialistRole
    expected_observation: str
    expected_assertion: str
    evidence_requirement: List[str]
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: str = "PENDING"  # "PENDING", "RUNNING", "COMPLETED", "FAILED", "SKIPPED", "UNVERIFIED"
    delegation_id: Optional[str] = None
    result_summary: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "mission_id": self.mission_id,
            "candidate_id": self.candidate_id,
            "acceptance_criterion": self.acceptance_criterion,
            "specialist_role": self.specialist_role.value,
            "expected_observation": self.expected_observation,
            "expected_assertion": self.expected_assertion,
            "evidence_requirement": list(self.evidence_requirement),
            "parameters": self.parameters,
            "status": self.status,
            "delegation_id": self.delegation_id,
            "result_summary": self.result_summary,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReviewPlanStep:
        role_val = data["specialist_role"]
        role = SpecialistRole(role_val) if role_val in SpecialistRole._value2member_map_ else SpecialistRole(str(role_val))
        return cls(
            step_id=data["step_id"],
            mission_id=data["mission_id"],
            candidate_id=data["candidate_id"],
            acceptance_criterion=data["acceptance_criterion"],
            specialist_role=role,
            expected_observation=data["expected_observation"],
            expected_assertion=data["expected_assertion"],
            evidence_requirement=data.get("evidence_requirement", []),
            parameters=data.get("parameters", {}),
            status=data.get("status", "PENDING"),
            delegation_id=data.get("delegation_id"),
            result_summary=data.get("result_summary"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )


@dataclass
class ReviewPlan:
    """
    Subordinate execution plan generated from mission-authorized candidates.
    Can order authorized work; CANNOT create new authority or expand scope.
    """
    plan_id: str
    mission_id: str
    steps: List[ReviewPlanStep]
    created_at: float = field(default_factory=time.time)
    total_estimated_actions: int = 0
    total_estimated_delegations: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "mission_id": self.mission_id,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "total_estimated_actions": self.total_estimated_actions,
            "total_estimated_delegations": self.total_estimated_delegations,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReviewPlan:
        steps = [ReviewPlanStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            plan_id=data["plan_id"],
            mission_id=data["mission_id"],
            steps=steps,
            created_at=data.get("created_at", time.time()),
            total_estimated_actions=data.get("total_estimated_actions", 0),
            total_estimated_delegations=data.get("total_estimated_delegations", len(steps)),
        )


@dataclass(frozen=True)
class AdmissionResult:
    """Authoritative result returned by the Mission Admission Gate."""
    is_admitted: bool
    mission_id: str
    rejections: List[str] = field(default_factory=list)
    admitted_mission: Optional[ReviewMission] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_admitted": self.is_admitted,
            "mission_id": self.mission_id,
            "rejections": list(self.rejections),
            "admitted_mission": self.admitted_mission.to_dict() if self.admitted_mission else None,
        }


@dataclass
class ReviewMissionResult:
    """
    Universal structured result envelope for an autonomous ReviewMission.
    Preserves tripartite verdict discipline (PASS, FAIL, UNVERIFIED) and failure evidence.
    """
    mission_id: str
    session_id: str
    final_status: MissionLifecycleState
    technical_verdict: str  # "PASS", "FAIL", "UNVERIFIED"
    completed_steps: List[Dict[str, Any]] = field(default_factory=list)
    failed_steps: List[Dict[str, Any]] = field(default_factory=list)
    unverified_steps: List[Dict[str, Any]] = field(default_factory=list)
    observations: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    recovery_attempts: List[Dict[str, Any]] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    trace_refs: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    confidence: float = 1.0
    duration_ms: float = 0.0
    budget_usage: Dict[str, Any] = field(default_factory=dict)
    cancellation_reason: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "session_id": self.session_id,
            "final_status": self.final_status.value,
            "technical_verdict": self.technical_verdict,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "unverified_steps": self.unverified_steps,
            "observations": self.observations,
            "diagnostics": self.diagnostics,
            "recovery_attempts": self.recovery_attempts,
            "evidence_refs": self.evidence_refs,
            "trace_refs": self.trace_refs,
            "limitations": self.limitations,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "budget_usage": self.budget_usage,
            "cancellation_reason": self.cancellation_reason,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReviewMissionResult:
        status_val = data["final_status"]
        status = MissionLifecycleState(status_val) if status_val in MissionLifecycleState._value2member_map_ else MissionLifecycleState(str(status_val))
        return cls(
            mission_id=data["mission_id"],
            session_id=data["session_id"],
            final_status=status,
            technical_verdict=data["technical_verdict"],
            completed_steps=data.get("completed_steps", []),
            failed_steps=data.get("failed_steps", []),
            unverified_steps=data.get("unverified_steps", []),
            observations=data.get("observations", {}),
            diagnostics=data.get("diagnostics", []),
            recovery_attempts=data.get("recovery_attempts", []),
            evidence_refs=data.get("evidence_refs", []),
            trace_refs=data.get("trace_refs", []),
            limitations=data.get("limitations", []),
            confidence=data.get("confidence", 1.0),
            duration_ms=data.get("duration_ms", 0.0),
            budget_usage=data.get("budget_usage", {}),
            cancellation_reason=data.get("cancellation_reason"),
            created_at=data.get("created_at", time.time()),
        )
