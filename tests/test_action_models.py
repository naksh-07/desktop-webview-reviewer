"""
Phase 5 Test Suite — Action Domain Models.
Tests ActionRequest, ActionTarget, ActionPreconditions, ActionReceipt, ActionOutcome,
all supporting enums, immutability guarantees, and serialization fidelity.
"""

import unittest
import time
import json
from dataclasses import FrozenInstanceError

from runtime.state import TargetPlane
from runtime.references import Rect
from runtime.action_models import (
    ActionType,
    DispatchMethod,
    ActionRiskLevel,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
    ActionTarget,
    ActionPreconditions,
    ActionRequest,
    ActionReceipt,
    ActionOutcome,
)


class TestActionEnums(unittest.TestCase):
    """Validates all action domain enumerations."""

    def test_action_type_members(self):
        expected = {"CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "TYPE", "KEY_PRESS",
                     "SCROLL", "FOCUS", "HOVER", "WAIT"}
        actual = {e.value for e in ActionType}
        self.assertEqual(actual, expected)

    def test_dispatch_method_members(self):
        expected = {"PHYSICAL_INPUT", "CDP_INPUT", "SEMANTIC_CONTROL_PATTERN",
                     "SCRIPTED_FALLBACK", "NATIVE_SENDINPUT"}
        actual = {e.value for e in DispatchMethod}
        self.assertEqual(actual, expected)

    def test_risk_level_members(self):
        expected = {"LOW_RISK", "INTERACTIVE", "POTENTIALLY_DESTRUCTIVE"}
        actual = {e.value for e in ActionRiskLevel}
        self.assertEqual(actual, expected)

    def test_dispatch_status_members(self):
        expected = {"DISPATCHED", "REJECTED", "FAILED"}
        actual = {e.value for e in DispatchStatus}
        self.assertEqual(actual, expected)

    def test_outcome_status_members(self):
        expected = {"DISPATCHED", "REJECTED", "FAILED", "UNKNOWN"}
        actual = {e.value for e in ActionOutcomeStatus}
        self.assertEqual(actual, expected)

    def test_state_change_members(self):
        expected = {"NO_EFFECT", "STATE_CHANGED", "TARGET_DISAPPEARED",
                     "NAVIGATED", "TARGET_CLOSED", "MODAL_APPEARED"}
        actual = {e.value for e in StateChangeClassification}
        self.assertEqual(actual, expected)

    def test_enum_string_comparison(self):
        """Verifies str enum allows direct string comparison."""
        self.assertEqual(ActionType.CLICK, "CLICK")
        self.assertEqual(DispatchMethod.CDP_INPUT, "CDP_INPUT")
        self.assertEqual(DispatchStatus.DISPATCHED, "DISPATCHED")


class TestActionTarget(unittest.TestCase):
    """Validates ActionTarget construction and immutability."""

    def _make_target(self, **kwargs):
        defaults = dict(
            session_id="sess-001",
            target_id="btn-submit",
            reference="w1e5",
            plane=TargetPlane.WEBVIEW_DOM,
            epoch=3,
            affordance_point=(200, 150),
            coordinate_space="VIEWPORT_LOGICAL",
            native_hwnd=0x123456,
            cdp_target_id="cdp-target-1",
            frame_id="frame-root",
            role="button",
            name="Submit",
            bounds=Rect(180, 130, 40, 40),
        )
        defaults.update(kwargs)
        return ActionTarget(**defaults)

    def test_creation(self):
        t = self._make_target()
        self.assertEqual(t.session_id, "sess-001")
        self.assertEqual(t.reference, "w1e5")
        self.assertEqual(t.plane, TargetPlane.WEBVIEW_DOM)
        self.assertEqual(t.epoch, 3)
        self.assertEqual(t.affordance_point, (200, 150))

    def test_immutability(self):
        t = self._make_target()
        with self.assertRaises(FrozenInstanceError):
            t.reference = "w1e6"

    def test_to_dict(self):
        t = self._make_target()
        d = t.to_dict()
        self.assertEqual(d["session_id"], "sess-001")
        self.assertEqual(d["reference"], "w1e5")
        self.assertIn("plane", d)
        self.assertEqual(d["native_hwnd"], hex(0x123456))
        self.assertIsInstance(d["bounds"], dict)

    def test_optional_defaults(self):
        t = ActionTarget(
            session_id="s1", target_id="t1", reference="ref1",
            plane=TargetPlane.NATIVE_SHELL, epoch=1,
        )
        self.assertIsNone(t.affordance_point)
        self.assertIsNone(t.native_hwnd)
        self.assertIsNone(t.cdp_target_id)
        self.assertEqual(t.coordinate_space, "VIEWPORT_LOGICAL")


