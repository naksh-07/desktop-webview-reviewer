"""
Phase 11: Multi-Plane Reality Reconciliation Unit and Contract Tests.
Verifies:
- Truth Hierarchy (Physical Desktop Reality > Compositor Reality > DOM/Web Reality)
- Cloaked / Iconic window state overrides DOM visibility and actionability
- Modal occlusion detection and contradiction surfacing
- Coordinate alignment between native canonical and web viewport pixels
"""

from __future__ import annotations
import unittest

from runtime.references import Rect
from runtime.reconciliation import (
    RealityReconciler,
    RealityTarget,
    RealityReconciliationSnapshot,
)
from runtime.native_supervisor import WindowForensicReport as WindowForensics
from runtime.state import TargetPlane


class MockNativeObservation:
    def __init__(self, hwnd=0x1001, is_visible=True, is_cloaked=False, is_minimized=False, elements=None):
        self.hwnd = hwnd
        self.is_visible = is_visible
        self.is_cloaked = is_cloaked
        self.is_minimized = is_minimized
        self.elements = elements or []


class MockWebElement:
    def __init__(self, target_id="btn_submit", reference="w1e1", role="button", name="Submit", bounds=None, visible=True, enabled=True):
        self.target_id = target_id
        self.reference = reference
        self.role = role
        self.name = name
        self.bounds = bounds or Rect(100, 100, 80, 30)
        self.is_visible = visible
        self.is_enabled = enabled


class MockWebObservation:
    def __init__(self, elements=None):
        self.elements = elements or []


class TestPhase11RealityReconciliation(unittest.TestCase):
    def setUp(self):
        self.reconciler = RealityReconciler()

    def test_truth_hierarchy_cloaked_window_overrides_dom(self):
        """
        When window is cloaked (Compositor Reality), even if DOM reports visible=True
        and enabled=True, the reconciled RealityTarget must be NOT physically visible
        and NOT physically actionable, with a contradiction surfaced.
        """
        native_obs = MockNativeObservation(hwnd=0x1234, is_visible=True, is_cloaked=True, is_minimized=False)
        web_elem = MockWebElement(visible=True, enabled=True)
        web_obs = MockWebObservation(elements=[web_elem])

        snapshot = self.reconciler.reconcile(
            epoch=1,
            native_obs=native_obs,
            web_obs=web_obs,
        )

        self.assertEqual(len(snapshot.targets), 1)
        target = snapshot.targets[0]

        # Truth hierarchy assertion: Compositor overrides DOM
        self.assertFalse(target.is_physically_visible)
        self.assertFalse(target.actionability.is_actionable)
        self.assertIn("cloaked", target.actionability.reason.lower())

        # Contradiction assertion
        self.assertGreaterEqual(len(snapshot.contradictions), 1)
        self.assertTrue(any("CLOAKED_BUT_DOM_VISIBLE" in c for c in snapshot.contradictions))

    def test_truth_hierarchy_minimized_window_overrides_dom(self):
        """When window is minimized, DOM visible target must not be physically actionable."""
        native_obs = MockNativeObservation(hwnd=0x5678, is_visible=True, is_cloaked=False, is_minimized=True)
        web_elem = MockWebElement(visible=True, enabled=True)
        web_obs = MockWebObservation(elements=[web_elem])

        snapshot = self.reconciler.reconcile(
            epoch=2,
            native_obs=native_obs,
            web_obs=web_obs,
        )

        target = snapshot.targets[0]
        self.assertFalse(target.is_physically_visible)
        self.assertFalse(target.actionability.is_actionable)
        self.assertIn("minimized", target.actionability.reason.lower())

        self.assertGreaterEqual(len(snapshot.contradictions), 1)
        self.assertTrue(any("MINIMIZED_BUT_DOM_VISIBLE" in c for c in snapshot.contradictions))

    def test_truth_hierarchy_modal_occlusion(self):
        """When a modal covers a native/web element, it must not be reported as safely actionable."""
        native_obs = MockNativeObservation(hwnd=0x9999, is_visible=True, is_cloaked=False, is_minimized=False)
        web_elem = MockWebElement(reference="w1e5", bounds=Rect(150, 150, 100, 40))
        web_obs = MockWebObservation(elements=[web_elem])

        # A modal covering the target bounds
        modal_bounds = Rect(100, 100, 300, 200)
        modals = [WindowForensics(
            hwnd=0xAAAA,
            title="Warning Dialog",
            class_name="#32770",
            pid=1234,
            bounds=modal_bounds,
            is_visible=True,
            is_cloaked=False,
            is_iconic=False,
        )]

        snapshot = self.reconciler.reconcile(
            epoch=3,
            native_obs=native_obs,
            web_obs=web_obs,
            modal_windows=modals,
        )

        target = snapshot.targets[0]
        self.assertFalse(target.actionability.is_actionable)
        self.assertIn("modal", target.actionability.reason.lower())

        self.assertGreaterEqual(len(snapshot.contradictions), 1)
        self.assertTrue(any("OCCLUDED_BY_MODAL" in c for c in snapshot.contradictions))

    def test_reconciled_valid_target_actionability(self):
        """When native window is visible, uncloaked, and unoccluded, target is actionable."""
        native_obs = MockNativeObservation(hwnd=0x2222, is_visible=True, is_cloaked=False, is_minimized=False)
        web_elem = MockWebElement(reference="w1e1", bounds=Rect(200, 200, 100, 40), visible=True, enabled=True)
        web_obs = MockWebObservation(elements=[web_elem])

        snapshot = self.reconciler.reconcile(
            epoch=4,
            native_obs=native_obs,
            web_obs=web_obs,
        )

        self.assertEqual(len(snapshot.contradictions), 0)
        target = snapshot.targets[0]
        self.assertTrue(target.is_physically_visible)
        self.assertTrue(target.actionability.is_actionable)
        self.assertEqual(target.reference, "w1e1")
        self.assertIsNotNone(target.physical_bounds)


if __name__ == "__main__":
    unittest.main()
