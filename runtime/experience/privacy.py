"""
Privacy Boundary and Secret Sanitization Subsystem for Experience Store.

Enforces Section 10 privacy guardrails:
Strictly prohibits persistence of:
- raw chain-of-thought
- hidden model reasoning
- unrestricted model transcripts
- passwords, API keys, bearer tokens
- authentication cookies, session cookies
- arbitrary secrets, private keys
- unrestricted application filesystem dumps

Reuses runtime.trace_engine.redact_sensitive_text for defense-in-depth sanitization.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set, Union

from runtime.errors import DesktopAutomationException
from runtime.trace_engine import redact_sensitive_text

logger = logging.getLogger("desktop_webview.experience.privacy")

# Maximum string length for an individual metadata attribute to prevent unrestricted file dumps
MAX_METADATA_STRING_LENGTH = 32768

PROHIBITED_KEY_PATTERN = re.compile(
    r"(?i)^(chain_of_thought|cot|hidden_thoughts|reasoning_trace|raw_reasoning|"
    r"model_transcript|unfiltered_prompt|prompt_archive|raw_transcript|"
    r"password|passwd|api_?key|bearer_?token|auth_?token|jwt|cookie|cookies|"
    r"private_?key|secret_?key)$"
)

SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)\b(bearer\s+)([a-zA-Z0-9\-\._~\+\/]+=*)"),
    re.compile(r"(?i)\b(api_?key[:=\s]+)\s*([^\s,;&]+)"),
    re.compile(r"(?i)\b(password[:=\s]+)\s*([^\s,;&]+)"),
    re.compile(r"(?i)\b(token[:=\s]+)\s*([^\s,;&]+)"),
    re.compile(r"\b(ey[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})\b"), # JWT
    re.compile(r"\b(ghp_[a-zA-Z0-9]{36}|gho_[a-zA-Z0-9]{36})\b"),                       # GitHub token
    re.compile(r"\b(xox[baprs]-[0-9a-zA-Z]{10,48})\b"),                                   # Slack token
]


class PrivacyViolationException(DesktopAutomationException):
    """Raised when data provided to ExperienceStore violates privacy boundaries."""
    pass


class PrivacyEnforcer:
    """
    Validates and sanitizes structured dictionaries before SQLite persistence.
    """

    @classmethod
    def check_and_sanitize(cls, data: Dict[str, Any], context: str = "record") -> Dict[str, Any]:
        """
        Scans data recursively:
        1. Raises PrivacyViolationException if prohibited keys exist.
        2. Redacts sensitive credential patterns from string values.
        3. Enforces payload length limits.
        """
        if not isinstance(data, dict):
            return {}

        sanitized: Dict[str, Any] = {}
        for key, value in data.items():
            key_str = str(key).strip()

            # 1. Prohibited key check
            if PROHIBITED_KEY_PATTERN.match(key_str):
                raise PrivacyViolationException(
                    f"Privacy violation in {context}: key '{key_str}' is strictly prohibited from "
                    f"Experience Store persistence. Prohibited types include model reasoning, "
                    f"transcripts, credentials, tokens, and cookies."
                )

            # 2. Recursive sanitization
            sanitized[key_str] = cls._sanitize_value(value, field_name=key_str, context=context)

        return sanitized

    @classmethod
    def _sanitize_value(cls, val: Any, field_name: str, context: str) -> Any:
        if isinstance(val, dict):
            return cls.check_and_sanitize(val, context=f"{context}.{field_name}")
        elif isinstance(val, list):
            return [cls._sanitize_value(item, field_name=f"{field_name}[]", context=context) for item in val]
        elif isinstance(val, str):
            # Enforce size limit
            if len(val) > MAX_METADATA_STRING_LENGTH:
                raise PrivacyViolationException(
                    f"Payload size violation in {context}.{field_name}: string of length {len(val)} "
                    f"exceeds maximum allowed size ({MAX_METADATA_STRING_LENGTH} bytes). "
                    f"Unrestricted filesystem or document dumps are strictly prohibited."
                )

            cleaned = val
            # 1. Apply specific token and credential regexes first
            for pat in SECRET_VALUE_PATTERNS:
                if pat.groups >= 2:
                    cleaned = pat.sub(r"\1[REDACTED_SECRET]", cleaned)
                else:
                    cleaned = pat.sub(r"[REDACTED_SECRET]", cleaned)

            # 2. Apply trace engine redact_sensitive_text
            cleaned = redact_sensitive_text(cleaned)

            return cleaned
        else:
            return val

