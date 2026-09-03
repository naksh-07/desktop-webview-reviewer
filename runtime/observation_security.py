"""
Observation Security & Untrusted UI Data Boundary (Section 30).
Guarantees that all observed strings (window titles, DOM text, accessible names,
attributes, and ARIA labels) are treated strictly as inert data and cannot alter
system-level instructions, poison prompt contexts, or execute as code.
"""

from __future__ import annotations
import html
import re
from typing import Dict, Any, Optional

from runtime.logging_events import UntrustedUIText


# Patterns commonly used in prompt-injection attacks embedded in web pages or window titles
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"(?:<|&lt;)\|im_start\|(?:>|&gt;)", re.IGNORECASE),
    re.compile(r"(?:<|&lt;)\|im_end\|(?:>|&gt;)", re.IGNORECASE),
    re.compile(r"\[instruction\]", re.IGNORECASE),
    re.compile(r"new\s+system\s+prompt", re.IGNORECASE),
]


def sanitize_observed_text(raw_text: Optional[str], source_plane: str = "unknown", max_len: int = 300) -> str:
    """
    Sanitizes raw observed text from native controls or web DOM nodes.
    Neutralizes ASCII control characters, prompt injection markers, and escaping traps.
    """
    if not raw_text:
        return ""

    untrusted = UntrustedUIText(raw_text=raw_text, source_plane=source_plane, max_len=max_len)
    sanitized = untrusted.sanitized

    # Neutralize common prompt injection prefixes without deleting data
    for pattern in PROMPT_INJECTION_PATTERNS:
        sanitized = pattern.sub("[UNTRUSTED_UI_DATA: \\g<0>]", sanitized)

    return sanitized


def create_safe_ui_envelope(text: str, source_plane: str) -> Dict[str, Any]:
    """Wraps text in a validated inert data envelope."""
    sanitized = sanitize_observed_text(text, source_plane)
    return {
        "type": "untrusted_ui_text",
        "source_plane": source_plane,
        "content": sanitized,
        "is_inert_data": True,
    }
