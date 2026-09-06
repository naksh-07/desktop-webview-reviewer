"""
Verification assertion tool for Desktop WebView Reviewer MCP Control Plane.
Implements desktop_assert with auto-retrying polling on element state or text (Docs 14 §3.11 & 18).
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, Optional

from runtime.mcp.errors import map_exception_to_mcp_error, McpControlPlaneException, McpErrorCode
from runtime.mcp.security import SecurityGate
from runtime.mcp.runtime_bridge import RuntimeBridge

logger = logging.getLogger("desktop_webview.mcp.tools.verification")


async def desktop_assert_impl(
    bridge: RuntimeBridge,
    session_id: str,
    ref: str,
    assertion: str,
    expected_text: Optional[str] = None,
    timeout_ms: int = 5000,
) -> Dict[str, Any]:
    """
    Performs an auto-retrying polling assertion on UI state or content before proceeding.
    """
    try:
        clean_sid = SecurityGate.validate_session_id(session_id)
        clean_ref = SecurityGate.validate_ref(ref)
        assertion_map = {
            "visible": "is_visible",
            "is_visible": "is_visible",
            "hidden": "is_hidden",
            "is_hidden": "is_hidden",
            "has_text": "has_text",
            "text": "has_text",
            "enabled": "is_enabled",
            "is_enabled": "is_enabled",
        }
        normalized_assertion = assertion_map.get(assertion)
        if not normalized_assertion:
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message=f"Invalid assertion '{assertion}'. Must be one of {set(assertion_map.keys())}.",
            )
        assertion = normalized_assertion

        if assertion == "has_text":
            if expected_text is None:
                raise McpControlPlaneException(
                    code=McpErrorCode.INVALID_ARGUMENT,
                    message="'expected_text' is required when assertion is 'has_text'.",
                )
            expected_text = SecurityGate.validate_text_input(expected_text)

        session = bridge.get_session(clean_sid)
        await bridge.initialize_session_engines(
            session,
            primary_hwnd=session.target_window.hwnd if session.target_window else None,
            cdp_port=session.target_endpoint.port if session.target_endpoint else None,
        )

        start_time = time.time()
        timeout_sec = max(0.5, timeout_ms / 1000.0)
        deadline = start_time + timeout_sec
        interval = 0.1

        actual_val: Optional[str] = None
        last_err: Optional[str] = None
        passed = False
        assert session.actionability_engine is not None, "Actionability engine not initialized"

        while time.time() < deadline:
            try:
                # Check reference in registry
                elem_ref = session.reference_registry.get_ref(ref)

                if assertion == "is_visible":
                    if elem_ref:
                        # Re-check actionability visibility
                        act_res = await session.actionability_engine.evaluate_actionability(ref_id=ref, timeout_ms=500)
                        actual_val = f"visible={act_res.visibility}, attached={act_res.attachment}"
                        if act_res.visibility and act_res.attachment:
                            passed = True
                            break
                    else:
                        actual_val = "ref_not_found"

                elif assertion == "is_hidden":
                    if not elem_ref:
                        actual_val = "ref_not_found"
                        passed = True
                        break
                    else:
                        act_res = await session.actionability_engine.evaluate_actionability(ref_id=ref, timeout_ms=500)
                        actual_val = f"visible={act_res.visibility}"
                        if not act_res.visibility or not act_res.attachment:
                            passed = True
                            break

                elif assertion == "has_text":
                    if elem_ref:
                        name_str = elem_ref.name or ""
                        actual_val = name_str
                        if expected_text and (expected_text.lower() in name_str.lower() or expected_text == name_str):
                            passed = True
                            break
                    else:
                        actual_val = "ref_not_found"

                elif assertion == "is_enabled":
                    if elem_ref:
                        act_res = await session.actionability_engine.evaluate_actionability(ref_id=ref, timeout_ms=500)
                        actual_val = f"enabled={act_res.enabled}"
                        if act_res.enabled:
                            passed = True
                            break
                    else:
                        actual_val = "ref_not_found"

            except Exception as e:
                last_err = str(e)

            await asyncio.sleep(interval)
            interval = min(interval * 1.5, 0.5)

        elapsed_ms = round((time.time() - start_time) * 1000.0, 2)

        if not passed and not last_err:
            last_err = f"Assertion '{assertion}' not satisfied after {elapsed_ms}ms (actual value: {actual_val})."

        return {
            "passed": passed,
            "duration_ms": elapsed_ms,
            "actual_value": actual_val,
            "reason": f"Assertion '{assertion}' satisfied ({actual_val})" if passed else (last_err or "Assertion failed"),
            "error": None if passed else last_err,
        }
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()
