"""
Tests for Antigravity-DWR Correlation Engine and Explicit Confidence Rules.

Enforces Sections 10, 12, 13 of Milestone 2.1 Prompt 3:
- EXACT: explicit correlation link or direct tool session match
- HIGH: same conversation_id during active action within tight window
- MEDIUM: same session / project within broader window
- LOW: project match with loose temporal proximity
- Never fabricates relationships when evidence is absent
"""

import time
import unittest
from runtime.experience.antigravity.contracts import (
    AgentEventEnvelope,
    AgentEventType,
    CorrelationConfidence,
)
from runtime.experience.antigravity.correlator import AgentDwrCorrelator


class TestAntigravityCorrelation(unittest.TestCase):
    def setUp(self):
        self.correlator = AgentDwrCorrelator(window_size=20, temporal_window_sec=60.0)

    def test_exact_correlation_via_explicit_correlation_id(self):
        """Verifies EXACT confidence when correlation_id matches an active DWR session."""
        self.correlator.set_active_session("dwr_sess_100", project_id="proj_alpha")

        env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            correlation_id="dwr_sess_100",
            tool_name="desktop_click",
        )
        record = self.correlator.correlate_event(env)

        self.assertIsNotNone(record)
        self.assertEqual(record.confidence, CorrelationConfidence.EXACT)
        self.assertEqual(record.dwr_session_id, "dwr_sess_100")
        self.assertEqual(record.correlation_source, "explicit_correlation_id_session_match")

    def test_exact_correlation_via_explicit_action_id_match(self):
        """Verifies EXACT confidence when correlation_id matches a specific DWR action."""
        self.correlator.record_dwr_action(
            action_id="act_click_01",
            session_id="dwr_sess_100",
            mission_id="mis_100",
            timestamp=time.time(),
        )

        env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            correlation_id="act_click_01",
            tool_name="desktop_click",
        )
        record = self.correlator.correlate_event(env)

        self.assertIsNotNone(record)
        self.assertEqual(record.confidence, CorrelationConfidence.EXACT)
        self.assertEqual(record.dwr_session_id, "dwr_sess_100")
        self.assertEqual(record.dwr_action_id, "act_click_01")

    def test_exact_correlation_via_tool_session_argument(self):
        """Verifies EXACT confidence when a DWR MCP tool includes explicit session_id arg."""
        env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            tool_name="desktop_click",
            safe_summary={"action_type": "CLICK", "session_id": "dwr_sess_exact_200"},
        )
        record = self.correlator.correlate_event(env)

        self.assertIsNotNone(record)
        self.assertEqual(record.confidence, CorrelationConfidence.EXACT)
        self.assertEqual(record.dwr_session_id, "dwr_sess_exact_200")

    def test_high_confidence_conversation_match_during_active_action(self):
        """Verifies HIGH confidence when conversation matches and action settles within 5 seconds."""
        now = time.time()
        self.correlator.set_active_session("dwr_sess_300", conversation_id="conv_live_1")
        self.correlator.record_dwr_action(
            action_id="act_type_01",
            session_id="dwr_sess_300",
            mission_id="mis_300",
            timestamp=now - 1.0,  # 1 second ago
        )

        env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            conversation_id="conv_live_1",
            tool_name="run_command",
            timestamp=now,
        )
        record = self.correlator.correlate_event(env)

        self.assertIsNotNone(record)
        self.assertEqual(record.confidence, CorrelationConfidence.HIGH)
        self.assertEqual(record.dwr_session_id, "dwr_sess_300")
        self.assertEqual(record.dwr_action_id, "act_type_01")

    def test_medium_confidence_for_broader_window_session_match(self):
        """Verifies MEDIUM confidence when conversation matches active session outside tight action window."""
        now = time.time()
        self.correlator.set_active_session("dwr_sess_400", conversation_id="conv_live_2")
        # No recent action within 5 seconds

        env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TURN_COMPLETED,
            conversation_id="conv_live_2",
            timestamp=now,
        )
        record = self.correlator.correlate_event(env)

        self.assertIsNotNone(record)
        self.assertEqual(record.confidence, CorrelationConfidence.MEDIUM)
        self.assertEqual(record.dwr_session_id, "dwr_sess_400")
        self.assertIsNone(record.dwr_action_id)

    def test_low_confidence_for_loose_project_match(self):
        """Verifies LOW confidence when only project matches without active conversation link."""
        now = time.time()
        self.correlator.set_active_session("dwr_sess_500", project_id="proj_shared")

        env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            project_id="proj_shared",
            conversation_id="conv_unrelated",
            timestamp=now,
        )
        record = self.correlator.correlate_event(env)

        self.assertIsNotNone(record)
        self.assertEqual(record.confidence, CorrelationConfidence.LOW)
        self.assertEqual(record.dwr_session_id, "dwr_sess_500")

    def test_no_fabricated_correlation_when_parameters_absent(self):
        """Verifies correlator returns None rather than inventing a correlation when no link exists."""
        self.correlator.set_active_session("dwr_sess_600", project_id="proj_closed")

        env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            conversation_id="completely_different_conv",
            project_id="different_project",
            tool_name="view_file",
        )
        record = self.correlator.correlate_event(env)
        self.assertIsNone(record)


if __name__ == "__main__":
    unittest.main()
