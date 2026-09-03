"""
Structured Diagnostics, Lifecycle Telemetry, and Untrusted UI Data Boundary.
Captures structured events across session transitions and guarantees that untrusted UI strings
(window titles, DOM text) are sanitized and never merged into trusted system control metadata.
"""

from __future__ import annotations
import html
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger("desktop_webview.lifecycle")


@dataclass
class UntrustedUIText:
    """
    Encapsulates raw UI text extracted from DOM or native window controls.
    Enforces sanitization, length boundaries, and strict containment to neutralize
    indirect prompt injection attacks.
    """
    raw_text: str
    max_len: int = 500

    @property
    def sanitized(self) -> str:
        """Escapes control characters and HTML/prompt delimiters."""
        if not self.raw_text:
            return ""
        # Strip ASCII control characters except newline and tab
        cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", self.raw_text)
        # Escape HTML / XML / Markdown delimiters
        escaped = html.escape(cleaned)
        # Truncate to maximum permitted length
        if len(escaped) > self.max_len:
            escaped = escaped[: self.max_len] + "... [truncated]"
        return escaped

    def to_envelope(self) -> Dict[str, str]:
        """Wraps text in an untrusted data envelope."""
        return {
            "kind": "untrusted_ui_content",
            "content": self.sanitized,
        }

    def __str__(self) -> str:
        return self.sanitized


@dataclass
class LifecycleEvent:
    """Standardized event envelope capturing lifecycle-critical milestones."""
    operation: str
    severity: str = "INFO"        # "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    session_id: Optional[str] = None
    target_id: Optional[str] = None
    pid: Optional[int] = None
    hwnd: Optional[int] = None
    state_transition: Optional[str] = None
    request_id: Optional[str] = None
    epoch: Optional[int] = None
    error_code: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "operation": self.operation,
            "severity": self.severity,
            "session_id": self.session_id,
            "target_id": self.target_id,
            "pid": self.pid,
            "hwnd": hex(self.hwnd) if self.hwnd is not None else None,
            "state_transition": self.state_transition,
            "request_id": self.request_id,
            "epoch": self.epoch,
            "error_code": self.error_code,
            "details": self.details,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def emit(self) -> None:
        """Logs structured event at appropriate severity."""
        msg = f"[{self.operation}] session={self.session_id} transition={self.state_transition} pid={self.pid} epoch={self.epoch}"
        if self.severity == "DEBUG":
            logger.debug(msg, extra={"event_data": self.to_dict()})
        elif self.severity == "WARNING":
            logger.warning(msg, extra={"event_data": self.to_dict()})
        elif self.severity in ("ERROR", "CRITICAL"):
            logger.error(msg, extra={"event_data": self.to_dict()})
        else:
            logger.info(msg, extra={"event_data": self.to_dict()})


class EventAuditor:
    """In-memory collector for auditing lifecycle events during test and execution."""

    def __init__(self):
        self.events: list[LifecycleEvent] = []

    def record(self, event: LifecycleEvent) -> LifecycleEvent:
        event.emit()
        self.events.append(event)
        return event

    def clear(self) -> None:
        self.events.clear()

    def filter_by_session(self, session_id: str) -> list[LifecycleEvent]:
        return [e for e in self.events if e.session_id == session_id]

    def filter_by_operation(self, operation: str) -> list[LifecycleEvent]:
        return [e for e in self.events if e.operation == operation]
