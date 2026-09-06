"""
Data models for Antigravity Experience persistence and correlation.

Defines durable records persisted to the Experience Store for:
- Agent sessions and turns
- Sanitized tool calls
- Subagent delegations
- Safe artifact references
- User/agent correction records
- Relational correlation links between Antigravity and DWR
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from runtime.experience.antigravity.contracts import CorrelationConfidence, UserCorrectionType


@dataclass
class AgentSessionRecord:
    """Durable record of an Antigravity agent session / conversation."""
    agent_session_id: str
    conversation_id: str
    agent_id: Optional[str] = None
    workspace_id: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    status: str = "ACTIVE"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentSessionRecord:
        return cls(
            agent_session_id=data["agent_session_id"],
            conversation_id=data["conversation_id"],
            agent_id=data.get("agent_id"),
            workspace_id=data.get("workspace_id"),
            started_at=data.get("started_at") or datetime.now(timezone.utc).isoformat(),
            completed_at=data.get("completed_at"),
            status=data.get("status", "ACTIVE"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AgentTurnRecord:
    """Durable record of an individual agent step / turn."""
    turn_id: str
    agent_session_id: str
    conversation_id: Optional[str] = None
    parent_turn_id: Optional[str] = None
    step_index: Optional[int] = None
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "COMPLETED"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentTurnRecord:
        return cls(
            turn_id=data["turn_id"],
            agent_session_id=data["agent_session_id"],
            conversation_id=data.get("conversation_id"),
            parent_turn_id=data.get("parent_turn_id"),
            step_index=data.get("step_index"),
            timestamp=float(data.get("timestamp", time.time())),
            iso_timestamp=data.get("iso_timestamp") or datetime.now(timezone.utc).isoformat(),
            status=data.get("status", "COMPLETED"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AgentToolCallRecord:
    """
    Durable record of an Antigravity tool execution.
    Stores only safe normalized summaries; never stores raw sensitive payloads.
    """
    tool_call_id: str
    turn_id: Optional[str] = None
    agent_session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    tool_name: str = "unknown"
    tool_category: str = "generic"
    success: bool = True
    error_class: Optional[str] = None
    duration_ms: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    safe_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentToolCallRecord:
        return cls(
            tool_call_id=data["tool_call_id"],
            turn_id=data.get("turn_id"),
            agent_session_id=data.get("agent_session_id"),
            conversation_id=data.get("conversation_id"),
            tool_name=data.get("tool_name", "unknown"),
            tool_category=data.get("tool_category", "generic"),
            success=bool(data.get("success", True)),
            error_class=data.get("error_class"),
            duration_ms=float(data["duration_ms"]) if data.get("duration_ms") is not None else None,
            timestamp=float(data.get("timestamp", time.time())),
            iso_timestamp=data.get("iso_timestamp") or datetime.now(timezone.utc).isoformat(),
            safe_summary=data.get("safe_summary", {}),
        )


@dataclass
class AgentSubagentRecord:
    """Durable record of subagent delegation relationships."""
    subagent_id: str
    parent_agent_id: Optional[str] = None
    delegation_id: Optional[str] = None
    conversation_id: Optional[str] = None
    agent_session_id: Optional[str] = None
    status: str = "COMPLETED"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentSubagentRecord:
        return cls(
            subagent_id=data["subagent_id"],
            parent_agent_id=data.get("parent_agent_id"),
            delegation_id=data.get("delegation_id"),
            conversation_id=data.get("conversation_id"),
            agent_session_id=data.get("agent_session_id"),
            status=data.get("status", "COMPLETED"),
            created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            completed_at=data.get("completed_at"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AgentArtifactRecord:
    """
    Durable reference to an Antigravity artifact.
    Contains metadata and safe references only; never stores artifact binaries or full contents.
    """
    artifact_id: str
    artifact_type: str
    safe_reference: str
    agent_session_id: Optional[str] = None
    turn_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentArtifactRecord:
        return cls(
            artifact_id=data["artifact_id"],
            artifact_type=data["artifact_type"],
            safe_reference=data["safe_reference"],
            agent_session_id=data.get("agent_session_id"),
            turn_id=data.get("turn_id"),
            timestamp=float(data.get("timestamp", time.time())),
            iso_timestamp=data.get("iso_timestamp") or datetime.now(timezone.utc).isoformat(),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AgentCorrectionRecord:
    """
    Structured record of user or agent correction following failures or reviewer observations.
    Captures only sanitized classification; never stores sensitive raw dialogue by default.
    """
    correction_id: str
    correction_type: str
    agent_session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    turn_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    related_dwr_session_id: Optional[str] = None
    related_action_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    classification_details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentCorrectionRecord:
        return cls(
            correction_id=data["correction_id"],
            correction_type=data["correction_type"],
            agent_session_id=data.get("agent_session_id"),
            conversation_id=data.get("conversation_id"),
            turn_id=data.get("turn_id"),
            tool_call_id=data.get("tool_call_id"),
            related_dwr_session_id=data.get("related_dwr_session_id"),
            related_action_id=data.get("related_action_id"),
            timestamp=float(data.get("timestamp", time.time())),
            iso_timestamp=data.get("iso_timestamp") or datetime.now(timezone.utc).isoformat(),
            classification_details=data.get("classification_details", {}),
        )


@dataclass
class AgentDwrCorrelationRecord:
    """
    Relational correlation record explicitly linking Antigravity activity with DWR reality.
    Preserves correlation confidence and provenance source.
    """
    correlation_id: str
    confidence: CorrelationConfidence
    agent_session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    turn_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    dwr_session_id: Optional[str] = None
    dwr_mission_id: Optional[str] = None
    dwr_action_id: Optional[str] = None
    correlation_source: str = "AntigravityCorrelationBridge"
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["confidence"] = self.confidence.value if isinstance(self.confidence, CorrelationConfidence) else str(self.confidence)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentDwrCorrelationRecord:
        conf = data.get("confidence", CorrelationConfidence.UNKNOWN)
        if isinstance(conf, str):
            try:
                conf = CorrelationConfidence(conf)
            except ValueError:
                conf = CorrelationConfidence.UNKNOWN
        return cls(
            correlation_id=data["correlation_id"],
            confidence=conf,
            agent_session_id=data.get("agent_session_id"),
            conversation_id=data.get("conversation_id"),
            turn_id=data.get("turn_id"),
            tool_call_id=data.get("tool_call_id"),
            dwr_session_id=data.get("dwr_session_id"),
            dwr_mission_id=data.get("dwr_mission_id"),
            dwr_action_id=data.get("dwr_action_id"),
            correlation_source=data.get("correlation_source", "AntigravityCorrelationBridge"),
            timestamp=float(data.get("timestamp", time.time())),
            iso_timestamp=data.get("iso_timestamp") or datetime.now(timezone.utc).isoformat(),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AntigravityBridgeStatus:
    """Safe diagnostic snapshot of the Antigravity correlation bridge."""
    installed_or_configured: bool
    enabled: bool
    last_event_timestamp: Optional[str]
    events_accepted: int
    events_rejected: int
    correlation_records: int
    privacy_violations_blocked: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
