"""
JavaScript evaluation tool for Desktop WebView Reviewer MCP Control Plane.
Safely evaluates JS in the isolated utility realm (__utility_world__) by default (Docs 14 §3.10 & 19 §3).
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict, Optional

from runtime.mcp.errors import map_exception_to_mcp_error, McpControlPlaneException, McpErrorCode
from runtime.mcp.security import SecurityGate
from runtime.mcp.runtime_bridge import RuntimeBridge

logger = logging.getLogger("desktop_webview.mcp.tools.evaluation")


async def desktop_evaluate_impl(
    bridge: RuntimeBridge,
    session_id: str,
    expression: str,
    in_main_world: bool = False,
    timeout_ms: int = 5000,
) -> Dict[str, Any]:
    """
    Evaluates a JavaScript expression safely inside the webview's isolated utility realm.
    Enforces expression length constraints and payload bounding.
    """
    try:
        clean_expr = SecurityGate.validate_js_expression(expression)
        session = bridge.get_session(session_id)

        await bridge.initialize_session_engines(
            session,
            primary_hwnd=session.target_window.hwnd if session.target_window else None,
            cdp_port=session.target_endpoint.port if session.target_endpoint else None,
        )

        core = session.webview_core
        if not core or not core.is_connected:
            return {
                "result": None,
                "exception_details": "Webview automation core is not attached or connected to this session.",
            }

        timeout_sec = max(1.0, timeout_ms / 1000.0)
        try:
            val = await core.evaluate_script(
                expression=clean_expr,
                in_utility_world=(not in_main_world),
                timeout=timeout_sec,
            )

            # Test serialization size
            try:
                serialized = json.dumps(val)
                if len(serialized) > SecurityGate.MAX_SERIALIZED_RESULT_SIZE:
                    return {
                        "result": serialized[:SecurityGate.MAX_SERIALIZED_RESULT_SIZE] + "... [truncated]",
                        "exception_details": f"Evaluation result exceeded maximum allowed serialization size ({len(serialized)} bytes).",
                    }
            except (TypeError, ValueError):
                val = str(val)

            return {
                "result": val,
                "exception_details": None,
            }
        except Exception as e:
            return {
                "result": None,
                "exception_details": str(e),
            }
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()
