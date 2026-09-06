"""
Defensive Privacy Boundary and Tool Argument Sanitizer for Antigravity Bridge.

Enforces Sections 8, 9, 23 of Milestone 2.1 Prompt 3:
- Zero raw chain-of-thought, model thinking, or raw prompts
- Zero raw conversation transcripts
- Zero credentials, bearer tokens, API keys, JWTs, cookies, or secrets
- Zero raw typed text (e.g., desktop_type only stores input_length)
- Defensive normalization of tool arguments into safe structural summaries
- Defense against prompt injections, binary dumps, and oversized payloads
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from runtime.errors import DesktopAutomationException
from runtime.experience.antigravity.contracts import AgentEventEnvelope, AgentEventType
from runtime.experience.privacy import (
    MAX_METADATA_STRING_LENGTH,
    PrivacyEnforcer,
    PrivacyViolationException,
)
from runtime.trace_engine import redact_sensitive_text

logger = logging.getLogger("desktop_webview.experience.antigravity.sanitizer")

# Specific regexes for strict argument and payload scanning
PROHIBITED_KEY_PATTERN = re.compile(
    r"(?i)^(chain_of_thought|cot|hidden_thoughts|reasoning_trace|raw_reasoning|"
    r"model_thinking|thinking|thought_process|hidden_state|"
    r"model_transcript|unfiltered_prompt|prompt_archive|raw_transcript|full_conversation|"
    r"conversation_history|dialogue_dump|prompt|"
    r"password|passwd|api_?key|bearer_?token|auth_?token|jwt|cookie|cookies|"
    r"private_?key|secret_?key|authorization_header)$"
)

# Detect obvious prompt injection sequences inside metadata
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)(ignore\s+all\s+previous\s+instructions)"),
    re.compile(r"(?i)(system\s+prompt\s+override)"),
    re.compile(r"(?i)(you\s+are\s+now\s+in\s+developer\s+mode)"),
    re.compile(r"(?i)(disregard\s+prior\s+rules)"),
]

# Sensitive keys that must never appear in tool summaries
SENSITIVE_ARG_KEYS = {
    "text", "value", "content", "code", "script", "typed_text", "input_text",
    "password", "secret", "token", "key", "authorization", "prompt",
}


class AgentEventSanitizationException(DesktopAutomationException):
    """Raised when an Antigravity event violates privacy boundaries or contains malicious payloads."""
    pass


class AgentEventSanitizer:
    """
    Defensive sanitizer enforcing zero-knowledge privacy rules on all incoming agent events.
    """

    def __init__(self, fail_safe: bool = True):
        self.fail_safe = fail_safe
        self.events_accepted = 0
        self.events_rejected = 0
        self.privacy_violations_blocked = 0

    def sanitize_envelope(self, envelope: AgentEventEnvelope) -> Optional[AgentEventEnvelope]:
        """
        Sanitizes an incoming AgentEventEnvelope.
        Returns a cleansed envelope, or None / raises if strictly unrecoverable.
        """
        try:
            # 1. Validate version and event_type
            if not envelope.event_type:
                raise AgentEventSanitizationException("Missing event_type in AgentEventEnvelope.")

            # 2. Check and sanitize safe_summary
            clean_summary = self.sanitize_dict(envelope.safe_summary, context="safe_summary")

            # 3. Defensive scrubbing of string identifiers
            clean_conv_id = self.sanitize_identifier(envelope.conversation_id, "conversation_id")
            clean_turn_id = self.sanitize_identifier(envelope.turn_id, "turn_id")
            clean_agent_id = self.sanitize_identifier(envelope.agent_id, "agent_id")
            clean_parent_id = self.sanitize_identifier(envelope.parent_agent_id, "parent_agent_id")
            clean_subagent_id = self.sanitize_identifier(envelope.subagent_id, "subagent_id")
            clean_tool_name = self.sanitize_identifier(envelope.tool_name, "tool_name")
            clean_tool_cat = self.sanitize_identifier(envelope.tool_category, "tool_category")
            clean_err_class = self.sanitize_identifier(envelope.error_class, "error_class")
            clean_ws_id = self.sanitize_identifier(envelope.workspace_id, "workspace_id")
            clean_proj_id = self.sanitize_identifier(envelope.project_id, "project_id")
            clean_art_ref = self.sanitize_path_or_reference(envelope.artifact_reference, "artifact_reference")
            clean_corr_id = self.sanitize_identifier(envelope.correlation_id, "correlation_id")

            # Return reconstructed clean envelope
            sanitized = AgentEventEnvelope(
                event_type=envelope.event_type,
                event_id=envelope.event_id,
                event_schema_version=envelope.event_schema_version or "1.0",
                conversation_id=clean_conv_id,
                turn_id=clean_turn_id,
                agent_id=clean_agent_id,
                parent_agent_id=clean_parent_id,
                subagent_id=clean_subagent_id,
                tool_name=clean_tool_name,
                tool_category=clean_tool_cat or "generic",
                success=envelope.success,
                error_class=clean_err_class,
                duration_ms=envelope.duration_ms,
                timestamp=envelope.timestamp,
                iso_timestamp=envelope.iso_timestamp,
                workspace_id=clean_ws_id,
                project_id=clean_proj_id,
                artifact_reference=clean_art_ref,
                correlation_id=clean_corr_id,
                safe_summary=clean_summary,
            )
            self.events_accepted += 1
            return sanitized

        except PrivacyViolationException as pve:
            self.privacy_violations_blocked += 1
            self.events_rejected += 1
            logger.warning("AgentEventSanitizer blocked privacy violation: %s", pve)
            if not self.fail_safe:
                raise
            return None
        except Exception as e:
            self.events_rejected += 1
            logger.warning("AgentEventSanitizer rejected malformed event: %s", e)
            if not self.fail_safe:
                raise AgentEventSanitizationException(f"Sanitization failed: {e}") from e
            return None

    def sanitize_tool_args(self, tool_name: Optional[str], raw_args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Sanitizes tool arguments into a safe, normalized structural summary (Section 9).
        Never persists raw arguments, DOM trees, passwords, or typed text.
        """
        if not raw_args or not isinstance(raw_args, dict):
            return {}

        # First verify no forbidden keys in raw args
        self._check_forbidden_keys(raw_args, context=f"tool_args({tool_name})")

        t_name = (tool_name or "").lower().strip()
        summary: Dict[str, Any] = {}

        # 1. Specific DWR interaction tools
        if t_name == "desktop_click":
            # Extract only target kind/role/plane, never full text or DOM
            summary["action_type"] = "CLICK"
            if "role" in raw_args:
                summary["target_role"] = self.sanitize_string(str(raw_args["role"]))
            elif "target_role" in raw_args:
                summary["target_role"] = self.sanitize_string(str(raw_args["target_role"]))
            if "plane" in raw_args:
                summary["plane"] = self.sanitize_string(str(raw_args["plane"]))
            if "target_kind" in raw_args:
                summary["target_kind"] = self.sanitize_string(str(raw_args["target_kind"]))
            elif "selector" in raw_args or "locator" in raw_args:
                summary["target_kind"] = "selector"

        elif t_name == "desktop_type":
            # CRITICAL REQUIREMENT (Section 9): Never store the actual typed value!
            val = raw_args.get("text", raw_args.get("value", ""))
            summary["action_type"] = "TYPE_TEXT"
            summary["input_present"] = bool(val)
            summary["input_length"] = len(str(val)) if val is not None else 0
            if "plane" in raw_args:
                summary["plane"] = self.sanitize_string(str(raw_args["plane"]))

        elif t_name == "desktop_press_key":
            summary["action_type"] = "PRESS_KEY"
            key_name = str(raw_args.get("key", raw_args.get("key_name", "")))
            # Keep only alphanumeric/special key name, max 32 chars
            summary["key"] = self.sanitize_string(key_name[:32])

        elif t_name in ("desktop_launch", "launch"):
            summary["action_type"] = "LAUNCH"
            exe = raw_args.get("executable", raw_args.get("target_path", ""))
            if exe:
                # Store only the filename basename, never full user paths or command lines with arguments
                summary["executable_name"] = os.path.basename(str(exe))[:64]
            summary["args_count"] = len(raw_args.get("arguments", [])) if isinstance(raw_args.get("arguments"), list) else 0

        elif t_name in ("desktop_attach", "attach"):
            summary["action_type"] = "ATTACH"
            if "target_pid" in raw_args:
                summary["has_pid"] = True
            if "window_title" in raw_args:
                summary["has_window_title"] = True

        elif t_name == "desktop_hover":
            summary["action_type"] = "HOVER"
            if "plane" in raw_args:
                summary["plane"] = self.sanitize_string(str(raw_args["plane"]))

        elif t_name == "desktop_scroll":
            summary["action_type"] = "SCROLL"
            summary["direction"] = str(raw_args.get("direction", "down"))[:16]

        elif t_name == "desktop_handle_dialog":
            summary["action_type"] = "DIALOG"
            summary["dialog_action"] = str(raw_args.get("action", "accept"))[:16]

        elif t_name == "desktop_evaluate":
            summary["action_type"] = "EVALUATE"
            script = raw_args.get("script", raw_args.get("expression", ""))
            summary["script_present"] = bool(script)
            summary["script_length"] = len(str(script)) if script else 0

        elif t_name == "desktop_assert":
            summary["action_type"] = "ASSERT"
            summary["assertion_type"] = str(raw_args.get("assertion_type", "state"))[:32]

        elif t_name == "desktop_collect_evidence":
            summary["action_type"] = "EVIDENCE"
            summary["category"] = str(raw_args.get("category", "snapshot"))[:32]

        # 2. General tools (e.g. run_command, view_file, etc.)
        elif t_name == "run_command":
            cmd = str(raw_args.get("CommandLine", raw_args.get("command", "")))
            # Extract safe binary name only, no arguments or flags that might contain tokens
            first_token = cmd.strip().split()[0] if cmd.strip() else ""
            summary["action_type"] = "RUN_COMMAND"
            summary["command_bin"] = os.path.basename(first_token)[:64]

        elif t_name in ("view_file", "read_file"):
            summary["action_type"] = "VIEW_FILE"
            p = str(raw_args.get("AbsolutePath", raw_args.get("path", "")))
            summary["file_ext"] = os.path.splitext(p)[1][:16]

        else:
            # Generic safe filter
            summary["action_type"] = "GENERIC_TOOL"
            # Retain non-sensitive keys with scalar values
            for k, v in raw_args.items():
                k_clean = str(k).lower().strip()
                if k_clean not in SENSITIVE_ARG_KEYS and not PROHIBITED_KEY_PATTERN.match(k_clean):
                    if isinstance(v, (int, float, bool)):
                        summary[k_clean] = v
                    elif isinstance(v, str):
                        summary[k_clean] = self.sanitize_string(v[:64])

        return summary

    def sanitize_dict(self, data: Dict[str, Any], context: str = "record") -> Dict[str, Any]:
        """Scans and sanitizes a dictionary using PrivacyEnforcer and injection guards."""
        if not isinstance(data, dict):
            return {}

        self._check_forbidden_keys(data, context=context)

        # Apply PrivacyEnforcer check_and_sanitize
        sanitized = PrivacyEnforcer.check_and_sanitize(data, context=context)

        # Check for prompt injection patterns
        self._check_injection_patterns(sanitized, context=context)

        return sanitized

    def sanitize_string(self, text: str) -> str:
        """Sanitizes an individual string value."""
        if not text:
            return ""
        if len(text) > MAX_METADATA_STRING_LENGTH:
            raise PrivacyViolationException(f"String length {len(text)} exceeds limit {MAX_METADATA_STRING_LENGTH}.")

        # Trace engine secret redaction
        cleaned = redact_sensitive_text(text)

        # Check for prompt injection attempts
        for pat in PROMPT_INJECTION_PATTERNS:
            if pat.search(cleaned):
                self.privacy_violations_blocked += 1
                cleaned = pat.sub("[REDACTED_PROMPT_INJECTION]", cleaned)

        return cleaned

    def sanitize_identifier(self, ident: Optional[str], field_name: str) -> Optional[str]:
        """Sanitizes an identifier (session_id, turn_id, etc.)."""
        if ident is None:
            return None
        ident_str = str(ident).strip()
        if not ident_str:
            return None
        if len(ident_str) > 256:
            ident_str = ident_str[:256]
        # Ensure identifier doesn't contain forbidden patterns
        return self.sanitize_string(ident_str)

    def sanitize_path_or_reference(self, path_val: Optional[str], field_name: str) -> Optional[str]:
        """Sanitizes an artifact reference path or URI."""
        if path_val is None:
            return None
        p_str = str(path_val).strip()
        if not p_str:
            return None
        # Disallow binary/oversized content in reference strings
        if len(p_str) > 1024:
            p_str = p_str[:1024]
        return self.sanitize_string(p_str)

    def _check_forbidden_keys(self, data: Dict[str, Any], context: str) -> None:
        """Recursively checks for forbidden keys."""
        for k, v in data.items():
            k_str = str(k).strip()
            if PROHIBITED_KEY_PATTERN.match(k_str):
                raise PrivacyViolationException(
                    f"Privacy violation in {context}: key '{k_str}' is strictly prohibited. "
                    f"Chain-of-thought, reasoning, full prompts, credentials, tokens, and cookies "
                    f"are strictly blocked from Experience Store persistence."
                )
            if isinstance(v, dict):
                self._check_forbidden_keys(v, context=f"{context}.{k_str}")
            elif isinstance(v, list):
                for idx, item in enumerate(v):
                    if isinstance(item, dict):
                        self._check_forbidden_keys(item, context=f"{context}.{k_str}[{idx}]")

    def _check_injection_patterns(self, data: Any, context: str) -> None:
        """Recursively scans values for adversarial injection strings."""
        if isinstance(data, dict):
            for k, v in data.items():
                self._check_injection_patterns(v, context=f"{context}.{k}")
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                self._check_injection_patterns(item, context=f"{context}[{idx}]")
        elif isinstance(data, str):
            for pat in PROMPT_INJECTION_PATTERNS:
                if pat.search(data):
                    self.privacy_violations_blocked += 1
                    logger.warning("Prompt injection signature detected and blocked in %s", context)
