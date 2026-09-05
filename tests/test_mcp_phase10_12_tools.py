"""
MCP Phase 10-12 Integration Tests.
Verifies:
- desktop_drag_drop tool implementation
- desktop_press_key tool implementation with modifier shortcuts
- desktop_screenshot tool implementation with desktop, window, and element scopes
- desktop_get_trace tool implementation with timeline queries
- MCP resources: desktop://sessions/{session_id}/trace, reality, and desktop://displays
"""

from __future__ import annotations
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane
from runtime.session_manager import SessionState, SessionManager, SessionConfig
from runtime.daemon import DesktopDaemon
from runtime.evidence_store import EvidenceStore
from runtime.mcp.runtime_bridge import RuntimeBridge
from runtime.action_models import (
    ActionOutcome,
    ActionReceipt,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
)
from runtime.trace_engine import DesktopTraceEngine
from runtime.mcp.tools.actions import desktop_drag_drop_impl, desktop_press_key_impl
from runtime.mcp.tools.observation import desktop_screenshot_impl, desktop_get_trace_impl


class TestMcpPhase1012Tools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session_id = "test_mcp_session"
        self.daemon = DesktopDaemon()
        self.session_manager = self.daemon.session_manager
        self.session = await self.session_manager.create_session(SessionConfig(session_id=self.session_id))
        self.session.trace_engine = DesktopTraceEngine(session_id=self.session_id)
        self.session.reference_registry = ReferenceRegistry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.session.evidence_store = EvidenceStore(base_dir=Path(self.temp_dir.name))
        self.bridge = RuntimeBridge(daemon=self.daemon)

    async def asyncTearDown(self):
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    async def test_mcp_desktop_drag_drop(self):
        """desktop_drag_drop_impl dispatches coordinate or reference drag-drop via action_engine."""
        receipt = ActionReceipt(
            action_id="act_drag",
            session_id=self.session_id,
            target_id="tgt_drag",
            epoch=1,
            plane=TargetPlane.NATIVE,
            reference="n1e1",
            action_type=ActionType.DRAG_AND_DROP,
            dispatch_method=DispatchMethod.NATIVE_SENDINPUT,
            dispatch_timestamp=1000.0,
            dispatch_status=DispatchStatus.DISPATCHED,
        )
        mock_outcome = ActionOutcome(
            action_id="act_drag",
            session_id=self.session_id,
            receipt=receipt,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=1,
            post_epoch=2,
            duration_ms=15.0,
        )
        mock_action_engine = MagicMock()
        mock_action_engine.execute = AsyncMock(return_value=mock_outcome)
        self.session.action_engine = mock_action_engine

        result = await desktop_drag_drop_impl(
            bridge=self.bridge,
            session_id=self.session_id,
            from_ref="n1e1",
            to_x=200,
            to_y=200,
        )

        self.assertTrue(result["executed"])
        self.assertEqual(result["action_id"], "act_drag")
        self.assertEqual(result["status"], "DISPATCHED")
        mock_action_engine.execute.assert_called_once()

    async def test_mcp_desktop_press_key_with_modifiers(self):
        """desktop_press_key_impl dispatches keyboard shortcut with modifiers."""
        receipt = ActionReceipt(
            action_id="act_key",
            session_id=self.session_id,
            target_id="tgt_key",
            epoch=1,
            plane=TargetPlane.NATIVE,
            reference="w1e1",
            action_type=ActionType.KEY_PRESS,
            dispatch_method=DispatchMethod.NATIVE_SENDINPUT,
            dispatch_timestamp=1000.0,
            dispatch_status=DispatchStatus.DISPATCHED,
        )
        mock_outcome = ActionOutcome(
            action_id="act_key",
            session_id=self.session_id,
            receipt=receipt,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.NO_EFFECT,
            pre_epoch=1,
            post_epoch=2,
            duration_ms=10.0,
        )
        mock_action_engine = MagicMock()
        mock_action_engine.execute = AsyncMock(return_value=mock_outcome)
        self.session.action_engine = mock_action_engine

        result = await desktop_press_key_impl(
            bridge=self.bridge,
            session_id=self.session_id,
            key="c",
            modifiers=["Control"],
        )

        self.assertTrue(result["executed"])
        self.assertEqual(result["action_id"], "act_key")
        self.assertEqual(result["status"], "DISPATCHED")
        mock_action_engine.execute.assert_called_once()

    async def test_mcp_desktop_screenshot_tool(self):
        """desktop_screenshot_impl captures desktop screenshot and records artifact."""
        mock_supervisor = MagicMock()
        mock_supervisor.capture_full_desktop_screenshot.return_value = (
            True,
            b"\x89PNG\r\n\x1a\nfake_full_screen",
            "fake_hash_123",
            {"width": 1920, "height": 1080},
        )
        self.session.native_supervisor = mock_supervisor

        result = await desktop_screenshot_impl(
            bridge=self.bridge,
            session_id=self.session_id,
            scope="desktop",
            store_evidence=True,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["scope"], "desktop")
        self.assertIsNotNone(result["artifact_id"])
        self.assertGreater(result["size_bytes"], 0)

    async def test_mcp_desktop_get_trace_tool(self):
        """desktop_get_trace_impl queries events from DesktopTraceEngine."""
        trace = self.session.trace_engine
        trace.emit(
            event_type="ACTION_REQUESTED",
            session_id=self.session_id,
            action_id="act_trace_1",
            status="RECEIVED",
            details={"step": "first"},
        )

        result = await desktop_get_trace_impl(
            bridge=self.bridge,
            session_id=self.session_id,
            limit=50,
        )

        self.assertEqual(result["session_id"], self.session_id)
        self.assertGreaterEqual(result["total_events"], 1)
        self.assertEqual(result["events"][0]["event_type"], "ACTION_REQUESTED")

    async def test_mcp_resources_trace_and_displays(self):
        """MCP server registers desktop://displays, trace, and reality resources."""
        from runtime.mcp.server import create_mcp_server
        server = create_mcp_server(daemon=self.daemon)

        # Check static resources
        resources = await server.list_resources()
        res_uris = [str(r.uri) for r in resources]
        self.assertTrue(any("desktop://displays" in u for u in res_uris))

        # Check resource templates
        templates = await server.list_resource_templates()
        template_uris = [str(t.uri_template) for t in templates]
        self.assertTrue(any("desktop://sessions/{session_id}/trace" in t for t in template_uris))
        self.assertTrue(any("desktop://sessions/{session_id}/reality" in t for t in template_uris))


if __name__ == "__main__":
    unittest.main()
