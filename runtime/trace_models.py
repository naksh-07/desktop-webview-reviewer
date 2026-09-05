"""
Desktop Trace Domain Models for Desktop WebView Reviewer 2.0 (Architecture H).
Defines the canonical 17 trace event types, correlation envelopes, and unified timeline models.
"""

from __future__ import annotations
import itertools
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

from runtime.state import TargetPlane

_trace_monotonic_counter = itertools.count(1)


class DesktopTraceEventType(str, Enum):
    """The canonical 17 Desktop Trace event types + harness telemetry markers."""
    APP_LAUNCH = "APP_LAUNCH"
    APP_ATTACH = "APP_ATTACH"
    WINDOW_DISCOVERED = "WINDOW_DISCOVERED"
    PROCESS_STATE = "PROCESS_STATE"
    WEBVIEW_CONNECTED = "WEBVIEW_CONNECTED"
    OBSERVATION = "OBSERVATION"
    TARGET_RESOLVED = "TARGET_RESOLVED"
    ACTION_REQUESTED = "ACTION_REQUESTED"
    ACTION_DISPATCHED = "ACTION_DISPATCHED"
    ACTION_SETTLED = "ACTION_SETTLED"
    SCREENSHOT = "SCREENSHOT"
    DOM_CHANGE = "DOM_CHANGE"
    UIA_CHANGE = "UIA_CHANGE"
    CONSOLE_EVENT = "CONSOLE_EVENT"
    LOG_EVENT = "LOG_EVENT"
    ASSERTION = "ASSERTION"
    RECOVERY = "RECOVERY"
    EVIDENCE_CREATED = "EVIDENCE_CREATED"
    # Harness integration extensions
    HARNESS_SIGNAL = "HARNESS_SIGNAL"
    HARNESS_TELEMETRY = "HARNESS_TELEMETRY"
    # Specialist & Recovery integration extensions (Phase 15-16)
    SPECIALIST_LIFECYCLE = "SPECIALIST_LIFECYCLE"
    SPECIALIST_TOOL_AUDIT = "SPECIALIST_TOOL_AUDIT"
    RECOVERY_ATTEMPT = "RECOVERY_ATTEMPT"


@dataclass(frozen=True)
class TraceCorrelation:
    """Universal correlation identifiers linking related cross-plane events."""
    session_id: str
    epoch_id: Optional[int] = None
    action_id: Optional[str] = None
    request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "epoch_id": self.epoch_id,
            "action_id": self.action_id,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class DesktopTraceEvent:
    """
    Canonical, immutable structured trace event for Desktop WebView Reviewer 2.0.
    Indexes native, web, visual, and diagnostic milestones along a single monotonic timeline.
    """
    event_type: DesktopTraceEventType
    correlation: TraceCorrelation
    plane: TargetPlane = TargetPlane.NATIVE
    target_reference: Optional[str] = None
    native_hwnd: Optional[int] = None
    cdp_target_id: Optional[str] = None
    process_id: Optional[int] = None
    status: str = "SUCCESS"
    duration_ms: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    artifact_references: List[str] = field(default_factory=list)
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    sequence_monotonic: int = field(default_factory=lambda: next(_trace_monotonic_counter))
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence_monotonic": self.sequence_monotonic,
            "event_type": self.event_type.value if isinstance(self.event_type, DesktopTraceEventType) else str(self.event_type),
            "timestamp": self.timestamp,
            "correlation": self.correlation.to_dict(),
            "plane": self.plane.value if isinstance(self.plane, TargetPlane) else str(self.plane),
            "target_reference": self.target_reference,
            "native_hwnd": hex(self.native_hwnd) if self.native_hwnd is not None else None,
            "cdp_target_id": self.cdp_target_id,
            "process_id": self.process_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "details": self.details,
            "artifact_references": self.artifact_references,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class TraceTimeline:
    """
    Monotonic trace timeline aggregator.
    Maintains time-ordered trace events and provides multi-key correlation queries.
    """

    def __init__(self):
        self._events: List[DesktopTraceEvent] = []

    def record(self, event: DesktopTraceEvent) -> DesktopTraceEvent:
        self._events.append(event)
        return event

    def get_events(self) -> List[DesktopTraceEvent]:
        return list(self._events)

    def filter_by_session(self, session_id: str) -> List[DesktopTraceEvent]:
        return [e for e in self._events if e.correlation.session_id == session_id]

    def filter_by_action(self, action_id: str) -> List[DesktopTraceEvent]:
        return [e for e in self._events if e.correlation.action_id == action_id]

    def filter_by_type(self, event_type: DesktopTraceEventType) -> List[DesktopTraceEvent]:
        return [e for e in self._events if e.event_type == event_type]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_events": len(self._events),
            "events": [e.to_dict() for e in self._events],
        }

    def clear(self) -> None:
        self._events.clear()
