"""
Contracts, Enums, and Event Envelopes for Antigravity Experience Integration.

Defines the normalized, versioned agent event envelope, correlation confidence levels,
and user correction taxonomies.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class AgentEventType(str, Enum):
    """
    Normalized taxonomy of supported Antigravity agent lifecycle and interaction events.
    Minimal, versioned event surface.
    """
    AGENT_SESSION_STARTED = "AGENT_SESSION_STARTED"
    AGENT_SESSION_COMPLETED = "AGENT_SESSION_COMPLETED"

    AGENT_TURN_STARTED = "AGENT_TURN_STARTED"
    AGENT_TURN_COMPLETED = "AGENT_TURN_COMPLETED"

    AGENT_TOOL_STARTED = "AGENT_TOOL_STARTED"
    AGENT_TOOL_COMPLETED = "AGENT_TOOL_COMPLETED"
    AGENT_TOOL_FAILED = "AGENT_TOOL_FAILED"

    AGENT_SUBAGENT_STARTED = "AGENT_SUBAGENT_STARTED"
    AGENT_SUBAGENT_COMPLETED = "AGENT_SUBAGENT_COMPLETED"
    AGENT_SUBAGENT_FAILED = "AGENT_SUBAGENT_FAILED"

    AGENT_ARTIFACT_CREATED = "AGENT_ARTIFACT_CREATED"
    AGENT_CORRECTION = "AGENT_CORRECTION"
    AGENT_USER_CORRECTION = "AGENT_USER_CORRECTION"


class CorrelationConfidence(str, Enum):
    """
    Explicit confidence levels for linking Antigravity agent events to DWR runtime reality.
    Correlation is never represented as certainty when it is merely inferential.
    """
    EXACT = "EXACT"        # Explicit correlation_id, matching session_id/action_id, or direct tool invocation
    HIGH = "HIGH"          # Same conversation_id within tight temporal window (<= 5s) during active DWR action
    MEDIUM = "MEDIUM"      # Same workspace/project within reasonable temporal window (<= 60s)
    LOW = "LOW"            # Same project or loose temporal/inferential proximity
    UNKNOWN = "UNKNOWN"    # Insufficient correlation parameters


class UserCorrectionType(str, Enum):
    """
    Structured taxonomy of agent and user corrections following reviewer failures or errors.
    """
    AGENT_MADE_ERROR = "AGENT_MADE_ERROR"
    USER_CORRECTED_AGENT = "USER_CORRECTED_AGENT"
    USER_REJECTED_RESULT = "USER_REJECTED_RESULT"
    USER_RETRIED_REQUEST = "USER_RETRIED_REQUEST"
    USER_CHANGED_TARGET = "USER_CHANGED_TARGET"


@dataclass
class AgentEventEnvelope:
    """
    Normalized, versioned event envelope for incoming Antigravity agent activity.
    Captures only metadata useful for correlation and experience analysis.
    Optional fields remain optional. No values manufactured.
    """
    event_type: AgentEventType
    event_id: str = field(default_factory=lambda: f"aevt_{uuid.uuid4().hex[:16]}")
    event_schema_version: str = "1.0"
    conversation_id: Optional[str] = None
    turn_id: Optional[str] = None
    agent_id: Optional[str] = None
    parent_agent_id: Optional[str] = None
    subagent_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_category: Optional[str] = None
    success: Optional[bool] = None
    error_class: Optional[str] = None
    duration_ms: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    iso_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    artifact_reference: Optional[str] = None
    correlation_id: Optional[str] = None
    safe_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value if isinstance(self.event_type, AgentEventType) else str(self.event_type)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentEventEnvelope:
        et = data.get("event_type", AgentEventType.AGENT_TOOL_COMPLETED)
        if isinstance(et, str):
            try:
                et = AgentEventType(et)
            except ValueError:
                et = AgentEventType.AGENT_TOOL_COMPLETED

        ts = float(data.get("timestamp", time.time()))
        iso_ts = data.get("iso_timestamp") or datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        return cls(
            event_type=et,
            event_id=data.get("event_id") or f"aevt_{uuid.uuid4().hex[:16]}",
            event_schema_version=data.get("event_schema_version", "1.0"),
            conversation_id=data.get("conversation_id"),
            turn_id=data.get("turn_id"),
            agent_id=data.get("agent_id"),
            parent_agent_id=data.get("parent_agent_id"),
            subagent_id=data.get("subagent_id"),
            tool_name=data.get("tool_name"),
            tool_category=data.get("tool_category"),
            success=data.get("success"),
            error_class=data.get("error_class"),
            duration_ms=float(data["duration_ms"]) if data.get("duration_ms") is not None else None,
            timestamp=ts,
            iso_timestamp=iso_ts,
            workspace_id=data.get("workspace_id"),
            project_id=data.get("project_id"),
            artifact_reference=data.get("artifact_reference"),
            correlation_id=data.get("correlation_id"),
            safe_summary=data.get("safe_summary") or {},
        )
