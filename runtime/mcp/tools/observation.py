"""
Observation tool for Desktop WebView Reviewer MCP Control Plane.
Implements desktop_inspect exposing the dual-perspective observation engine (Docs 14 §3.3 & 16).
"""

from __future__ import annotations
import logging
from typing import Any, Dict, Optional, Set

from runtime.mcp.errors import map_exception_to_mcp_error
from runtime.mcp.security import SecurityGate
from runtime.mcp.runtime_bridge import RuntimeBridge
from runtime.native_supervisor import NativeSupervisor

logger = logging.getLogger("desktop_webview.mcp.tools.observation")


async def desktop_inspect_impl(
    bridge: RuntimeBridge,
    session_id: str,
    perspective: str = "auto",
    diff_only: bool = False,
    max_depth: int = 7,
    role: Optional[str] = None,
    visible_only: bool = True,
    actionable_only: bool = False,
) -> Dict[str, Any]:
    """
    Captures the dual-perspective state of the active window and returns a compact,
    ref-annotated accessibility tree without raw DOM or huge JSON payloads.
    """
    try:
        clean_sid = SecurityGate.validate_session_id(session_id)
        session = bridge.get_session(clean_sid)
        await bridge.initialize_session_engines(
            session,
            primary_hwnd=session.target_window.hwnd if session.target_window else None,
            cdp_port=session.target_endpoint.port if session.target_endpoint else None,
        )

        target_hwnd = session.target_window.hwnd if session.target_window else None
        if not target_hwnd and session.native_supervisor:
            target_pid = session.target_process.pid if session.target_process else None
            if target_pid:
                try:
                    candidate_pids = {target_pid}
                    import psutil
                    proc = psutil.Process(target_pid)
                    candidate_pids.update(c.pid for c in proc.children(recursive=True))
                    for c_pid in candidate_pids:
                        for h in session.native_supervisor.find_windows_by_pid(c_pid):
                            if session.native_supervisor.is_window_visible(h):
                                target_hwnd = h
                                insp = session.native_supervisor.inspect_window(h)
                                from runtime.target_manager import WindowIdentity
                                session.target_window = WindowIdentity(
                                    hwnd=h,
                                    pid=insp.pid,
                                    title=insp.title,
                                    class_name=insp.class_name,
                                    bounds=insp.bounds,
                                    is_visible=insp.is_visible,
                                    is_cloaked=insp.is_cloaked,
                                    is_minimized=insp.is_minimized,
                                    is_hung=insp.is_hung,
                                )
                                if session.webview_core:
                                    session.webview_core.native_hwnd = h
                                break
                        if target_hwnd:
                            break
                except Exception:
                    pass

        role_filter = {role} if role else None

        assert session.observation_engine is not None, "Observation engine not initialized"
        snapshot = await session.observation_engine.observe(
            hwnd=target_hwnd,
            diff_only=diff_only,
            max_depth=max_depth,
            role_filter=role_filter,
            visible_only=visible_only,
            actionable_only=actionable_only,
        )

        # Count total elements
        elem_count = 0
        if snapshot.web_observation and snapshot.web_observation.elements:
            elem_count += len(snapshot.web_observation.elements)
        if snapshot.native_observation and snapshot.native_observation.elements:
            elem_count += len(snapshot.native_observation.elements)

        # Extract window forensics
        supervisor = session.native_supervisor
        win_title = ""
        is_visible = True
        is_cloaked = False
        bounds = [0, 0, 0, 0]

        if target_hwnd and supervisor:
            try:
                insp = supervisor.inspect_window(target_hwnd)
                win_title = insp.title
                is_visible = insp.is_visible
                is_cloaked = insp.is_cloaked
                bounds = [insp.bounds.x, insp.bounds.y, insp.bounds.width, insp.bounds.height]
            except Exception:
                if session.target_window:
                    win_title = session.target_window.title
                    is_visible = session.target_window.is_visible
                    is_cloaked = session.target_window.is_cloaked
                    bounds = [
                        session.target_window.bounds.x,
                        session.target_window.bounds.y,
                        session.target_window.bounds.width,
                        session.target_window.bounds.height,
                    ]

        return {
            "session_id": session_id,
            "epoch_id": snapshot.epoch,
            "active_plane": session.active_plane.value,
            "tree": snapshot.text_representation,
            "is_diff": snapshot.is_diff,
            "element_count": elem_count,
            "window_forensics": {
                "title": SecurityGate.envelope_untrusted_text(win_title)["value"],
                "is_visible": is_visible,
                "is_cloaked": is_cloaked,
                "bounds": bounds,
            },
        }
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()