class TestActionPreconditions(unittest.TestCase):
    """Validates ActionPreconditions forensic record."""

    def test_all_pass(self):
        p = ActionPreconditions(
            attachment=True, visibility=True, motion_stable=True,
            enabled=True, unoccluded=True, physical_valid=True,
            modal_clear=True, epoch_match=True, is_all_passed=True,
        )
        self.assertTrue(p.is_all_passed)
        d = p.to_dict()
        self.assertTrue(all(v is True for k, v in d.items()
                          if k not in ("reasons", "evaluated_at")))

    def test_failed_gate(self):
        p = ActionPreconditions(
            attachment=True, visibility=False, motion_stable=True,
            enabled=True, unoccluded=True, physical_valid=True,
            modal_clear=True, epoch_match=True, is_all_passed=False,
            reasons=("element is hidden by display:none",),
        )
        self.assertFalse(p.is_all_passed)
        self.assertIn("element is hidden by display:none", p.reasons)

    def test_immutability(self):
        p = ActionPreconditions(
            attachment=True, visibility=True, motion_stable=True,
            enabled=True, unoccluded=True, physical_valid=True,
            modal_clear=True, epoch_match=True, is_all_passed=True,
        )
        with self.assertRaises(FrozenInstanceError):
            p.attachment = False


class TestActionRequest(unittest.TestCase):
    """Validates ActionRequest construction and defaults."""

    def test_basic_click_request(self):
        req = ActionRequest(
            session_id="sess-01",
            reference="w1e10",
            action_type=ActionType.CLICK,
            observation_epoch=5,
        )
        self.assertEqual(req.session_id, "sess-01")
        self.assertEqual(req.action_type, ActionType.CLICK)
        self.assertEqual(req.observation_epoch, 5)
        self.assertEqual(req.risk_level, ActionRiskLevel.INTERACTIVE)
        self.assertTrue(req.require_strict_locator)
        self.assertTrue(req.allow_stale_recovery)
        self.assertIsNotNone(req.action_id)
        self.assertGreater(req.timestamp, 0)

    def test_type_request_with_params(self):
        req = ActionRequest(
            session_id="sess-02",
            reference="w1e20",
            action_type=ActionType.TYPE,
            observation_epoch=7,
            params={"text": "Hello World", "clear_first": True},
            risk_level=ActionRiskLevel.LOW_RISK,
        )
        self.assertEqual(req.params["text"], "Hello World")
        self.assertEqual(req.risk_level, ActionRiskLevel.LOW_RISK)

    def test_to_dict_roundtrip(self):
        req = ActionRequest(
            session_id="sess-03",
            reference="n1e5",
            action_type=ActionType.SCROLL,
            observation_epoch=2,
            params={"delta_y": -120},
        )
        d = req.to_dict()
        self.assertEqual(d["action_type"], "SCROLL")
        self.assertEqual(d["session_id"], "sess-03")
        # Verify JSON serializable
        json.dumps(d)

    def test_immutability(self):
        req = ActionRequest(
            session_id="s1", reference="ref1",
            action_type=ActionType.CLICK, observation_epoch=1,
        )
        with self.assertRaises(FrozenInstanceError):
            req.session_id = "s2"


