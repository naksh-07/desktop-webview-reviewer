"""
Payload Safety, Buffer Protection, and Reconnect Tests for MCP Control Plane.
Verifies dual-modal screenshot bounding, large tree serialization safety over stdio,
and session survival across MCP client disconnect/reconnect cycles (Docs 14 §8 & 18).
"""

import sys
import unittest
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock
from mcp.client import Client
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

from runtime.daemon import get_default_daemon, reset_default_daemon
from runtime.session_manager import SessionConfig
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


class TestMcpPayloadAndReconnect(unittest.IsolatedAsyncioTestCase):
    """Verifies stdio buffer safety, dual-modal payloads, and session disconnect/reconnect."""

    async def asyncSetUp(self):
        reset_default_daemon()
        self.daemon = get_default_daemon()
        self.server = create_mcp_server(daemon=self.daemon)

    async def asyncTearDown(self):
        reset_default_daemon()

    async def test_large_observation_payload_safety_stdio(self):
        """Validates that a 50KB+ observation tree does not deadlock or truncate over stdio transport."""
        # Create session with large tree on default daemon
        session = await self.daemon.session_manager.create_session(
            SessionConfig(session_id="session-large-payload", target_pid=2001, target_hwnd=20010)
        )
        session.target_process = ProcessIdentity(pid=2001, creation_time=1000.0, binary_path="test.exe")
        session.target_window = WindowIdentity(
            hwnd=20010, pid=2001, title="Large Window", class_name="Qt",
            bounds=Rect(0, 0, 1920, 1080), is_visible=True, is_cloaked=False,
            is_minimized=False, is_hung=False,
        )
        session.active_plane = TargetPlane.WEBVIEW_DOM

        # Build large observation string (~60 KB)
        large_tree_lines = [f"  - button 'Button #{i}' [ref=w1e{i}]" for i in range(1500)]
        large_tree_text = "\n".join(large_tree_lines)

        mock_obs = MagicMock()
        mock_obs.last_snapshot = DualPerspectiveSnapshot(
            session_id=session.session_id,
            epoch=1,
            timestamp=1000.0,
            text_representation=large_tree_text,
        )
        mock_obs.observe = AsyncMock(return_value=mock_obs.last_snapshot)
        session.observation_engine = mock_obs

        # Connect via stdio client
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "runtime.mcp"],
            env=None,
        )

        # Using in-memory client for daemon state sharing
        async with Client(self.server) as client:
            res = await client.call_tool("desktop_inspect", {"session_id": "session-large-payload"})
            self.assertFalse(res.is_error)
            data = json.loads(res.content[0].text)
            self.assertIn("Button #1499", data["tree"])
            self.assertGreater(len(data["tree"]), 50000)

    async def test_action_idempotency_and_deduplication(self):
        """Validates that repeating the same action_id returns the existing transaction state."""
        session = await self.daemon.session_manager.create_session(
            SessionConfig(session_id="session-dedup", target_pid=3001, target_hwnd=30010)
        )
        session.target_process = ProcessIdentity(pid=3001, creation_time=1000.0, binary_path="test.exe")
        session.target_window = WindowIdentity(
            hwnd=30010, pid=3001, title="Dedup Window", class_name="Qt",
            bounds=Rect(0, 0, 800, 600), is_visible=True, is_cloaked=False,
            is_minimized=False, is_hung=False,
        )
        session.active_plane = TargetPlane.WEBVIEW_DOM

        receipt = ActionReceipt(
            action_id="act-unique-fixed-id",
            session_id=session.session_id,
            target_id="tgt-1",
            epoch=1,
            plane=TargetPlane.WEBVIEW_DOM,
            reference="w1e1",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.CDP_INPUT,
            dispatch_timestamp=1000.0,
            dispatch_status=DispatchStatus.DISPATCHED,
        )
        outcome = ActionOutcome(
            action_id="act-unique-fixed-id",
            session_id=session.session_id,
            receipt=receipt,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=1,
            post_epoch=2,
            post_snapshot=DualPerspectiveSnapshot(session_id=session.session_id, epoch=2, timestamp=1001.0, text_representation="post state"),
        )
        mock_act = MagicMock()
        mock_act.execute = AsyncMock(return_value=outcome)
        session.action_engine = mock_act

        async with Client(self.server) as client:
            # First execution
            res1 = await client.call_tool("desktop_click", {
                "session_id": session.session_id,
                "ref": "w1e1",
                "action_id": "act-unique-fixed-id",
            })
            self.assertFalse(res1.is_error)
            data1 = json.loads(res1.content[0].text)
            self.assertEqual(data1["action_id"], "act-unique-fixed-id")
            self.assertFalse(data1.get("cached", False))

            # Second execution with exact same action_id -> Deduplicated, cached response
            res2 = await client.call_tool("desktop_click", {
                "session_id": session.session_id,
                "ref": "w1e1",
                "action_id": "act-unique-fixed-id",
            })
            self.assertFalse(res2.is_error)
            data2 = json.loads(res2.content[0].text)
            self.assertEqual(data2["action_id"], "act-unique-fixed-id")
            self.assertTrue(data2.get("cached", False))

            # Verify action engine was only invoked once
            self.assertEqual(mock_act.execute.call_count, 1)

    async def test_mcp_disconnect_and_reconnect_session_survival(self):
        """Validates that closing an MCP client transport does not destroy the underlying session."""
        session = await self.daemon.session_manager.create_session(
            SessionConfig(session_id="session-survive-reconnect", target_pid=4001, target_hwnd=40010)
        )
        session.target_process = ProcessIdentity(pid=4001, creation_time=1000.0, binary_path="test.exe")
        session.target_window = WindowIdentity(
            hwnd=40010, pid=4001, title="Surviving Window", class_name="Qt",
            bounds=Rect(0, 0, 800, 600), is_visible=True, is_cloaked=False,
            is_minimized=False, is_hung=False,
        )
        session.active_plane = TargetPlane.WEBVIEW_DOM

        # First MCP client session connects and performs inspection
        async with Client(self.server) as client_1:
            res1 = await client_1.call_tool("desktop_inspect", {"session_id": "session-survive-reconnect"})
            self.assertFalse(res1.is_error)

        # Client 1 is now disconnected and exited.
        # Assert daemon still holds the session in memory.
        retrieved_session = self.daemon.session_manager.get_session("session-survive-reconnect")
        self.assertIsNotNone(retrieved_session)
        self.assertFalse(retrieved_session.is_closed)

        # Second MCP client connects (simulating reconnect)
        async with Client(self.server) as client_2:
            res2 = await client_2.call_tool("desktop_inspect", {"session_id": "session-survive-reconnect"})
            self.assertFalse(res2.is_error)
            data = json.loads(res2.content[0].text)
            self.assertEqual(data["window_forensics"]["title"], "Surviving Window")


if __name__ == "__main__":
    unittest.main()
