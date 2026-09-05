"""
Unit tests for RecoveryEngine, RecoveryPolicy, and CircuitBreaker (Phase 16 - Prompt P4).
"""
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock
from runtime.diagnostics import FailureCategory, DiagnosticDiagnosis
from runtime.recovery_engine import (
    RecoveryEngine,
    RecoveryAction,
    RecoveryPolicy,
    CircuitBreaker,
    CircuitState,
    RecoveryBlockedException,
)


class TestRecoveryEngineAndCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.session_id = "test-session-recovery"
        self.mock_session.current_epoch = 1
        self.mock_session.target_window = None
        self.mock_session.target_hwnd = 0x9999

        # Observation engine
        self.mock_obs_engine = MagicMock()
        self.mock_obs_engine.capture_observation = AsyncMock(return_value=MagicMock())
        self.mock_session.observation_engine = self.mock_obs_engine

        # Native supervisor
        self.mock_supervisor = MagicMock()
        self.mock_session.native_supervisor = self.mock_supervisor

        self.mock_trace = MagicMock()
        self.mock_session.trace_engine = self.mock_trace

    def test_circuit_breaker_trips_after_consecutive_failures(self):
        """Circuit breaker transitions to OPEN after 3 consecutive failures."""
        cb = CircuitBreaker(max_consecutive_failures=3, cooldown_period_sec=10.0)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertFalse(cb.is_blocked())

        cb.record_failure("Failure 1")
        self.assertEqual(cb.failure_count, 1)
        self.assertEqual(cb.state, CircuitState.CLOSED)

        cb.record_failure("Failure 2")
        self.assertEqual(cb.failure_count, 2)
        self.assertEqual(cb.state, CircuitState.CLOSED)

        cb.record_failure("Failure 3")
        self.assertEqual(cb.failure_count, 3)
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertTrue(cb.is_blocked())
        self.assertIn("Consecutive failure threshold (3) exceeded", cb.block_reason)

    def test_circuit_breaker_half_open_after_cooldown(self):
        """Circuit breaker enters HALF_OPEN after cooldown period elapses."""
        cb = CircuitBreaker(max_consecutive_failures=2, cooldown_period_sec=5.0)
        now = 1000.0
        cb.record_failure("Fail 1", now=now)
        cb.record_failure("Fail 2", now=now)
        self.assertTrue(cb.is_blocked(now=now + 2.0))

        # After 5.0 seconds cooldown
        self.assertFalse(cb.is_blocked(now=now + 6.0))
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # On success in half-open, circuit closes
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.failure_count, 0)

    def test_recovery_engine_executes_policy_candidate_and_succeeds(self):
        """RecoveryEngine executes mapped policy action and records success."""
        diag = DiagnosticDiagnosis(
            session_id="test-session-recovery",
            failure_category=FailureCategory.WINDOW_CLOAKED,
            root_cause_summary="Window is cloaked",
            confidence=0.9,
        )

        engine = RecoveryEngine()
        success, record = asyncio.run(engine.execute_recovery(diag, self.mock_session))

        self.assertTrue(success)
        self.assertEqual(record.action, RecoveryAction.REFRESH_OBSERVATION)
        self.assertEqual(record.result, "SUCCESS")
        self.assertEqual(engine.circuit_breaker.failure_count, 0)
        self.mock_obs_engine.capture_observation.assert_awaited_once()

    def test_recovery_engine_blocked_when_circuit_breaker_open(self):
        """RecoveryEngine raises RecoveryBlockedException when CircuitBreaker is OPEN."""
        diag = DiagnosticDiagnosis(
            session_id="test-session-recovery",
            failure_category=FailureCategory.WINDOW_CLOAKED,
            root_cause_summary="Window is cloaked",
            confidence=0.9,
        )

        cb = CircuitBreaker(max_consecutive_failures=1)
        cb.record_failure("Pre-existing trip")
        self.assertTrue(cb.is_blocked())

        engine = RecoveryEngine(circuit_breaker=cb)
        with self.assertRaises(RecoveryBlockedException):
            asyncio.run(engine.execute_recovery(diag, self.mock_session))


if __name__ == "__main__":
    unittest.main()
