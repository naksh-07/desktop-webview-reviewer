"""
Phase 5 Test Suite — Action Outcome Classification.
Tests for StateChangeClassification: STATE_CHANGED, NO_EFFECT,
TARGET_DISAPPEARED, NAVIGATED, TARGET_CLOSED, MODAL_APPEARED.
Validates the outcome classification logic in ActionOutcome model.
"""

import unittest
import time

from runtime.state import TargetPlane
from runtime.action_models import (
    ActionReceipt, ActionOutcome, ActionType, DispatchMethod,
    DispatchStatus, ActionOutcomeStatus, StateChangeClassification,
)


def make_receipt(**kwargs):
    defaults = dict(
        action_id="act-001",
        session_id="sess-001",
        target_id="btn-1",
        epoch=5,
        plane=TargetPlane.WEBVIEW_DOM,
        reference="w1e5",
        action_type=ActionType.CLICK,
        dispatch_method=DispatchMethod.CDP_INPUT,
        dispatch_timestamp=time.time(),
        dispatch_status=DispatchStatus.DISPATCHED,
    )
    defaults.update(kwargs)
    return ActionReceipt(**defaults)


class TestOutcomeClassificationStateChanged(unittest.TestCase):
    """Tests STATE_CHANGED classification."""

    def test_state_changed_outcome(self):
        outcome = ActionOutcome(
            action_id="act-001",
            session_id="sess-001",
            receipt=make_receipt(),
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=5,
            post_epoch=6,
            duration_ms=45.0,
        )
        self.assertEqual(outcome.state_change, StateChangeClassification.STATE_CHANGED)
        self.assertEqual(outcome.pre_epoch, 5)
        self.assertEqual(outcome.post_epoch, 6)
        self.assertNotEqual(outcome.pre_epoch, outcome.post_epoch)

    def test_state_changed_serialization(self):
        outcome = ActionOutcome(
            action_id="act-001",
            session_id="sess-001",
            receipt=make_receipt(),
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=5,
            post_epoch=6,
        )
        d = outcome.to_dict()
        self.assertEqual(d["state_change"], "STATE_CHANGED")
        self.assertEqual(d["outcome_status"], "DISPATCHED")


class TestOutcomeClassificationNoEffect(unittest.TestCase):
    """Tests NO_EFFECT classification."""

    def test_no_effect_outcome(self):
        outcome = ActionOutcome(
            action_id="act-002",
            session_id="sess-001",
            receipt=make_receipt(action_id="act-002"),
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.NO_EFFECT,
            pre_epoch=5,
            post_epoch=6,
            duration_ms=32.0,
        )
        self.assertEqual(outcome.state_change, StateChangeClassification.NO_EFFECT)

    def test_rejected_has_no_effect(self):
        receipt = make_receipt(
            action_id="act-003",
            dispatch_status=DispatchStatus.REJECTED,
            error="Precondition failed",
        )
        outcome = ActionOutcome(
            action_id="act-003",
            session_id="sess-001",
            receipt=receipt,
            outcome_status=ActionOutcomeStatus.REJECTED,
            state_change=StateChangeClassification.NO_EFFECT,
            pre_epoch=5,
            post_epoch=5,
        )
        self.assertEqual(outcome.state_change, StateChangeClassification.NO_EFFECT)
        self.assertEqual(outcome.pre_epoch, outcome.post_epoch)


class TestOutcomeClassificationNavigated(unittest.TestCase):
    """Tests NAVIGATED classification."""

    def test_navigated_outcome(self):
        outcome = ActionOutcome(
            action_id="act-004",
            session_id="sess-001",
            receipt=make_receipt(action_id="act-004"),
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.NAVIGATED,
            pre_epoch=5,
            post_epoch=6,
            navigation_url="https://example.com/dashboard",
        )
        self.assertEqual(outcome.state_change, StateChangeClassification.NAVIGATED)
        self.assertEqual(outcome.navigation_url, "https://example.com/dashboard")

    def test_navigated_serialization(self):
        outcome = ActionOutcome(
            action_id="act-005",
            session_id="sess-001",
            receipt=make_receipt(action_id="act-005"),
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.NAVIGATED,
            pre_epoch=5,
            post_epoch=6,
            navigation_url="http://new-page.com",
        )
        d = outcome.to_dict()
        self.assertEqual(d["state_change"], "NAVIGATED")
        self.assertEqual(d["navigation_url"], "http://new-page.com")


class TestOutcomeClassificationTargetDisappeared(unittest.TestCase):
    """Tests TARGET_DISAPPEARED classification."""

    def test_target_disappeared_outcome(self):
        outcome = ActionOutcome(
            action_id="act-006",
            session_id="sess-001",
            receipt=make_receipt(action_id="act-006"),
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.TARGET_DISAPPEARED,
            pre_epoch=5,
            post_epoch=6,
        )
        self.assertEqual(outcome.state_change, StateChangeClassification.TARGET_DISAPPEARED)


class TestOutcomeClassificationTargetClosed(unittest.TestCase):
    """Tests TARGET_CLOSED classification."""

    def test_target_closed_outcome(self):
        outcome = ActionOutcome(
            action_id="act-007",
            session_id="sess-001",
            receipt=make_receipt(action_id="act-007"),
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.TARGET_CLOSED,
            pre_epoch=5,
            post_epoch=6,
        )
        self.assertEqual(outcome.state_change, StateChangeClassification.TARGET_CLOSED)


class TestOutcomeClassificationModalAppeared(unittest.TestCase):
    """Tests MODAL_APPEARED classification."""

    def test_modal_appeared_outcome(self):
        outcome = ActionOutcome(
            action_id="act-008",
            session_id="sess-001",
            receipt=make_receipt(action_id="act-008"),
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.MODAL_APPEARED,
            pre_epoch=5,
            post_epoch=6,
            modal_details={"modals": [{"class": "#32770", "title": "Confirm Delete"}]},
        )
        self.assertEqual(outcome.state_change, StateChangeClassification.MODAL_APPEARED)
        self.assertIsNotNone(outcome.modal_details)
        self.assertEqual(outcome.modal_details["modals"][0]["title"], "Confirm Delete")


class TestOutcomeStatusValues(unittest.TestCase):
    """Tests ActionOutcomeStatus and StateChangeClassification values."""

    def test_outcome_statuses(self):
        self.assertEqual(ActionOutcomeStatus.DISPATCHED, "DISPATCHED")
        self.assertEqual(ActionOutcomeStatus.REJECTED, "REJECTED")
        self.assertEqual(ActionOutcomeStatus.FAILED, "FAILED")
        self.assertEqual(ActionOutcomeStatus.UNKNOWN, "UNKNOWN")

    def test_state_change_classifications(self):
        all_values = {e.value for e in StateChangeClassification}
        self.assertIn("NO_EFFECT", all_values)
        self.assertIn("STATE_CHANGED", all_values)
        self.assertIn("TARGET_DISAPPEARED", all_values)
        self.assertIn("NAVIGATED", all_values)
        self.assertIn("TARGET_CLOSED", all_values)
        self.assertIn("MODAL_APPEARED", all_values)


if __name__ == "__main__":
    unittest.main()
