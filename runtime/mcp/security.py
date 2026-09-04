"""
Security and policy gate for Desktop WebView Reviewer MCP Control Plane.
Enforces binary allowlists/blocklists, directory traversal prevention,
JS evaluation limits, and untrusted UI data enveloping (Docs 14 & 19).
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from runtime.mcp.errors import McpErrorCode, McpControlPlaneException

SAFE_IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
VALID_REF_REGEX = re.compile(r"^[wn]\d+e\d+$")
WINDOWS_DEVICE_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

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
MAX_SERIALIZED_RESULT_SIZE = 500_000  # 500 KB
MAX_TEXT_INPUT_LENGTH = 100_000      # 100 KB
MAX_REF_LENGTH = 64
MAX_SESSION_ID_LENGTH = 128


class SecurityGate:
    """Central policy validation gate for MCP commands and parameters."""

    @classmethod
    def validate_session_id(cls, session_id: str) -> str:
        """
        Validates session identifier format and bounds.
        Rejects empty strings, oversized IDs, and traversal/metacharacters.
        """
        if not session_id or not isinstance(session_id, str):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_SESSION,
                message="Session ID must be a non-empty string.",
                agent_action_hint="Provide a valid session identifier returned from desktop_launch or desktop_attach.",
            )

        clean_id = session_id.strip()
        if len(clean_id) > MAX_SESSION_ID_LENGTH:
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_SESSION,
                message=f"Session ID exceeds maximum length of {MAX_SESSION_ID_LENGTH} characters.",
            )

        if not SAFE_IDENTIFIER_REGEX.match(clean_id):
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"Session ID contains invalid or unsafe characters: '{clean_id}'.",
                agent_action_hint="Session IDs must contain only alphanumeric characters, dashes, underscores, or dots.",
            )

        return clean_id

    @classmethod
    def validate_ref(cls, ref: str) -> str:
        """
        Validates an interaction reference token (e.g. 'w1e4' or 'n1e2').
        Enforces strict syntax, bounds, and character set.
        """
        if not ref or not isinstance(ref, str):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message="Reference token must be a non-empty string.",
                agent_action_hint="Inspect the UI using desktop_inspect to obtain valid [ref=...] tokens.",
            )

        clean_ref = ref.strip()
        if len(clean_ref) > MAX_REF_LENGTH:
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message=f"Reference token exceeds maximum length of {MAX_REF_LENGTH} characters.",
            )

        if not VALID_REF_REGEX.match(clean_ref):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message=f"Malformed reference token: '{clean_ref}'. Expected format 'w<epoch>e<id>' or 'n<epoch>e<id>'.",
                agent_action_hint="Do not construct manual refs; obtain them directly from desktop_inspect.",
                details={"ref": clean_ref},
            )

        return clean_ref

    @classmethod
    def validate_pid(cls, pid: Optional[int]) -> Optional[int]:
        """Validates that a process ID is a positive integer within valid OS bounds."""
        if pid is None:
            return None
        if not isinstance(pid, int) or pid <= 0 or pid > 4_194_304:
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message=f"Invalid process ID: {pid}. Must be a positive integer in range 1..4194304.",
            )
        return pid

    @classmethod
    def validate_hwnd(cls, hwnd: Optional[int]) -> Optional[int]:
        """Validates that a window handle (HWND) is a valid positive integer."""
        if hwnd is None:
            return None
        if not isinstance(hwnd, int) or hwnd <= 0:
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message=f"Invalid window handle (HWND): {hwnd}. Must be a positive integer.",
            )
        return hwnd

    @classmethod
    def validate_cdp_port(cls, port: Optional[int]) -> Optional[int]:
        """Validates that a CDP debugging port is within the non-privileged TCP range."""
        if port is None:
            return None
        if not isinstance(port, int) or port < 1024 or port > 65535:
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message=f"Invalid CDP debugging port: {port}. Must be an integer between 1024 and 65535.",
            )
        return port

    @classmethod
    def validate_text_input(cls, text: str) -> str:
        """Validates and bounds text to be typed into an affordance."""
        if not isinstance(text, str):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message="Text parameter must be a string.",
            )
        if len(text) > MAX_TEXT_INPUT_LENGTH:
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message=f"Input text exceeds maximum allowed length ({len(text)} > {MAX_TEXT_INPUT_LENGTH} chars).",
            )
        return text

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

        # Reject Windows device / UNC paths
        raw_lower = executable_path.strip().lower()
        if raw_lower.startswith(("\\\\.\\", "\\\\?\\", "//./", "//?/")):
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"Device namespace paths are prohibited: '{executable_path}'.",
            )
        if raw_lower.startswith(("\\\\", "//")):
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"UNC network paths are prohibited for executable launch: '{executable_path}'.",
            )

        clean_path = Path(executable_path).resolve()
        bin_name = clean_path.name.lower()
        base_stem = clean_path.stem.lower()

        if base_stem in WINDOWS_DEVICE_NAMES:
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"Windows reserved device name prohibited: '{clean_path.name}'.",
            )

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
        Prevents directory traversal escapes, device paths, and UNC exploits.
        """
        if not file_path or not isinstance(file_path, str):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_ARGUMENT,
                message="File path must be a non-empty string.",
            )

        raw_trimmed = file_path.strip()
        raw_lower = raw_trimmed.lower()

        # Reject Windows device namespaces
        if raw_lower.startswith(("\\\\.\\", "\\\\?\\", "//./", "//?/")):
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"Device namespace paths are prohibited: '{file_path}'.",
            )

        # Reject UNC paths
        if raw_lower.startswith(("\\\\", "//")):
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"UNC network paths are prohibited: '{file_path}'.",
            )

        # Check for reserved DOS device names in segments
        segments = raw_lower.replace("\\", "/").split("/")
        for seg in segments:
            stem = seg.split(".")[0]
            if stem in WINDOWS_DEVICE_NAMES:
                raise McpControlPlaneException(
                    code=McpErrorCode.SECURITY_BLOCKED,
                    message=f"Windows reserved device name prohibited in path: '{seg}'.",
                )

        if ".." in file_path:
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
