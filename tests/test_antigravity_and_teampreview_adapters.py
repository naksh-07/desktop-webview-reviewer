"""
Tests for Antigravity Host Adapter and TeamPreview Presentation Consumer (Phase 18).
Verifies:
1. Antigravity adapter mission submission, execution, and event streaming
2. Outgoing event notification dispatch
3. TeamPreview read-only queries (mission overview, reality snapshot, diagnostics, evidence)
4. TeamPreview Zero-Mutation Law: direct action execution, specialist invocation,
   and scope alteration are strictly blocked with TeamPreviewMutationForbiddenException.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import SpecialistResult, SpecialistResultStatus
from runtime.mission_models import (
    ReviewMission,
    MissionLifecycleState,
    ReviewMissionResult,
)
from runtime.mission_orchestrator import ReviewMissionOrchestrator
from runtime.antigravity_adapter import AntigravityReviewerAdapter
from runtime.teampreview_adapter import TeamPreviewConsumer, TeamPreviewMutationForbiddenException


class TestAntigravityAndTeamPreviewAdapters(unittest.TestCase):
    def setUp(self):
        self.session_id = "sess_adapter_test_01"
        self.session_state = MagicMock()
        self.session_state.session_id = self.session_id
        self.session_state.is_closed = False
        self.session_state.current_epoch = 1
        self.session_state.trace_engine = None

        self.valid_payload = {
            "session_id": self.session_id,
            "objective": "Verify math practice card renders formula and submit button answers card.",
            "declared_scope": ["CardViewport", "AnswerButtons"],
            "allowed_surfaces": ["MainWindow", "CardViewport", "AnswerButtons"],
            "prohibited_surfaces": ["SettingsDialog"],
            "acceptance_criteria": [
                "Formula is rendered in CardViewport",
                "Answer button responds to submission",
            ],
            "max_duration_sec": 60.0,
            "max_actions": 10,
            "max_delegations": 6,
        }

    def test_antigravity_adapter_submission_and_event_streaming(self):
        """Proves Antigravity adapter submits missions and streams progress events."""
        mock_orchestrator = MagicMock()
        adapter = AntigravityReviewerAdapter(orchestrator=mock_orchestrator)

        events_received = []

        def on_event(event_type: str, payload: dict):
            events_received.append((event_type, payload))

        adapter.add_listener(on_event)

        # 1. Submit mission
        mock_admission_res = MagicMock(is_admitted=True, rejections=[])
        mock_orchestrator.admit.return_value = mock_admission_res
        admission = adapter.submit_mission(self.valid_payload, session_state=self.session_state)

        self.assertTrue(admission.is_admitted)
        self.assertEqual(len(events_received), 1)
        self.assertEqual(events_received[0][0], "mission_admission")

        # 2. Execute mission
        mock_mission = ReviewMission.from_dict(self.valid_payload)
        mock_orchestrator.get_mission.return_value = mock_mission

        mock_mission_result = ReviewMissionResult(
            mission_id=mock_mission.mission_id,
            session_id=self.session_id,
            final_status=MissionLifecycleState.COMPLETED,
            technical_verdict="PASS",
            completed_steps=[{"step": 1}],
            evidence_refs=["manifest_01.json"],
        )
        mock_orchestrator.run_mission = AsyncMock(return_value=mock_mission_result)

        result = asyncio.run(adapter.execute_mission(mock_mission.mission_id, session_state=self.session_state))

        self.assertEqual(result.technical_verdict, "PASS")
        event_types = [e[0] for e in events_received]
        self.assertIn("mission_started", event_types)
        self.assertIn("mission_completed", event_types)

    def test_teampreview_read_only_queries(self):
        """Proves TeamPreview consumer provides read-only inspection of mission, reality, and evidence."""
        mock_orchestrator = MagicMock()
        mock_mission = ReviewMission.from_dict(self.valid_payload)
        mock_orchestrator.get_mission.return_value = mock_mission

        mock_result = ReviewMissionResult(
            mission_id=mock_mission.mission_id,
            session_id=self.session_id,
            final_status=MissionLifecycleState.COMPLETED,
            technical_verdict="PASS",
            evidence_refs=["evidence_pkg_001.zip"],
            budget_usage={"actions": 4, "delegations": 3},
        )
        mock_orchestrator.get_mission_result.return_value = mock_result

        consumer = TeamPreviewConsumer(orchestrator=mock_orchestrator)

        # Overview query
        overview = consumer.get_mission_overview(mock_mission.mission_id)
        self.assertIsNotNone(overview)
        self.assertEqual(overview["mission_id"], mock_mission.mission_id)
        self.assertEqual(overview["final_verdict"], "PASS")

        # Evidence catalog query
        evidence = consumer.get_evidence_catalog(mock_mission.mission_id)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["evidence_ref"], "evidence_pkg_001.zip")

        # Reality snapshot query
        reality = consumer.get_reality_snapshot(self.session_id, session_state=self.session_state)
        self.assertEqual(reality["session_id"], self.session_id)

    def test_teampreview_zero_mutation_law_enforcement(self):
        """Proves TeamPreview strictly prohibits action execution, specialist invocation, or scope mutation."""
        mock_orchestrator = MagicMock()
        consumer = TeamPreviewConsumer(orchestrator=mock_orchestrator)

        # Direct action execution attempt
        with self.assertRaises(TeamPreviewMutationForbiddenException):
            consumer.execute_action(ref="w0e1", action="click")

        # Direct specialist invocation attempt
        with self.assertRaises(TeamPreviewMutationForbiddenException):
            consumer.invoke_specialist(role="TESTER")

        # Scope mutation attempt
        with self.assertRaises(TeamPreviewMutationForbiddenException):
            consumer.alter_mission_scope(new_scope=["AdminPanel"])

        # Admission bypass attempt
        with self.assertRaises(TeamPreviewMutationForbiddenException):
            consumer.bypass_admission(mission_id="msn_bypass")


if __name__ == "__main__":
    unittest.main()
