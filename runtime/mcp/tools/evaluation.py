"""
JavaScript evaluation tool for Desktop WebView Reviewer MCP Control Plane.
Safely evaluates JS in the isolated utility realm (__utility_world__) by default (Docs 14 §3.10 & 19 §3).
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict, Optional, Set

from runtime.session_manager import TargetPlane
from runtime.mcp.errors import map_exception_to_mcp_error, McpControlPlaneException, McpErrorCode
from runtime.mcp.security import SecurityGate
from runtime.mcp.runtime_bridge import RuntimeBridge

logger = logging.getLogger("desktop_webview.mcp.tools.evaluation")


def _sanitize_for_json(val: Any, max_depth: int = 8, seen: Optional[Set[int]] = None) -> Any:
    """
    Recursively sanitizes evaluation output into JSON-compliant structures.
    Prevents cyclic reference recursion, huge binary dumps, and non-serializable objects.
    """
    if seen is None:
        seen = set()

    if val is None or isinstance(val, (int, float, bool)):
        return val

    if isinstance(val, str):
        if len(val) > 10000:
            return val[:10000] + "... [TRUNCATED_PAYLOAD]"
        return val

    if isinstance(val, bytes):
        return f"[BINARY_DATA: {len(val)} bytes]"

    val_id = id(val)
    if val_id in seen or max_depth <= 0:
        return "[CIRCULAR_OR_DEEP_REFERENCE]"

    seen.add(val_id)
    try:
        if isinstance(val, dict):
            clean_dict: Dict[str, Any] = {}
            for idx, (k, v) in enumerate(val.items()):
                if idx >= 150:
                    clean_dict["_truncated"] = f"Total {len(val)} keys; remaining keys omitted"
                    break
                clean_dict[str(k)] = _sanitize_for_json(v, max_depth - 1, seen)
            return clean_dict
        elif isinstance(val, (list, tuple, set)):
            clean_list = []
            for idx, item in enumerate(val):
                if idx >= 200:
                    clean_list.append(f"[Truncated: Total {len(val)} items]")
                    break
                clean_list.append(_sanitize_for_json(item, max_depth - 1, seen))
            return clean_list
        else:
            return str(val)
    finally:
        seen.discard(val_id)


async def desktop_evaluate_impl(
    bridge: RuntimeBridge,
    session_id: str,
    expression: str,
    in_main_world: bool = False,
    timeout_ms: int = 5000,
) -> Dict[str, Any]:
    """
    Evaluates a JavaScript expression safely inside the webview's execution realm.

    World Isolation Semantics:
    -------------------------
    - in_main_world = False (DEFAULT & RECOMMENDED):
      Executes inside '__utility_world__', an isolated V8 script execution realm.
      Shares the same DOM tree and window geometry as the application, but possesses
      its own independent JavaScript global namespace (window). Scripts evaluated here
      CANNOT be inspected, tampered with, or poisoned by the application's page scripts,
      and cannot accidentally overwrite application global state.

    - in_main_world = True:
      Executes inside the application's primary JavaScript context.
      Use ONLY when verifying application-specific global variables (e.g. window.__APP_STATE__,
      Redux stores, Qt WebChannel bridges) or triggering application functions that cannot
      be reached via DOM affordances.

    Safety Guarantees:
    ------------------
    - Expression length is capped at 10,000 characters to prevent memory exhaustion.
    - Result serialization is capped at 500 KB to avoid stdio buffer deadlocks.
    - Cyclic object graphs and deeply nested structures are neutralized into safe tokens.
    - Timeouts are strictly enforced (500ms to 30,000ms bounds).
    - Failure during target navigation or frame detachment is captured cleanly without crashing.
    """
    try:
        clean_sid = SecurityGate.validate_session_id(session_id)
        clean_expr = SecurityGate.validate_js_expression(expression)
        bounded_timeout_ms = max(500, min(timeout_ms, 30000))

        session = bridge.get_session(clean_sid)

        if session.active_plane == TargetPlane.NATIVE_SHELL and not session.webview_core:
            raise McpControlPlaneException(
                code=McpErrorCode.CAPABILITY_UNAVAILABLE,
                message=f"Session '{session_id}' is operating on NATIVE_SHELL plane and does not host an active webview for JavaScript evaluation.",
                agent_action_hint="Inspect UI via desktop_inspect or interact using native input actions.",
            )

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

        timeout_sec = bounded_timeout_ms / 1000.0
        try:
            val = await core.evaluate_script(
                expression=clean_expr,
                in_utility_world=(not in_main_world),
                timeout=timeout_sec,
            )

            # Sanitize and guard against circular or oversized structures
            safe_val = _sanitize_for_json(val)
            try:
                serialized = json.dumps(safe_val)
                if len(serialized) > SecurityGate.MAX_SERIALIZED_RESULT_SIZE:
                    return {
                        "result": serialized[:SecurityGate.MAX_SERIALIZED_RESULT_SIZE] + "... [truncated]",
                        "exception_details": f"Evaluation result exceeded maximum allowed serialization size ({len(serialized)} bytes).",
                    }
            except Exception:
                safe_val = str(safe_val)

            return {
                "result": safe_val,
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
