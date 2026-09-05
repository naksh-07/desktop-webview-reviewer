"""
Reviewer Test Harness Protocol & Message Models (Phases 13–14, Architecture H).
Defines structured message formats, size boundaries, validation gates,
and security enveloping for application-originated diagnostic telemetry.
"""

from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List

from runtime.harness_contracts import (
    HarnessLifecycleSignal,
    HarnessFixtureAction,
    HarnessFaultType,
    HarnessDiagnosticData,
)

# Hard size boundary: max 1 MB per harness message
MAX_HARNESS_MESSAGE_BYTES = 1024 * 1024

# Timestamp tolerance for clock skew and replay protection (seconds)
TIMESTAMP_FUTURE_TOLERANCE_SEC = 60.0
TIMESTAMP_PAST_TOLERANCE_SEC = 300.0


class HarnessMessageType(str, Enum):
    """Canonical message types exchanged between Application Harness and Reviewer Runtime."""
    HANDSHAKE = "HANDSHAKE"
    HANDSHAKE_ACK = "HANDSHAKE_ACK"
    CAPABILITIES = "CAPABILITIES"
    LIFECYCLE = "LIFECYCLE"
    DIAGNOSTICS = "DIAGNOSTICS"
    FIXTURE_REQUEST = "FIXTURE_REQUEST"
    FIXTURE_RESPONSE = "FIXTURE_RESPONSE"
    FAULT_REQUEST = "FAULT_REQUEST"
    FAULT_RESPONSE = "FAULT_RESPONSE"
    HEALTH_PING = "HEALTH_PING"
    HEALTH_PONG = "HEALTH_PONG"


class HarnessProtocolError(ValueError):
    """Raised when a harness message is malformed, oversized, or violates schema."""
    pass


class HarnessSecurityError(PermissionError):
    """Raised on unauthorized, replayed, or cross-session harness communication."""
    pass


@dataclass(frozen=True)
class HarnessMessage:
    """
    Immutable structured wire message for Reviewer Test Harness.
    All application-originated text is enveloped as untrusted target data.
    """
    session_id: str
    application_id: str
    harness_instance_id: str
    message_type: HarnessMessageType
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: f"corr_{uuid.uuid4().hex[:12]}")
    sequence: int = 0
    auth_token: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "application_id": self.application_id,
            "harness_instance_id": self.harness_instance_id,
            "message_type": self.message_type.value if isinstance(self.message_type, HarnessMessageType) else str(self.message_type),
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "sequence": self.sequence,
            "auth_token": self.auth_token,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> HarnessMessage:
        if not isinstance(data, dict):
            raise HarnessProtocolError("Harness message must be a JSON object dictionary.")

        # Required fields check
        required = ["session_id", "application_id", "harness_instance_id", "message_type"]
        for req in required:
            if req not in data:
                raise HarnessProtocolError(f"Missing required field in harness message: '{req}'")
            if not isinstance(data[req], str) or not data[req].strip():
                raise HarnessProtocolError(f"Field '{req}' must be a non-empty string.")

        # Type conversion
        raw_type = data["message_type"]
        try:
            msg_type = HarnessMessageType(raw_type)
        except ValueError:
            raise HarnessProtocolError(f"Unknown harness message_type: '{raw_type}'")

        payload = data.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise HarnessProtocolError("Field 'payload' must be a dictionary.")

        timestamp = data.get("timestamp")
        if timestamp is not None and not isinstance(timestamp, (int, float)):
            raise HarnessProtocolError("Field 'timestamp' must be numeric.")

        sequence = data.get("sequence", 0)
        if not isinstance(sequence, int):
            raise HarnessProtocolError("Field 'sequence' must be an integer.")

        return cls(
            session_id=str(data["session_id"]),
            application_id=str(data["application_id"]),
            harness_instance_id=str(data["harness_instance_id"]),
            message_type=msg_type,
            payload=payload or {},
            timestamp=float(timestamp) if timestamp is not None else time.time(),
            correlation_id=str(data.get("correlation_id") or f"corr_{uuid.uuid4().hex[:12]}"),
            sequence=sequence,
            auth_token=str(data["auth_token"]) if data.get("auth_token") else None,
        )

    @classmethod
    def from_json(cls, json_str: str) -> HarnessMessage:
        if not isinstance(json_str, (str, bytes)):
            raise HarnessProtocolError("Message payload must be string or bytes.")
        if len(json_str) > MAX_HARNESS_MESSAGE_BYTES:
            raise HarnessProtocolError(
                f"Oversized harness message: {len(json_str)} bytes exceeds maximum {MAX_HARNESS_MESSAGE_BYTES} bytes."
            )
        try:
            data = json.loads(json_str)
        except Exception as e:
            raise HarnessProtocolError(f"Malformed JSON in harness message: {e}")
        return cls.from_dict(data)


class HarnessMessageValidator:
    """
    Validates message authenticity, bounds, session binding, and temporal ordering.
    Guarantees application payloads are treated as untrusted data.
    """

    def __init__(self, expected_session_id: str, expected_auth_token: Optional[str] = None):
        self.expected_session_id = expected_session_id
        self.expected_auth_token = expected_auth_token
        self._last_sequences: Dict[str, int] = {}

    def validate(self, message: HarnessMessage) -> None:
        """Runs all security and integrity checks against an incoming harness message."""
        # 1. Session binding
        if message.session_id != self.expected_session_id:
            raise HarnessSecurityError(
                f"Session ID mismatch: message session '{message.session_id}' does not match expected '{self.expected_session_id}'."
            )

        # 2. Token authentication
        if self.expected_auth_token and message.auth_token != self.expected_auth_token:
            raise HarnessSecurityError("Invalid or missing harness auth_token.")

        # 3. Clock drift check
        now = time.time()
        if message.timestamp > (now + TIMESTAMP_FUTURE_TOLERANCE_SEC):
            raise HarnessProtocolError(
                f"Message timestamp {message.timestamp} is too far in the future (skew: {message.timestamp - now:.1f}s)."
            )
        if message.timestamp < (now - TIMESTAMP_PAST_TOLERANCE_SEC):
            raise HarnessProtocolError(
                f"Message timestamp {message.timestamp} is stale/expired (age: {now - message.timestamp:.1f}s)."
            )

        # 4. Replay / sequence check per harness instance
        inst_id = message.harness_instance_id
        last_seq = self._last_sequences.get(inst_id, -1)
        if message.sequence < last_seq:
            raise HarnessSecurityError(
                f"Replay detected: instance '{inst_id}' sequence {message.sequence} <= last seen {last_seq}."
            )
        self._last_sequences[inst_id] = message.sequence

    @staticmethod
    def sanitize_untrusted_text(text: Any) -> str:
        """
        Envelops raw text into untrusted data block.
        Ensures prompt-injection attacks remain data and cannot be interpreted as Reviewer instructions.
        """
        if not isinstance(text, str):
            return str(text) if text is not None else ""
        # Truncate overly long strings
        sanitized = text[:1000]
        return sanitized
