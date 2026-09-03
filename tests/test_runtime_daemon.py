"""
Unit tests for runtime/daemon.py.
Validates long-lived daemon lifecycle (START, INITIALIZE, ACCEPT SESSION, RUN, SHUTDOWN, CLEANUP, EXIT),
idempotent shutdown, multi-session concurrency without cross-talk, and maintenance cycles.
"""

import asyncio
import sys
import unittest

from runtime.daemon import DesktopDaemon
from runtime.state import DaemonLifecycleState, SessionLifecycleState, TargetPlane
from runtime.session_manager import SessionConfig
from runtime.transport import MockTransport


class TestRuntimeDaemon(unittest.IsolatedAsyncioTestCase):
    """Test suite for DesktopDaemon lifecycle and multi-session orchestration."""

    async def asyncSetUp(self):
        self.daemon = DesktopDaemon()
        await self.daemon.initialize()

    async def asyncTearDown(self):
        await self.daemon.shutdown()

    async def test_daemon_lifecycle_progression(self):
        """Verifies START -> INITIALIZE -> RUNNING -> SHUTDOWN -> STOPPED progression."""
        self.assertEqual(self.daemon.state, DaemonLifecycleState.RUNNING)

        # Register mock transport
        mock_transport = MockTransport()
        await mock_transport.connect()
        self.daemon.register_transport(mock_transport)

        # Launch a dummy target under supervision
        cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        session = await self.daemon.launch_target(cmd=cmd)

        self.assertIsNotNone(session.session_id)
        self.assertEqual(session.lifecycle_state, SessionLifecycleState.CREATED)
        self.assertIsNotNone(session.target_process)

        # Verify auditor recorded launch event
        events = self.daemon.auditor.filter_by_session(session.session_id)
        self.assertTrue(len(events) > 0)
        self.assertEqual(events[0].operation, "TARGET_LAUNCHED")

        # Shutdown daemon
        await self.daemon.shutdown()
        self.assertEqual(self.daemon.state, DaemonLifecycleState.STOPPED)
        self.assertTrue(session.is_closed)
        self.assertFalse(mock_transport.is_connected)

    async def test_idempotent_shutdown(self):
        """Verifies calling shutdown multiple times does not raise exceptions or corrupt state."""
        self.assertEqual(self.daemon.state, DaemonLifecycleState.RUNNING)

        # First shutdown
        await self.daemon.shutdown()
        self.assertEqual(self.daemon.state, DaemonLifecycleState.STOPPED)

        # Second shutdown (idempotent)
        await self.daemon.shutdown()
        self.assertEqual(self.daemon.state, DaemonLifecycleState.STOPPED)

        # Third shutdown (idempotent)
        await self.daemon.shutdown()
        self.assertEqual(self.daemon.state, DaemonLifecycleState.STOPPED)

    async def test_concurrent_sessions_no_crosstalk(self):
        """Verifies at least 2 independent sessions operate without state cross-talk."""
        cmd1 = [sys.executable, "-c", "import time; time.sleep(30)"]
        cmd2 = [sys.executable, "-c", "import time; time.sleep(30)"]

        session1 = await self.daemon.launch_target(cmd=cmd1)
        session2 = await self.daemon.launch_target(cmd=cmd2)

        self.assertNotEqual(session1.session_id, session2.session_id)
        self.assertNotEqual(session1.target_process.pid, session2.target_process.pid)

        # Connect and activate session1, leave session2 untouched
        await self.daemon.session_manager.connect_session(session1.session_id)
        await self.daemon.session_manager.activate_session(session1.session_id, TargetPlane.NATIVE_SHELL)

        self.assertEqual(session1.lifecycle_state, SessionLifecycleState.ACTIVE)
        self.assertEqual(session2.lifecycle_state, SessionLifecycleState.CREATED)

        # Advance epoch in session1
        session1.reference_registry.increment_epoch("mutation_test")
        self.assertEqual(session1.current_epoch, 2)
        self.assertEqual(session2.current_epoch, 1)

        # Close session1
        await self.daemon.session_manager.close_session(session1.session_id)
        self.assertTrue(session1.is_closed)
        self.assertFalse(session2.is_closed)

        active = await self.daemon.session_manager.list_active_sessions()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].session_id, session2.session_id)

    async def test_maintenance_cycle_cleans_dead_processes(self):
        """Verifies maintenance cycle detects process exit and closes associated session."""
        # Launch short-lived process that exits immediately
        cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
        session = await self.daemon.launch_target(cmd=cmd)

        # Wait for process to exit
        await asyncio.sleep(0.5)

        # Run maintenance cycle
        report = await self.daemon.run_maintenance_cycle()
        self.assertIn(session.target_process.pid, report["dead_pids"])
        self.assertTrue(session.is_closed)


if __name__ == "__main__":
    unittest.main()
