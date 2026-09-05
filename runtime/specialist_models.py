"""
Specialist Subagent Domain Models, Delegation Contracts & Result Envelopes (Architecture H).
Defines formal operational data structures for subordinate specialists:
Explorer, Tester, Reality Inspector, Debugger, and Evidence Specialist.
Enforces strict parameter boundaries, timeout budgets, and untrusted observation guarantees.
"""

from __future__ import annotations
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Any

from runtime.specialist_contracts import (
    SpecialistRole,
    SpecialistContract,
    SpecialistRegistry,
)
from runtime.trace_engine import redact_sensitive_trace_payload


class SpecialistLifecycleState(str, Enum):
    """Deterministic lifecycle state of a specialist subagent execution."""
    DELEGATED = "DELEGATED"
    VALIDATING = "VALIDATING"
    RUNNING = "RUNNING"
    OBSERVING = "OBSERVING"
    ACTING = "ACTING"
    COLLECTING_RESULT = "COLLECTING_RESULT"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            SpecialistLifecycleState.COMPLETED,
            SpecialistLifecycleState.REJECTED,
            SpecialistLifecycleState.TIMED_OUT,
            SpecialistLifecycleState.CANCELLED,
            SpecialistLifecycleState.FAILED,
        )


class SpecialistResultStatus(str, Enum):
    """Explicit verdict states for a specialist result."""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class DelegationScope:
    """
    Explicit scope boundaries constraining a specialist invocation.
    Prevents unauthorized exploration, out-of-session interaction, and scope creep.
    """
    session_id: str
    target_id: Optional[str] = None
    target_epoch: Optional[int] = None
    expected_pid: Optional[int] = None
    allowed_screens: Optional[List[str]] = None
    workflow_steps_allowed: Optional[List[str]] = None
    max_actions: int = 10
    custom_constraints: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_id": self.target_id,
            "target_epoch": self.target_epoch,
            "expected_pid": self.expected_pid,
            "allowed_screens": list(self.allowed_screens) if self.allowed_screens else None,
            "workflow_steps_allowed": list(self.workflow_steps_allowed) if self.workflow_steps_allowed else None,
            "max_actions": self.max_actions,
            "custom_constraints": self.custom_constraints,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DelegationScope:
        return cls(
            session_id=data["session_id"],
            target_id=data.get("target_id"),
            target_epoch=data.get("target_epoch"),
            expected_pid=data.get("expected_pid"),
            allowed_screens=data.get("allowed_screens"),
            workflow_steps_allowed=data.get("workflow_steps_allowed"),
            max_actions=data.get("max_actions", 10),
            custom_constraints=data.get("custom_constraints", {}),
        )


@dataclass(frozen=True)
class SpecialistDelegation:
    """
    Concrete delegation contract from the Controlling Orchestrator to a subordinate specialist.
    Establishes WHO, WHAT, SCOPE, TOOLS, TIME (deadline), and AUTHORITY.
    """
    role: SpecialistRole
    task: str
    scope: DelegationScope
    permitted_tools: Set[str]
    timeout_sec: float = 30.0
    delegation_id: str = field(default_factory=lambda: f"delg_{uuid.uuid4().hex[:12]}")
    parent_action_id: Optional[str] = None
    allow_state_mutation: bool = False
    expected_output_format: str = "structured"
    parameters: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def deadline(self) -> float:
        return self.created_at + self.timeout_sec

    def is_expired(self, now: Optional[float] = None) -> bool:
        t = now if now is not None else time.time()
        return t > self.deadline

    def get_remaining_timeout(self, now: Optional[float] = None) -> float:
        t = now if now is not None else time.time()
        remaining = self.deadline - t
        return max(0.0, remaining)

    def validate(
        self,
        current_session_id: str,
        current_epoch: Optional[int] = None,
        current_pid: Optional[int] = None,
        now: Optional[float] = None,
    ) -> List[str]:
        """
        Validates the delegation against session state and constitutional boundaries.
        Returns a list of rejection reasons. If empty, delegation is valid.
        """
        rejections: List[str] = []

        # 1. Session boundary check
        if self.scope.session_id != current_session_id:
            rejections.append(
                f"Session mismatch: delegation targeted session '{self.scope.session_id}' but current session is '{current_session_id}'"
            )

        # 2. Expiration check
        if self.is_expired(now):
            rejections.append(
                f"Delegation expired: deadline was {self.deadline:.2f}, current time is {(now or time.time()):.2f}"
            )

        # 3. Epoch check (stale delegation protection)
        if (
            self.scope.target_epoch is not None
            and current_epoch is not None
            and self.scope.target_epoch != current_epoch
        ):
            rejections.append(
                f"Stale observation epoch: delegation epoch={self.scope.target_epoch} != current epoch={current_epoch}"
            )

        # 4. Process PID check (process recycling protection)
        if (
            self.scope.expected_pid is not None
            and current_pid is not None
            and self.scope.expected_pid != current_pid
        ):
            rejections.append(
                f"Target process PID mismatch: expected PID={self.scope.expected_pid} != actual PID={current_pid}"
            )

        # 5. Role contract boundary check
        contract = SpecialistRegistry.get_contract(self.role)
        for tool in self.permitted_tools:
            if not contract.validate_tool_access(tool):
                rejections.append(
                    f"Forbidden tool for role {self.role.value}: '{tool}' is not in permitted tools {sorted(list(contract.permitted_tools))}"
                )

        # 6. Read-only mutation check
        if contract.is_read_only and self.allow_state_mutation:
            rejections.append(
                f"Constitutional violation: role {self.role.value} is read-only; cannot grant allow_state_mutation=True"
            )

        return rejections

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delegation_id": self.delegation_id,
            "role": self.role.value if isinstance(self.role, SpecialistRole) else str(self.role),
            "task": self.task,
            "scope": self.scope.to_dict(),
            "permitted_tools": sorted(list(self.permitted_tools)),
            "timeout_sec": self.timeout_sec,
            "deadline": self.deadline,
            "parent_action_id": self.parent_action_id,
            "allow_state_mutation": self.allow_state_mutation,
            "expected_output_format": self.expected_output_format,
            "parameters": self.parameters,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SpecialistDelegation:
        role = SpecialistRole(data["role"]) if data.get("role") in SpecialistRole._value2member_map_ else SpecialistRole(data["role"])
        return cls(
            delegation_id=data.get("delegation_id", f"delg_{uuid.uuid4().hex[:12]}"),
            role=role,
            task=data["task"],
            scope=DelegationScope.from_dict(data["scope"]),
            permitted_tools=set(data.get("permitted_tools", [])),
            timeout_sec=data.get("timeout_sec", 30.0),
            parent_action_id=data.get("parent_action_id"),
            allow_state_mutation=data.get("allow_state_mutation", False),
            expected_output_format=data.get("expected_output_format", "structured"),
            parameters=data.get("parameters", {}),
            created_at=data.get("created_at", time.time()),
        )


