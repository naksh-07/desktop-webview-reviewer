"""
Antigravity Lifecycle Hook Adapter.

Consumes structured Antigravity lifecycle hook payloads (PreToolUse, PostToolUse,
PreInvocation, PostInvocation, Stop) following the official Antigravity hooks specification.
Translates them into normalized AgentEventEnvelope records.
Provides both programmatic Python ingestion and CLI stdin/stdout execution.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TextIO

from runtime.experience.antigravity.contracts import (
    AgentEventEnvelope,
    AgentEventType,
    UserCorrectionType,
)
from runtime.experience.antigravity.sanitizer import AgentEventSanitizer

logger = logging.getLogger("desktop_webview.experience.antigravity.hook_adapter")


class AntigravityHookAdapter:
    """
    Adapter consuming structured Antigravity hook events and translating them into
    privacy-safe AgentEventEnvelopes.
    """

    def __init__(self, sanitizer: Optional[AgentEventSanitizer] = None):
        self.sanitizer = sanitizer or AgentEventSanitizer(fail_safe=True)

    def parse_pre_tool_use(self, payload: Dict[str, Any]) -> AgentEventEnvelope:
        """
        Translates a PreToolUse hook payload into AGENT_TOOL_STARTED.
        """
        conv_id = payload.get("conversationId") or payload.get("conversation_id")
        step_idx = payload.get("stepIdx") or payload.get("step_idx")
        turn_id = f"turn_{step_idx}" if step_idx is not None else None

        tool_call = payload.get("toolCall") or payload.get("tool_call") or {}
        tool_name = tool_call.get("name") or payload.get("tool_name") or "unknown"
        raw_args = tool_call.get("args") or tool_call.get("arguments") or {}

        # Sanitize arguments defensively
        safe_summary = self.sanitizer.sanitize_tool_args(tool_name, raw_args)

        # Infer category
        category = "mcp" if tool_name.startswith("desktop_") else "system"

        workspace_paths = payload.get("workspacePaths") or payload.get("workspace_paths") or []
        project_id = os.path.basename(workspace_paths[0]) if workspace_paths else None

        return AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_STARTED,
            event_id=f"aevt_{uuid.uuid4().hex[:16]}",
            conversation_id=conv_id,
            turn_id=turn_id,
            agent_id=payload.get("agentId") or payload.get("agent_id"),
            tool_name=tool_name,
            tool_category=category,
            project_id=project_id,
            workspace_id=workspace_paths[0] if workspace_paths else None,
            safe_summary=safe_summary,
            timestamp=time.time(),
        )

    def parse_post_tool_use(self, payload: Dict[str, Any]) -> AgentEventEnvelope:
        """
        Translates a PostToolUse hook payload into AGENT_TOOL_COMPLETED or AGENT_TOOL_FAILED.
        """
        conv_id = payload.get("conversationId") or payload.get("conversation_id")
        step_idx = payload.get("stepIdx") or payload.get("step_idx")
        turn_id = f"turn_{step_idx}" if step_idx is not None else None

        tool_call = payload.get("toolCall") or payload.get("tool_call") or {}
        tool_name = tool_call.get("name") or payload.get("tool_name") or "unknown"
        raw_args = tool_call.get("args") or tool_call.get("arguments") or {}

        err = payload.get("error")
        success = not bool(err)
        event_type = AgentEventType.AGENT_TOOL_COMPLETED if success else AgentEventType.AGENT_TOOL_FAILED

        safe_summary = self.sanitizer.sanitize_tool_args(tool_name, raw_args)
        if err:
            safe_summary["error_indicator"] = True
            safe_summary["error_class"] = self.sanitizer.sanitize_string(str(err)[:64])

        workspace_paths = payload.get("workspacePaths") or payload.get("workspace_paths") or []
        project_id = os.path.basename(workspace_paths[0]) if workspace_paths else None

        return AgentEventEnvelope(
            event_type=event_type,
            event_id=f"aevt_{uuid.uuid4().hex[:16]}",
            conversation_id=conv_id,
            turn_id=turn_id,
            agent_id=payload.get("agentId") or payload.get("agent_id"),
            tool_name=tool_name,
            tool_category="mcp" if tool_name.startswith("desktop_") else "system",
            success=success,
            error_class=str(err)[:64] if err else None,
            duration_ms=float(payload.get("durationMs", payload.get("duration_ms", 0.0))),
            project_id=project_id,
            workspace_id=workspace_paths[0] if workspace_paths else None,
            safe_summary=safe_summary,
            timestamp=time.time(),
        )

    def parse_pre_invocation(self, payload: Dict[str, Any]) -> AgentEventEnvelope:
        """Translates PreInvocation payload into AGENT_TURN_STARTED."""
        conv_id = payload.get("conversationId") or payload.get("conversation_id")
        inv_num = payload.get("invocationNum") or payload.get("invocation_num") or 0
        return AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TURN_STARTED,
            event_id=f"aevt_{uuid.uuid4().hex[:16]}",
            conversation_id=conv_id,
            turn_id=f"inv_{inv_num}",
            agent_id=payload.get("agentId") or payload.get("agent_id"),
            timestamp=time.time(),
            safe_summary={"invocation_num": inv_num},
        )

    def parse_post_invocation(self, payload: Dict[str, Any]) -> AgentEventEnvelope:
        """Translates PostInvocation payload into AGENT_TURN_COMPLETED."""
        conv_id = payload.get("conversationId") or payload.get("conversation_id")
        inv_num = payload.get("invocationNum") or payload.get("invocation_num") or 0
        return AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TURN_COMPLETED,
            event_id=f"aevt_{uuid.uuid4().hex[:16]}",
            conversation_id=conv_id,
            turn_id=f"inv_{inv_num}",
            agent_id=payload.get("agentId") or payload.get("agent_id"),
            timestamp=time.time(),
            safe_summary={"invocation_num": inv_num},
        )

    def parse_stop(self, payload: Dict[str, Any]) -> AgentEventEnvelope:
        """Translates Stop hook payload into AGENT_SESSION_COMPLETED."""
        conv_id = payload.get("conversationId") or payload.get("conversation_id")
        reason = payload.get("terminationReason") or payload.get("termination_reason") or "normal_stop"
        err = payload.get("error")
        return AgentEventEnvelope(
            event_type=AgentEventType.AGENT_SESSION_COMPLETED,
            event_id=f"aevt_{uuid.uuid4().hex[:16]}",
            conversation_id=conv_id,
            agent_id=payload.get("agentId") or payload.get("agent_id"),
            success=not bool(err),
            error_class=str(err)[:64] if err else None,
            timestamp=time.time(),
            safe_summary={"termination_reason": str(reason)[:32]},
        )

    def parse_correction(self, payload: Dict[str, Any]) -> AgentEventEnvelope:
        """Translates a user or agent correction into AGENT_USER_CORRECTION."""
        conv_id = payload.get("conversationId") or payload.get("conversation_id")
        ctype = payload.get("correctionType", UserCorrectionType.USER_CORRECTED_AGENT.value)
        return AgentEventEnvelope(
            event_type=AgentEventType.AGENT_USER_CORRECTION,
            event_id=f"aevt_{uuid.uuid4().hex[:16]}",
            conversation_id=conv_id,
            turn_id=payload.get("turnId") or payload.get("turn_id"),
            correlation_id=payload.get("relatedDwrSessionId") or payload.get("related_dwr_session_id"),
            safe_summary={
                "correction_type": str(ctype)[:32],
                "target_changed": bool(payload.get("targetChanged", False)),
            },
            timestamp=time.time(),
        )

    def translate_hook(self, hook_event_name: str, payload: Dict[str, Any]) -> Optional[AgentEventEnvelope]:
        """Dispatches an arbitrary hook event name to the appropriate parsing method."""
        normalized_name = hook_event_name.lower().replace("_", "").replace("-", "")
        if normalized_name in ("pretooluse", "pretool"):
            return self.parse_pre_tool_use(payload)
        elif normalized_name in ("posttooluse", "posttool"):
            return self.parse_post_tool_use(payload)
        elif normalized_name in ("preinvocation", "preinv"):
            return self.parse_pre_invocation(payload)
        elif normalized_name in ("postinvocation", "postinv"):
            return self.parse_post_invocation(payload)
        elif normalized_name in ("stop", "sessionstop"):
            return self.parse_stop(payload)
        elif normalized_name in ("correction", "usercorrection"):
            return self.parse_correction(payload)
        else:
            # Fallback envelope
            return AgentEventEnvelope(
                event_type=AgentEventType.AGENT_TOOL_COMPLETED,
                conversation_id=payload.get("conversationId") or payload.get("conversation_id"),
                timestamp=time.time(),
                safe_summary={"raw_hook": hook_event_name[:32]},
            )

    def execute_cli_hook(
        self,
        hook_name: str,
        in_stream: TextIO = sys.stdin,
        out_stream: TextIO = sys.stdout,
        bridge: Optional[Any] = None,
    ) -> int:
        """
        Executes a CLI hook run via Antigravity hooks.json.
        Reads JSON from stdin, translates, sanitizes, forwards to bridge, and emits stdout JSON.
        Guarantees exit code 0 and default allow decision so the agent loop is never stalled.
        """
        try:
            raw_input = in_stream.read()
            payload = json.loads(raw_input) if raw_input.strip() else {}
        except Exception as e:
            logger.warning("Could not read hook stdin: %s", e)
            payload = {}

        try:
            envelope = self.translate_hook(hook_name, payload)
            if envelope and bridge:
                bridge.ingest_event(envelope)
        except Exception as e:
            logger.warning("Hook execution error in bridge: %s", e)

        # Provide standard compliant Antigravity hook responses
        norm_hook = hook_name.lower()
        if "pretool" in norm_hook:
            resp = {"decision": "allow"}
        elif "posttool" in norm_hook:
            resp = {}
        elif "preinv" in norm_hook or "postinv" in norm_hook:
            resp = {"injectSteps": []}
        elif "stop" in norm_hook:
            resp = {"decision": "allow"}
        else:
            resp = {}

        out_stream.write(json.dumps(resp))
        out_stream.flush()
        return 0
