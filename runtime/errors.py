"""
Runtime error models and structured exceptions for Desktop WebView Reviewer.
Preserves machine-readable error codes, recoverability flags, and agent action hints.
"""

from __future__ import annotations
from typing import Optional, Any, Dict


class DesktopAutomationException(Exception):
    """Base class for all structured platform exceptions."""

    def __init__(
        self,
        message: str,
        code: str = "GENERIC_AUTOMATION_ERROR",
        recoverable: bool = False,
        agent_action_hint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.recoverable = recoverable
        self.agent_action_hint = agent_action_hint
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Returns machine-readable representation of the error."""
        return {
            "error_type": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "agent_action_hint": self.agent_action_hint,
            "details": self.details,
        }


class SessionNotFoundException(DesktopAutomationException):
    """Target session ID is unknown, expired, or terminated."""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"Session '{session_id}' not found or lease expired.",
            code="SESSION_NOT_FOUND",
            recoverable=False,
            agent_action_hint="Call desktop_launch or desktop_attach to start a new session.",
            details={"session_id": session_id},
        )
        self.session_id = session_id


class InvalidTargetException(DesktopAutomationException):
    """Specified HWND, PID, or target entity could not be resolved or is invalid."""

    def __init__(self, message: str, target_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="INVALID_TARGET",
            recoverable=False,
            agent_action_hint="Verify the target exists and re-scan active application windows.",
            details={"target_id": target_id, **(details or {})},
        )
        self.target_id = target_id


class TargetNotFoundException(InvalidTargetException):
    """Backward-compatible alias for target resolution failure."""
    pass


class TargetExitedException(DesktopAutomationException):
    """Target application process terminated unexpectedly."""

    def __init__(self, pid: int, exit_code: Optional[int] = None):
        super().__init__(
            message=f"Target process PID {pid} has exited (exit code: {exit_code}).",
            code="TARGET_EXITED",
            recoverable=False,
            agent_action_hint="Target application crashed or closed. Inspect crash logs or relaunch.",
            details={"pid": pid, "exit_code": exit_code},
        )
        self.pid = pid
        self.exit_code = exit_code


class TargetHungException(DesktopAutomationException):
    """Target window thread is unresponsive to Win32 message pump."""

    def __init__(self, hwnd: int, timeout_ms: int = 500):
        super().__init__(
            message=f"Target window HWND {hex(hwnd)} (or {hwnd}) is hung and failed SendMessageTimeout(WM_NULL) within {timeout_ms}ms.",
            code="TARGET_HUNG",
            recoverable=True,
            agent_action_hint="Application UI thread is blocked. Wait for thread to unblock or terminate hung process.",
            details={"hwnd": hwnd, "timeout_ms": timeout_ms},
        )
        self.hwnd = hwnd
        self.timeout_ms = timeout_ms


class TargetMismatchException(DesktopAutomationException):
    """Physical target identity (PID, creation time, binary) does not match expected session bound identity."""

    def __init__(self, expected_pid: int, actual_pid: int, reason: str):
        super().__init__(
            message=f"Target mismatch: expected PID {expected_pid}, got PID {actual_pid} ({reason}).",
            code="TARGET_MISMATCH",
            recoverable=False,
            agent_action_hint="Target process PID was recycled or altered. Re-correlate session target.",
            details={"expected_pid": expected_pid, "actual_pid": actual_pid, "reason": reason},
        )
        self.expected_pid = expected_pid
        self.actual_pid = actual_pid


class StaleReferenceException(DesktopAutomationException):
    """Interaction ref belongs to an older observation epoch."""

    def __init__(self, ref_id: str, current_epoch: int, ref_epoch: Optional[int] = None):
        super().__init__(
            message=f"Reference '{ref_id}' is stale (active epoch: {current_epoch}, ref epoch: {ref_epoch}).",
            code="STALE_REFERENCE",
            recoverable=True,
            agent_action_hint="Request a fresh observation snapshot via desktop_inspect before acting.",
            details={"ref_id": ref_id, "current_epoch": current_epoch, "ref_epoch": ref_epoch},
        )
        self.ref_id = ref_id
        self.current_epoch = current_epoch
        self.ref_epoch = ref_epoch


class TransportErrorException(DesktopAutomationException):
    """Failure communicating across IPC transport (Named Pipe / stdio)."""

    def __init__(self, message: str, endpoint: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="TRANSPORT_ERROR",
            recoverable=True,
            agent_action_hint="Check if the worker sidecar process is running and the pipe is available.",
            details={"endpoint": endpoint, **(details or {})},
        )
        self.endpoint = endpoint


class TransportTimeoutException(TransportErrorException):
    """IPC transport request timed out."""

    def __init__(self, message: str, timeout_sec: float, endpoint: Optional[str] = None):
        super().__init__(
            message=message,
            endpoint=endpoint,
            details={"timeout_sec": timeout_sec},
        )
        self.code = "TRANSPORT_TIMEOUT"
        self.timeout_sec = timeout_sec


class CapabilityUnavailableException(DesktopAutomationException):
    """Requested capability is unsupported or degraded on the target platform/engine."""

    def __init__(self, capability: str, reason: str):
        super().__init__(
            message=f"Capability '{capability}' is unavailable: {reason}",
            code="CAPABILITY_UNAVAILABLE",
            recoverable=False,
            agent_action_hint="Query supported capabilities via session metadata and select an alternate workflow.",
            details={"capability": capability, "reason": reason},
        )
        self.capability = capability
        self.reason = reason


class UnsupportedOperationException(DesktopAutomationException):
    """The requested operation cannot be performed in the current target plane or state."""

    def __init__(self, operation: str, plane: str, reason: str):
        super().__init__(
            message=f"Operation '{operation}' is unsupported on plane '{plane}': {reason}",
            code="UNSUPPORTED_OPERATION",
            recoverable=False,
            agent_action_hint="Use plane-appropriate operations (e.g. CDP for webview, UIA for native shell).",
            details={"operation": operation, "plane": plane, "reason": reason},
        )
        self.operation = operation
        self.plane = plane


class InvalidCoordinateSpaceException(DesktopAutomationException):
    """Coordinate translation calculation failed or out-of-bounds."""

    def __init__(self, message: str, coordinates: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="INVALID_COORDINATE_SPACE",
            recoverable=False,
            agent_action_hint="Verify window bounds and monitor virtual screen layout.",
            details=coordinates,
        )


class SidecarUnavailableException(DesktopAutomationException):
    """Out-of-process .NET FlaUI sidecar is not installed, failed to spawn, or crashed."""

    def __init__(self, sidecar_path: str, reason: str):
        super().__init__(
            message=f"Native sidecar '{sidecar_path}' is unavailable: {reason}",
            code="SIDECAR_UNAVAILABLE",
            recoverable=False,
            agent_action_hint="Ensure DesktopBridge.UIA3.exe is built and available on PATH or binary dir.",
            details={"sidecar_path": sidecar_path, "reason": reason},
        )
        self.sidecar_path = sidecar_path


class ProtocolErrorException(DesktopAutomationException):
    """Malformed JSON-RPC message, invalid request envelope, or protocol mismatch."""

    def __init__(self, message: str, raw_payload: Optional[str] = None):
        super().__init__(
            message=message,
            code="PROTOCOL_ERROR",
            recoverable=False,
            agent_action_hint="Verify protocol envelope versions match specification.",
            details={"raw_payload": raw_payload},
        )


class CleanupErrorException(DesktopAutomationException):
    """Resource teardown failed during session or daemon shutdown."""

    def __init__(self, message: str, failed_resources: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="CLEANUP_ERROR",
            recoverable=True,
            agent_action_hint="Inspect process supervisor logs and verify Job Object release.",
            details={"failed_resources": failed_resources},
        )


class TargetAmbiguousException(DesktopAutomationException):
    """Locator resolved to multiple matching elements in strict mode."""

    def __init__(self, locator: str, match_count: int):
        super().__init__(
            message=f"Query '{locator}' resolved to {match_count} elements. Strict mode requires a unique match.",
            code="TARGET_AMBIGUOUS",
            recoverable=True,
            agent_action_hint="Refine locator with get_by_role, index, or unique text.",
            details={"locator": locator, "match_count": match_count},
        )
        self.locator = locator
        self.match_count = match_count


class WindowCloakedException(DesktopAutomationException):
    """Target window is cloaked by DWM (virtual desktop, minimized, or lock screen)."""

    def __init__(self, hwnd: int):
        super().__init__(
            message=f"Window HWND {hex(hwnd)} (or {hwnd}) is cloaked by DWM.",
            code="WINDOW_CLOAKED",
            recoverable=True,
            agent_action_hint="Bring window to foreground or switch to the appropriate virtual desktop.",
            details={"hwnd": hwnd},
        )
        self.hwnd = hwnd


class NativeModalBlockedException(DesktopAutomationException):
    """An unhandled native Win32 modal dialog (#32770) is blocking the application."""

    def __init__(self, dialog_title: str, dialog_hwnd: int):
        super().__init__(
            message=f"Native modal dialog '{dialog_title}' (HWND {dialog_hwnd}) is blocking UI.",
            code="NATIVE_MODAL_BLOCKED",
            recoverable=True,
            agent_action_hint="Invoke desktop_handle_dialog to dismiss or interact with modal.",
            details={"dialog_title": dialog_title, "dialog_hwnd": dialog_hwnd},
        )
        self.dialog_title = dialog_title
        self.dialog_hwnd = dialog_hwnd


class InvalidStateTransitionError(DesktopAutomationException):
    """Attempted illegal transition between session lifecycle states."""

    def __init__(self, current_state: str, target_state: str, allowed: list[str]):
        super().__init__(
            message=f"Invalid state transition from '{current_state}' to '{target_state}'. Allowed: {allowed}",
            code="INVALID_STATE_TRANSITION",
            recoverable=False,
            agent_action_hint=f"Respect session lifecycle ordering: {allowed}",
            details={"current_state": current_state, "target_state": target_state, "allowed": allowed},
        )
        self.current_state = current_state
        self.target_state = target_state
        self.allowed = allowed
