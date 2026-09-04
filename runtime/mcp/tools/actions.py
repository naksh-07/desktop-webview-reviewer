"""
Action tools for Desktop WebView Reviewer MCP Control Plane.
Implements desktop_click, desktop_type, desktop_press_key, desktop_hover, and desktop_scroll
delegating entirely to the Phase 5 Action Engine (Docs 14 §3.4-3.8 & 17).
"""

from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, Optional

from runtime.action_models import ActionRequest, ActionType, ActionRiskLevel
from runtime.mcp.errors import map_exception_to_mcp_error, McpControlPlaneException, McpErrorCode
from runtime.mcp.runtime_bridge import RuntimeBridge

logger = logging.getLogger("desktop_webview.mcp.tools.actions")


def _format_action_result(outcome: Any, post_snapshot_str: Optional[str], cached: bool = False) -> Dict[str, Any]:
    """Formats standardized semantic response for mutating action tools."""
    receipt = outcome.receipt
    is_executed = receipt.dispatch_status.value == "DISPATCHED" if hasattr(receipt.dispatch_status, "value") else str(receipt.dispatch_status) == "DISPATCHED"
    receipt_summary = f"{receipt.action_type.value} on '{receipt.reference}' via {receipt.dispatch_method.value} (status: {receipt.dispatch_status.value})"

    res: Dict[str, Any] = {
        "executed": is_executed,
        "action_id": receipt.action_id,
        "cached": cached,
        "duration_ms": round(getattr(outcome, "duration_ms", 0.0), 2),
        "action_receipt": receipt_summary,
        "new_epoch_id": outcome.post_epoch,
        "status": outcome.outcome_status.value if hasattr(outcome.outcome_status, "value") else str(outcome.outcome_status),
    }
    if post_snapshot_str is not None:
        res["post_snapshot"] = post_snapshot_str
    if receipt.error:
        res["error"] = receipt.error

    return res


async def desktop_click_impl(
    bridge: RuntimeBridge,
    session_id: str,
    ref: str,
    click_count: int = 1,
    button: str = "left",
    include_snapshot: bool = True,
    timeout_ms: int = 5000,
    action_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Clicks an interactive element affordance identified by an ephemeral reference token.
    Enforces the composite actionability gate, motion settlement, and fused post-observation.
    """
    try:
        session = bridge.get_session(session_id)
        act_id = action_id or str(uuid.uuid4())

        request = ActionRequest(
            action_id=act_id,
            session_id=session_id,
            reference=ref,
            action_type=ActionType.DOUBLE_CLICK if click_count == 2 else (ActionType.RIGHT_CLICK if button == "right" else ActionType.CLICK),
            observation_epoch=session.current_epoch,
            params={"click_count": click_count, "button": button},
            timeout_ms=timeout_ms,
        )

        outcome, post_snap, cached = await bridge.execute_action_deduplicated(session, request, include_snapshot=include_snapshot)
        return _format_action_result(outcome, post_snap, cached=cached)
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()


async def desktop_type_impl(
    bridge: RuntimeBridge,
    session_id: str,
    ref: str,
    text: str,
    clear_existing: bool = True,
    press_enter: bool = False,
    include_snapshot: bool = True,
    timeout_ms: int = 5000,
    action_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Types text into an input affordance with authentic event bubbling across native and web planes.
    """
    try:
        session = bridge.get_session(session_id)
        act_id = action_id or str(uuid.uuid4())

        request = ActionRequest(
            action_id=act_id,
            session_id=session_id,
            reference=ref,
            action_type=ActionType.TYPE,
            observation_epoch=session.current_epoch,
            params={"text": text, "clear_existing": clear_existing, "press_enter": press_enter},
            timeout_ms=timeout_ms,
        )

        outcome, post_snap, cached = await bridge.execute_action_deduplicated(session, request, include_snapshot=include_snapshot)
        return _format_action_result(outcome, post_snap, cached=cached)
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()


async def desktop_press_key_impl(
    bridge: RuntimeBridge,
    session_id: str,
    key: str,
    ref: Optional[str] = None,
    include_snapshot: bool = True,
    timeout_ms: int = 5000,
    action_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Dispatches navigation or shortcut key combinations (e.g. 'Enter', 'Escape', 'Tab', 'Control+A').
    """
    try:
        session = bridge.get_session(session_id)
        act_id = action_id or str(uuid.uuid4())

        # If ref is not supplied, use active window root or focused control
        target_ref = ref or (session.reference_registry.get_active_refs()[0] if session.reference_registry.get_active_refs() else "w1e1")

        request = ActionRequest(
            action_id=act_id,
            session_id=session_id,
            reference=target_ref,
            action_type=ActionType.KEY_PRESS,
            observation_epoch=session.current_epoch,
            params={"key": key},
            timeout_ms=timeout_ms,
        )

        outcome, post_snap, cached = await bridge.execute_action_deduplicated(session, request, include_snapshot=include_snapshot)
        return _format_action_result(outcome, post_snap, cached=cached)
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()


async def desktop_hover_impl(
    bridge: RuntimeBridge,
    session_id: str,
    ref: str,
    include_snapshot: bool = True,
    timeout_ms: int = 5000,
    action_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Hovers the cursor over an element affordance to trigger tooltips or CSS hover states with motion settlement.
    """
    try:
        session = bridge.get_session(session_id)
        act_id = action_id or str(uuid.uuid4())

        request = ActionRequest(
            action_id=act_id,
            session_id=session_id,
            reference=ref,
            action_type=ActionType.HOVER,
            observation_epoch=session.current_epoch,
            params={},
            timeout_ms=timeout_ms,
        )

        outcome, post_snap, cached = await bridge.execute_action_deduplicated(session, request, include_snapshot=include_snapshot)
        return _format_action_result(outcome, post_snap, cached=cached)
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()


async def desktop_scroll_impl(
    bridge: RuntimeBridge,
    session_id: str,
    ref: Optional[str] = None,
    direction: str = "into_view",
    delta_y: int = 300,
    include_snapshot: bool = True,
    timeout_ms: int = 5000,
    action_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Scrolls a container or window element to bring targets into view.
    """
    try:
        session = bridge.get_session(session_id)
        act_id = action_id or str(uuid.uuid4())

        target_ref = ref or (session.reference_registry.get_active_refs()[0] if session.reference_registry.get_active_refs() else "w1e1")

        request = ActionRequest(
            action_id=act_id,
            session_id=session_id,
            reference=target_ref,
            action_type=ActionType.SCROLL,
            observation_epoch=session.current_epoch,
            params={"direction": direction, "delta_y": delta_y},
            timeout_ms=timeout_ms,
        )

        outcome, post_snap, cached = await bridge.execute_action_deduplicated(session, request, include_snapshot=include_snapshot)
        return _format_action_result(outcome, post_snap, cached=cached)
    except Exception as e:
        mcp_err = map_exception_to_mcp_error(e)
        mcp_err.raise_as_tool_error()
