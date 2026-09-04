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
        role_filter = {role} if role else None

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
