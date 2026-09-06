"""
Lifecycle tools for Desktop WebView Reviewer MCP Control Plane.
Implements desktop_launch and desktop_attach with process supervision,
Job Object binding, identity correlation, and initial observation capture (Docs 14 §3.1-3.2).
"""

from __future__ import annotations
import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime.state import TargetPlane, SessionLifecycleState
from runtime.target_manager import WindowIdentity
from runtime.native_supervisor import NativeSupervisor
from runtime.cdp_target import CDPTargetManager
from runtime.mcp.errors import McpErrorCode, McpControlPlaneException, map_exception_to_mcp_error
from runtime.mcp.security import SecurityGate
from runtime.mcp.runtime_bridge import RuntimeBridge

logger = logging.getLogger("desktop_webview.mcp.tools.lifecycle")


async def desktop_launch_impl(
    bridge: RuntimeBridge,
    executable_path: str,
    args: Optional[List[str]] = None,
    working_directory: Optional[str] = None,
    engine_hint: str = "auto",
    remote_debugging_port: Optional[int] = None,
    timeout_sec: int = 30,
) -> Dict[str, Any]:
    """
    Spawns a target desktop application within a managed Windows Job Object.
    Discovers native window HWND, webview CDP target if available, creates a session,
    and returns initial accessibility state.
    """
    try:
        await bridge.ensure_initialized()

        # 1. Security Gate Validation
        clean_exe = SecurityGate.validate_executable_path(executable_path)
        clean_port = SecurityGate.validate_cdp_port(remote_debugging_port)
        cmd_args = [str(clean_exe)] + (list(args) if args else [])
        cwd = str(Path(working_directory).resolve()) if working_directory else None

        # 2. Prepare environment and adapter flags
        env = os.environ.copy()
        adapter = None
        if working_directory:
            try:
                from detectors.engine_detector import EngineDetector
                adapter, _ = EngineDetector.detect_with_details(working_directory)
            except Exception:
                pass
        if not adapter and engine_hint and engine_hint != "auto":
            try:
                from adapters import get_adapter
                adapter = get_adapter(engine_hint)
            except Exception:
                pass

        if adapter and clean_port:
            env = adapter.prepare_environment(env, port=clean_port)
            adapter_flags = adapter.get_launch_args(port=clean_port)
            for flag in adapter_flags:
                if flag not in cmd_args:
                    cmd_args.append(flag)
        elif clean_port:
            cmd_args.append(f"--remote-debugging-port={clean_port}")

        # 3. Launch supervised process via DesktopDaemon (Win32 Job Object)
        session = await bridge.daemon.launch_target(
            cmd=cmd_args,
            cwd=cwd,
            env=env,
            cdp_port=remote_debugging_port,
            lease_timeout_sec=300,
        )

        assert session.target_process is not None, "Target process is missing"
        pid = session.target_process.pid

        # 3. Discover native HWND
        supervisor = NativeSupervisor()
        candidate_pids = {pid}
        try:
            import psutil
            proc = psutil.Process(pid)
            for child in proc.children(recursive=True):
                candidate_pids.add(child.pid)
        except Exception:
            pass

        primary_hwnd = 0
        deadline = time.time() + min(timeout_sec, 15)
        while time.time() < deadline:
            try:
                import psutil
                proc = psutil.Process(pid)
                candidate_pids = {pid}.union({c.pid for c in proc.children(recursive=True)})
            except Exception:
                pass
            for c_pid in candidate_pids:
                hwnds = supervisor.find_windows_by_pid(c_pid)
                for h in hwnds:
                    if supervisor.is_window_visible(h):
                        primary_hwnd = h
                        break
                if primary_hwnd:
                    break
            if primary_hwnd:
                break
            await asyncio.sleep(0.5)

        if primary_hwnd:
            try:
                insp = supervisor.inspect_window(primary_hwnd)
                session.target_window = WindowIdentity(
                    hwnd=primary_hwnd,
                    pid=insp.pid,
                    title=insp.title,
                    class_name=insp.class_name,
                    bounds=insp.bounds,
                    is_visible=insp.is_visible,
                    is_cloaked=insp.is_cloaked,
                    is_minimized=insp.is_minimized,
                    is_hung=insp.is_hung,
                )
            except Exception:
                session.target_window = WindowIdentity(
                    hwnd=primary_hwnd,
                    pid=pid,
                    title="",
                    class_name="",
                    bounds=supervisor.get_window_bounds(primary_hwnd),
                    is_visible=True,
                    is_cloaked=False,
                    is_minimized=False,
                    is_hung=False,
                )

        # 4. Initialize engines & discover webview if CDP port is provided
        await bridge.initialize_session_engines(
            session=session,
            primary_hwnd=primary_hwnd if primary_hwnd else None,
            cdp_port=remote_debugging_port,
        )

        # 4.1 Re-probe for top-level window if process was still launching during initial probe
        if not primary_hwnd or primary_hwnd == 0:
            try:
                import psutil
                proc = psutil.Process(pid)
                candidate_pids = {pid}.union({c.pid for c in proc.children(recursive=True)})
                for c_pid in candidate_pids:
                    hwnds = supervisor.find_windows_by_pid(c_pid)
                    for h in hwnds:
                        if supervisor.is_window_visible(h):
                            primary_hwnd = h
                            break
                    if primary_hwnd:
                        break
                if primary_hwnd:
                    insp = supervisor.inspect_window(primary_hwnd)
                    session.target_window = WindowIdentity(
                        hwnd=primary_hwnd,
                        pid=insp.pid,
                        title=insp.title,
                        class_name=insp.class_name,
                        bounds=insp.bounds,
                        is_visible=insp.is_visible,
                        is_cloaked=insp.is_cloaked,
                        is_minimized=insp.is_minimized,
                        is_hung=insp.is_hung,
                    )
            except Exception:
                pass

        active_plane = TargetPlane.WEBVIEW_DOM if session.webview_core else TargetPlane.NATIVE_SHELL
        await bridge.daemon.session_manager.connect_session(session.session_id)
        await bridge.daemon.session_manager.activate_session(session.session_id, plane=active_plane)

        # 5. Capture initial snapshot
        initial_snapshot = ""
        try:
            assert session.observation_engine is not None, "Observation engine not initialized"
            snap = await session.observation_engine.observe(hwnd=primary_hwnd if primary_hwnd else None)
            initial_snapshot = snap.text_representation
        except Exception as e:
            logger.debug(f"Initial observation skipped: {e}")
            initial_snapshot = f"# Active Window HWND {hex(primary_hwnd) if primary_hwnd else 'None'} (initial observation deferred)"

        caps = [c.value if hasattr(c, "value") else str(c) for c in session.capabilities.supported_capabilities()]

        return {
            "session_id": session.session_id,
            "pid": pid,
            "hwnd": primary_hwnd,
            "capabilities": caps,
            "active_plane": active_plane.value,
            "initial_snapshot": initial_snapshot,
            "observation_epoch": session.current_epoch,
            "lifecycle_state": session.lifecycle_state.value,
        }
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()


