"""
Unit tests for Deterministic Locator Foundation & Safety (Phase 4).
Verifies ranking strategies, strict ambiguity rejection, frame scoping,
and explicit stale reference re-resolution.
"""

import unittest
import time
from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane
from runtime.errors import TargetNotFoundException, TargetAmbiguousException, StaleReferenceException
from runtime.observation_models import (
    DualPerspectiveSnapshot,
    WebObservation,
    WebElementObservation,
    NativeObservation,
    NativeElementObservation,
    VisibilityObservation,
    InteractionObservation,
    RoleSource,
)
from runtime.locators import LocatorQuery, DeterministicLocatorEngine


class TestLocators(unittest.TestCase):
    def setUp(self):
        self.session_id = "test_loc_sess"
        self.engine = DeterministicLocatorEngine()
        self.now = time.time()
        self.registry = ReferenceRegistry(self.session_id, initial_epoch=1)

    def _create_web_elem(
        self,
        ref: str,
        role: str,
        name: str,
        frame_id: str = "frame_root",
        text: str = "",
        test_id: str = "",
        ph: str = "",
    ):
        return WebElementObservation(
            session_id=self.session_id,
            observation_epoch=1,
            timestamp=self.now,
            source_plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            reference=ref,
            role=role,
            normalized_role=role,
            role_source=RoleSource.ACCESSIBILITY,
            accessible_name=name,
            visible_text=text or name,
            placeholder=ph,
            attributes={"data-testid": test_id} if test_id else {},
            frame_id=frame_id,
            bounds=Rect(10, 10, 100, 30),
            visibility=VisibilityObservation(attached=True, visible=True, in_viewport=True, physically_occluded=False),
            interaction=InteractionObservation(is_enabled=True, is_focused=False, affordance_point=(60, 25), supported_actions=("click",)),
        )

    def test_unique_match_by_role_and_name(self):
        """Single matching element succeeds with high confidence and documented match strategy."""
        e1 = self._create_web_elem("w1e1", "button", "Submit")
        e2 = self._create_web_elem("w1e2", "button", "Cancel")

        snap = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            web_observation=WebObservation(
                session_id=self.session_id, epoch=1, timestamp=self.now,
                target_id="t1", target_title="T", target_url="U", root_frame_id="f1",
                elements=(e1, e2),
            ),
        )

        query = LocatorQuery(role="button", name="Submit")
        match = self.engine.resolve(query, snap)
        self.assertEqual(match.reference, "w1e1")
        self.assertEqual(match.confidence, 0.95)
        self.assertEqual(match.match_strategy, "role_and_name_exact")

    def test_strictness_enforcement_raises_target_ambiguous(self):
        """CRITICAL: Multiple elements with equal top score MUST raise TargetAmbiguousException instead of choosing first."""
        e1 = self._create_web_elem("w1e1", "button", "Delete")
        e2 = self._create_web_elem("w1e2", "button", "Delete")

        snap = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            web_observation=WebObservation(
                session_id=self.session_id, epoch=1, timestamp=self.now,
                target_id="t1", target_title="T", target_url="U", root_frame_id="f1",
                elements=(e1, e2),
            ),
        )

        query = LocatorQuery(role="button", name="Delete")
        with self.assertRaises(TargetAmbiguousException) as ctx:
            self.engine.resolve(query, snap, strict=True)

        err = ctx.exception
        self.assertEqual(err.code, "TARGET_AMBIGUOUS")
        self.assertEqual(len(err.candidates), 2)
        self.assertEqual(err.candidates[0]["ref"], "w1e1")
        self.assertEqual(err.candidates[1]["ref"], "w1e2")

    def test_explicit_index_bypass(self):
        """When index is explicitly provided in query, strict ambiguity error is bypassed."""
        e1 = self._create_web_elem("w1e1", "button", "Delete")
        e2 = self._create_web_elem("w1e2", "button", "Delete")

        snap = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            web_observation=WebObservation(
                session_id=self.session_id, epoch=1, timestamp=self.now,
                target_id="t1", target_title="T", target_url="U", root_frame_id="f1",
                elements=(e1, e2),
            ),
        )

        query = LocatorQuery(role="button", name="Delete", index=1)
        match = self.engine.resolve(query, snap, strict=True)
        self.assertEqual(match.reference, "w1e2")
        self.assertIn("indexed", match.match_strategy)

    def test_frame_aware_scoping(self):
        """Element inside frame A is not returned if frame B is requested."""
        e_root = self._create_web_elem("w1e1", "button", "Submit", frame_id="frame_root")
        e_child = self._create_web_elem("w1e2", "button", "Submit", frame_id="frame_child")

        snap = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            web_observation=WebObservation(
                session_id=self.session_id, epoch=1, timestamp=self.now,
                target_id="t1", target_title="T", target_url="U", root_frame_id="frame_root",
                elements=(e_root, e_child),
            ),
        )

        query = LocatorQuery(role="button", name="Submit", frame_id="frame_child")
        match = self.engine.resolve(query, snap)
        self.assertEqual(match.reference, "w1e2")

    def test_target_not_found(self):
        """Unmatched query raises TargetNotFoundException."""
        snap = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            web_observation=WebObservation(
                session_id=self.session_id, epoch=1, timestamp=self.now,
                target_id="t1", target_title="T", target_url="U", root_frame_id="f1",
                elements=(),
            ),
        )

        query = LocatorQuery(role="button", name="NonExistent")
        with self.assertRaises(TargetNotFoundException):
            self.engine.resolve(query, snap)

    def test_stale_ref_re_resolution(self):
        """Re-resolution takes stale ref from epoch 1 and re-locates unique match in epoch 2."""
        # Register ref in epoch 1
        ref1 = self.registry.register_ref(
            role="button",
            plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            bounds=Rect(10, 10, 100, 30),
            locator_recipe={"role": "button", "name": "Start Review"},
        )
        self.assertEqual(ref1.ref_id, "w1e1")

        # Advance to epoch 2
        self.registry.advance_epoch()
        self.assertEqual(self.registry.current_epoch, 2)

        # In epoch 2, register new ref with same semantics
        ref2 = self.registry.register_ref(
            role="button",
            plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            bounds=Rect(15, 15, 100, 30),
            locator_recipe={"role": "button", "name": "Start Review"},
        )
        self.assertEqual(ref2.ref_id, "w2e1")

        # Create snapshot for epoch 2
        elem_new = WebElementObservation(
            session_id=self.session_id,
            observation_epoch=2,
            timestamp=self.now,
            source_plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            reference="w2e1",
            role="button",
            normalized_role="button",
            accessible_name="Start Review",
            bounds=Rect(15, 15, 100, 30),
            visibility=VisibilityObservation(attached=True, visible=True, in_viewport=True, physically_occluded=False),
            interaction=InteractionObservation(is_enabled=True, is_focused=False, affordance_point=(65, 30), supported_actions=("click",)),
        )

        snap2 = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=2,
            timestamp=self.now,
            web_observation=WebObservation(
                session_id=self.session_id, epoch=2, timestamp=self.now,
                target_id="target_01", target_title="T", target_url="U", root_frame_id="f1",
                elements=(elem_new,),
            ),
        )

        # Attempt to resolve stale ref directly -> raises StaleReferenceException
        with self.assertRaises(StaleReferenceException):
            self.registry.resolve_ref("w1e1")

        # Controlled re-resolution via stored recipe
        new_resolved_ref = self.engine.re_resolve_stale_ref("w1e1", self.registry, snap2)
        self.assertEqual(new_resolved_ref.ref_id, "w2e1")
        self.assertEqual(new_resolved_ref.epoch_id, 2)


if __name__ == "__main__":
    unittest.main()
