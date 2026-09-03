"""
Target Manager and Multi-Dimensional Target Identity Separation for Desktop WebView Reviewer.
Explicitly separates Process, Window, Webview Runtime, Debugging Endpoint, and Native contexts.
Establishes a single authoritative validation path for Window and Process identities,
protecting against HWND reuse, PID reuse, destroyed windows, and reparented surfaces.
"""

from __future__ import annotations
import json
import logging
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set

from runtime.references import Rect
from runtime.state import HealthState
from runtime.native_supervisor import NativeOSSupervisor, WindowForensicReport
from runtime.errors import (
    InvalidTargetException,
    TargetExitedException,
    TargetMismatchException,
    TargetNotFoundException,
    TargetHungException,
)

logger = logging.getLogger("desktop_webview.target_manager")

try:
    import psutil
except ImportError:
    psutil = None


@dataclass(frozen=True)
class ProcessIdentity:
    """Immutable identity of the host operating system process."""
    pid: int
    creation_time: float
    binary_path: str
    command_line: List[str] = field(default_factory=list)
    is_elevated: bool = False
    job_handle: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "creation_time": self.creation_time,
            "binary_path": self.binary_path,
            "command_line": self.command_line,
            "is_elevated": self.is_elevated,
            "job_handle": self.job_handle,
        }


@dataclass(frozen=True)
class WindowIdentity:
    """Authoritative identity and physical state of a native window."""
    hwnd: int
    pid: int
    title: str
    class_name: str
    bounds: Rect                   # Canonical physical bounds via DWM
    is_visible: bool
    is_cloaked: bool
    is_minimized: bool
    is_hung: bool
    dpi_scaling: float = 1.0
    raw_window_rect: Optional[Rect] = None  # Raw GetWindowRect (diagnostic)
    client_rect: Optional[Rect] = None      # Client bounds
    creation_time: Optional[float] = None
    root_owner_hwnd: Optional[int] = None
    parent_hwnd: Optional[int] = None
    health_state: HealthState = HealthState.HEALTHY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd),
            "pid": self.pid,
            "title": self.title,
            "class_name": self.class_name,
            "bounds": self.bounds.to_dict(),
            "raw_window_rect": (self.raw_window_rect or self.bounds).to_dict(),
            "client_rect": (self.client_rect or self.bounds).to_dict(),
            "is_visible": self.is_visible,
            "is_cloaked": self.is_cloaked,
            "is_minimized": self.is_minimized,
            "is_hung": self.is_hung,
            "dpi_scaling": self.dpi_scaling,
            "creation_time": self.creation_time,
            "root_owner_hwnd": hex(self.root_owner_hwnd) if self.root_owner_hwnd else None,
            "parent_hwnd": hex(self.parent_hwnd) if self.parent_hwnd else None,
            "health_state": self.health_state.value,
        }


@dataclass(frozen=True)
class WindowValidationResult:
    """Authoritative structured output of a window identity validation check."""
    is_valid: bool
    window: Optional[WindowIdentity] = None
    error_code: Optional[str] = None  # "WINDOW_NOT_FOUND", "TARGET_MISMATCH", "TARGET_HUNG", etc.
    failure_reason: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "window": self.window.to_dict() if self.window else None,
            "error_code": self.error_code,
            "failure_reason": self.failure_reason,
            "diagnostics": self.diagnostics,
        }


@dataclass(frozen=True)
class WebviewRuntimeIdentity:
    """Identity of the embedded webview engine runtime."""
    engine_type: str              # "qtwebengine", "webview2", "electron", "chromium", "unknown"
    version: Optional[str] = None
    detected_confidence: str = "unknown"
    framework_indicators: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine_type": self.engine_type,
            "version": self.version,
            "detected_confidence": self.detected_confidence,
            "framework_indicators": self.framework_indicators,
        }


@dataclass(frozen=True)
class DebuggingEndpointIdentity:
    """CDP WebSocket endpoint identity."""
    port: int
    host: str = "127.0.0.1"
    target_id: Optional[str] = None
    type: str = "page"            # "page", "iframe", "worker"
    url: Optional[str] = None
    title: Optional[str] = None
    ws_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "port": self.port,
            "host": self.host,
            "target_id": self.target_id,
            "type": self.type,
            "url": self.url,
            "title": self.title,
            "ws_url": self.ws_url,
        }


@dataclass(frozen=True)
class NativeAutomationContext:
    """Context for native UIA3 automation."""
    hwnd: int
    pid: int
    uia_supported: bool = True
    sidecar_pipe_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd),
            "pid": self.pid,
            "uia_supported": self.uia_supported,
            "sidecar_pipe_name": self.sidecar_pipe_name,
        }


