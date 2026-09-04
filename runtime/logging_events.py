"""
Structured Diagnostics, Lifecycle Telemetry, and Untrusted UI Data Boundary.
Captures structured events across session transitions and guarantees that untrusted UI strings
(window titles, DOM text) are sanitized and never merged into trusted system control metadata.
"""

from __future__ import annotations
import html
import itertools
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("desktop_webview.lifecycle")

_monotonic_counter = itertools.count(1)


class TelemetryRedactor:
    """
    Configurable redactor for runtime telemetry and structured event logging.
    Prevents leaking passwords, tokens, API keys, and unbounded DOM/JS payloads into logs.
    """

    SENSITIVE_PATTERNS = [
        re.compile(r'(?i)(password|secret|token|api[_-]?key|bearer|authorization|passwd)[\s*:=]+([^\s,;\"\'}{]+)'),
        re.compile(r'(?i)\b(bearer\s+[A-Za-z0-9\-\._~\+\/]+=*)'),
    ]

    MAX_STRING_LENGTH = 500

    @classmethod
    def redact_text(cls, text: str) -> str:
        if not text:
            return ""
        redacted = text
        for pat in cls.SENSITIVE_PATTERNS:
            redacted = pat.sub(r'\1 [REDACTED]', redacted)
        if len(redacted) > cls.MAX_STRING_LENGTH:
            redacted = redacted[:cls.MAX_STRING_LENGTH] + "... [TRUNCATED_FOR_TELEMETRY]"
        return redacted

    @classmethod
    def redact_value(cls, val: Any) -> Any:
        if isinstance(val, str):
            return cls.redact_text(val)
        elif isinstance(val, dict):
            return {k: cls.redact_value(v) for k, v in val.items()}
        elif isinstance(val, (list, tuple)):
            return [cls.redact_value(item) for item in val]
        return val


@dataclass
class UntrustedUIText:
    """
    Encapsulates raw UI text extracted from DOM or native window controls.
    Enforces sanitization, length boundaries, and strict containment to neutralize
    indirect prompt injection attacks.
    """
    raw_text: str
    source_plane: str = "unknown"
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

    def to_log_repr(self) -> str:
        """Single-line log representation safe against log injection."""
        return self.sanitized.replace("\n", " ").replace("\r", " ")

    def to_envelope(self) -> Dict[str, str]:
        """Wraps text in an untrusted data envelope."""
        return {
            "kind": "untrusted_ui_content",
            "content": self.sanitized,
            "source_plane": self.source_plane,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Structured dictionary flagging content as untrusted."""
        return {
            "raw_text": self.raw_text,
            "sanitized": self.sanitized,
            "source_plane": self.source_plane,
            "is_untrusted": True,
        }

    def __str__(self) -> str:
        return self.sanitized


@dataclass
class LifecycleEvent:
    """
    Standardized production telemetry event envelope capturing lifecycle and action milestones.
    Supports structured logging, duration metrics, sequence ordering, and automatic data redaction.
    """
    operation: str
    severity: str = "INFO"        # "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    session_id: Optional[str] = None
    action_id: Optional[str] = None
    observation_epoch: Optional[int] = None
    target_id: Optional[str] = None
    pid: Optional[int] = None
    hwnd: Optional[int] = None
    cdp_target_id: Optional[str] = None
    state_transition: Optional[str] = None
    request_id: Optional[str] = None
    epoch: Optional[int] = None
    duration_ms: Optional[float] = None
    status: Optional[str] = "SUCCESS"
    error_code: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    sequence_monotonic: int = field(default_factory=lambda: next(_monotonic_counter))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if self.epoch is not None and self.observation_epoch is None:
            self.observation_epoch = self.epoch
        elif self.observation_epoch is not None and self.epoch is None:
            self.epoch = self.observation_epoch

    @property
    def timestamp_wall(self) -> str:
        return self.timestamp.isoformat()

    def to_dict(self, redact: bool = True) -> Dict[str, Any]:
        raw_details = self.details
        if redact:
            raw_details = TelemetryRedactor.redact_value(raw_details)
        return {
            "sequence_monotonic": self.sequence_monotonic,
            "timestamp": self.timestamp_wall,
            "timestamp_wall": self.timestamp_wall,
            "operation": self.operation,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "severity": self.severity,
            "session_id": self.session_id,
            "action_id": self.action_id,
            "observation_epoch": self.observation_epoch,
            "epoch": self.epoch,
            "target_id": self.target_id,
            "pid": self.pid,
            "hwnd": hex(self.hwnd) if self.hwnd is not None else None,
            "cdp_target_id": self.cdp_target_id,
            "state_transition": self.state_transition,
            "request_id": self.request_id,
            "error_code": self.error_code,
            "details": raw_details,
        }

    def to_json(self, redact: bool = True) -> str:
        return json.dumps(self.to_dict(redact=redact))

    def emit(self) -> None:
        """Logs structured event at appropriate severity."""
        msg = (
            f"[{self.operation}] seq={self.sequence_monotonic} "
            f"session={self.session_id} transition={self.state_transition} "
            f"pid={self.pid} epoch={self.observation_epoch} status={self.status}"
        )
        data = self.to_dict(redact=True)
        if self.severity == "DEBUG":
            logger.debug(msg, extra={"event_data": data})
        elif self.severity == "WARNING":
            logger.warning(msg, extra={"event_data": data})
        elif self.severity in ("ERROR", "CRITICAL"):
            logger.error(msg, extra={"event_data": data})
        else:
            logger.info(msg, extra={"event_data": data})


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
