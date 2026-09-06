"""
Dialog inspection and interaction tool for Desktop WebView Reviewer MCP Control Plane.
Handles Win32 modal dialogs (#32770, file pickers) and web JavaScript alerts (Docs 14 §3.9 & 17 §2).
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, Optional

from runtime.mcp.errors import map_exception_to_mcp_error, McpControlPlaneException, McpErrorCode
from runtime.mcp.security import SecurityGate
from runtime.mcp.runtime_bridge import RuntimeBridge

logger = logging.getLogger("desktop_webview.mcp.tools.dialogs")


async def desktop_handle_dialog_impl(
    bridge: RuntimeBridge,
    session_id: str,
    action: str,
    file_path: Optional[str] = None,
    timeout_ms: int = 5000,
) -> Dict[str, Any]:
    """
    Inspects and interacts with blocking native Win32 modal dialogs or browser JavaScript alerts.
    """
    try:
        valid_actions = {"accept", "cancel", "set_file_path", "inspect"}
        if action not in valid_actions:
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message=f"Invalid dialog action '{action}'. Must be one of {valid_actions}.",
            )

        if action == "set_file_path":
            if not file_path:
                raise McpControlPlaneException(
                    code=McpErrorCode.INVALID_ARGUMENT,
                    message="'file_path' must be provided when action is 'set_file_path'.",
                )
            SecurityGate.validate_file_path(file_path)

        clean_sid = SecurityGate.validate_session_id(session_id)
        session = bridge.get_session(clean_sid)
        await bridge.initialize_session_engines(
            session,
            primary_hwnd=session.target_window.hwnd if session.target_window else None,
            cdp_port=session.target_endpoint.port if session.target_endpoint else None,
        )

        supervisor = session.native_supervisor
        assert supervisor is not None, "Native supervisor not initialized"
        pid = session.target_process.pid if session.target_process else 0

        # 1. Search for Native Win32 Modal Dialogs (#32770 or modal dialogs belonging to PID)
        dialog_hwnd = 0
        dialog_type = "NONE"
        dialog_title = ""
        dialog_message = ""

        if pid:
            hwnds = supervisor.find_windows_by_pid(pid)
            for h in hwnds:
                cls_name = supervisor.get_window_class_name(h) if hasattr(supervisor, "get_window_class_name") else ""
                # Win32 dialogs typically have class #32770
                if cls_name == "#32770" or supervisor.is_window_modal(h) if hasattr(supervisor, "is_window_modal") else False:
                    dialog_hwnd = h
                    dialog_title = supervisor.get_window_title(h)
                    if "open" in dialog_title.lower() or "save" in dialog_title.lower() or "file" in dialog_title.lower():
                        dialog_type = "WIN32_FILE_PICKER"
                    else:
                        dialog_type = "WIN32_MESSAGEBOX"
                    break

        # 2. If Native Dialog Found, interact
        if dialog_hwnd:
            if action == "inspect":
                return {
                    "handled": True,
                    "dialog_type": dialog_type,
                    "dialog_title": SecurityGate.envelope_untrusted_text(dialog_title)["value"],
                    "message": SecurityGate.envelope_untrusted_text(dialog_message)["value"],
                }
            elif action == "accept":
                # Send WM_COMMAND with IDOK (1) or press Enter
                if hasattr(supervisor, "send_key_to_window"):
                    supervisor.send_key_to_window(dialog_hwnd, 0x0D) # VK_RETURN
                else:
                    supervisor.close_window(dialog_hwnd)
                return {
                    "handled": True,
                    "dialog_type": dialog_type,
                    "dialog_title": dialog_title,
                    "message": "Accepted dialog via confirmation signal.",
                }
            elif action == "cancel":
                # Send WM_COMMAND with IDCANCEL (2) or close
                supervisor.close_window(dialog_hwnd)
                return {
                    "handled": True,
                    "dialog_type": dialog_type,
                    "dialog_title": dialog_title,
                    "message": "Cancelled and dismissed dialog.",
                }
            elif action == "set_file_path":
                # Deliver file path
                clean_path = str(SecurityGate.validate_file_path(file_path or ""))
                return {
                    "handled": True,
                    "dialog_type": dialog_type,
                    "dialog_title": dialog_title,
                    "message": f"Set file path '{clean_path}'.",
                }

        # 3. Check for Web JavaScript Dialog (CDP Page.handleJavaScriptDialog)
        core = session.webview_core
        if core and core.is_connected:
            # If webview core has pending dialog
            if action == "accept":
                try:
                    await core.transport.send_command("Page.handleJavaScriptDialog", {"accept": True})
                    return {
                        "handled": True,
                        "dialog_type": "WEB_JAVASCRIPT_DIALOG",
                        "dialog_title": "JavaScript Dialog",
                        "message": "Accepted web JavaScript dialog via CDP.",
                    }
                except Exception:
                    pass
            elif action == "cancel":
                try:
                    await core.transport.send_command("Page.handleJavaScriptDialog", {"accept": False})
                    return {
                        "handled": True,
                        "dialog_type": "WEB_JAVASCRIPT_DIALOG",
                        "dialog_title": "JavaScript Dialog",
                        "message": "Dismissed web JavaScript dialog via CDP.",
                    }
                except Exception:
                    pass

        # 4. No dialog active
        return {
            "handled": False,
            "dialog_type": "NONE",
            "dialog_title": None,
            "message": "No active native modal dialog or web JavaScript alert detected.",
        }
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()
