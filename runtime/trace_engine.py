"""
Unified Desktop Trace Engine & Observability Subsystem (Architecture H).
Manages monotonic timeline ingestion, bounded trace retention, multi-source
telemetry multiplexing (logs, console, screenshots, process, native, web),
universal correlation envelopes, and sensitive token redaction.
"""

from __future__ import annotations
import collections
import json
import logging
import re
import time
import uuid
from typing import Dict, List, Optional, Any, Set, Tuple

from runtime.state import TargetPlane
from runtime.trace_models import (
    DesktopTraceEventType,
    DesktopTraceEvent,
    TraceCorrelation,
    TraceTimeline,
)

logger = logging.getLogger("desktop_webview.trace_engine")

# Regex pattern for masking sensitive data (passwords, bearer tokens, api keys)
REDACTION_PATTERN = re.compile(
    r"(?i)\b(password|token|bearer|secret|api_?key|auth(?:orization)?|private_?key)(?:[:=\s]+)\s*([^\s,;&]+)",
)


def redact_sensitive_trace_payload(text: str) -> str:
    """Redacts potential credentials, access tokens, and secret strings."""
    if not text:
        return text
    return REDACTION_PATTERN.sub(r"\1 [REDACTED]", text)


redact_sensitive_text = redact_sensitive_trace_payload


class BoundedTraceTimeline(TraceTimeline):
    """
    In-memory bounded monotonic trace timeline.
    Prevents infinite event accumulation and memory leaks by keeping
    up to max_events events in a circular queue.
    """

    def __init__(self, max_events: int = 5000):
        super().__init__()
        self.max_events = max_events
        self._deque: collections.deque[DesktopTraceEvent] = collections.deque(maxlen=max_events)

    def record(self, event: DesktopTraceEvent) -> DesktopTraceEvent:
        self._deque.append(event)
        return event

    def get_events(self) -> List[DesktopTraceEvent]:
        return list(self._deque)

    @property
    def events(self) -> List[DesktopTraceEvent]:
        return list(self._deque)

    def filter_by_session(self, session_id: str) -> List[DesktopTraceEvent]:
        return [e for e in self._deque if e.correlation.session_id == session_id]

    def filter_by_action(self, action_id: str) -> List[DesktopTraceEvent]:
        return [e for e in self._deque if e.correlation.action_id == action_id]

    def filter_by_type(self, event_type: DesktopTraceEventType) -> List[DesktopTraceEvent]:
        return [e for e in self._deque if e.event_type == event_type]

    def clear(self) -> None:
        self._deque.clear()

    def to_dict(self) -> Dict[str, Any]:
        events = list(self._deque)
        return {
            "total_events": len(events),
            "max_capacity": self.max_events,
            "events": [e.to_dict() for e in events],
        }


