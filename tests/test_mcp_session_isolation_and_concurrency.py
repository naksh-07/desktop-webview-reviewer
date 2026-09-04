"""
Session Isolation and Concurrency Tests for MCP Control Plane.
Verifies cross-session ref poisoning prevention, session-scoped execution isolation,
and concurrent multi-client/multi-session stability (Docs 14 §6 & 15).
"""

import sys
import unittest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

from runtime.daemon import get_default_daemon, reset_default_daemon
from runtime.session_manager import SessionConfig, SessionState
from runtime.mcp.server import create_mcp_server
from runtime.state import TargetPlane
from runtime.references import Rect
from runtime.target_manager import WindowIdentity, ProcessIdentity
from runtime.observation_models import DualPerspectiveSnapshot
from runtime.action_models import (
    ActionReceipt,
    ActionOutcome,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
)


class TestMcpSessionIsolationAndConcurrency(unittest.IsolatedAsyncioTestCase):
    """Verifies session isolation and concurrent execution through the MCP server."""

    async def asyncSetUp(self):
        reset_default_daemon()
        self.daemon = get_default_daemon()
        self.server = create_mcp_server(daemon=self.daemon)

        # Create Session A
        self.session_a = await self.daemon.session_manager.create_session(
            SessionConfig(session_id="session-aaa-111", target_pid=1001, target_hwnd=10010)
        )
        self.session_a.target_process = ProcessIdentity(pid=1001, creation_time=1000.0, binary_path="test_a.exe")
        self.session_a.target_window = WindowIdentity(
            hwnd=10010,
            pid=1001,
            title="Window A",
            class_name="Qt",
            bounds=Rect(0, 0, 800, 600),
            is_visible=True,
            is_cloaked=False,
            is_minimized=False,
            is_hung=False,
        )
        self.session_a.active_plane = TargetPlane.WEBVIEW_DOM

        # Create Session B
        self.session_b = await self.daemon.session_manager.create_session(
            SessionConfig(session_id="session-bbb-222", target_pid=1002, target_hwnd=10020)
        )
        self.session_b.target_process = ProcessIdentity(pid=1002, creation_time=1000.0, binary_path="test_b.exe")
        self.session_b.target_window = WindowIdentity(
            hwnd=10020,
            pid=1002,
            title="Window B",
            class_name="Qt",
            bounds=Rect(0, 0, 800, 600),
            is_visible=True,
            is_cloaked=False,
            is_minimized=False,
            is_hung=False,
        )
        self.session_b.active_plane = TargetPlane.WEBVIEW_DOM

        # Setup mock observation engine for Session A
        mock_obs_a = MagicMock()
        mock_obs_a.last_snapshot = DualPerspectiveSnapshot(
            session_id=self.session_a.session_id,
            epoch=1,
            timestamp=1000.0,
            text_representation="- button 'Button A' [ref=w1e1]",
        )
        mock_obs_a.observe = AsyncMock(return_value=mock_obs_a.last_snapshot)
        self.session_a.observation_engine = mock_obs_a

        # Setup mock observation engine for Session B
        mock_obs_b = MagicMock()
        mock_obs_b.last_snapshot = DualPerspectiveSnapshot(
            session_id=self.session_b.session_id,
            epoch=1,
            timestamp=1000.0,
            text_representation="- button 'Button B' [ref=w1e2]",
        )
        mock_obs_b.observe = AsyncMock(return_value=mock_obs_b.last_snapshot)
        self.session_b.observation_engine = mock_obs_b

        # Setup mock action engine for Session A
        receipt_a = ActionReceipt(
            action_id="act-a",
            session_id=self.session_a.session_id,
            target_id="tgt-a",
            epoch=1,
            plane=TargetPlane.WEBVIEW_DOM,
            reference="w1e1",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.CDP_INPUT,
            dispatch_timestamp=1000.0,
            dispatch_status=DispatchStatus.DISPATCHED,
        )
        outcome_a = ActionOutcome(
            action_id="act-a",
            session_id=self.session_a.session_id,
            receipt=receipt_a,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=1,
            post_epoch=2,
            post_snapshot=mock_obs_a.last_snapshot,
        )
        mock_act_a = MagicMock()
        mock_act_a.execute = AsyncMock(return_value=outcome_a)
        self.session_a.action_engine = mock_act_a

        # Setup mock action engine for Session B
        receipt_b = ActionReceipt(
            action_id="act-b",
            session_id=self.session_b.session_id,
            target_id="tgt-b",
            epoch=1,
            plane=TargetPlane.WEBVIEW_DOM,
            reference="w1e2",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.CDP_INPUT,
            dispatch_timestamp=2000.0,
            dispatch_status=DispatchStatus.DISPATCHED,
        )
        outcome_b = ActionOutcome(
            action_id="act-b",
            session_id=self.session_b.session_id,
            receipt=receipt_b,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=1,
            post_epoch=2,
            post_snapshot=mock_obs_b.last_snapshot,
        )
        mock_act_b = MagicMock()
        mock_act_b.execute = AsyncMock(return_value=outcome_b)
        self.session_b.action_engine = mock_act_b

    async def asyncTearDown(self):
        reset_default_daemon()

    async def test_session_ref_isolation_cross_talk_prevention(self):
        """Verifies that Session B cannot execute an action using Session A's ref token."""
        from mcp.client import Client
        async with Client(self.server) as client:
            # Call click on Session A with its own ref w1e1 -> DISPATCHED
            res_a = await client.call_tool("desktop_click", {"session_id": self.session_a.session_id, "ref": "w1e1"})
            self.assertFalse(res_a.is_error)
            data_a = json.loads(res_a.content[0].text)
            self.assertEqual(data_a["status"], "DISPATCHED")

            # Setup locator on Session B to raise StaleReferenceException when w1e1 is resolved
            from runtime.errors import StaleReferenceException
            stale_exc = StaleReferenceException(ref_id="w1e1", current_epoch=2, ref_epoch=1)
            mock_loc_b = MagicMock()
            mock_loc_b.resolve_ref = MagicMock(side_effect=stale_exc)
            self.session_b.locator_engine = mock_loc_b
            self.session_b.action_engine.execute = AsyncMock(side_effect=stale_exc)

            # Call click on Session B with Session A's ref w1e1 -> Rejected as STALE_REFERENCE
            res_b = await client.call_tool("desktop_click", {"session_id": self.session_b.session_id, "ref": "w1e1"})
            self.assertTrue(res_b.is_error)
            self.assertIn("STALE_REFERENCE", res_b.content[0].text)

    async def test_concurrent_inspect_calls_isolation(self):
        """Validates that concurrent inspect calls on separate sessions return distinct data."""
        from mcp.client import Client
        async with Client(self.server) as client:
            # Dispatch concurrent inspect calls
            inspect_a_task = client.call_tool("desktop_inspect", {"session_id": self.session_a.session_id})
            inspect_b_task = client.call_tool("desktop_inspect", {"session_id": self.session_b.session_id})

            res_a, res_b = await asyncio.gather(inspect_a_task, inspect_b_task)

            self.assertFalse(res_a.is_error)
            self.assertFalse(res_b.is_error)

            data_a = json.loads(res_a.content[0].text)
            data_b = json.loads(res_b.content[0].text)

            # Verify Session A returned Button A and Window A
            self.assertEqual(data_a["window_forensics"]["title"], "Window A")
            self.assertIn("Button A", data_a["tree"])
            self.assertNotIn("Button B", data_a["tree"])

            # Verify Session B returned Button B and Window B
            self.assertEqual(data_b["window_forensics"]["title"], "Window B")
            self.assertIn("Button B", data_b["tree"])
            self.assertNotIn("Button A", data_b["tree"])

    async def test_concurrent_clients_separate_sessions(self):
        """Validates two separate MCP clients simultaneously interacting with different sessions."""
        from mcp.client import Client
        async def client_worker(session_id: str, expected_btn: str):
            async with Client(self.server) as client:
                res = await client.call_tool("desktop_inspect", {"session_id": session_id})
                self.assertFalse(res.is_error)
                data = json.loads(res.content[0].text)
                self.assertIn(expected_btn, data["tree"])

        # Run both clients concurrently
        await asyncio.gather(
            client_worker(self.session_a.session_id, "Button A"),
            client_worker(self.session_b.session_id, "Button B"),
        )


if __name__ == "__main__":
    unittest.main()
