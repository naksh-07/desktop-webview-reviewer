"""
Phase 5 Test Suite — Stale Reference Recovery.
Tests that the locator engine correctly re-resolves stale references during the
action-observation transaction loop: unique match succeeds, ambiguous match halts
with TargetAmbiguousException, and 0 candidates halts with TargetNotFoundException.
"""

import time
import unittest

from runtime.state import TargetPlane
from runtime.references import Rect, ElementRef, ReferenceRegistry
from runtime.locators import DeterministicLocatorEngine, LocatorQuery
from runtime.observation_models import (
    DualPerspectiveSnapshot, WebObservation, WebElementObservation,
    GeometryObservation, VisibilityObservation, InteractionObservation,
    RoleSource,
)
from runtime.errors import (
    TargetNotFoundException,
    TargetAmbiguousException,
    StaleReferenceException,
)


def make_web_element(ref_id, role, name, text="", bounds=None):
    """Creates a WebElementObservation for test fixtures."""
    if bounds is None:
        bounds = Rect(100, 100, 50, 30)
    now = time.time()
    return WebElementObservation(
        session_id="test-session",
        observation_epoch=1,
        timestamp=now,
        source_plane=TargetPlane.WEBVIEW_DOM,
        target_id="target_01",
        reference=ref_id,
        role=role,
        normalized_role=role,
        role_source=RoleSource.ACCESSIBILITY,
        accessible_name=name,
        visible_text=text or name,
        tag_name="button",
        frame_id="",
        bounds=bounds,
        geometry=GeometryObservation(bounds=bounds, screen_bounds=bounds),
        visibility=VisibilityObservation(attached=True, visible=True, in_viewport=True, physically_occluded=False),
        interaction=InteractionObservation(is_enabled=True, is_focused=False, affordance_point=(bounds.x + 10, bounds.y + 10), supported_actions=("click",)),
        attributes={},
    )


def make_snapshot(web_elements):
    """Creates a DualPerspectiveSnapshot with the given web elements."""
    now = time.time()
    web_obs = WebObservation(
        session_id="test-session",
        epoch=5,
        timestamp=now,
        target_id="target-main",
        target_title="Test Page",
        target_url="http://test/page",
        root_frame_id="FRAME_ROOT",
        elements=tuple(web_elements),
        frames=(),
    )
    return DualPerspectiveSnapshot(
        session_id="test-session",
        epoch=5,
        timestamp=now,
        web_observation=web_obs,
        native_observation=None,
    )


class TestStaleRecoveryUniqueMatch(unittest.TestCase):
    """Tests that re-resolution succeeds when exactly one candidate matches."""

    def test_unique_candidate_re_resolves(self):
        reg = ReferenceRegistry()
        for _ in range(5):
            reg.advance_epoch(reason="setup")

        # Register a ref in epoch 5
        reg.register_ref(
            ref_id="w1e5", target_id="btn-submit", plane=TargetPlane.WEBVIEW_DOM,
            role="button", name="Submit", bounds=Rect(100, 100, 50, 30),
            frame_id="FRAME_ROOT", locator_recipe={"role": "button", "name": "Submit"},
        )

        # Advance epoch to make it stale
        reg.advance_epoch(reason="mutation")

        # Re-register a new element with same role+name in current epoch
        reg.register_ref(
            ref_id="w1e6", target_id="btn-submit-new", plane=TargetPlane.WEBVIEW_DOM,
            role="button", name="Submit", bounds=Rect(100, 100, 50, 30),
            frame_id="FRAME_ROOT", locator_recipe={"role": "button", "name": "Submit"},
        )

        # Create snapshot with the new element
        snap = make_snapshot([
            make_web_element("w1e6", "button", "Submit"),
        ])

        locator = DeterministicLocatorEngine()
        recovered = locator.re_resolve_stale_ref("w1e5", reg, snap)

        self.assertEqual(recovered.ref_id, "w1e6")
        self.assertEqual(recovered.role, "button")
        self.assertEqual(recovered.name, "Submit")


class TestStaleRecoveryNoCandidate(unittest.TestCase):
    """Tests that re-resolution fails cleanly when no candidates match."""

    def test_zero_candidates_raises_not_found(self):
        reg = ReferenceRegistry()
        for _ in range(5):
            reg.advance_epoch(reason="setup")

        reg.register_ref(
            ref_id="w1e5", target_id="btn-gone", plane=TargetPlane.WEBVIEW_DOM,
            role="button", name="DisappearedButton", bounds=Rect(100, 100, 50, 30),
            frame_id="FRAME_ROOT", locator_recipe={"role": "button", "name": "DisappearedButton"},
        )

        # Advance epoch to make it stale
        reg.advance_epoch(reason="mutation")

        # Empty snapshot — element is gone
        snap = make_snapshot([])

        locator = DeterministicLocatorEngine()
        with self.assertRaises(TargetNotFoundException):
            locator.re_resolve_stale_ref("w1e5", reg, snap)


class TestStaleRecoveryAmbiguous(unittest.TestCase):
    """Tests that re-resolution fails when multiple candidates match equally."""

    def test_ambiguous_candidates_raises(self):
        reg = ReferenceRegistry()
        for _ in range(5):
            reg.advance_epoch(reason="setup")

        reg.register_ref(
            ref_id="w1e5", target_id="btn-ok", plane=TargetPlane.WEBVIEW_DOM,
            role="button", name="OK", bounds=Rect(100, 100, 50, 30),
            frame_id="FRAME_ROOT", locator_recipe={"role": "button", "name": "OK"},
        )

        # Advance epoch to make it stale
        reg.advance_epoch(reason="mutation")

        # Register 2 identical candidates in new epoch
        reg.register_ref(
            ref_id="w1e6", target_id="btn-ok-1", plane=TargetPlane.WEBVIEW_DOM,
            role="button", name="OK", bounds=Rect(100, 100, 50, 30),
            frame_id="FRAME_ROOT", locator_recipe={"role": "button", "name": "OK"},
        )
        reg.register_ref(
            ref_id="w1e7", target_id="btn-ok-2", plane=TargetPlane.WEBVIEW_DOM,
            role="button", name="OK", bounds=Rect(300, 100, 50, 30),
            frame_id="FRAME_ROOT", locator_recipe={"role": "button", "name": "OK"},
        )

        snap = make_snapshot([
            make_web_element("w1e6", "button", "OK"),
            make_web_element("w1e7", "button", "OK"),
        ])

        locator = DeterministicLocatorEngine()
        with self.assertRaises(TargetAmbiguousException):
            locator.re_resolve_stale_ref("w1e5", reg, snap)


class TestStaleRecoveryNoRecipe(unittest.TestCase):
    """Tests that re-resolution fails when stale ref has no locator recipe."""

    def test_no_recipe_raises_not_found(self):
        reg = ReferenceRegistry()
        for _ in range(5):
            reg.advance_epoch(reason="setup")

        reg.register_ref(
            ref_id="w1e5", target_id="no-recipe", plane=TargetPlane.WEBVIEW_DOM,
            role="generic", name="", bounds=Rect(0, 0, 0, 0),
            locator_recipe=None,
        )

        reg.advance_epoch(reason="mutation")

        snap = make_snapshot([])
        locator = DeterministicLocatorEngine()
        with self.assertRaises(TargetNotFoundException):
            locator.re_resolve_stale_ref("w1e5", reg, snap)


if __name__ == "__main__":
    unittest.main()