async def desktop_screenshot_impl(
    bridge: RuntimeBridge,
    session_id: str,
    scope: str = "window",
    ref: Optional[str] = None,
    store_evidence: bool = True,
) -> Dict[str, Any]:
    """
    Captures a real visual screenshot of the window, full desktop, or a specific element affordance.
    Returns SHA-256 content-addressed artifact reference and metadata.
    """
    try:
        clean_sid = SecurityGate.validate_session_id(session_id)
        session = bridge.get_session(clean_sid)
        supervisor = session.native_supervisor or NativeSupervisor()
        target_hwnd = session.target_window.hwnd if session.target_window else None

        png_bytes: Optional[bytes] = None
        crop_bounds: Optional[Dict[str, int]] = None

        if scope == "element" and ref:
            clean_ref = SecurityGate.validate_ref(ref)
            ref_obj = session.reference_registry.resolve_ref(clean_ref)
            if ref_obj and ref_obj.bounds and ref_obj.bounds.area > 0:
                crop_bounds = {
                    "x": int(ref_obj.bounds.x),
                    "y": int(ref_obj.bounds.y),
                    "width": int(ref_obj.bounds.width),
                    "height": int(ref_obj.bounds.height),
                }
                res = supervisor.capture_element_crop(hwnd=target_hwnd, element_bounds=ref_obj.bounds)
                png_bytes = res[1] if isinstance(res, tuple) and res[0] else (res if isinstance(res, bytes) else None)
        elif scope == "desktop":
            res = supervisor.capture_full_desktop_screenshot()
            png_bytes = res[1] if isinstance(res, tuple) and res[0] else (res if isinstance(res, bytes) else None)
        else:
            if target_hwnd:
                res = supervisor.capture_window_screenshot(target_hwnd)
                png_bytes = res[1] if isinstance(res, tuple) and res[0] else (res if isinstance(res, bytes) else None)
            if not png_bytes:
                res = supervisor.capture_full_desktop_screenshot()
                png_bytes = res[1] if isinstance(res, tuple) and res[0] else (res if isinstance(res, bytes) else None)

        if not png_bytes:
            return {
                "session_id": session_id,
                "success": False,
                "scope": scope,
                "error": "Screenshot capture unavailable in current desktop environment",
            }

        artifact_id = None
        sha256 = None
        size_bytes = len(png_bytes)

        if store_evidence and session.evidence_store:
            import uuid
            action_id = f"snap_{uuid.uuid4().hex[:8]}"
            rel_path = f"artifacts/screenshots/{scope}_{action_id}.png"
            artifact = session.evidence_store.store_bytes(
                session_id=clean_sid,
                action_id=action_id,
                relative_path=rel_path,
                data=png_bytes,
                mime_type="image/png",
                metadata={"scope": scope, "ref": ref, "epoch": session.current_epoch},
            )
            artifact_id = artifact.artifact_id
            sha256 = artifact.sha256

        return {
            "session_id": session_id,
            "success": True,
            "scope": scope,
            "artifact_id": artifact_id,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "epoch_id": session.current_epoch,
            "crop_bounds": crop_bounds,
        }
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()


async def desktop_get_trace_impl(
    bridge: RuntimeBridge,
    session_id: str,
    action_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Retrieves the chronological trace timeline of events for a session or action,
    providing complete causal reconstruction.
    """
    try:
        clean_sid = SecurityGate.validate_session_id(session_id)
        session = bridge.get_session(clean_sid)
        trace_engine = getattr(session, "trace_engine", None)
        if not trace_engine:
            return {
                "session_id": session_id,
                "total_events": 0,
                "events": [],
            }

        events = trace_engine.query(
            action_id=action_id,
            event_type=event_type,
            limit=limit,
        )

        return {
            "session_id": session_id,
            "action_id": action_id,
            "total_events": len(events),
            "events": [e.to_dict() for e in events],
        }
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()