class DesktopTraceEngine:
    """
    Authoritative Desktop Trace & Observability Engine.
    Emits structured, correlated trace events across all runtime planes
    and coordinates application log and console stream multiplexing.
    """

    def __init__(self, session_id: Optional[str] = None, max_events_per_session: int = 5000):
        if isinstance(session_id, int):
            max_events_per_session = session_id
            session_id = None
        self.default_session_id = session_id or "default"
        self.max_events_per_session = int(max_events_per_session)
        self._timelines: Dict[str, BoundedTraceTimeline] = {}
        self._global_timeline = BoundedTraceTimeline(max_events=self.max_events_per_session * 2)

    @property
    def timeline(self) -> BoundedTraceTimeline:
        return self.get_or_create_timeline(self.default_session_id)

    def get_or_create_timeline(self, session_id: str) -> BoundedTraceTimeline:
        if session_id not in self._timelines:
            self._timelines[session_id] = BoundedTraceTimeline(max_events=self.max_events_per_session)
        return self._timelines[session_id]

    def _redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        redacted = {}
        for k, v in data.items():
            if isinstance(v, str):
                redacted[k] = redact_sensitive_trace_payload(v)[:1000]
            elif isinstance(v, dict):
                redacted[k] = self._redact_dict(v)
            else:
                redacted[k] = v
        return redacted

    def record_event(
        self,
        event: Optional[DesktopTraceEvent] = None,
        *,
        event_type: Optional[DesktopTraceEventType] = None,
        correlation: Optional[TraceCorrelation] = None,
        plane: TargetPlane = TargetPlane.NATIVE,
        target_reference: Optional[str] = None,
        native_hwnd: Optional[int] = None,
        cdp_target_id: Optional[str] = None,
        process_id: Optional[int] = None,
        status: str = "SUCCESS",
        duration_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        artifact_references: Optional[List[str]] = None,
    ) -> DesktopTraceEvent:
        """Records an event in both session-specific and global timelines."""
        if event is None:
            if correlation is None or event_type is None:
                raise ValueError("Must provide either 'event' or both 'event_type' and 'correlation'")
            event = DesktopTraceEvent(
                event_type=event_type,
                correlation=correlation,
                plane=plane,
                target_reference=target_reference,
                native_hwnd=native_hwnd,
                cdp_target_id=cdp_target_id,
                process_id=process_id,
                status=status,
                duration_ms=duration_ms,
                details=self._redact_dict(details or {}),
                artifact_references=list(artifact_references or []),
            )
        session_id = event.correlation.session_id
        session_timeline = self.get_or_create_timeline(session_id)
        session_timeline.record(event)
        self._global_timeline.record(event)
        return event

    def emit(
        self,
        event_type: DesktopTraceEventType,
        session_id: str,
        epoch_id: Optional[int] = None,
        action_id: Optional[str] = None,
        request_id: Optional[str] = None,
        plane: TargetPlane = TargetPlane.NATIVE,
        target_reference: Optional[str] = None,
        native_hwnd: Optional[int] = None,
        cdp_target_id: Optional[str] = None,
        process_id: Optional[int] = None,
        status: str = "SUCCESS",
        duration_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        artifact_references: Optional[List[str]] = None,
    ) -> DesktopTraceEvent:
        """Constructs and records a correlated DesktopTraceEvent."""
        correlation = TraceCorrelation(
            session_id=session_id,
            epoch_id=epoch_id,
            action_id=action_id,
            request_id=request_id,
        )
        safe_details = details or {}
        # Redact any strings in top-level details
        redacted_details = {}
        for k, v in safe_details.items():
            if isinstance(v, str):
                redacted_details[k] = redact_sensitive_trace_payload(v)[:1000]
            else:
                redacted_details[k] = v

        event = DesktopTraceEvent(
            event_type=event_type,
            correlation=correlation,
            plane=plane,
            target_reference=target_reference,
            native_hwnd=native_hwnd,
            cdp_target_id=cdp_target_id,
            process_id=process_id,
            status=status,
            duration_ms=duration_ms,
            details=redacted_details,
            artifact_references=artifact_references or [],
        )
        return self.record_event(event)

    # -------------------------------------------------------------------------
    # Stream Multiplexing: Application Logs & CDP Console
    # -------------------------------------------------------------------------
    def ingest_log_line(
        self,
        stream_name: str = "stdout",
        line: str = "",
        session_id: Optional[str] = None,
        stream: Optional[str] = None,
        timestamp: Optional[float] = None,
        epoch_id: Optional[int] = None,
        action_id: Optional[str] = None,
        process_id: Optional[int] = None,
        **kwargs: Any,
    ) -> DesktopTraceEvent:
        """
        Ingests a line from stdout, stderr, or application log files into the trace timeline.
        Enforces token redaction and bounded line length.
        """
        sid = session_id or self.default_session_id
        st = stream or stream_name
        clean_text = redact_sensitive_trace_payload(line.strip())[:500]
        return self.emit(
            event_type=DesktopTraceEventType.LOG_EVENT,
            session_id=sid,
            epoch_id=epoch_id,
            action_id=action_id,
            plane=TargetPlane.NATIVE,
            process_id=process_id,
            status="SUCCESS",
            details={
                "stream": st,
                "text": clean_text,
                "message": clean_text,
                "raw_length": len(line),
            },
        )

    def ingest_console_message(
        self,
        msg_type: str = "log",
        text: str = "",
        session_id: Optional[str] = None,
        level: Optional[str] = None,
        message: Optional[str] = None,
        timestamp: Optional[float] = None,
        source: Optional[str] = None,
        epoch_id: Optional[int] = None,
        action_id: Optional[str] = None,
        cdp_target_id: Optional[str] = None,
        **kwargs: Any,
    ) -> DesktopTraceEvent:
        """
        Ingests a Chromium DevTools Protocol console or exception event into the trace timeline.
        Treats page-supplied content as untrusted data.
        """
        sid = session_id or self.default_session_id
        lvl = level or msg_type
        txt = message or text
        clean_text = redact_sensitive_trace_payload(txt)[:500]
        status = "ERROR" if lvl in ("error", "exception") else "SUCCESS"
        return self.emit(
            event_type=DesktopTraceEventType.CONSOLE_EVENT,
            session_id=sid,
            epoch_id=epoch_id,
            action_id=action_id,
            plane=TargetPlane.WEBVIEW,
            cdp_target_id=cdp_target_id,
            status=status,
            details={
                "console_type": lvl,
                "level": lvl,
                "text": clean_text,
                "message": clean_text,
                "source": source or "cdp_console",
            },
        )

    def ingest_harness_event(
        self,
        signal_or_telemetry: str,
        session_id: Optional[str] = None,
        is_signal: bool = True,
        epoch_id: Optional[int] = None,
        action_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        status: str = "SUCCESS",
    ) -> DesktopTraceEvent:
        """
        Ingests in-process Reviewer Test Harness timing signals and diagnostic events.
        Enforces source='harness', trust_class='diagnostic'.
        Harness events must never masquerade as PHYSICAL_VERIFICATION or COMPOSITOR_OBSERVATION.
        """
        sid = session_id or self.default_session_id
        safe_details = dict(details or {})
        safe_details["source"] = "harness"
        safe_details["trust_class"] = "diagnostic"
        safe_details["signal"] = str(signal_or_telemetry)
        event_type = DesktopTraceEventType.HARNESS_SIGNAL if is_signal else DesktopTraceEventType.HARNESS_TELEMETRY
        return self.emit(
            event_type=event_type,
            session_id=sid,
            epoch_id=epoch_id,
            action_id=action_id,
            plane=TargetPlane.NATIVE,
            status=status,
            details=safe_details,
        )

    # -------------------------------------------------------------------------
    # Query & Extraction APIs
    # -------------------------------------------------------------------------
    def get_action_lifecycle(self, action_id: str, session_id: Optional[str] = None) -> List[DesktopTraceEvent]:
        """Returns all trace events correlated with a given action_id in monotonic order."""
        timeline = self.get_or_create_timeline(session_id or self.default_session_id)
        return timeline.filter_by_action(action_id)

    def query(
        self,
        session_id: Optional[str] = None,
        action_id: Optional[str] = None,
        event_type: Optional[Any] = None,
        limit: int = 100,
    ) -> List[DesktopTraceEvent]:
        """Queries events matching session, action, or event_type."""
        timeline = self.get_or_create_timeline(session_id or self.default_session_id)
        events = timeline.get_events()
        if action_id:
            events = [e for e in events if e.correlation.action_id == action_id]
        if event_type:
            et_val = event_type.value if hasattr(event_type, "value") else str(event_type)
            events = [e for e in events if (e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)) == et_val]
        return events[-limit:]

    def get_timeline(
        self,
        session_id: str,
        action_id: Optional[str] = None,
        event_types: Optional[Set[DesktopTraceEventType]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DesktopTraceEvent]:
        """Queries the session timeline with filtering and pagination."""
        timeline = self.get_or_create_timeline(session_id)
        events = timeline.get_events()

        if action_id:
            events = [e for e in events if e.correlation.action_id == action_id]

        if event_types:
            events = [e for e in events if e.event_type in event_types]

        # Return paginated slice
        return events[offset : offset + limit]

    def get_action_reconstruction(
        self,
        session_id: str,
        action_id: str,
    ) -> List[DesktopTraceEvent]:
        """
        Returns all trace events causally linked to an action in monotonic chronological order,
        enabling full before-during-after reconstruction.
        """
        timeline = self.get_or_create_timeline(session_id)
        return timeline.filter_by_action(action_id)

    def export_json(self, session_id: str) -> str:
        """Exports the entire session timeline to a JSON document."""
        timeline = self.get_or_create_timeline(session_id)
        return json.dumps(timeline.to_dict(), indent=2)

    def clear_session(self, session_id: str) -> None:
        """Frees trace memory for a closed session."""
        if session_id in self._timelines:
            self._timelines[session_id].clear()
            del self._timelines[session_id]