class TestActionReceipt(unittest.TestCase):
    """Validates ActionReceipt immutable dispatch record."""

    def _make_receipt(self, **kwargs):
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
            coordinates=(200, 150),
            dispatch_status=DispatchStatus.DISPATCHED,
            duration_ms=12.5,
        )
        defaults.update(kwargs)
        return ActionReceipt(**defaults)

    def test_dispatched_receipt(self):
        r = self._make_receipt()
        self.assertEqual(r.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertIsNone(r.error)
        self.assertEqual(r.coordinates, (200, 150))

    def test_rejected_receipt(self):
        r = self._make_receipt(
            dispatch_status=DispatchStatus.REJECTED,
            error="Epoch mismatch",
        )
        self.assertEqual(r.dispatch_status, DispatchStatus.REJECTED)
        self.assertIn("Epoch", r.error)

    def test_immutability(self):
        r = self._make_receipt()
        with self.assertRaises(FrozenInstanceError):
            r.dispatch_status = DispatchStatus.FAILED

    def test_serialization(self):
        r = self._make_receipt(native_hwnd=0xABCDEF)
        d = r.to_dict()
        self.assertEqual(d["native_hwnd"], hex(0xABCDEF))
        self.assertEqual(d["action_type"], "CLICK")
        self.assertEqual(d["dispatch_method"], "CDP_INPUT")
        # JSON serializable
        json.dumps(d)

    def test_recovery_provenance(self):
        r = self._make_receipt(recovered_from_ref="w1e3_stale")
        self.assertEqual(r.recovered_from_ref, "w1e3_stale")
        d = r.to_dict()
        self.assertEqual(d["recovered_from_ref"], "w1e3_stale")


class TestActionOutcome(unittest.TestCase):
    """Validates ActionOutcome transaction cycle result."""

    def _make_outcome(self, **kwargs):
        receipt = ActionReceipt(
            action_id="act-002",
            session_id="sess-002",
            target_id="input-1",
            epoch=10,
            plane=TargetPlane.WEBVIEW_DOM,
            reference="w1e10",
            action_type=ActionType.TYPE,
            dispatch_method=DispatchMethod.CDP_INPUT,
            dispatch_timestamp=time.time(),
            dispatch_status=DispatchStatus.DISPATCHED,
        )
        defaults = dict(
            action_id="act-002",
            session_id="sess-002",
            receipt=receipt,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=10,
            post_epoch=11,
            duration_ms=45.2,
        )
        defaults.update(kwargs)
        return ActionOutcome(**defaults)

    def test_successful_outcome(self):
        o = self._make_outcome()
        self.assertEqual(o.outcome_status, ActionOutcomeStatus.DISPATCHED)
        self.assertEqual(o.state_change, StateChangeClassification.STATE_CHANGED)
        self.assertEqual(o.pre_epoch, 10)
        self.assertEqual(o.post_epoch, 11)

    def test_rejected_outcome(self):
        receipt = ActionReceipt(
            action_id="act-rej",
            session_id="sess-002",
            target_id="input-1",
            epoch=10,
            plane=TargetPlane.WEBVIEW_DOM,
            reference="w1e10",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.CDP_INPUT,
            dispatch_timestamp=time.time(),
            dispatch_status=DispatchStatus.REJECTED,
            error="Visibility gate failed",
        )
        o = ActionOutcome(
            action_id="act-rej",
            session_id="sess-002",
            receipt=receipt,
            outcome_status=ActionOutcomeStatus.REJECTED,
            state_change=StateChangeClassification.NO_EFFECT,
            pre_epoch=10,
            post_epoch=10,
        )
        self.assertEqual(o.outcome_status, ActionOutcomeStatus.REJECTED)
        self.assertEqual(o.state_change, StateChangeClassification.NO_EFFECT)
        self.assertEqual(o.pre_epoch, o.post_epoch)

    def test_serialization(self):
        o = self._make_outcome()
        d = o.to_dict()
        self.assertEqual(d["outcome_status"], "DISPATCHED")
        self.assertEqual(d["state_change"], "STATE_CHANGED")
        self.assertIn("receipt", d)
        self.assertIsInstance(d["receipt"], dict)
        # JSON serializable
        json.dumps(d)

    def test_immutability(self):
        o = self._make_outcome()
        with self.assertRaises(FrozenInstanceError):
            o.state_change = StateChangeClassification.NAVIGATED

    def test_navigation_outcome(self):
        o = self._make_outcome(
            state_change=StateChangeClassification.NAVIGATED,
            navigation_url="https://example.com/next",
        )
        self.assertEqual(o.state_change, StateChangeClassification.NAVIGATED)
        self.assertEqual(o.navigation_url, "https://example.com/next")

    def test_modal_outcome(self):
        o = self._make_outcome(
            state_change=StateChangeClassification.MODAL_APPEARED,
            modal_details={"modals": [{"class": "#32770", "title": "Save As"}]},
        )
        self.assertEqual(o.state_change, StateChangeClassification.MODAL_APPEARED)
        self.assertEqual(o.modal_details["modals"][0]["title"], "Save As")


if __name__ == "__main__":
    unittest.main()
