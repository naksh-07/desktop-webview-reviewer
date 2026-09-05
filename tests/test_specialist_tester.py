"""
Unit tests for the Tester Specialist Subagent (Phase 15).
Verifies delegated workflow execution, settlement monitoring, assertion evaluation,
tool permission enforcement, and non-bypass of failed acceptance criteria.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import (
    SpecialistDelegation,
    DelegationScope,
    SpecialistResultStatus,
)
from runtime.specialists import TesterSpecialist, SpecialistSecurityException
from runtime.state import TargetPlane
from runtime.action_models import (
    ActionReceipt,
    ActionOutcome,
    ActionOutcomeStatus,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    StateChangeClassification,
)
from runtime.references import Rect


class TestSpecialistTester(unittest.TestCase):
    """Tests Tester specialist execution and boundary enforcement."""

    def setUp(self):
        self.session_state = MagicMock()
        self.session_state.session_id = "sess_tester_1"
        self.session_state.current_epoch = 1

        # Mock Action Engine
        self.action_engine = MagicMock()
        receipt = ActionReceipt(
            action_id="act_click_1",
            session_id="sess_tester_1",
            target_id="tgt_main",
            epoch=1,
            plane=TargetPlane.WEBVIEW,
            reference="w1e2",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.PHYSICAL_INPUT,
            dispatch_timestamp=1000.0,
            dispatch_status=DispatchStatus.DISPATCHED,
        )
        outcome = ActionOutcome(
            action_id="act_click_1",
            session_id="sess_tester_1",
            receipt=receipt,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=1,
            post_epoch=2,
            duration_ms=25.0,
        )
        self.action_engine.execute_transaction = AsyncMock(return_value=(receipt, outcome))
        self.session_state.action_engine = self.action_engine

        # Mock Observation Engine for assertions
        self.obs_engine = MagicMock()
        node1 = MagicMock(reference="w1e2", role="button", is_visible=True)
        node1.name = "Save File"
        node2 = MagicMock(reference="w1e3", role="status", is_visible=True)
        node2.name = "Saved successfully"
        obs = MagicMock(nodes=[node1, node2], epoch=2)
        self.obs_engine.capture_observation = AsyncMock(return_value=obs)
        self.session_state.observation_engine = self.obs_engine

        # Mock Settlement Engine
        self.settle_engine = MagicMock()
        self.settle_engine.wait_for_settlement = AsyncMock(return_value=MagicMock(is_settled=True))
        self.session_state.settlement_engine = self.settle_engine

    def test_tester_executes_delegated_workflow_successfully(self):
        """Verifies Tester executes requested workflow steps and assertion to SUCCESS."""
        steps = [
            {"action_type": "CLICK", "ref": "w1e2"},
            {"action_type": "ASSERT", "ref": "w1e3", "assertion": "text_contains", "expected_text": "Saved"},
        ]
        delegation = SpecialistDelegation(
            role=SpecialistRole.TESTER,
            task="Click Save and verify status message",
            scope=DelegationScope(session_id="sess_tester_1"),
            permitted_tools={"desktop_click", "desktop_assert", "desktop_settle"},
            allow_state_mutation=True,
            parameters={"workflow_steps": steps},
        )
        tester = TesterSpecialist(delegation=delegation, session_state=self.session_state)

        result = asyncio.run(tester.run())
        self.assertEqual(result.status, SpecialistResultStatus.SUCCESS)
        self.assertEqual(result.role, SpecialistRole.TESTER)
        self.assertEqual(len(result.observations["steps_executed"]), 1)
        self.assertEqual(len(result.observations["assertions_evaluated"]), 1)
        self.assertTrue(result.observations["assertions_evaluated"][0]["passed"])
        self.assertEqual(len(result.errors), 0)

    def test_tester_fails_when_assertion_fails(self):
        """Verifies Tester does not bypass failed assertions and returns FAILED."""
        steps = [
            {"action_type": "CLICK", "ref": "w1e2"},
            {"action_type": "ASSERT", "ref": "w1e3", "assertion": "text_equals", "expected_text": "Error Occurred"},
        ]
        delegation = SpecialistDelegation(
            role=SpecialistRole.TESTER,
            task="Verify error text",
            scope=DelegationScope(session_id="sess_tester_1"),
            permitted_tools={"desktop_click", "desktop_assert"},
            allow_state_mutation=True,
            parameters={"workflow_steps": steps},
        )
        tester = TesterSpecialist(delegation=delegation, session_state=self.session_state)

        result = asyncio.run(tester.run())
        self.assertEqual(result.status, SpecialistResultStatus.FAILED)
        self.assertFalse(result.observations["assertions_evaluated"][0]["passed"])
        self.assertTrue(any("Assertion failed" in err for err in result.errors))

    def test_tester_rejects_unauthorized_tool(self):
        """Verifies Tester cannot call tools outside its delegation."""
        steps = [
            {"action_type": "CLICK", "ref": "w1e2"},
        ]
        delegation = SpecialistDelegation(
            role=SpecialistRole.TESTER,
            task="Click without permitted click tool",
            scope=DelegationScope(session_id="sess_tester_1"),
            permitted_tools={"desktop_assert"},  # desktop_click is missing from permitted_tools!
            allow_state_mutation=True,
            parameters={"workflow_steps": steps},
        )
        tester = TesterSpecialist(delegation=delegation, session_state=self.session_state)

        result = asyncio.run(tester.run())
        self.assertEqual(result.status, SpecialistResultStatus.FAILED)
        self.assertTrue(any("SPECIALIST_TOOL_FORBIDDEN" in err or "denied access" in err for err in result.errors))


if __name__ == "__main__":
    unittest.main()
