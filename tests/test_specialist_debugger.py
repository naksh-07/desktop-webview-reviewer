"""
Unit tests for DebuggerSpecialist (Phase 15 - Prompt P4).
"""
import asyncio
import unittest
from unittest.mock import MagicMock
from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import SpecialistDelegation, DelegationScope, SpecialistResultStatus
from runtime.specialists.debugger import DebuggerSpecialist
from runtime.trace_models import DesktopTraceEvent, DesktopTraceEventType, TraceCorrelation


class TestDebuggerSpecialist(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.session_id = "test-session-debug"
        self.mock_session.current_epoch = 1
        self.mock_session.target_window = None
        self.mock_session.target_hwnd = 0x54321
        self.mock_session.last_outcome = None

        # Mock target process alive
        self.mock_proc = MagicMock()
        self.mock_proc.pid = 4321
        self.mock_proc.is_alive.return_value = True
        self.mock_session.target_process = self.mock_proc

        # Mock native supervisor
        self.mock_supervisor = MagicMock()
        self.mock_insp = MagicMock()
        self.mock_insp.is_cloaked = False
        self.mock_insp.is_iconic = False
        self.mock_supervisor.inspect_window.return_value = self.mock_insp
        self.mock_supervisor.is_window_hung.return_value = False
        self.mock_supervisor.find_modal_dialogs.return_value = []
        self.mock_session.native_supervisor = self.mock_supervisor

        # Mock trace engine
        self.mock_trace = MagicMock()
        self.mock_session.trace_engine = self.mock_trace

    def test_debugger_correlates_console_exception(self):
        """Debugger correlates Chromium console error to identify CONSOLE_EXCEPTION root cause."""
        # Create a console error event
        ev = DesktopTraceEvent(
            event_id="ev-console-1",
            event_type=DesktopTraceEventType.CONSOLE_EVENT,
            correlation=TraceCorrelation(session_id="test-session-debug", action_id="act-99"),
            timestamp=100.0,
            status="ERROR",
            details={"message": "Uncaught TypeError: Cannot read properties of undefined (reading 'submit')"}
        )
        self.mock_trace.get_action_lifecycle.return_value = [ev]

        delegation = SpecialistDelegation(
            role=SpecialistRole.DEBUGGER,
            task="Diagnose why act-99 failed",
            scope=DelegationScope(session_id="test-session-debug"),
            permitted_tools={"desktop_get_trace", "desktop_get_window_forensics"},
            parent_action_id="act-99",
            parameters={"action_id": "act-99"},
            timeout_sec=5.0
        )

        specialist = DebuggerSpecialist(delegation=delegation, session_state=self.mock_session)
        result = asyncio.run(specialist.run())

        self.assertEqual(result.status, SpecialistResultStatus.SUCCESS)
        self.assertEqual(result.observations["root_cause"], "CONSOLE_EXCEPTION")
        self.assertEqual(result.observations["affected_component"], "webview_javascript")
        self.assertTrue(any("Uncaught TypeError" in f for f in result.observations["observed_facts"]))
        self.assertIn("ev-console-1", result.trace_refs)

    def test_debugger_detects_process_crash(self):
        """Debugger detects process crash and recommends RESTART_TEST_FIXTURE."""
        self.mock_proc.is_alive.return_value = False
        self.mock_proc.exit_code = 3221225477  # 0xC0000005 Access Violation
        self.mock_trace.get_action_lifecycle.return_value = []

        delegation = SpecialistDelegation(
            role=SpecialistRole.DEBUGGER,
            task="Diagnose sudden action timeout",
            scope=DelegationScope(session_id="test-session-debug"),
            permitted_tools={"desktop_get_trace"},
            timeout_sec=5.0
        )

        specialist = DebuggerSpecialist(delegation=delegation, session_state=self.mock_session)
        result = asyncio.run(specialist.run())

        self.assertEqual(result.status, SpecialistResultStatus.SUCCESS)
        self.assertEqual(result.observations["root_cause"], "PROCESS_CRASH")
        self.assertIn("RESTART_TEST_FIXTURE", result.observations["recovery_candidates"])
        self.assertTrue(any("PID 4321 has terminated" in f for f in result.observations["observed_facts"]))

    def test_debugger_detects_ui_thread_hang(self):
        """Debugger detects window UI thread hang via supervisor."""
        self.mock_supervisor.is_window_hung.return_value = True
        self.mock_trace.get_action_lifecycle.return_value = []

        delegation = SpecialistDelegation(
            role=SpecialistRole.DEBUGGER,
            task="Diagnose unresponsiveness",
            scope=DelegationScope(session_id="test-session-debug"),
            permitted_tools={"desktop_get_window_forensics"},
            timeout_sec=5.0
        )

        specialist = DebuggerSpecialist(delegation=delegation, session_state=self.mock_session)
        result = asyncio.run(specialist.run())

        self.assertEqual(result.status, SpecialistResultStatus.SUCCESS)
        self.assertEqual(result.observations["root_cause"], "PROCESS_HANG")
        self.assertEqual(result.observations["affected_component"], "ui_message_pump")
        self.assertIn("WAIT_FOR_PROCESS", result.observations["recovery_candidates"])


if __name__ == "__main__":
    unittest.main()