@dataclass(frozen=True)
class ToolAuditRecord:
    """
    Audit entry for an individual tool call made by a specialist subagent.
    Guarantees traceability of who called what under which delegation.
    """
    specialist_id: str
    role: SpecialistRole
    delegation_id: str
    tool: str
    timestamp: float
    duration_ms: float
    arguments_digest: str
    authorization_result: str   # "AUTHORIZED", "REJECTED_UNPERMITTED_TOOL", "REJECTED_MUTATION_FORBIDDEN"
    result_status: str          # "SUCCESS", "ERROR"
    error: Optional[str] = None
    audit_id: str = field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:12]}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "specialist_id": self.specialist_id,
            "role": self.role.value if isinstance(self.role, SpecialistRole) else str(self.role),
            "delegation_id": self.delegation_id,
            "tool": self.tool,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "arguments_digest": self.arguments_digest,
            "authorization_result": self.authorization_result,
            "result_status": self.result_status,
            "error": self.error,
        }


@dataclass
class SpecialistResult:
    """
    Universal result envelope returned by all five subordinate specialists.
    Standardizes answers, observations, proof links, and execution diagnostics.
    """
    specialist_id: str
    role: SpecialistRole
    delegation_id: str
    session_id: str
    status: SpecialistResultStatus
    answer: str
    observations: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    trace_refs: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    confidence: float = 1.0
    duration_ms: float = 0.0
    tools_used: List[str] = field(default_factory=list)
    lifecycle_history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "specialist_id": self.specialist_id,
            "role": self.role.value if isinstance(self.role, SpecialistRole) else str(self.role),
            "delegation_id": self.delegation_id,
            "session_id": self.session_id,
            "status": self.status.value if isinstance(self.status, SpecialistResultStatus) else str(self.status),
            "answer": self.answer,
            "observations": self.observations,
            "evidence_refs": self.evidence_refs,
            "trace_refs": self.trace_refs,
            "limitations": self.limitations,
            "errors": self.errors,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "tools_used": self.tools_used,
            "lifecycle_history": self.lifecycle_history,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SpecialistResult:
        role = SpecialistRole(data["role"]) if data.get("role") in SpecialistRole._value2member_map_ else SpecialistRole(data["role"])
        status = SpecialistResultStatus(data["status"]) if data.get("status") in SpecialistResultStatus._value2member_map_ else SpecialistResultStatus(data["status"])
        return cls(
            specialist_id=data["specialist_id"],
            role=role,
            delegation_id=data["delegation_id"],
            session_id=data["session_id"],
            status=status,
            answer=data.get("answer", ""),
            observations=data.get("observations", {}),
            evidence_refs=data.get("evidence_refs", []),
            trace_refs=data.get("trace_refs", []),
            limitations=data.get("limitations", []),
            errors=data.get("errors", []),
            confidence=data.get("confidence", 1.0),
            duration_ms=data.get("duration_ms", 0.0),
            tools_used=data.get("tools_used", []),
            lifecycle_history=data.get("lifecycle_history", []),
            created_at=data.get("created_at", time.time()),
        )