async def desktop_attach_impl(
    bridge: RuntimeBridge,
    hwnd: Optional[int] = None,
    pid: Optional[int] = None,
    window_title_pattern: Optional[str] = None,
    cdp_port: Optional[int] = None,
    timeout_sec: int = 30,
) -> Dict[str, Any]:
    """
    Attaches to an existing running application window or process without re-launching.
    Correlates PID, HWND, and CDP port.
    """
    try:
        await bridge.ensure_initialized()

        target_hwnd = SecurityGate.validate_hwnd(hwnd)
        target_pid = SecurityGate.validate_pid(pid)
        clean_cdp_port = SecurityGate.validate_cdp_port(cdp_port)

        supervisor = NativeSupervisor()

        # Resolve HWND / PID by window title pattern if needed
        if not target_hwnd and window_title_pattern:
            all_hwnds = supervisor.list_top_level_windows(visible_only=True)
            for h in all_hwnds:
                try:
                    insp = supervisor.inspect_window(h)
                    if window_title_pattern.lower() in insp.title.lower():
                        target_hwnd = h
                        target_pid = insp.pid
                        break
                except Exception:
                    continue

        # Resolve PID from HWND
        if target_hwnd and not target_pid:
            target_pid = supervisor.get_window_pid(target_hwnd)

        # Resolve HWND from PID
        if target_pid and not target_hwnd:
            hwnds = supervisor.find_windows_by_pid(target_pid)
            for h in hwnds:
                if supervisor.is_window_visible(h):
                    target_hwnd = h
                    break

        if not target_pid and not target_hwnd and not clean_cdp_port:
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message="At least one of 'hwnd', 'pid', 'window_title_pattern', or 'cdp_port' must be provided to attach.",
                agent_action_hint="Specify a running PID, HWND, or CDP port.",
            )

        # Attach process via daemon
        resolved_pid = target_pid or (os.getpid() if not target_pid else target_pid)
        session = await bridge.daemon.attach_target_process(
            pid=resolved_pid,
            hwnd=target_hwnd,
            cdp_port=clean_cdp_port,
            lease_timeout_sec=300,
        )

        if target_hwnd:
            try:
                insp = supervisor.inspect_window(target_hwnd)
                session.target_window = WindowIdentity(
                    hwnd=target_hwnd,
                    pid=insp.pid,
                    title=insp.title,
                    class_name=insp.class_name,
                    bounds=insp.bounds,
                    is_visible=insp.is_visible,
                    is_cloaked=insp.is_cloaked,
                    is_minimized=insp.is_minimized,
                    is_hung=insp.is_hung,
                )
            except Exception:
                session.target_window = WindowIdentity(
                    hwnd=target_hwnd,
                    pid=resolved_pid,
                    title="",
                    class_name="",
                    bounds=supervisor.get_window_bounds(target_hwnd),
                    is_visible=True,
                    is_cloaked=False,
                    is_minimized=False,
                    is_hung=False,
                )

        # Initialize engines & CDP
        await bridge.initialize_session_engines(
            session=session,
            primary_hwnd=target_hwnd,
            cdp_port=cdp_port,
        )

        active_plane = TargetPlane.WEBVIEW_DOM if session.webview_core else TargetPlane.NATIVE_SHELL
        await bridge.daemon.session_manager.connect_session(session.session_id)
        await bridge.daemon.session_manager.activate_session(session.session_id, plane=active_plane)

        # Capture initial snapshot
        initial_snapshot = ""
        try:
            assert session.observation_engine is not None, "Observation engine not initialized"
            snap = await session.observation_engine.observe(hwnd=target_hwnd)
            initial_snapshot = snap.text_representation
        except Exception as e:
            initial_snapshot = f"# Attached Session {session.session_id} (HWND {hex(target_hwnd) if target_hwnd else 'None'})"

        caps = [c.value if hasattr(c, "value") else str(c) for c in session.capabilities.supported_capabilities()]

        return {
            "session_id": session.session_id,
            "pid": resolved_pid,
            "hwnd": target_hwnd or 0,
            "capabilities": caps,
            "active_plane": active_plane.value,
            "initial_snapshot": initial_snapshot,
            "observation_epoch": session.current_epoch,
            "lifecycle_state": session.lifecycle_state.value,
        }
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()
