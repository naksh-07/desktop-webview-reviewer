"""
Unit tests for DiagnosticAggregator and Failure Classification (Phase 16 - Prompt P4).
"""
import unittest
from unittest.mock import MagicMock
from runtime.diagnostics import (
    DiagnosticAggregator,
    FailureCategory,
    DiagnosticDiagnosis,
)
from runtime.trace_models import DesktopTraceEvent, DesktopTraceEventType, TraceCorrelation


class TestDiagnosticAggregator(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.session_id = "test-session-diag"
        self.mock_session.target_window = None
        self.mock_session.target_hwnd = 0x1234
        self.mock_session.target_process = MagicMock(pid=7777, is_alive=lambda: True)
        self.mock_session.last_outcome = None

        self.mock_supervisor = MagicMock()
        self.mock_insp = MagicMock(is_cloaked=False, is_iconic=False, is_visible=True)
        self.mock_insp.bounds = MagicMock(x=0, y=0, width=1024, height=768)
        self.mock_supervisor.inspect_window.return_value = self.mock_insp
        self.mock_supervisor.is_window_hung.return_value = False
        self.mock_supervisor.find_modal_dialogs.return_value = []
        self.mock_session.native_supervisor = self.mock_supervisor

        self.mock_trace = MagicMock()
        self.mock_trace.get_action_lifecycle.return_value = []
        self.mock_trace.query.return_value = []
        self.mock_session.trace_engine = self.mock_trace

        self.aggregator = DiagnosticAggregator(self.mock_trace)

    def test_process_crash_diagnosis(self):
        """Process crash is classified as non-recoverable with high confidence."""
        mock_proc = MagicMock(pid=8888)
        mock_proc.is_alive.return_value = False
        mock_proc.exit_code = 1
        self.mock_session.target_process = mock_proc

        diag = self.aggregator.diagnose_failure(self.mock_session)
        self.assertEqual(diag.failure_category, FailureCategory.PROCESS_CRASH)
        self.assertFalse(diag.is_recoverable)
        self.assertGreaterEqual(diag.confidence, 0.95)
        self.assertTrue(any(c.claim_type == "OBSERVED_FACT" for c in diag.claims))
        self.assertIn("RESTART_TEST_FIXTURE", diag.recovery_candidates)

    def test_window_cloaked_diagnosis(self):
        """DWM cloaking is classified as WINDOW_CLOAKED and recoverable via REFRESH_OBSERVATION."""
        self.mock_insp.is_cloaked = True

        diag = self.aggregator.diagnose_failure(self.mock_session)
        self.assertEqual(diag.failure_category, FailureCategory.WINDOW_CLOAKED)
        self.assertTrue(diag.is_recoverable)
        self.assertIn("REFRESH_OBSERVATION", diag.recovery_candidates)

    def test_window_minimized_diagnosis(self):
        """Minimized window is classified as WINDOW_MINIMIZED and recoverable via REATTACH."""
        self.mock_insp.is_iconic = True

        diag = self.aggregator.diagnose_failure(self.mock_session)
        self.assertEqual(diag.failure_category, FailureCategory.WINDOW_MINIMIZED)
        self.assertTrue(diag.is_recoverable)
        self.assertIn("REATTACH", diag.recovery_candidates)

    def test_process_hang_diagnosis(self):
        """Hung window UI thread is classified as PROCESS_HANG."""
        self.mock_supervisor.is_window_hung.return_value = True

        diag = self.aggregator.diagnose_failure(self.mock_session)
        self.assertEqual(diag.failure_category, FailureCategory.PROCESS_HANG)
        self.assertIn("WAIT_FOR_PROCESS", diag.recovery_candidates)

    def test_harness_failure_diagnosis(self):
        """Harness telemetry error signal classifies as HARNESS_FAILURE."""
        ev = DesktopTraceEvent(
            event_id="ev-harness-1",
            event_type=DesktopTraceEventType.HARNESS_SIGNAL,
            correlation=TraceCorrelation(session_id="test-session-diag", action_id="act-55"),
            timestamp=200.0,
            status="ERROR",
            details={"signal": "DOCUMENT_SAVE_FAILED: Disk full"}
        )
        self.mock_trace.get_action_lifecycle.return_value = [ev]

        diag = self.aggregator.diagnose_failure(self.mock_session, action_id="act-55")
        self.assertEqual(diag.failure_category, FailureCategory.HARNESS_FAILURE)
        self.assertEqual(diag.affected_component, "application_internal")
        self.assertTrue(any("DOCUMENT_SAVE_FAILED" in c.description for c in diag.claims))

    def test_settlement_timeout_diagnosis(self):
        """Settlement timeout in trace classifies as SETTLEMENT_TIMEOUT."""
        ev = DesktopTraceEvent(
            event_id="ev-settle-1",
            event_type=DesktopTraceEventType.ACTION_SETTLED,
            correlation=TraceCorrelation(session_id="test-session-diag", action_id="act-77"),
            timestamp=300.0,
            status="ERROR",
            details={"error": "Settlement condition timed out after 5.0s"}
        )
        self.mock_trace.get_action_lifecycle.return_value = [ev]

        diag = self.aggregator.diagnose_failure(self.mock_session, action_id="act-77")
        self.assertEqual(diag.failure_category, FailureCategory.SETTLEMENT_TIMEOUT)
        self.assertEqual(diag.affected_component, "settlement_engine")

    def test_state_not_changed_inference(self):
        """Zero state change in last_outcome generates an INFERENCE claim and STATE_NOT_CHANGED."""
        mock_outcome = MagicMock()
        mock_outcome.state_change = "NO_EFFECT"
        mock_outcome.error = None
        self.mock_session.last_outcome = mock_outcome

        diag = self.aggregator.diagnose_failure(self.mock_session)
        self.assertEqual(diag.failure_category, FailureCategory.STATE_NOT_CHANGED)
        self.assertTrue(any(c.claim_type == "INFERENCE" for c in diag.claims))


if __name__ == "__main__":
    unittest.main()
