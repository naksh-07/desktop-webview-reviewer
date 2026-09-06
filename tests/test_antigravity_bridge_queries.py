"""
Tests for Antigravity-DWR Historical Correlation Intelligence Queries.

Enforces Sections 1, 16, and 31 of Milestone 2.1 Prompt 3:
- Which agent/tool activity preceded a review?
- Which DWR session belonged to which agent session?
- Which agent tool call resulted in a DWR action?
- How often did a particular agent workflow require recovery?
- Which agent corrections followed reviewer failures?
- Which agent/tool patterns correlate with successful or unsuccessful review outcomes?
"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.models import (
    NormalizedFailureRecord,
    OutcomeRecord,
    RecoveryExperienceRecord,
    SessionExperienceRecord,
)
from runtime.experience.store import ExperienceStore
from runtime.experience.antigravity.contracts import (
    CorrelationConfidence,
    UserCorrectionType,
)
from runtime.experience.antigravity.models import (
    AgentCorrectionRecord,
    AgentDwrCorrelationRecord,
    AgentSessionRecord,
    AgentToolCallRecord,
    AgentTurnRecord,
)


class TestAntigravityHistoricalQueries(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="agy_queries_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=False)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)

        self._populate_fixtures()

    def _populate_fixtures(self):
        """Populates rich fixtures linking agent activity with DWR reality."""
        now = time.time()

        # DWR Sessions: 1 Successful (PASS), 1 Failed (FAIL)
        self.store.record_session(
            SessionExperienceRecord(
                session_id="dwr_sess_pass",
                created_at="2026-09-06T12:00:00Z",
                status="COMPLETED",
            )
        )
        self.store.record_outcome(
            OutcomeRecord(
                outcome_id="out_pass",
                session_id="dwr_sess_pass",
                verdict="PASS",
                confidence=1.0,
            )
        )

        self.store.record_session(
            SessionExperienceRecord(
                session_id="dwr_sess_fail",
                created_at="2026-09-06T12:05:00Z",
                status="COMPLETED",
            )
        )
        self.store.record_outcome(
            OutcomeRecord(
                outcome_id="out_fail",
                session_id="dwr_sess_fail",
                verdict="FAIL",
                confidence=1.0,
                error_category="TARGET_NOT_FOUND",
            )
        )

        # Recorded failure on dwr_sess_fail
        self.store.record_failure(
            NormalizedFailureRecord(
                failure_id="fail_001",
                session_id="dwr_sess_fail",
                category="ELEMENT_OBSCURED",
                original_classification="TARGET_NOT_FOUND",
                signature="WINDOW_MINIMIZED#ELEMENT_OBSCURED",
                action_id="act_fail_01",
            )
        )

        # Recovery attempt on dwr_sess_fail
        self.store.record_recovery_attempt(
            RecoveryExperienceRecord(
                recovery_id="rec_001",
                session_id="dwr_sess_fail",
                failure_category="ELEMENT_OBSCURED",
                recovery_action="RESTORE_AND_FOCUS_WINDOW",
                result="SUCCESS",
                duration_ms=250.0,
            )
        )

        # Agent Session & Turns
        self.store.record_agent_session(
            AgentSessionRecord(
                agent_session_id="asess_alpha",
                conversation_id="conv_101",
                agent_id="lead_orchestrator",
            )
        )

        # Agent Tool Calls:
        # Tool 1: desktop_launch (for PASS session)
        self.store.record_agent_tool_call(
            AgentToolCallRecord(
                tool_call_id="atool_launch",
                agent_session_id="asess_alpha",
                conversation_id="conv_101",
                tool_name="desktop_launch",
                tool_category="mcp",
                success=True,
                timestamp=now - 50,
                safe_summary={"action_type": "LAUNCH", "executable_name": "calc.exe"},
            )
        )
        self.store.record_agent_correlation(
            AgentDwrCorrelationRecord(
                correlation_id="corr_01",
                confidence=CorrelationConfidence.EXACT,
                agent_session_id="asess_alpha",
                conversation_id="conv_101",
                tool_call_id="atool_launch",
                dwr_session_id="dwr_sess_pass",
                dwr_action_id="act_launch_01",
            )
        )

        # Tool 2: desktop_click (for FAIL session)
        self.store.record_agent_tool_call(
            AgentToolCallRecord(
                tool_call_id="atool_click_fail",
                agent_session_id="asess_alpha",
                conversation_id="conv_101",
                tool_name="desktop_click",
                tool_category="mcp",
                success=False,
                error_class="TARGET_NOT_FOUND",
                timestamp=now - 20,
                safe_summary={"action_type": "CLICK", "target_role": "button"},
            )
        )
        self.store.record_agent_correlation(
            AgentDwrCorrelationRecord(
                correlation_id="corr_02",
                confidence=CorrelationConfidence.EXACT,
                agent_session_id="asess_alpha",
                conversation_id="conv_101",
                tool_call_id="atool_click_fail",
                dwr_session_id="dwr_sess_fail",
                dwr_action_id="act_fail_01",
            )
        )

        # User correction associated with the failure session
        self.store.record_agent_correction(
            AgentCorrectionRecord(
                correction_id="acorr_001",
                correction_type=UserCorrectionType.USER_CHANGED_TARGET.value,
                agent_session_id="asess_alpha",
                conversation_id="conv_101",
                related_dwr_session_id="dwr_sess_fail",
                related_action_id="act_fail_01",
                classification_details={"adjusted_target": "MainFrameButton"},
            )
        )

    def test_query_agent_tool_calls_for_session(self):
        """Verifies querying agent tool calls associated with a given DWR session."""
        pass_tools = self.store.get_agent_tool_calls_for_session("dwr_sess_pass")
        self.assertEqual(len(pass_tools), 1)
        self.assertEqual(pass_tools[0].tool_name, "desktop_launch")

        fail_tools = self.store.get_agent_tool_calls_for_session("dwr_sess_fail")
        self.assertEqual(len(fail_tools), 1)
        self.assertEqual(fail_tools[0].tool_name, "desktop_click")
        self.assertFalse(fail_tools[0].success)

    def test_query_agent_activity_for_dwr_action(self):
        """Verifies querying the agent tool call associated with a specific DWR action."""
        action_tools = self.store.get_agent_activity_for_dwr_action("act_fail_01")
        self.assertEqual(len(action_tools), 1)
        self.assertEqual(action_tools[0].tool_call_id, "atool_click_fail")

    def test_query_agent_tool_calls_by_outcome(self):
        """Verifies querying tool calls associated with successful (PASS) vs failed (FAIL) reviews."""
        pass_results = self.store.get_agent_tool_calls_by_outcome("PASS")
        self.assertEqual(len(pass_results), 1)
        self.assertEqual(pass_results[0]["tool_name"], "desktop_launch")
        self.assertEqual(pass_results[0]["review_verdict"], "PASS")

        fail_results = self.store.get_agent_tool_calls_by_outcome("FAIL")
        self.assertEqual(len(fail_results), 1)
        self.assertEqual(fail_results[0]["tool_name"], "desktop_click")
        self.assertEqual(fail_results[0]["review_verdict"], "FAIL")

    def test_query_recovery_frequency_by_agent_tool_category(self):
        """Verifies computing recovery attempt frequency grouped by preceding agent tool category."""
        recovery_stats = self.store.get_recovery_frequency_by_agent_tool_category()
        self.assertTrue(len(recovery_stats) >= 1)
        item = recovery_stats[0]
        self.assertEqual(item["tool_category"], "mcp")
        self.assertEqual(item["recovery_attempts_count"], 1)

    def test_query_user_corrections_for_failures(self):
        """Verifies querying user corrections associated with failed review sessions."""
        corrections = self.store.get_user_corrections_for_failures()
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0].correction_type, UserCorrectionType.USER_CHANGED_TARGET.value)
        self.assertEqual(corrections[0].related_dwr_session_id, "dwr_sess_fail")

    def test_agent_experience_summary(self):
        """Verifies summary statistics of agent experience and correlations."""
        summary = self.store.get_agent_experience_summary()
        self.assertEqual(summary["agent_sessions"], 1)
        self.assertEqual(summary["agent_tool_calls"], 2)
        self.assertEqual(summary["correlations"], 2)
        self.assertEqual(summary["corrections"], 1)
        self.assertIn("mcp", summary["tool_categories"])


if __name__ == "__main__":
    unittest.main()
