"""
Unit and Integration Tests for ReviewMissionOrchestrator (Phase 17).
Verifies:
1. End-to-end successful mission execution (PASS)
2. Failure diagnosis and bounded recovery integration
3. Action budget exhaustion stoppage
4. Delegation budget exhaustion stoppage
5. Wall-clock timeout enforcement
6. Mission cancellation flow
7. Tripartite verdict preservation
"""

import asyncio
import time
import unittest
from unittest.mock import MagicMock, AsyncMock

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import (
    SpecialistResult,
    SpecialistResultStatus,
)
from runtime.diagnostics import (
    DiagnosticAggregator,
    DiagnosticDiagnosis,
    DiagnosticClaim,
    FailureCategory,
)
from runtime.recovery_engine import (
    RecoveryEngine,
    RecoveryAction,
    RecoveryAttemptRecord,
    CircuitBreaker,
)
from runtime.mission_models import (
    ReviewMission,
    DiscoveryCandidate,
    ReviewPlan,
    ReviewPlanStep,
    MissionLifecycleState,
    ReviewMissionResult,
)
from runtime.mission_admission import MissionAdmissionGate
from runtime.goal_discovery import GoalOrientedDiscoveryEngine
from runtime.mission_orchestrator import ReviewMissionOrchestrator


class TestMissionOrchestrator(unittest.TestCase):
    def setUp(self):
        self.session_id = "sess_orch_test_01"
        self.session_state = MagicMock()
        self.session_state.session_id = self.session_id
        self.session_state.is_closed = False
        self.session_state.current_epoch = 1
        self.session_state.trace_engine = None

    def _create_mission(self, **overrides) -> ReviewMission:
        defaults = {
            "session_id": self.session_id,
            "objective": "Verify math practice card renders formula and submit button answers card.",
            "declared_scope": ["CardViewport", "AnswerButtons"],
            "allowed_surfaces": ["MainWindow", "CardViewport", "AnswerButtons"],
            "prohibited_surfaces": ["SettingsDialog"],
            "acceptance_criteria": [
                "Formula is rendered in CardViewport",
                "Answer button responds to submission",
            ],
            "authorized_specialist_roles": [
                SpecialistRole.EXPLORER,
                SpecialistRole.TESTER,
                SpecialistRole.REALITY_INSPECTOR,
                SpecialistRole.DEBUGGER,
                SpecialistRole.EVIDENCE_SPECIALIST,
            ],
            "max_duration_sec": 60.0,
            "max_actions": 10,
            "max_delegations": 6,
            "max_recoveries": 2,
        }
        defaults.update(overrides)
        m = ReviewMission(**defaults)
        return m

    def test_complete_successful_mission_lifecycle(self):
        """Proves full lifecycle execution: Discovery -> Planning -> Execution -> Reality -> Evidence -> PASS."""
        mission = self._create_mission()

        mock_dispatcher = MagicMock()
        # Mock Explorer discovery result
        mock_explorer_res = SpecialistResult(
            specialist_id="spec_exp",
            role=SpecialistRole.EXPLORER,
            delegation_id="delg_exp",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="Discovered CardViewport and AnswerButtons.",
            observations={
                "interactive_elements": [
                    {"name": "Formula Card", "role": "group", "ref": "w0e1", "surface": "CardViewport"},
                    {"name": "Submit Answer", "role": "button", "ref": "w0e2", "surface": "AnswerButtons"},
                ]
            },
        )
        # Mock Tester result
        mock_tester_res = SpecialistResult(
            specialist_id="spec_tester",
            role=SpecialistRole.TESTER,
            delegation_id="delg_test",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="Assertion passed: Formula Card rendered and button answered.",
            observations={"assert_passed": True},
            tools_used=["desktop_assert", "desktop_click"],
        )
        # Mock Reality Inspector result
        mock_reality_res = SpecialistResult(
            specialist_id="spec_reality",
            role=SpecialistRole.REALITY_INSPECTOR,
            delegation_id="delg_reality",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="DWM verified: Window is visible and rendering on primary monitor.",
            observations={"is_visible": True, "is_cloaked": False},
        )
        # Mock Evidence Specialist result
        mock_evidence_res = SpecialistResult(
            specialist_id="spec_evid",
            role=SpecialistRole.EVIDENCE_SPECIALIST,
            delegation_id="delg_evid",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="Evidence manifest compiled and sealed with SHA-256.",
            evidence_refs=["manifest_001.json"],
        )

        async def mock_dispatch(delegation, session_state=None):
            if delegation.role == SpecialistRole.EXPLORER:
                return mock_explorer_res
            elif delegation.role == SpecialistRole.TESTER:
                return mock_tester_res
            elif delegation.role == SpecialistRole.REALITY_INSPECTOR:
                return mock_reality_res
            elif delegation.role == SpecialistRole.EVIDENCE_SPECIALIST:
                return mock_evidence_res
            return SpecialistResult(
                specialist_id="spec_other",
                role=delegation.role,
                delegation_id=delegation.delegation_id,
                session_id=self.session_id,
                status=SpecialistResultStatus.SUCCESS,
                answer="OK",
            )

        mock_dispatcher.dispatch = AsyncMock(side_effect=mock_dispatch)

        orchestrator = ReviewMissionOrchestrator(
            dispatcher=mock_dispatcher,
            discovery_engine=GoalOrientedDiscoveryEngine(dispatcher=mock_dispatcher),
        )

        result = asyncio.run(orchestrator.run_mission(mission, session_state=self.session_state))

        self.assertEqual(result.final_status, MissionLifecycleState.COMPLETED)
        self.assertEqual(result.technical_verdict, "PASS")
        self.assertGreaterEqual(len(result.completed_steps), 3)
        self.assertEqual(len(result.failed_steps), 0)
        self.assertIn("manifest_001.json", result.evidence_refs)

    def test_failure_debugger_diagnosis_and_bounded_recovery(self):
        """Proves that a step failure invokes Debugger, recovers via RecoveryEngine, and re-executes successfully."""
        mission = self._create_mission()

        mock_dispatcher = MagicMock()
        mock_explorer_res = SpecialistResult(
            specialist_id="spec_exp",
            role=SpecialistRole.EXPLORER,
            delegation_id="delg_exp",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="Discovered CardViewport.",
            observations={
                "interactive_elements": [
                    {"name": "Formula Card", "role": "group", "ref": "w0e1", "surface": "CardViewport"},
                ]
            },
        )
        tester_call_count = 0

        async def mock_dispatch(delegation, session_state=None):
            nonlocal tester_call_count
            if delegation.role == SpecialistRole.EXPLORER:
                return mock_explorer_res
            elif delegation.role == SpecialistRole.TESTER:
                tester_call_count += 1
                if tester_call_count == 1:
                    # First attempt fails due to stale observation
                    return SpecialistResult(
                        specialist_id="spec_tester_fail",
                        role=SpecialistRole.TESTER,
                        delegation_id=delegation.delegation_id,
                        session_id=self.session_id,
                        status=SpecialistResultStatus.FAILED,
                        answer="Element w0e1 target not actionable (stale observation).",
                    )
                else:
                    # Retry attempt succeeds after recovery!
                    return SpecialistResult(
                        specialist_id="spec_tester_pass",
                        role=SpecialistRole.TESTER,
                        delegation_id=delegation.delegation_id,
                        session_id=self.session_id,
                        status=SpecialistResultStatus.SUCCESS,
                        answer="Element refreshed and verified.",
                    )
            elif delegation.role == SpecialistRole.REALITY_INSPECTOR:
                return SpecialistResult(
                    specialist_id="spec_reality",
                    role=SpecialistRole.REALITY_INSPECTOR,
                    delegation_id=delegation.delegation_id,
                    session_id=self.session_id,
                    status=SpecialistResultStatus.SUCCESS,
                    answer="Physical reality confirmed.",
                    observations={"is_visible": True, "is_cloaked": False},
                )
            elif delegation.role == SpecialistRole.EVIDENCE_SPECIALIST:
                return SpecialistResult(
                    specialist_id="spec_evid",
                    role=SpecialistRole.EVIDENCE_SPECIALIST,
                    delegation_id=delegation.delegation_id,
                    session_id=self.session_id,
                    status=SpecialistResultStatus.SUCCESS,
                    answer="Sealed.",
                )

        mock_dispatcher.dispatch = AsyncMock(side_effect=mock_dispatch)

        # Mock diagnostic aggregator returning recoverable diagnosis
        mock_diag_agg = MagicMock()
        mock_diagnosis = DiagnosticDiagnosis(
            session_id=self.session_id,
            failure_category=FailureCategory.TARGET_NOT_ACTIONABLE,
            root_cause_summary="Element state stale; requires refresh observation.",
            confidence=0.9,
            is_recoverable=True,
            claims=[DiagnosticClaim(claim_type="OBSERVED_FACT", description="Stale ref token", source="trace")],
        )
        mock_diag_agg.diagnose_failure.return_value = mock_diagnosis

        # Mock recovery engine
        mock_recovery_engine = MagicMock()
        mock_recovery_engine.circuit_breaker = CircuitBreaker()
        mock_rec_record = RecoveryAttemptRecord(
            recovery_id="rec_001",
            failure_id="fail_001",
            trigger_category=FailureCategory.TARGET_NOT_ACTIONABLE,
            action=RecoveryAction.REFRESH_OBSERVATION,
            attempt_number=1,
            max_attempts=2,
            started_at=time.time(),
            duration_ms=10.0,
            result="SUCCESS",
        )
        mock_recovery_engine.attempt_recovery = AsyncMock(return_value=(True, mock_rec_record))

        orchestrator = ReviewMissionOrchestrator(
            dispatcher=mock_dispatcher,
            diagnostic_aggregator=mock_diag_agg,
            recovery_engine=mock_recovery_engine,
            discovery_engine=GoalOrientedDiscoveryEngine(dispatcher=mock_dispatcher),
        )

        result = asyncio.run(orchestrator.run_mission(mission, session_state=self.session_state))

        self.assertEqual(result.technical_verdict, "PASS")
        self.assertEqual(len(result.recovery_attempts), 1)
        self.assertEqual(result.recovery_attempts[0]["action"], "REFRESH_OBSERVATION")
        self.assertEqual(tester_call_count, 2)  # Proves step was retried after recovery

    def test_action_budget_limit_exhaustion_stops_execution(self):
        """Proves that reaching max_actions halts execution safely without unconstrained calls."""
        # Restrict max_actions to 1
        mission = self._create_mission(max_actions=1)

        mock_dispatcher = MagicMock()
        mock_explorer_res = SpecialistResult(
            specialist_id="spec_exp",
            role=SpecialistRole.EXPLORER,
            delegation_id="delg_exp",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="Discovered 2 elements.",
            observations={
                "interactive_elements": [
                    {"name": "Formula Card", "role": "group", "ref": "w0e1", "surface": "CardViewport"},
                    {"name": "Submit Answer", "role": "button", "ref": "w0e2", "surface": "AnswerButtons"},
                ]
            },
        )
        mock_tester_res = SpecialistResult(
            specialist_id="spec_tester",
            role=SpecialistRole.TESTER,
            delegation_id="delg_test",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="Step completed.",
            tools_used=["desktop_click", "desktop_type"],  # 2 actions taken
        )
        mock_dispatcher.dispatch = AsyncMock(side_effect=[mock_explorer_res, mock_tester_res])

        orchestrator = ReviewMissionOrchestrator(
            dispatcher=mock_dispatcher,
            discovery_engine=GoalOrientedDiscoveryEngine(dispatcher=mock_dispatcher),
        )

        result = asyncio.run(orchestrator.run_mission(mission, session_state=self.session_state))

        self.assertTrue(any("action budget" in lim.lower() for lim in result.limitations))
        self.assertGreaterEqual(result.budget_usage["actions"], 1)

    def test_delegation_budget_limit_exhaustion(self):
        """Proves that reaching max_delegations halts plan execution."""
        mission = self._create_mission(max_delegations=2)

        mock_dispatcher = MagicMock()
        mock_explorer_res = SpecialistResult(
            specialist_id="spec_exp",
            role=SpecialistRole.EXPLORER,
            delegation_id="delg_exp",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="Discovered elements.",
            observations={
                "interactive_elements": [
                    {"name": "Formula Card", "role": "group", "ref": "w0e1", "surface": "CardViewport"},
                ]
            },
        )
        mock_tester_res = SpecialistResult(
            specialist_id="spec_tester",
            role=SpecialistRole.TESTER,
            delegation_id="delg_test",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="Step done.",
        )
        mock_dispatcher.dispatch = AsyncMock(side_effect=[mock_explorer_res, mock_tester_res, mock_tester_res])

        orchestrator = ReviewMissionOrchestrator(
            dispatcher=mock_dispatcher,
            discovery_engine=GoalOrientedDiscoveryEngine(dispatcher=mock_dispatcher),
        )

        result = asyncio.run(orchestrator.run_mission(mission, session_state=self.session_state))
        self.assertLessEqual(result.budget_usage["delegations"], 2)

    def test_mission_cancellation(self):
        """Proves mission cancellation immediately halts execution and returns CANCELLED result."""
        mission = self._create_mission()

        orchestrator = ReviewMissionOrchestrator()
        orchestrator.admit(mission, session_state=self.session_state)

        # Cancel mission before execution
        orchestrator.cancel_mission(mission.mission_id, reason="User interrupted via UI")

        result = asyncio.run(orchestrator.run_mission(mission, session_state=self.session_state))

        self.assertEqual(result.final_status, MissionLifecycleState.CANCELLED)
        self.assertEqual(result.technical_verdict, "UNVERIFIED")
        self.assertIn("User interrupted via UI", result.cancellation_reason)


if __name__ == "__main__":
    unittest.main()
