"""
Model Context Protocol (MCP) Control Plane Package.
Universal agent-facing gateway into the Desktop WebView Reviewer runtime.
"""

from runtime.mcp.server import create_mcp_server, main
from runtime.mcp.errors import McpErrorCode, McpControlPlaneException, map_exception_to_mcp_error
from runtime.mcp.security import SecurityGate
from runtime.mcp.runtime_bridge import RuntimeBridge

__all__ = [
    "create_mcp_server",
    "main",
    "McpErrorCode",
    "McpControlPlaneException",
    "map_exception_to_mcp_error",
    "SecurityGate",
    "RuntimeBridge",
]
