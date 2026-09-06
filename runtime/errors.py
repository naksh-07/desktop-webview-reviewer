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

    def __init__(self, hwnd_or_message: Any, timeout_ms: int = 500, **kwargs):
        if isinstance(hwnd_or_message, int):
            hwnd = hwnd_or_message
            msg = f"Target window HWND {hex(hwnd)} (or {hwnd}) is hung and failed SendMessageTimeout(WM_NULL) within {timeout_ms}ms."
        else:
            hwnd = kwargs.get("hwnd", 0)
            msg = str(hwnd_or_message)
        super().__init__(
            message=msg,
            code="TARGET_HUNG",
            recoverable=True,
            agent_action_hint="Application UI thread is blocked. Wait for thread to unblock or terminate hung process.",
            details={"hwnd": hwnd, "timeout_ms": timeout_ms, **kwargs},
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


class NativeBridgeException(DesktopAutomationException):
    """Failure communicating with or executing within out-of-process native UIA bridge."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="NATIVE_BRIDGE_ERROR",
            recoverable=True,
            agent_action_hint="Check if the .NET FlaUI sidecar binary is built and responsive.",
            details=details or {},
        )


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

    def __init__(
        self,
        locator_or_message: str = "",
        match_count_or_candidates: Optional[Any] = None,
        candidates: Optional[Any] = None,
        query: Optional[Any] = None,
        remediation: str = "Specify unique text, role, or explicit index.",
        message: Optional[str] = None,
        **kwargs,
    ):
        if isinstance(match_count_or_candidates, int):
            locator = locator_or_message
            match_count = match_count_or_candidates
            cand_list = list(candidates) if candidates else []
            msg = message or f"Query '{locator}' resolved to {match_count} elements. Strict mode requires a unique match."
        else:
            msg = message or locator_or_message
            cand_list = list(match_count_or_candidates or candidates or [])
            match_count = len(cand_list)
            locator = str(query or "")

        super().__init__(
            message=msg,
            code="TARGET_AMBIGUOUS",
            recoverable=True,
            agent_action_hint=remediation,
            details={
                "locator": locator,
                "candidates": cand_list,
                "candidate_count": match_count,
                "query": query or {},
                "remediation": remediation,
                **kwargs,
            },
        )
        self.locator = locator
        self.match_count = match_count
        self.candidates = cand_list
        self.query = query or {}
        self.remediation = remediation


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


class CDPConnectionException(DesktopAutomationException):
    """Failure establishing, maintaining, or recovering a CDP WebSocket connection."""

    def __init__(self, message: str, endpoint: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="CDP_CONNECTION_ERROR",
            recoverable=True,
            agent_action_hint="Check if the remote debugging port is open, responsive, and owned by target PID.",
            details={"endpoint": endpoint, **(details or {})},
        )
        self.endpoint = endpoint


class CDPProtocolException(DesktopAutomationException):
    """Chrome DevTools Protocol error returned from browser/webview."""

    def __init__(self, error_code: int, message: str, method: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"CDP Error ({error_code}) in '{method or 'unknown'}': {message}",
            code="CDP_PROTOCOL_ERROR",
            recoverable=False,
            agent_action_hint="Inspect CDP method arguments or verify domain support.",
            details={"error_code": error_code, "method": method, **(details or {})},
        )
        self.error_code = error_code
        self.method = method


class CDPTimeoutException(DesktopAutomationException):
    """Timed out waiting for response to a CDP command."""

    def __init__(self, method: str, req_id: int, timeout_sec: float):
        super().__init__(
            message=f"Timed out waiting for response to CDP command '{method}' (id={req_id}) after {timeout_sec}s.",
            code="CDP_TIMEOUT",
            recoverable=True,
            agent_action_hint="Increase command timeout or verify if target UI thread is blocked.",
            details={"method": method, "req_id": req_id, "timeout_sec": timeout_sec},
        )
        self.method = method
        self.req_id = req_id
        self.timeout_sec = timeout_sec


class CDPTargetClosedException(DesktopAutomationException):
    """Target was closed or destroyed while an operation was in flight."""

    def __init__(self, target_id: str, reason: str = "Target was closed/destroyed"):
        super().__init__(
            message=f"CDP Target '{target_id}' closed: {reason}",
            code="CDP_TARGET_CLOSED",
            recoverable=False,
            agent_action_hint="Target webview surface was closed. Re-discover active targets.",
            details={"target_id": target_id, "reason": reason},
        )
        self.target_id = target_id


class CDPTargetCrashedException(DesktopAutomationException):
    """Renderer process crashed for the active CDP target."""

    def __init__(self, target_id: str, error_code: Optional[int] = None):
        super().__init__(
            message=f"CDP Target '{target_id}' renderer process crashed (code: {error_code}).",
            code="CDP_TARGET_CRASHED",
            recoverable=False,
            agent_action_hint="Webview renderer process crashed. Collect crash dump and relaunch.",
            details={"target_id": target_id, "error_code": error_code},
        )
        self.target_id = target_id
        self.error_code = error_code


class CDPNavigationRaceException(DesktopAutomationException):
    """Navigation replaced the document context while an operation was resolving."""

    def __init__(self, old_loader_id: str, new_loader_id: Optional[str] = None):
        super().__init__(
            message=f"Navigation race: document replaced (old loader: {old_loader_id}, new: {new_loader_id}).",
            code="CDP_NAVIGATION_RACE",
            recoverable=True,
            agent_action_hint="Target page navigated. Re-query elements in the new observation epoch.",
            details={"old_loader_id": old_loader_id, "new_loader_id": new_loader_id},
        )
        self.old_loader_id = old_loader_id
        self.new_loader_id = new_loader_id


class ExecutionContextDestroyedException(DesktopAutomationException):
    """JavaScript execution context was destroyed (e.g. frame navigation or reload)."""

    def __init__(self, context_id: int, reason: str = "Execution context destroyed"):
        super().__init__(
            message=f"Execution context {context_id} destroyed: {reason}",
            code="EXECUTION_CONTEXT_DESTROYED",
            recoverable=True,
            agent_action_hint="Re-create or re-acquire execution context in the active frame.",
            details={"context_id": context_id, "reason": reason},
        )
        self.context_id = context_id


class FrameDetachedException(DesktopAutomationException):
    """Frame was detached from the DOM while an operation was in flight."""

    def __init__(self, frame_id: str):
        super().__init__(
            message=f"Frame '{frame_id}' has been detached from document.",
            code="FRAME_DETACHED",
            recoverable=False,
            agent_action_hint="Frame no longer exists in DOM. Refresh frame hierarchy.",
            details={"frame_id": frame_id},
        )
        self.frame_id = frame_id


class FrameNotFoundException(DesktopAutomationException):
    """Requested frame ID does not exist in the frame tree."""

    def __init__(self, frame_id: str):
        super().__init__(
            message=f"Frame '{frame_id}' not found in active frame hierarchy.",
            code="FRAME_NOT_FOUND",
            recoverable=False,
            agent_action_hint="Enumerate reachable frames via frame manager.",
            details={"frame_id": frame_id},
        )
        self.frame_id = frame_id


class AXFreezeDetectedException(DesktopAutomationException):
    """Chromium accessibility tree diagnosed as frozen or un-materialized."""

    def __init__(self, ax_count: int, dom_count: int, ratio: float):
        super().__init__(
            message=f"Lazy accessibility tree freeze detected: AX={ax_count}, DOM={dom_count}, ratio={ratio:.3f}",
            code="AX_FREEZE_DETECTED",
            recoverable=True,
            agent_action_hint="Execute accessibility disable/enable reset cycle or fall back to utility realm DOM.",
            details={"ax_count": ax_count, "dom_count": dom_count, "ratio": ratio},
        )
        self.ax_count = ax_count
        self.dom_count = dom_count
        self.ratio = ratio


class CrossDomainFrameAccessException(DesktopAutomationException):
    """Direct DOM access to cross-origin or out-of-process iframe is restricted by browser security."""

    def __init__(self, frame_id: str, security_origin: str):
        super().__init__(
            message=f"Cross-domain access restricted for frame '{frame_id}' (origin: {security_origin}).",
            code="CROSS_DOMAIN_FRAME_RESTRICTED",
            recoverable=True,
            agent_action_hint="Attach to target session directly (OOPIF) or interact via native coordinates.",
            details={"frame_id": frame_id, "security_origin": security_origin},
        )
        self.frame_id = frame_id
        self.security_origin = security_origin


class ActionNotReadyException(DesktopAutomationException):
    """Element failed one or more actionability preconditions within the allowed timeout."""

    def __init__(self, ref_id: str, reasons: Optional[list[str]] = None, details: Optional[Dict[str, Any]] = None):
        reason_str = "; ".join(reasons or []) if reasons else "Actionability check failed."
        super().__init__(
            message=f"Element '{ref_id}' is not actionable: {reason_str}",
            code="ACTION_NOT_READY",
            recoverable=True,
            agent_action_hint="Wait for animations to complete, element to become visible/enabled, or re-inspect target.",
            details={"ref_id": ref_id, "reasons": reasons or [], **(details or {})},
        )
        self.ref_id = ref_id
        self.reasons = reasons or []


class ActionExecutionException(DesktopAutomationException):
    """Action dispatch or execution failed unexpectedly."""

    def __init__(self, message: str, action_type: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="ACTION_EXECUTION_FAILED",
            recoverable=False,
            agent_action_hint="Check application responsiveness, target attachment, and coordinate bounds.",
            details={"action_type": action_type, **(details or {})},
        )
        self.action_type = action_type


class ActionDispatchRejectedException(DesktopAutomationException):
    """Action was rejected by physical safety policy or precondition gate."""

    def __init__(self, message: str, code: str = "ACTION_DISPATCH_REJECTED", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=code,
            recoverable=False,
            agent_action_hint="Inspect native window state (minimized, cloaked, hung, modal blocked).",
            details=details or {},
        )


class GovernanceBypassException(DesktopAutomationException):
    """Raised when an unauthorized bypass of human governance or durable knowledge invariants is attempted."""

    def __init__(self, message: str, code: str = "GOVERNANCE_BYPASS_ATTEMPTED", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=code,
            recoverable=False,
            agent_action_hint="Submit candidates for human review; direct writes of durable knowledge without governance are prohibited.",
            details=details or {},
        )


