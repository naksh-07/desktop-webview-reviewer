"""
Tests for Canonical Review Mission Contracts & Admission Gate (Phase 17).
Verifies:
1. Valid mission admission and authority sealing
2. 13-point admission gate validation
3. Rejection of unspecified / vague scope (no crawling)
4. Authority immutability (mutations after admission rejected)
5. Lifecycle state transitions & transition matrix enforcement
6. Conflicting surface detection
"""

import time
import unittest
from unittest.mock import MagicMock

from runtime.specialist_contracts import SpecialistRole
from runtime.mission_models import (
    ReviewMission,
    MissionLifecycleState,
    MissionAuthorityMutatedException,
    InvalidMissionTransitionException,
    AdmissionResult,
)
from runtime.mission_admission import MissionAdmissionGate


class TestMissionContractsAndAdmission(unittest.TestCase):
    def setUp(self):
        self.session_id = "sess_admission_test_01"
        self.valid_mission_data = {
            "session_id": self.session_id,
            "objective": "Verify math practice card renders and updates review queue upon answer submission.",
            "declared_scope": ["MathsReviewDeck", "CardViewport", "AnswerControls"],
            "allowed_surfaces": ["MainReviewWindow", "AnswerButtons"],
            "prohibited_surfaces": ["SettingsDialog", "AccountProfile"],
            "acceptance_criteria": [
                "Math formula is visually rendered in card viewport",
                "Answer submit button transitions card to settled state",
            ],
            "authorized_specialist_roles": [
                SpecialistRole.EXPLORER,
                SpecialistRole.TESTER,
                SpecialistRole.REALITY_INSPECTOR,
                SpecialistRole.DEBUGGER,
                SpecialistRole.EVIDENCE_SPECIALIST,
            ],
            "max_duration_sec": 120.0,
            "max_actions": 15,
            "max_delegations": 8,
            "max_recoveries": 2,
            "orchestrator_identity": "antigravity",
        }

    def test_valid_mission_admission_and_authority_sealing(self):
        """Proves a fully specified mission is admitted and sealed."""
        mission = ReviewMission(**self.valid_mission_data)
        self.assertEqual(mission.lifecycle_status, MissionLifecycleState.CREATED)
        self.assertFalse(mission.is_admitted)

        gate = MissionAdmissionGate()
        result = gate.validate(mission)

        self.assertTrue(result.is_admitted)
        self.assertEqual(result.rejections, [])
        self.assertEqual(mission.lifecycle_status, MissionLifecycleState.ADMITTED)
        self.assertTrue(mission.is_admitted)
        self.assertIsNotNone(mission._authority_digest)

        # Verify authority integrity holds
        self.assertTrue(mission.verify_authority_integrity())

    def test_authority_immutability_enforcement(self):
        """Proves that mutating mission authority after admission triggers MissionAuthorityMutatedException."""
        mission = ReviewMission(**self.valid_mission_data)
        gate = MissionAdmissionGate()
        result = gate.validate(mission)
        self.assertTrue(result.is_admitted)

        # An unauthorized attempt to expand scope or alter objective
        mission.declared_scope.append("AdminPanel")  # Scope creep attempt!

        with self.assertRaises(MissionAuthorityMutatedException):
            mission.verify_authority_integrity()

        with self.assertRaises(MissionAuthorityMutatedException):
            mission.transition_to(MissionLifecycleState.DISCOVERING)

    def test_rejection_of_unspecified_or_vague_scope(self):
        """Proves the gate rejects 'review this app' / 'unspecified' without crawling."""
        vague_scopes = [
            [],
            ["*"],
            ["all"],
            ["unspecified"],
            ["entire app"],
        ]
        gate = MissionAdmissionGate()

        for scope in vague_scopes:
            data = dict(self.valid_mission_data)
            data["declared_scope"] = scope
            mission = ReviewMission(**data)
            result = gate.validate(mission)
            self.assertFalse(result.is_admitted)
            self.assertEqual(mission.lifecycle_status, MissionLifecycleState.REJECTED)
            self.assertTrue(any("Point 4" in r for r in result.rejections))

    def test_rejection_of_generic_or_empty_objective(self):
        """Proves the gate rejects generic objectives like 'test' or empty strings."""
        gate = MissionAdmissionGate()
        for bad_obj in ["", "   ", "test", "review", "check"]:
            data = dict(self.valid_mission_data)
            data["objective"] = bad_obj
            mission = ReviewMission(**data)
            result = gate.validate(mission)
            self.assertFalse(result.is_admitted)
            self.assertTrue(any("Point 3" in r for r in result.rejections))

    def test_rejection_of_missing_acceptance_criteria(self):
        """Proves the gate rejects missions lacking explicit criteria."""
        data = dict(self.valid_mission_data)
        data["acceptance_criteria"] = []
        mission = ReviewMission(**data)
        gate = MissionAdmissionGate()
        result = gate.validate(mission)
        self.assertFalse(result.is_admitted)
        self.assertTrue(any("Point 5" in r for r in result.rejections))

    def test_rejection_of_conflicting_surfaces(self):
        """Proves the gate rejects missions where allowed and prohibited surfaces intersect."""
        data = dict(self.valid_mission_data)
        data["allowed_surfaces"] = ["MainDeck", "SettingsDialog"]
        data["prohibited_surfaces"] = ["settingsdialog", "AccountProfile"]
        mission = ReviewMission(**data)
        gate = MissionAdmissionGate()
        result = gate.validate(mission)
        self.assertFalse(result.is_admitted)
        self.assertTrue(any("Point 12" in r for r in result.rejections))

    def test_rejection_of_excessive_or_nonpositive_budgets(self):
        """Proves the gate enforces hard budget limits."""
        gate = MissionAdmissionGate()

        # Nonpositive action budget
        data = dict(self.valid_mission_data)
        data["max_actions"] = 0
        mission = ReviewMission(**data)
        result = gate.validate(mission)
        self.assertFalse(result.is_admitted)
        self.assertTrue(any("Point 8" in r for r in result.rejections))

        # Excessive action budget
        data = dict(self.valid_mission_data)
        data["max_actions"] = 999
        mission = ReviewMission(**data)
        result = gate.validate(mission)
        self.assertFalse(result.is_admitted)
        self.assertTrue(any("Point 8" in r for r in result.rejections))

    def test_rejection_of_unauthorized_orchestrator(self):
        """Proves unknown orchestrator identities are rejected."""
        data = dict(self.valid_mission_data)
        data["orchestrator_identity"] = "rogue_external_script"
        mission = ReviewMission(**data)
        gate = MissionAdmissionGate()
        result = gate.validate(mission)
        self.assertFalse(result.is_admitted)
        self.assertTrue(any("Point 6" in r for r in result.rejections))

    def test_lifecycle_transition_matrix(self):
        """Proves that invalid lifecycle transitions are blocked."""
        mission = ReviewMission(**self.valid_mission_data)
        # Attempt illegal skip from CREATED directly to EXECUTING
        with self.assertRaises(InvalidMissionTransitionException):
            mission.transition_to(MissionLifecycleState.EXECUTING)

        # Admitted mission cannot jump directly to COMPLETED without discovering/executing
        mission.transition_to(MissionLifecycleState.VALIDATING)
        mission.transition_to(MissionLifecycleState.ADMITTED)
        with self.assertRaises(InvalidMissionTransitionException):
            mission.transition_to(MissionLifecycleState.COLLECTING_EVIDENCE)


if __name__ == "__main__":
    unittest.main()
