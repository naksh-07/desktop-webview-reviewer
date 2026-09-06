"""
Unit tests for runtime/session_manager.py and runtime/state.py.
Validates session creation, explicit state transitions, invalid transition rejection,
idempotent duplicate closure, lease expiration, and multi-session concurrency isolation.
"""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from runtime.state import (
    SessionLifecycleState,
    ConnectionState,
    TargetPlane,
)
from runtime.session_manager import SessionManager, SessionConfig
from runtime.errors import (
    SessionNotFoundException,
    InvalidStateTransitionError,
)


class TestRuntimeSession(unittest.IsolatedAsyncioTestCase):
    """Test suite for session lifecycle state machine and session manager."""

    async def asyncSetUp(self):
        self.manager = SessionManager()

    async def test_session_creation(self):
        """Verifies session is created in CREATED state with valid defaults."""
        config = SessionConfig(target_executable="test_app.exe", lease_timeout_sec=120)
        session = await self.manager.create_session(config)

        self.assertIsNotNone(session.session_id)
        self.assertEqual(session.lifecycle_state, SessionLifecycleState.CREATED)
        self.assertEqual(session.connection_state, ConnectionState.DISCONNECTED)
        self.assertEqual(session.lease_timeout_sec, 120)
        self.assertEqual(session.current_epoch, 1)
        self.assertFalse(session.is_active)
        self.assertFalse(session.is_closed)

    async def test_valid_state_transitions(self):
        """Verifies full lifecycle progression: CREATED -> CONNECTING -> CONNECTED -> ACTIVE -> DISCONNECTING -> CLOSED."""
        session = await self.manager.create_session(SessionConfig())
        self.assertEqual(session.lifecycle_state, SessionLifecycleState.CREATED)

        # Connect session (transitions CREATED -> CONNECTING -> CONNECTED)
        await self.manager.connect_session(session.session_id)
        self.assertEqual(session.lifecycle_state, SessionLifecycleState.CONNECTED)
        self.assertEqual(session.connection_state, ConnectionState.CONNECTED)

        # Activate session (transitions CONNECTED -> ACTIVE)
        await self.manager.activate_session(session.session_id, TargetPlane.NATIVE_SHELL)
        self.assertEqual(session.lifecycle_state, SessionLifecycleState.ACTIVE)
        self.assertTrue(session.is_active)

        # Close session (transitions ACTIVE -> DISCONNECTING -> CLOSED)
        await self.manager.close_session(session.session_id, reason="normal_test_completion")
        self.assertEqual(session.lifecycle_state, SessionLifecycleState.CLOSED)
        self.assertTrue(session.is_closed)
        self.assertFalse(session.is_active)

    async def test_invalid_state_transitions(self):
        """Verifies illegal state transitions raise InvalidStateTransitionError."""
        session = await self.manager.create_session(SessionConfig())

        # Cannot jump directly from CREATED to ACTIVE
        with self.assertRaises(InvalidStateTransitionError):
            session.transition_lifecycle(SessionLifecycleState.ACTIVE)

        # Once closed, terminal state cannot transition anywhere
        await self.manager.close_session(session.session_id)
        self.assertEqual(session.lifecycle_state, SessionLifecycleState.CLOSED)

        with self.assertRaises(InvalidStateTransitionError):
            session.transition_lifecycle(SessionLifecycleState.ACTIVE)

        with self.assertRaises(InvalidStateTransitionError):
            session.transition_lifecycle(SessionLifecycleState.CONNECTING)

    async def test_duplicate_close_is_idempotent(self):
        """Verifies repeated close requests on the same session do not throw exceptions."""
        session = await self.manager.create_session(SessionConfig())
        await self.manager.connect_session(session.session_id)
        await self.manager.activate_session(session.session_id)

        # First close
        closed1 = await self.manager.close_session(session.session_id)
        self.assertEqual(closed1.lifecycle_state, SessionLifecycleState.CLOSED)

        # Second close (must be idempotent)
        closed2 = await self.manager.close_session(session.session_id)
        self.assertEqual(closed2.lifecycle_state, SessionLifecycleState.CLOSED)

    async def test_session_not_found(self):
        """Verifies querying nonexistent session raises SessionNotFoundException."""
        with self.assertRaises(SessionNotFoundException):
            self.manager.get_session("nonexistent-guid-12345")

    async def test_lease_expiration_and_pruning(self):
        """Verifies expired leases are identified and pruned by maintenance."""
        config = SessionConfig(lease_timeout_sec=10)
        session = await self.manager.create_session(config)
        await self.manager.connect_session(session.session_id)
        await self.manager.activate_session(session.session_id)

        # Artificially age the heartbeat beyond 10s
        session.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=15)
        self.assertTrue(session.is_lease_expired())

        # Prune expired sessions
        pruned = await self.manager.prune_expired_sessions()
        self.assertIn(session.session_id, pruned)
        self.assertTrue(session.is_closed)

    async def test_concurrent_sessions_isolation(self):
        """Verifies two independent concurrent sessions operate without state cross-talk."""
        session1 = await self.manager.create_session(SessionConfig(target_executable="app1.exe"))
        session2 = await self.manager.create_session(SessionConfig(target_executable="app2.exe"))

        self.assertNotEqual(session1.session_id, session2.session_id)

        # Advance session1 to ACTIVE, keep session2 in CREATED
        await self.manager.connect_session(session1.session_id)
        await self.manager.activate_session(session1.session_id, TargetPlane.WEBVIEW_DOM)

        self.assertEqual(session1.lifecycle_state, SessionLifecycleState.ACTIVE)
        self.assertEqual(session1.active_plane, TargetPlane.WEBVIEW_DOM)
        self.assertEqual(session2.lifecycle_state, SessionLifecycleState.CREATED)
        self.assertEqual(session2.active_plane, TargetPlane.UNKNOWN)

        # Increment epoch in session1, verify session2 epoch is untouched
        session1.reference_registry.increment_epoch("nav_app1")
        self.assertEqual(session1.current_epoch, 2)
        self.assertEqual(session2.current_epoch, 1)

        # Close session1, verify session2 remains unclosed
        await self.manager.close_session(session1.session_id)
        self.assertTrue(session1.is_closed)
        self.assertFalse(session2.is_closed)

        active = await self.manager.list_active_sessions()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].session_id, session2.session_id)


if __name__ == "__main__":
    unittest.main()
