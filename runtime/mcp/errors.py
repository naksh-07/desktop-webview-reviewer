"""
Error taxonomy and structured exception mapping for Desktop WebView Reviewer MCP Control Plane.
Maps runtime exceptions into standardized machine-readable MCP error codes and envelopes.
"""

from __future__ import annotations
import json
import logging
from enum import Enum
from typing import Any, Dict, Optional, Tuple, NoReturn

from mcp.server.mcpserver.exceptions import ToolError

from runtime.errors import (
    DesktopAutomationException,
    SessionNotFoundException,
    InvalidTargetException,
    TargetNotFoundException,
    TargetHungException,
    TargetExitedException,
    TargetMismatchException,
    StaleReferenceException,
    TargetAmbiguousException,
    CapabilityUnavailableException,
    ActionNotReadyException,
    ActionDispatchRejectedException,
    CDPConnectionException,
    CDPProtocolException,
    CDPTimeoutException,
    CDPTargetClosedException,
    CDPTargetCrashedException,
    WindowCloakedException,
    NativeModalBlockedException,
    NativeBridgeException,
)
from runtime.evidence_store import (
    EvidenceSecurityException,
    IntegrityVerificationException,
    EvidenceTamperException,
)

FlaUIException = NativeBridgeException

logger = logging.getLogger("desktop_webview.mcp.errors")


class McpErrorCode(str, Enum):
    """Architecture-mandated machine-readable MCP error codes."""
    INVALID_SESSION = "INVALID_SESSION"
    INVALID_TARGET = "INVALID_TARGET"
    TARGET_HUNG = "TARGET_HUNG"
    TARGET_CLOSED = "TARGET_CLOSED"
    STALE_REFERENCE = "STALE_REFERENCE"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    ACTION_NOT_READY = "ACTION_NOT_READY"
    ACTION_REJECTED = "ACTION_REJECTED"
    CDP_ERROR = "CDP_ERROR"
    NATIVE_AUTOMATION_ERROR = "NATIVE_AUTOMATION_ERROR"
    VERIFICATION_UNVERIFIED = "VERIFICATION_UNVERIFIED"
    EVIDENCE_INTEGRITY_ERROR = "EVIDENCE_INTEGRITY_ERROR"
    SECURITY_BLOCKED = "SECURITY_BLOCKED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"


