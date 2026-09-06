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
from core.version import get_version_info
from runtime.lifecycle import LifecycleUpdater

logger = logging.getLogger("desktop_webview.mcp.resources")

# Maximum resource payload size: 10 MB
MAX_RESOURCE_PAYLOAD_SIZE = 10 * 1024 * 1024


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
        clean_sid = SecurityGate.validate_session_id(session_id)
        SecurityGate.validate_resource_uri(f"desktop://sessions/{clean_sid}")
        session = bridge.get_session(clean_sid)
        return json.dumps(session.to_dict(), indent=2)

    # 3. desktop://sessions/{session_id}/observation
    @server.resource(
        "desktop://sessions/{session_id}/observation",
        name="session_observation",
        description="Latest compact accessibility observation tree for a session.",
        mime_type="text/plain",
    )
    async def get_session_observation(session_id: str) -> str:
        clean_sid = SecurityGate.validate_session_id(session_id)
        SecurityGate.validate_resource_uri(f"desktop://sessions/{clean_sid}/observation")
        session = bridge.get_session(clean_sid)
        if session.observation_engine and session.observation_engine.last_snapshot:
            return session.observation_engine.last_snapshot.text_representation
        assert session.observation_engine is not None, "Observation engine not initialized"
        snap = await session.observation_engine.observe(
            hwnd=session.target_window.hwnd if session.target_window else None,
        )
        return snap.text_representation

    # desktop://sessions/{session_id}/trace
    @server.resource(
        "desktop://sessions/{session_id}/trace",
        name="session_trace",
        description="Unified chronological trace timeline of events for a session.",
        mime_type="application/json",
    )
    async def get_session_trace(session_id: str) -> str:
        clean_sid = SecurityGate.validate_session_id(session_id)
        SecurityGate.validate_resource_uri(f"desktop://sessions/{clean_sid}/trace")
        session = bridge.get_session(clean_sid)
        if getattr(session, "trace_engine", None):
            assert session.trace_engine is not None
            return json.dumps(session.trace_engine.timeline.to_dict(), indent=2)
        return json.dumps({"total_events": 0, "events": []}, indent=2)

    # desktop://sessions/{session_id}/reality
    @server.resource(
        "desktop://sessions/{session_id}/reality",
        name="session_reality",
        description="Reconciled multi-plane Reality model targets under the Truth Hierarchy.",
        mime_type="application/json",
    )
    async def get_session_reality(session_id: str) -> str:
        clean_sid = SecurityGate.validate_session_id(session_id)
        SecurityGate.validate_resource_uri(f"desktop://sessions/{clean_sid}/reality")
        session = bridge.get_session(clean_sid)
        target_hwnd = session.target_window.hwnd if session.target_window else None
        assert session.observation_engine is not None, "Observation engine not initialized"
        snap = await session.observation_engine.observe_reality(hwnd=target_hwnd)
        return json.dumps(snap.to_dict(), indent=2)

    # desktop://displays
    @server.resource(
        "desktop://displays",
        name="displays_topology",
        description="JSON inventory of physical desktop displays, monitor bounds, and DPI scaling.",
        mime_type="application/json",
    )
    async def get_displays_topology() -> str:
        supervisor = NativeSupervisor()
        topology = supervisor.get_monitor_topology()
        return json.dumps([m.to_dict() for m in topology], indent=2)

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
        base_dir_resolved = store.base_dir.resolve()

        # Scan session directories for evidence manifest
        for sess_dir in store.base_dir.glob("session-*"):
            manifest_file = sess_dir / f"action-{evidence_id}" / "manifest.json"
            if manifest_file.exists() and manifest_file.resolve().is_relative_to(base_dir_resolved):
                return manifest_file.read_text(encoding="utf-8")

        # Fallback direct manifest lookup
        for manifest_path in store.base_dir.rglob("manifest.json"):
            try:
                if not manifest_path.resolve().is_relative_to(base_dir_resolved):
                    continue
                content = manifest_path.read_text(encoding="utf-8")
                data = json.loads(content)
                if data.get("evidence_id") == evidence_id or data.get("manifest_id") == evidence_id or evidence_id in str(manifest_path):
                    return content
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
        base_dir_resolved = store.base_dir.resolve()
        clean_type = type.lower()

        # Check action directories first
        for sess_dir in store.base_dir.glob("session-*"):
            act_dir = sess_dir / f"action-{evidence_id}"
            if act_dir.exists() and act_dir.resolve().is_relative_to(base_dir_resolved):
                for shot_file in act_dir.glob("*.png"):
                    if clean_type in shot_file.name.lower() and shot_file.resolve().is_relative_to(base_dir_resolved):
                        if shot_file.stat().st_size > MAX_RESOURCE_PAYLOAD_SIZE:
                            raise McpControlPlaneException(
                                code=McpErrorCode.SECURITY_BLOCKED,
                                message=f"Screenshot file exceeds maximum size limit ({MAX_RESOURCE_PAYLOAD_SIZE} bytes).",
                            )
                        return shot_file.read_bytes()

        # Search matching screenshot file associated with evidence_id
        pattern = f"*{clean_type}*.png"
        for shot_file in store.base_dir.rglob(pattern):
            if evidence_id in str(shot_file) and shot_file.resolve().is_relative_to(base_dir_resolved):
                if shot_file.stat().st_size > MAX_RESOURCE_PAYLOAD_SIZE:
                    raise McpControlPlaneException(
                        code=McpErrorCode.SECURITY_BLOCKED,
                        message=f"Screenshot file exceeds maximum size limit ({MAX_RESOURCE_PAYLOAD_SIZE} bytes).",
                    )
                return shot_file.read_bytes()

        raise McpControlPlaneException(
            code=McpErrorCode.TARGET_NOT_FOUND,
            message=f"Screenshot of type '{type}' for evidence '{evidence_id}' not found in evidence store.",
        )

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
        base_dir_resolved = store.base_dir.resolve()

        # Disallow wildcard characters in artifact_id
        if any(c in artifact_id for c in ("*", "?", "[", "]")):
            raise McpControlPlaneException(
                code=McpErrorCode.SECURITY_BLOCKED,
                message=f"Wildcards not permitted in artifact identifier: '{artifact_id}'.",
            )

        # Check action directories for this evidence_id
        for sess_dir in store.base_dir.glob("session-*"):
            act_dir = sess_dir / f"action-{evidence_id}"
            if act_dir.exists() and act_dir.resolve().is_relative_to(base_dir_resolved):
                for art_file in act_dir.glob(f"*{artifact_id}*"):
                    if art_file.is_file() and art_file.resolve().is_relative_to(base_dir_resolved):
                        if art_file.stat().st_size > MAX_RESOURCE_PAYLOAD_SIZE:
                            raise McpControlPlaneException(
                                code=McpErrorCode.SECURITY_BLOCKED,
                                message=f"Artifact exceeds maximum allowed retrieval size ({MAX_RESOURCE_PAYLOAD_SIZE} bytes).",
                            )
                        return art_file.read_bytes()

        raise McpControlPlaneException(
            code=McpErrorCode.TARGET_NOT_FOUND,
            message=f"Evidence artifact '{artifact_id}' not found for evidence '{evidence_id}'.",
        )

    # 6. desktop://missions/active
    @server.resource(
        "desktop://missions/active",
        name="active_missions",
        description="JSON inventory of admitted and active autonomous review missions.",
        mime_type="application/json",
    )
    async def get_active_missions() -> str:
        orch = getattr(bridge, "mission_orchestrator", None)
        if not orch:
            return json.dumps([], indent=2)
        active = [m.to_dict() for m in orch._active_missions.values()]
        return json.dumps(active, indent=2)

    # 7. desktop://missions/{mission_id}
    @server.resource(
        "desktop://missions/{mission_id}",
        name="mission_details",
        description="Detailed review mission authority, execution plan, progress, and result.",
        mime_type="application/json",
    )
    async def get_mission_details(mission_id: str) -> str:
        orch = getattr(bridge, "mission_orchestrator", None)
        if not orch:
            raise McpControlPlaneException(
                code=McpErrorCode.TARGET_NOT_FOUND,
                message="Mission orchestrator not initialized.",
            )
        mission = orch.get_mission(mission_id)
        if not mission:
            raise McpControlPlaneException(
                code=McpErrorCode.TARGET_NOT_FOUND,
                message=f"Mission '{mission_id}' not found.",
            )
        result = orch.get_mission_result(mission_id)
        payload = {
            "mission": mission.to_dict(),
            "result": result.to_dict() if result else None,
        }
        return json.dumps(payload, indent=2)

    # 8. desktop://system/version
    @server.resource(
        "desktop://system/version",
        name="system_version",
        description="Authoritative product and runtime version contract and environment metadata.",
        mime_type="application/json",
    )
    async def get_system_version() -> str:
        SecurityGate.validate_resource_uri("desktop://system/version")
        vinfo = get_version_info()
        return json.dumps(vinfo.to_dict(), indent=2)

    # 9. desktop://system/lifecycle
    @server.resource(
        "desktop://system/lifecycle",
        name="system_lifecycle",
        description="Product installation lifecycle status, pinning, and update availability.",
        mime_type="application/json",
    )
    async def get_system_lifecycle() -> str:
        SecurityGate.validate_resource_uri("desktop://system/lifecycle")
        updater = LifecycleUpdater()
        status = updater.get_status()
        return json.dumps(status, indent=2)

