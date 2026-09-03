"""
Unit tests for runtime/cdp_target.py.
Validates target discovery, multiplexing, lifecycle tracking, target crash and close handling,
and debugging endpoint process correlation.
"""

import unittest
from unittest.mock import patch, MagicMock

from runtime.cdp_transport import MockCDPTransport
from runtime.cdp_target import CDPTargetManager, CDPTargetInfo, EndpointProcessCorrelation
from runtime.state import TargetLifecycleState
from runtime.errors import (
    CDPTargetClosedException,
    TargetNotFoundException,
)


class TestCDPTargetManager(unittest.IsolatedAsyncioTestCase):
    """Test suite for CDP target management, lifecycle events, and multiplexing."""

    async def asyncSetUp(self):
        self.transport = MockCDPTransport()
        await self.transport.connect()
        self.target_manager = CDPTargetManager(transport=self.transport, session_id="test_session_1")

    async def asyncTearDown(self):
        await self.transport.disconnect()

    async def test_initialization_populates_targets(self):
        """Verifies initialize fetches initial targets and sets primary target."""
        self.transport.register_handler("Target.getTargets", lambda p: {
            "targetInfos": [
                {
                    "targetId": "page_main",
                    "type": "page",
                    "title": "Main Window",
                    "url": "http://127.0.0.1:8000/main",
                    "attached": False,
                },
                {
                    "targetId": "page_toolbar",
                    "type": "page",
                    "title": "Toolbar",
                    "url": "http://127.0.0.1:8000/toolbar",
                    "attached": False,
                }
            ]
        })

        await self.target_manager.initialize()

        targets = self.target_manager.list_targets()
        self.assertEqual(len(targets), 2)
        self.assertIsNotNone(self.target_manager.primary_target)
        self.assertEqual(self.target_manager.primary_target.target_id, "page_main")

    async def test_target_lifecycle_created_destroyed(self):
        """Verifies targetCreated and targetDestroyed events update target state."""
        await self.target_manager.initialize()

        # Emit targetCreated
        self.transport.emit_event("Target.targetCreated", {
            "targetInfo": {
                "targetId": "page_dynamic",
                "type": "page",
                "title": "Dynamic Dialog",
                "url": "http://127.0.0.1:8000/dialog",
            }
        })

        target = self.target_manager.get_target("page_dynamic")
        self.assertEqual(target.title, "Dynamic Dialog")
        self.assertEqual(target.lifecycle_state, TargetLifecycleState.CREATED)

        # Emit targetDestroyed
        self.transport.emit_event("Target.targetDestroyed", {"targetId": "page_dynamic"})

        target_after = self.target_manager.get_target("page_dynamic")
        self.assertEqual(target_after.lifecycle_state, TargetLifecycleState.CLOSED)
        # Verify active_only filter excludes it
        active = self.target_manager.list_targets(active_only=True)
        self.assertNotIn("page_dynamic", [t.target_id for t in active])

    async def test_target_crashed_handling(self):
        """Verifies targetCrashed transitions target state to CRASHED."""
        await self.target_manager.initialize()

        self.transport.emit_event("Target.targetCreated", {
            "targetInfo": {"targetId": "page_worker", "type": "page", "title": "Worker"}
        })

        self.transport.emit_event("Target.targetCrashed", {
            "targetId": "page_worker",
            "status": "crashed",
            "errorCode": 5,
        })

        target = self.target_manager.get_target("page_worker")
        self.assertEqual(target.lifecycle_state, TargetLifecycleState.CRASHED)

    async def test_target_multiplexing_attach_detach(self):
        """Verifies attaching to specific targets allocates session IDs and tracks mapping."""
        await self.target_manager.initialize()

        self.transport.emit_event("Target.targetCreated", {
            "targetInfo": {"targetId": "page_alpha", "type": "page", "title": "Alpha"}
        })
        self.transport.register_handler("Target.attachToTarget", lambda p: {"sessionId": "cdp_sess_alpha"})

        session_id = await self.target_manager.attach_target("page_alpha")
        self.assertEqual(session_id, "cdp_sess_alpha")

        # Verify mapping
        self.assertEqual(self.target_manager.get_session_id_for_target("page_alpha"), "cdp_sess_alpha")

        # Detach
        await self.target_manager.detach_target("page_alpha")
        self.assertIsNone(self.target_manager.get_session_id_for_target("page_alpha"))

    async def test_attach_to_closed_target_raises(self):
        """Verifies attempting to attach to a closed or crashed target raises CDPTargetClosedException."""
        await self.target_manager.initialize()

        self.transport.emit_event("Target.targetCreated", {
            "targetInfo": {"targetId": "dead_page", "type": "page", "title": "Dead"}
        })
        self.transport.emit_event("Target.targetDestroyed", {"targetId": "dead_page"})

        with self.assertRaises(CDPTargetClosedException):
            await self.target_manager.attach_target("dead_page")

    def test_endpoint_process_correlation_verified(self):
        """Verifies endpoint correlation proof succeeds when port ownership matches PID."""
        with patch("core.window_forensics.WindowForensicsEngine.verify_port_listening_process", return_value=(True, 1234, "PID matches")):
            corr = CDPTargetManager.verify_endpoint_ownership(
                port=9222,
                expected_pid=1234,
            )
            self.assertTrue(corr.is_verified)
            self.assertEqual(corr.proof_status, "VERIFIED")
            self.assertEqual(corr.listening_pid, 1234)

    def test_endpoint_process_correlation_unknown_when_unprovable(self):
        """Verifies endpoint correlation returns UNKNOWN rather than false certainty when proof unavailable."""
        with patch("core.window_forensics.WindowForensicsEngine.verify_port_listening_process", return_value=(False, None, "Netstat unavailable")):
            corr = CDPTargetManager.verify_endpoint_ownership(
                port=9222,
                expected_pid=1234,
            )
            self.assertFalse(corr.is_verified)
            self.assertEqual(corr.proof_status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
