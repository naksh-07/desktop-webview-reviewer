"""
MCP Resources for Desktop WebView Reviewer MCP Control Plane.
Exposes passive, read-only system inventory, session states, observations,
evidence manifests, and full-resolution screenshot binaries (Docs 14 §4 & 18).
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer

from runtime.mcp.runtime_bridge import RuntimeBridge
from runtime.mcp.security import SecurityGate
from runtime.mcp.errors import McpControlPlaneException, McpErrorCode, map_exception_to_mcp_error
from runtime.native_supervisor import NativeSupervisor
from runtime.evidence_store import EvidenceStore

logger = logging.getLogger("desktop_webview.mcp.resources")

# Standard 1x1 transparent PNG fallback
FALLBACK_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"


def register_all_resources(server: MCPServer, bridge: RuntimeBridge) -> None:
    """Registers all architecture-mandated resource endpoints on the server."""

    # 1. desktop://sessions
    @server.resource(
        "desktop://sessions",
        name="sessions_inventory",
        description="JSON array of active and known desktop automation sessions.",
        mime_type="application/json",
    )
    async def get_sessions_inventory() -> str:
        sessions = await bridge.daemon.session_manager.list_all_sessions()
        inv = [s.to_dict() for s in sessions]
        return json.dumps(inv, indent=2)

    # 2. desktop://sessions/{session_id}
    @server.resource(
        "desktop://sessions/{session_id}",
        name="session_state",
        description="Detailed session state, target identities, and capability matrix.",
        mime_type="application/json",
    )
    async def get_session_state(session_id: str) -> str:
        # Validate ID to prevent traversal
        SecurityGate.validate_resource_uri(f"desktop://sessions/{session_id}")
        session = bridge.get_session(session_id)
        return json.dumps(session.to_dict(), indent=2)

    # 3. desktop://sessions/{session_id}/observation
    @server.resource(
        "desktop://sessions/{session_id}/observation",
        name="session_observation",
        description="Latest compact accessibility observation tree for a session.",
        mime_type="text/plain",
    )
    async def get_session_observation(session_id: str) -> str:
        SecurityGate.validate_resource_uri(f"desktop://sessions/{session_id}/observation")
        session = bridge.get_session(session_id)
        if session.observation_engine and session.observation_engine.last_snapshot:
            return session.observation_engine.last_snapshot.text_representation
        snap = await session.observation_engine.observe(
            hwnd=session.target_window.hwnd if session.target_window else None,
        )
        return snap.text_representation

    # 4. desktop://windows
    @server.resource(
        "desktop://windows",
        name="windows_inventory",
        description="JSON inventory of all visible and top-level desktop windows.",
        mime_type="application/json",
    )
    async def get_windows_inventory() -> str:
        supervisor = NativeSupervisor()
        hwnds = supervisor.list_top_level_windows(visible_only=True)
        windows: List[Dict[str, Any]] = []
        for h in hwnds:
            try:
                insp = supervisor.inspect_window(h)
                windows.append({
                    "hwnd": h,
                    "hwnd_hex": hex(h),
                    "title": SecurityGate.envelope_untrusted_text(insp.title)["value"],
                    "pid": insp.pid,
                    "bounds": [insp.bounds.x, insp.bounds.y, insp.bounds.width, insp.bounds.height],
                    "is_cloaked": insp.is_cloaked,
                })
            except Exception:
                continue
        return json.dumps(windows, indent=2)

    # 5. desktop://evidence/{evidence_id}
    @server.resource(
        "desktop://evidence/{evidence_id}",
        name="evidence_manifest",
        description="Complete JSON audit bundle manifest (evidence.json) for a test or verification run.",
        mime_type="application/json",
    )
    async def get_evidence_manifest(evidence_id: str) -> str:
        SecurityGate.validate_resource_uri(f"desktop://evidence/{evidence_id}")
        store = EvidenceStore()
        # Scan session directories for evidence manifest
        for sess_dir in store.base_dir.glob("session-*"):
            manifest_file = sess_dir / f"action-{evidence_id}" / "manifest.json"
            if manifest_file.exists():
                return manifest_file.read_text(encoding="utf-8")

        # Fallback direct manifest lookup
        for manifest_path in store.base_dir.rglob("manifest.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if data.get("evidence_id") == evidence_id or data.get("manifest_id") == evidence_id or evidence_id in str(manifest_path):
                    return json.dumps(data, indent=2)
            except Exception:
                pass

        raise McpControlPlaneException(
            code=McpErrorCode.TARGET_NOT_FOUND,
            message=f"Evidence manifest '{evidence_id}' not found in evidence store.",
        )

    # 6. desktop://evidence/{evidence_id}/screenshot/{type}
    @server.resource(
        "desktop://evidence/{evidence_id}/screenshot/{type}",
        name="evidence_screenshot",
        description="Full-resolution binary PNG screenshot (type: 'native' or 'webview').",
        mime_type="image/png",
    )
    async def get_evidence_screenshot(evidence_id: str, type: str) -> bytes:
        SecurityGate.validate_resource_uri(f"desktop://evidence/{evidence_id}/screenshot/{type}")
        store = EvidenceStore()

        # Find matching screenshot file
        pattern = f"*{type}*.png"
        for shot_file in store.base_dir.rglob(pattern):
            if evidence_id in str(shot_file):
                return shot_file.read_bytes()

        # Check in artifacts/screenshots/
        for sess_dir in store.base_dir.glob("session-*"):
            act_dir = sess_dir / f"action-{evidence_id}"
            if act_dir.exists():
                for shot_file in act_dir.rglob("*.png"):
                    if type.lower() in shot_file.name.lower():
                        return shot_file.read_bytes()

        return FALLBACK_PNG_BYTES

    # 7. desktop://evidence/{evidence_id}/artifact/{artifact_id}
    @server.resource(
        "desktop://evidence/{evidence_id}/artifact/{artifact_id}",
        name="evidence_artifact",
        description="Raw byte content of a content-addressed forensic evidence artifact.",
        mime_type="application/octet-stream",
    )
    async def get_evidence_artifact(evidence_id: str, artifact_id: str) -> bytes:
        SecurityGate.validate_resource_uri(f"desktop://evidence/{evidence_id}/artifact/{artifact_id}")
        store = EvidenceStore()
        for art_file in store.base_dir.rglob(f"*{artifact_id}*"):
            if art_file.is_file():
                return art_file.read_bytes()

        raise McpControlPlaneException(
            code=McpErrorCode.TARGET_NOT_FOUND,
            message=f"Evidence artifact '{artifact_id}' not found.",
        )