class McpControlPlaneException(Exception):
    """Base structured exception for MCP gateway operations."""

    def __init__(
        self,
        code: McpErrorCode,
        message: str,
        recoverable: bool = False,
        agent_action_hint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.agent_action_hint = agent_action_hint or ""
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": True,
            "code": self.code.value,
            "message": self.message,
            "recoverable": self.recoverable,
            "agent_action_hint": self.agent_action_hint,
            "details": self.details,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def raise_as_tool_error(self) -> NoReturn:
        """Raises official ToolError wrapping formatted machine-readable JSON."""
        raise ToolError(self.to_json())


class VerificationUnverifiedException(DesktopAutomationException):
    """Raised when an operation or assertion produces an UNVERIFIED verdict."""
    pass


def map_exception_to_mcp_error(exc: Exception) -> McpControlPlaneException:
    """
    Translates any runtime exception into a structured McpControlPlaneException
    with an architecture-mandated error code and zero raw traceback leaks.
    """
    if isinstance(exc, McpControlPlaneException):
        return exc

    # Session errors
    if isinstance(exc, SessionNotFoundException):
        return McpControlPlaneException(
            code=McpErrorCode.INVALID_SESSION,
            message=str(exc),
            recoverable=False,
            agent_action_hint="Session has expired or does not exist. Call desktop_launch or desktop_attach.",
            details=getattr(exc, "details", {}),
        )

    # Security & Traversal errors
    if isinstance(exc, EvidenceSecurityException):
        return McpControlPlaneException(
            code=McpErrorCode.SECURITY_BLOCKED,
            message=str(exc),
            recoverable=False,
            agent_action_hint="Operation blocked by security policy (prohibited executable, path traversal, or elevation mismatch).",
            details=getattr(exc, "details", {}),
        )

    # Evidence integrity
    if isinstance(exc, (IntegrityVerificationException, EvidenceTamperException)):
        return McpControlPlaneException(
            code=McpErrorCode.EVIDENCE_INTEGRITY_ERROR,
            message=str(exc),
            recoverable=False,
            agent_action_hint="Evidence artifact failed cryptographic hash check. Manifest was tampered with or corrupted.",
            details=getattr(exc, "details", {}),
        )

    # Stale reference
    if isinstance(exc, StaleReferenceException):
        return McpControlPlaneException(
            code=McpErrorCode.STALE_REFERENCE,
            message=str(exc),
            recoverable=True,
            agent_action_hint="UI state mutated or re-rendered. Call desktop_inspect to refresh refs before retrying.",
            details=getattr(exc, "details", {}),
        )

    # Target Ambiguous
    if isinstance(exc, TargetAmbiguousException):
        return McpControlPlaneException(
            code=McpErrorCode.TARGET_AMBIGUOUS,
            message=str(exc),
            recoverable=True,
            agent_action_hint="Target query matched multiple controls. Refine locator query with role or index.",
            details=getattr(exc, "details", {}),
        )

    # Target Not Found
    if isinstance(exc, TargetNotFoundException):
        return McpControlPlaneException(
            code=McpErrorCode.TARGET_NOT_FOUND,
            message=str(exc),
            recoverable=True,
            agent_action_hint="Target element or window could not be resolved. Call desktop_inspect to locate available refs.",
            details=getattr(exc, "details", {}),
        )

    # Invalid Target
    if isinstance(exc, InvalidTargetException):
        return McpControlPlaneException(
            code=McpErrorCode.INVALID_TARGET,
            message=str(exc),
            recoverable=False,
            agent_action_hint="Specified HWND, PID, or target entity is invalid or no longer exists.",
            details=getattr(exc, "details", {}),
        )

    # Target Hung
    if isinstance(exc, TargetHungException):
        return McpControlPlaneException(
            code=McpErrorCode.TARGET_HUNG,
            message=str(exc),
            recoverable=True,
            agent_action_hint="Target window thread is unresponsive to Win32 message pump. Wait for unblock or restart.",
            details=getattr(exc, "details", {}),
        )

    # Target Closed
    if isinstance(exc, TargetExitedException):
        return McpControlPlaneException(
            code=McpErrorCode.TARGET_CLOSED,
            message=str(exc),
            recoverable=False,
            agent_action_hint="Target application process terminated unexpectedly. Check crash logs or re-launch.",
            details=getattr(exc, "details", {}),
        )

    # Target Mismatch
    if isinstance(exc, TargetMismatchException):
        return McpControlPlaneException(
            code=McpErrorCode.INVALID_TARGET,
            message=str(exc),
            recoverable=False,
            agent_action_hint="Physical PID was recycled or altered. Re-correlate session target.",
            details=getattr(exc, "details", {}),
        )

    # Capability Unavailable
    if isinstance(exc, CapabilityUnavailableException):
        return McpControlPlaneException(
            code=McpErrorCode.CAPABILITY_UNAVAILABLE,
            message=str(exc),
            recoverable=False,
            agent_action_hint="Target does not support requested capability.",
            details=getattr(exc, "details", {}),
        )

    # Actionability & Action readiness
    if isinstance(exc, (ActionNotReadyException, WindowCloakedException, NativeModalBlockedException)):
        return McpControlPlaneException(
            code=McpErrorCode.ACTION_NOT_READY,
            message=str(exc),
            recoverable=True,
            agent_action_hint="Target element failed actionability preconditions (invisible, cloaked, occluded, or animating).",
            details=getattr(exc, "details", {}),
        )

    # Action dispatch rejected
    if isinstance(exc, ActionDispatchRejectedException):
        return McpControlPlaneException(
            code=McpErrorCode.ACTION_REJECTED,
            message=str(exc),
            recoverable=False,
            agent_action_hint="Action was rejected by runtime policy or action dispatcher.",
            details=getattr(exc, "details", {}),
        )

    # CDP protocol errors
    if isinstance(exc, (CDPConnectionException, CDPProtocolException, CDPTimeoutException, CDPTargetClosedException, CDPTargetCrashedException)):
        return McpControlPlaneException(
            code=McpErrorCode.CDP_ERROR,
            message=str(exc),
            recoverable=True,
            agent_action_hint="Underlying CDP communication failed or timed out. Verify remote debugging port.",
            details=getattr(exc, "details", {}),
        )

    # Native Automation & FlaUI
    if isinstance(exc, FlaUIException):
        return McpControlPlaneException(
            code=McpErrorCode.NATIVE_AUTOMATION_ERROR,
            message=str(exc),
            recoverable=True,
            agent_action_hint="Native Win32 or UIA automation failed. Verify window bounds and focus state.",
            details=getattr(exc, "details", {}),
        )

    # Verification unverified
    if isinstance(exc, VerificationUnverifiedException):
        return McpControlPlaneException(
            code=McpErrorCode.VERIFICATION_UNVERIFIED,
            message=str(exc),
            recoverable=True,
            agent_action_hint="Forensic evidence was incomplete or ambiguous. Review verification proof metrics.",
            details=getattr(exc, "details", {}),
        )

    # Argument validation
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return McpControlPlaneException(
            code=McpErrorCode.INVALID_ARGUMENT,
            message=str(exc),
            recoverable=False,
            agent_action_hint="Invalid arguments supplied to MCP tool. Check tool schema requirements.",
            details={"exception_type": exc.__class__.__name__},
        )

    # General fallback
    if isinstance(exc, DesktopAutomationException):
        return McpControlPlaneException(
            code=McpErrorCode.NATIVE_AUTOMATION_ERROR,
            message=exc.message,
            recoverable=exc.recoverable,
            agent_action_hint=exc.agent_action_hint,
            details=exc.details,
        )

    return McpControlPlaneException(
        code=McpErrorCode.NATIVE_AUTOMATION_ERROR,
        message=f"Unhandled runtime exception: {str(exc)}",
        recoverable=False,
        agent_action_hint="An internal error occurred in the automation runtime.",
        details={"type": exc.__class__.__name__},
    )
