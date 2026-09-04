"""
Security and policy gate for Desktop WebView Reviewer MCP Control Plane.
Enforces binary allowlists/blocklists, directory traversal prevention,
JS evaluation limits, and untrusted UI data enveloping (Docs 14 & 19).
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

from runtime.mcp.errors import McpErrorCode, McpControlPlaneException

SAFE_IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")

PROHIBITED_EXECUTABLES = {
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "bash.exe",
    "sh.exe",
    "zsh.exe",
    "wscript.exe",
    "cscript.exe",
    "regedit.exe",
    "format.com",
}

MAX_JS_EXPRESSION_LENGTH = 10_000
MAX_SERIALIZED_RESULT_SIZE = 500_000 # 500 KB


class SecurityGate:
    """Central policy validation gate for MCP commands and parameters."""

    @classmethod
    def validate_executable_path(cls, executable_path: str, allow_shell_override: bool = False) -> Path:
        """
        Validates target binary path.
        Rejects prohibited shell / destructive binaries and non-existent paths.
        """
        if not executable_path or not isinstance(executable_path, str):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message="Executable path must be a non-empty string.",
                agent_action_hint="Provide a valid absolute or relative executable file path.",
            )

        clean_path = Path(executable_path).resolve()
        bin_name = clean_path.name.lower()

        if not allow_shell_override and bin_name in PROHIBITED_EXECUTABLES:
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"Executable '{bin_name}' is prohibited by security policy (arbitrary shell execution blocked).",
                agent_action_hint="Specify the application binary directly rather than invoking via system shell.",
                details={"prohibited_binary": bin_name, "path": str(clean_path)},
            )

        if not clean_path.exists():
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_TARGET,
                message=f"Executable path not found: {clean_path}",
                agent_action_hint="Verify the target binary exists on disk.",
                details={"path": str(clean_path)},
            )

        return clean_path

    @classmethod
    def validate_file_path(cls, file_path: str, must_exist: bool = False) -> Path:
        """
        Validates an arbitrary file path parameter (e.g. for dialog file pickers).
        Prevents directory traversal escapes.
        """
        if not file_path or not isinstance(file_path, str):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message="File path must be a non-empty string.",
            )

        if ".." in file_path:
            # Check for suspicious traversal sequences
            normalized = os.path.normpath(file_path)
            if normalized.startswith("..") or "/../" in file_path.replace("\\", "/"):
                raise McpControlPlaneException(
                    code=McpErrorCode.SECURITY_BLOCKED,
                    message=f"Directory traversal detected in file path '{file_path}'.",
                    agent_action_hint="Use explicit absolute or clean relative paths without '..'.",
                )

        resolved = Path(file_path).resolve()
        if must_exist and not resolved.exists():
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message=f"File path does not exist: {resolved}",
            )
        return resolved

    @classmethod
    def validate_js_expression(cls, expression: str) -> str:
        """
        Validates JavaScript expression to evaluate.
        Enforces maximum length to prevent resource exhaustion or buffer blowout.
        """
        if not expression or not isinstance(expression, str):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message="JavaScript expression must be a non-empty string.",
            )

        if len(expression) > MAX_JS_EXPRESSION_LENGTH:
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"JavaScript expression length ({len(expression)} chars) exceeds maximum allowed limit ({MAX_JS_EXPRESSION_LENGTH} chars).",
                agent_action_hint="Break complex evaluations into smaller discrete expressions or use utility world functions.",
                details={"length": len(expression), "max_allowed": MAX_JS_EXPRESSION_LENGTH},
            )

        return expression

    @classmethod
    def validate_resource_uri(cls, uri: str) -> Tuple[str, ...]:
        """
        Validates an MCP resource URI (e.g. 'desktop://evidence/{evidence_id}').
        Ensures URI scheme is 'desktop://' and path contains no traversal elements.
        Returns parsed path segments.
        """
        if not uri or not isinstance(uri, str):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message="Resource URI must be a non-empty string.",
            )

        if not uri.startswith("desktop://"):
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"Unsupported resource URI scheme '{uri}'. Only 'desktop://' is permitted.",
                agent_action_hint="Use URIs formatted as 'desktop://...'.",
            )

        path_part = uri[len("desktop://"):]
        if ".." in path_part or "\\" in path_part:
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"Directory traversal tokens rejected in resource URI: '{uri}'.",
                agent_action_hint="Resource URIs must not contain '..' or backslashes.",
            )

        segments = [s for s in path_part.split("/") if s]
        for seg in segments:
            if not SAFE_IDENTIFIER_REGEX.match(seg):
                raise McpControlPlaneException(
                    code=McpErrorCode.SECURITY_BLOCKED,
                    message=f"Invalid characters in resource URI segment: '{seg}'.",
                )

        return tuple(segments)

    @classmethod
    def envelope_untrusted_text(cls, text: Optional[str]) -> Dict[str, Any]:
        """
        Wraps observed application UI text in an explicit untrusted structured envelope
        so it is never confused with LLM instruction channels (Doc 19 §2).
        """
        raw = str(text or "")
        return {
            "value": raw,
            "untrusted_ui_data": True,
            "length": len(raw),
        }
