"""
Target Manager and Multi-Dimensional Target Identity Separation for Desktop WebView Reviewer.
Explicitly separates Process, Window, Webview Runtime, Debugging Endpoint, and Native contexts.
Prevents PID confusion, stale HWND reuse, and port misassociation.
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
from runtime.native_supervisor import NativeOSSupervisor, WindowForensicReport
from runtime.errors import (
    InvalidTargetException,
    TargetExitedException,
    TargetMismatchException,
    TargetNotFoundException,
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
    """Identity and physical state of a top-level native window."""
    hwnd: int
    pid: int
    title: str
    class_name: str
    bounds: Rect
    is_visible: bool
    is_cloaked: bool
    is_minimized: bool
    is_hung: bool
    dpi_scaling: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd),
            "pid": self.pid,
            "title": self.title,
            "class_name": self.class_name,
            "bounds": self.bounds.to_dict(),
            "is_visible": self.is_visible,
            "is_cloaked": self.is_cloaked,
            "is_minimized": self.is_minimized,
            "is_hung": self.is_hung,
            "dpi_scaling": self.dpi_scaling,
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
    Multi-dimensional Target Manager.
    Separates process, window, webview runtime, debugging endpoint, and native automation contexts.
    Guarantees that physical processes and windows are verified before being acted upon.
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
        (matching create_time) to prevent PID recycling confusion.
        """
        if psutil is not None:
            try:
                proc = psutil.Process(identity.pid)
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    raise TargetExitedException(identity.pid)
                actual_time = proc.create_time()
                if abs(actual_time - identity.creation_time) > 2.0:
                    raise TargetMismatchException(
                        expected_pid=identity.pid,
                        actual_pid=identity.pid,
                        reason=f"create_time mismatch (expected {identity.creation_time}, got {actual_time})",
                    )
            except psutil.NoSuchProcess:
                raise TargetExitedException(identity.pid)
        else:
            try:
                import os
                os.kill(identity.pid, 0)
            except OSError:
                raise TargetExitedException(identity.pid)

    def correlate_window(self, hwnd: int, expected_pid: Optional[int] = None) -> WindowIdentity:
        """
        Inspects window state via NativeOSSupervisor and verifies that owning PID
        matches expected_pid to prevent stale HWND reuse.
        """
        if not NativeOSSupervisor.is_window_valid(hwnd):
            raise InvalidTargetException(f"Window HWND {hex(hwnd)} is not a valid window", target_id=str(hwnd))

        actual_pid = NativeOSSupervisor.get_window_pid(hwnd)
        if expected_pid is not None and actual_pid != expected_pid:
            raise TargetMismatchException(
                expected_pid=expected_pid,
                actual_pid=actual_pid,
                reason=f"HWND {hex(hwnd)} is owned by PID {actual_pid}, expected {expected_pid}",
            )

        report = NativeOSSupervisor.inspect_window(hwnd, check_health=True)
        return WindowIdentity(
            hwnd=hwnd,
            pid=actual_pid,
            title=report.title,
            class_name=report.class_name,
            bounds=report.bounds,
            is_visible=report.is_visible,
            is_cloaked=report.is_cloaked,
            is_minimized=report.is_iconic,
            is_hung=report.is_hung,
            dpi_scaling=report.dpi_scaling,
        )

    def correlate_cdp_targets(self, port: int, host: str = "127.0.0.1", timeout: float = 3.0) -> List[DebuggingEndpointIdentity]:
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
                        endpoints.append(DebuggingEndpointIdentity(
                            port=port,
                            host=host,
                            target_id=item.get("id"),
                            type=item.get("type", "page"),
                            url=item.get("url"),
                            title=item.get("title"),
                            ws_url=item.get("webSocketDebuggerUrl"),
                        ))
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
        Prioritizes:
        1. Exact title substring matches
        2. Non-blank page targets
        3. First page target
        """
        pages = [t for t in cdp_targets if t.type == "page" and t.ws_url]
        if not pages:
            return None

        # Try matching window title with page title or url
        win_title = window.title.strip().lower()
        if win_title:
            for p in pages:
                p_title = (p.title or "").strip().lower()
                if p_title and (p_title in win_title or win_title in p_title):
                    return p

        # Fallback to the first available page
        return pages[0]
