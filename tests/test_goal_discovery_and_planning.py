"""
Tests for Goal-Oriented Discovery Engine and Review Plan Builder (Phase 17).
Verifies:
1. Bounded discovery generates candidates with verified provenance
2. Candidates without mission linkage or targeting prohibited surfaces are rejected
3. Review plan builds ordered steps subordinate to mission authority
4. Hard action and delegation budget limits are respected during plan creation
5. Reality Inspector and Evidence Specialist steps are staged
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import (
    SpecialistResult,
    SpecialistResultStatus,
)
from runtime.mission_models import (
    ReviewMission,
    DiscoveryCandidate,
    ReviewPlan,
)
from runtime.goal_discovery import GoalOrientedDiscoveryEngine
from runtime.review_plan import ReviewPlanBuilder


class TestGoalDiscoveryAndPlanning(unittest.TestCase):
    def setUp(self):
        self.session_id = "sess_discovery_test_01"
        self.mission = ReviewMission(
            session_id=self.session_id,
            objective="Verify math question card renders formula and submit button answers card.",
            declared_scope=["CardViewport", "AnswerButtons"],
            allowed_surfaces=["MainWindow", "CardViewport", "AnswerButtons"],
            prohibited_surfaces=["AccountSettings", "PreferencesDialog"],
            acceptance_criteria=[
                "Formula is rendered in CardViewport",
                "Answer button responds to submission",
            ],
            authorized_specialist_roles=[
                SpecialistRole.EXPLORER,
                SpecialistRole.TESTER,
                SpecialistRole.REALITY_INSPECTOR,
                SpecialistRole.DEBUGGER,
                SpecialistRole.EVIDENCE_SPECIALIST,
            ],
            max_actions=10,
            max_delegations=6,
        )
        self.mission.seal_authority()

    def test_bounded_discovery_provenance_and_prohibited_filter(self):
        """Proves discovery links candidates to criteria and excludes prohibited surfaces."""
        mock_dispatcher = MagicMock()
        mock_explorer_result = SpecialistResult(
            specialist_id="spec_explorer_01",
            role=SpecialistRole.EXPLORER,
            delegation_id="delg_exp_01",
            session_id=self.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer="Discovered 3 elements in CardViewport and MainWindow.",
            observations={
                "interactive_elements": [
                    {
                        "name": "Math Formula Container",
                        "role": "group",
                        "ref": "w0e10",
                        "surface": "CardViewport",
                    },
                    {
                        "name": "Submit Answer Button",
                        "role": "button",
                        "ref": "w0e12",
                        "surface": "AnswerButtons",
                    },
                    {
                        "name": "Open PreferencesDialog",  # Prohibited!
                        "role": "button",
                        "ref": "w0e99",
                        "surface": "PreferencesDialog",
                    },
                ],
                "windows": [{"title": "Anki Maths Reviewer", "surface": "MainWindow"}],
            },
        )
        mock_dispatcher.dispatch = AsyncMock(return_value=mock_explorer_result)

        engine = GoalOrientedDiscoveryEngine(dispatcher=mock_dispatcher)
        candidates = asyncio.run(engine.discover_candidates(self.mission))

        # Check that candidates were produced
        self.assertGreaterEqual(len(candidates), 2)

        # Check that prohibited surface was excluded
        for c in candidates:
            self.assertNotEqual(c.target_name, "Open PreferencesDialog")
            self.assertNotIn("PreferencesDialog", c.technical_rationale)
            # Check provenance: must reference mission and one of acceptance criteria
            self.assertEqual(c.mission_id, self.mission.mission_id)
            self.assertIn(c.acceptance_criterion_reference, self.mission.acceptance_criteria)
            self.assertIn(c.scope_reference, self.mission.declared_scope)

    def test_review_plan_builder_ordering_and_budgets(self):
        """Proves ReviewPlan stages Tester, Reality Inspector, and Evidence Specialist within budgets."""
        candidates = [
            DiscoveryCandidate(
                candidate_id="cand_01",
                mission_id=self.mission.mission_id,
                scope_reference="CardViewport",
                acceptance_criterion_reference="Formula is rendered in CardViewport",
                technical_rationale="Formula text matches expected math problem",
                required_specialist=SpecialistRole.TESTER,
                estimated_action_cost=1,
                risk="LOW",
                required_evidence=["screenshot"],
                action_type="assert",
                target_ref="w0e10",
                target_name="Math Formula Container",
            ),
            DiscoveryCandidate(
                candidate_id="cand_02",
                mission_id=self.mission.mission_id,
                scope_reference="AnswerButtons",
                acceptance_criterion_reference="Answer button responds to submission",
                technical_rationale="Click submit button triggers state change",
                required_specialist=SpecialistRole.TESTER,
                estimated_action_cost=1,
                risk="LOW",
                required_evidence=["screenshot", "trace"],
                action_type="click",
                target_ref="w0e12",
                target_name="Submit Answer Button",
            ),
        ]

        plan = ReviewPlanBuilder.build_plan(self.mission, candidates)

        self.assertEqual(plan.mission_id, self.mission.mission_id)
        # Expected steps: 2 tester steps + 1 reality inspector step + 1 evidence specialist step = 4 steps
        self.assertEqual(len(plan.steps), 4)

        step_roles = [s.specialist_role for s in plan.steps]
        self.assertEqual(
            step_roles,
            [
                SpecialistRole.TESTER,
                SpecialistRole.TESTER,
                SpecialistRole.REALITY_INSPECTOR,
                SpecialistRole.EVIDENCE_SPECIALIST,
            ],
        )

        # Ensure budget calculations are accurate
        self.assertLessEqual(plan.total_estimated_actions, self.mission.max_actions)
        self.assertLessEqual(plan.total_estimated_delegations, self.mission.max_delegations)

    def test_review_plan_builder_rejects_foreign_candidate(self):
        """Proves plan builder rejects candidates belonging to a different mission."""
        foreign_candidate = DiscoveryCandidate(
            candidate_id="cand_foreign",
            mission_id="msn_other_mission_999",  # Foreign mission ID
            scope_reference="CardViewport",
            acceptance_criterion_reference="Formula is rendered in CardViewport",
            technical_rationale="Foreign candidate injection",
            required_specialist=SpecialistRole.TESTER,
            estimated_action_cost=1,
            risk="HIGH",
            required_evidence=[],
        )

        plan = ReviewPlanBuilder.build_plan(self.mission, [foreign_candidate])
        # Foreign candidate should be rejected, only reality & evidence steps present
        candidate_ids = [s.candidate_id for s in plan.steps]
        self.assertNotIn("cand_foreign", candidate_ids)


if __name__ == "__main__":
    unittest.main()