class TargetManager:
    """
    Authoritative Multi-dimensional Target Manager.
    Separates process, window, webview runtime, debugging endpoint, and native automation contexts.
    Enforces a single authoritative validation path to guarantee physical window and process identity.
    """

    def __init__(self):
        self._correlated_targets: Dict[str, Dict[str, Any]] = {}

    def correlate_process(self, pid: int) -> ProcessIdentity:
        """
        Validates that a process exists and captures its immutable identity tuple:
        (PID, creation_time, binary_path).
        """
        if pid <= 0:
            raise InvalidTargetException(f"Invalid process ID: {pid}")

        creation_time = time.time()
        binary_path = ""
        cmdline = []
        is_elevated = False

        if psutil is not None:
            try:
                proc = psutil.Process(pid)
                creation_time = proc.create_time()
                try:
                    binary_path = proc.exe()
                except Exception:
                    binary_path = proc.name()
                try:
                    cmdline = proc.cmdline()
                except Exception:
                    pass
            except psutil.NoSuchProcess:
                raise TargetExitedException(pid)
            except Exception as e:
                logger.warning(f"Error inspecting PID {pid}: {e}")
        else:
            try:
                import os
                os.kill(pid, 0)
            except OSError:
                raise TargetExitedException(pid)

        return ProcessIdentity(
            pid=pid,
            creation_time=creation_time,
            binary_path=binary_path,
            command_line=cmdline,
            is_elevated=is_elevated,
        )

    def verify_process_identity(self, identity: ProcessIdentity) -> None:
        """
        Verifies that the target process is still running and is the exact same process
        (matching create_time within 1.0s) to defend against PID recycling.
        """
        if psutil is not None:
            try:
                proc = psutil.Process(identity.pid)
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    raise TargetExitedException(identity.pid)
                actual_time = proc.create_time()
                if abs(actual_time - identity.creation_time) > 1.0:
                    raise TargetMismatchException(
                        expected_pid=identity.pid,
                        actual_pid=identity.pid,
                        reason=f"create_time mismatch (expected {identity.creation_time}, got {actual_time}) - recycled PID",
                    )
            except psutil.NoSuchProcess:
                raise TargetExitedException(identity.pid)
        else:
            try:
                import os
                os.kill(identity.pid, 0)
            except OSError:
                raise TargetExitedException(identity.pid)

    # -------------------------------------------------------------------------
    # Single Authoritative Window Identity Validation Path
    # -------------------------------------------------------------------------
    def validate_window_identity(
        self,
        hwnd: int,
        expected_pid: Optional[int] = None,
        expected_create_time: Optional[float] = None,
        expected_title_substring: Optional[str] = None,
        expected_class_name: Optional[str] = None,
    ) -> WindowValidationResult:
        """
        Single Authoritative Validation Path (Goal 4 & Goal B):
        Validates window existence, owning PID, process creation time (defending against PID reuse),
        window class/title, DWM bounds, and pre-flight responsiveness.
        Never guesses; returns explicit WindowValidationResult with machine-readable error codes.
        """
        # 1. Existence check
        if not NativeOSSupervisor.is_window_valid(hwnd):
            return WindowValidationResult(
                is_valid=False,
                error_code="WINDOW_NOT_FOUND",
                failure_reason=f"Window handle HWND {hex(hwnd)} does not exist or has been destroyed",
            )

        # 2. Owning PID check
        actual_pid = NativeOSSupervisor.get_window_pid(hwnd)
        if expected_pid is not None and actual_pid != expected_pid:
            return WindowValidationResult(
                is_valid=False,
                error_code="TARGET_MISMATCH",
                failure_reason=f"HWND {hex(hwnd)} is owned by PID {actual_pid}, expected PID {expected_pid}",
                diagnostics={"actual_pid": actual_pid, "expected_pid": expected_pid},
            )

        # 3. Process create_time check (PID recycling defense)
        proc_create_time = None
        if actual_pid > 0 and psutil is not None:
            try:
                p = psutil.Process(actual_pid)
                proc_create_time = p.create_time()
                if expected_create_time is not None:
                    if abs(proc_create_time - expected_create_time) > 1.0:
                        return WindowValidationResult(
                            is_valid=False,
                            error_code="TARGET_MISMATCH",
                            failure_reason=(
                                f"PID {actual_pid} create_time mismatch (expected {expected_create_time}, "
                                f"got {proc_create_time}). Target PID has been recycled."
                            ),
                            diagnostics={
                                "actual_create_time": proc_create_time,
                                "expected_create_time": expected_create_time,
                            },
                        )
            except psutil.NoSuchProcess:
                return WindowValidationResult(
                    is_valid=False,
                    error_code="TARGET_EXITED",
                    failure_reason=f"Owning process PID {actual_pid} has exited",
                )

        # 4. Forensic inspection (DWM bounds, cloaked, client rect, title, class, responsiveness)
        try:
            report = NativeOSSupervisor.inspect_window(
                hwnd, check_health=True, check_occlusion=False, check_modals=False
            )
        except InvalidTargetException as e:
            return WindowValidationResult(
                is_valid=False,
                error_code="WINDOW_NOT_FOUND",
                failure_reason=str(e),
            )

        # 5. Title substring matching
        if expected_title_substring is not None:
            if expected_title_substring.lower() not in report.title.lower():
                return WindowValidationResult(
                    is_valid=False,
                    error_code="TITLE_MISMATCH",
                    failure_reason=f"Window title '{report.title}' does not contain expected substring '{expected_title_substring}'",
                    diagnostics={"actual_title": report.title, "expected_substring": expected_title_substring},
                )

        # 6. Class name matching
        if expected_class_name is not None:
            if report.class_name != expected_class_name:
                return WindowValidationResult(
                    is_valid=False,
                    error_code="CLASS_MISMATCH",
                    failure_reason=f"Window class '{report.class_name}' does not match expected '{expected_class_name}'",
                    diagnostics={"actual_class": report.class_name, "expected_class": expected_class_name},
                )

        # 7. Construct verified WindowIdentity
        root_owner = NativeOSSupervisor.get_window_root(hwnd)
        parent = NativeOSSupervisor.get_window_owner(hwnd)

        identity = WindowIdentity(
            hwnd=hwnd,
            pid=actual_pid,
            title=report.title,
            class_name=report.class_name,
            bounds=report.bounds,
            raw_window_rect=report.raw_window_rect,
            client_rect=report.client_rect,
            is_visible=report.is_visible,
            is_cloaked=report.is_cloaked,
            is_minimized=report.is_iconic,
            is_hung=report.is_hung,
            dpi_scaling=report.dpi_scaling,
            creation_time=proc_create_time,
            root_owner_hwnd=root_owner,
            parent_hwnd=parent,
            health_state=report.health_state,
        )

        return WindowValidationResult(
            is_valid=True,
            window=identity,
            diagnostics={
                "bounds": report.bounds.to_dict(),
                "health_state": report.health_state.value,
                "dpi_scaling": report.dpi_scaling,
            },
        )

    def correlate_window(
        self,
        hwnd: int,
        expected_pid: Optional[int] = None,
        expected_create_time: Optional[float] = None,
    ) -> WindowIdentity:
        """
        Inspects window state using the single authoritative validation path.
        Raises structured TargetMismatchException or InvalidTargetException on failure.
        """
        result = self.validate_window_identity(
            hwnd=hwnd,
            expected_pid=expected_pid,
            expected_create_time=expected_create_time,
        )

        if not result.is_valid:
            if result.error_code == "TARGET_MISMATCH":
                raise TargetMismatchException(
                    expected_pid=expected_pid or 0,
                    actual_pid=result.diagnostics.get("actual_pid", 0),
                    reason=result.failure_reason or "Target mismatch",
                )
            if result.error_code == "TARGET_EXITED":
                raise TargetExitedException(expected_pid or hwnd)
            raise InvalidTargetException(result.failure_reason or f"Window HWND {hex(hwnd)} is invalid", target_id=str(hwnd))

        assert result.window is not None
        return result.window

    def correlate_cdp_targets(
        self, port: int, host: str = "127.0.0.1", timeout: float = 3.0
    ) -> List[DebuggingEndpointIdentity]:
        """
        Queries http://{host}:{port}/json/list to enumerate active CDP page targets.
        """
        url = f"http://{host}:{port}/json/list"
        req = urllib.request.Request(url, headers={"User-Agent": "DesktopWebViewReviewer/1.0"})
        endpoints: List[DebuggingEndpointIdentity] = []

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list):
                    for item in data:
                        endpoints.append(
                            DebuggingEndpointIdentity(
                                port=port,
                                host=host,
                                target_id=item.get("id"),
                                type=item.get("type", "page"),
                                url=item.get("url"),
                                title=item.get("title"),
                                ws_url=item.get("webSocketDebuggerUrl"),
                            )
                        )
        except Exception as e:
            logger.debug(f"Failed to query CDP endpoints at {url}: {e}")

        return endpoints

    def match_window_to_cdp(
        self,
        window: WindowIdentity,
        cdp_targets: List[DebuggingEndpointIdentity],
    ) -> Optional[DebuggingEndpointIdentity]:
        """
        Correlates a native window with its corresponding embedded CDP target page.
        Prioritizes exact/substring title matches, followed by non-blank pages.
        """
        pages = [t for t in cdp_targets if t.type == "page" and t.ws_url]
        if not pages:
            return None

        win_title = window.title.strip().lower()
        if win_title:
            for p in pages:
                p_title = (p.title or "").strip().lower()
                if p_title and (p_title in win_title or win_title in p_title):
                    return p

        return pages[0]
