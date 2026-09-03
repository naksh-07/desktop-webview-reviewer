"""
Unit tests for Context Reconciliation & Physical Reality Primacy (Phase 4).
Verifies spatial relationship classification and explicit contradiction reporting.
"""

import unittest
import time
from runtime.references import Rect
from runtime.state import TargetPlane
from runtime.observation_models import (
    NativeObservation,
    WebObservation,
    WebElementObservation,
    NativeElementObservation,
    VisibilityObservation,
    RelationshipType,
    Certainty,
)
from runtime.reconciliation import ContextReconciler


class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.reconciler = ContextReconciler()
        self.session_id = "test_reconcile"
        self.now = time.time()

    def test_relationship_hosts_when_webview_inside_native(self):
        """Native window containing embedded webview is classified as HOSTS."""
        native_obs = NativeObservation(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            hwnd=0x1000,
            title="Desktop App",
            class_name="QtWindow",
            pid=2000,
            bounds=Rect(100, 100, 1200, 800),
            client_bounds=Rect(100, 140, 1200, 760),
            is_visible=True,
            is_minimized=False,
            is_cloaked=False,
            is_responsive=True,
        )

        web_elem = WebElementObservation(
            session_id=self.session_id,
            observation_epoch=1,
            timestamp=self.now,
            source_plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_1",
            reference="w1e1",
            role="button",
            normalized_role="button",
            bounds=Rect(200, 200, 100, 40),
            visibility=VisibilityObservation(
                attached=True,
                visible=True,
                in_viewport=True,
                physically_occluded=False,
            ),
        )

        web_obs = WebObservation(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            target_id="target_1",
            target_title="Web Title",
            target_url="http://app/home",
            root_frame_id="frame_root",
            elements=(web_elem,),
        )

        reconcil = self.reconciler.reconcile(native_obs, web_obs)
        self.assertEqual(reconcil.relationship_type, RelationshipType.HOSTS)
        self.assertEqual(len(reconcil.contradictions), 0)
        self.assertEqual(reconcil.confidence, Certainty.DEFINITIVE)

    def test_physical_reality_primacy_minimized_contradiction(self):
        """When native window is minimized, DOM visibility claim is flagged as CONTRADICTION."""
        native_obs = NativeObservation(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            hwnd=0x1000,
            title="Desktop App",
            class_name="QtWindow",
            pid=2000,
            bounds=Rect(0, 0, 0, 0),
            client_bounds=Rect(0, 0, 0, 0),
            is_visible=False,
            is_minimized=True,  # Minimized!
            is_cloaked=False,
            is_responsive=True,
        )

        web_elem = WebElementObservation(
            session_id=self.session_id,
            observation_epoch=1,
            timestamp=self.now,
            source_plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_1",
            reference="w1e1",
            role="button",
            normalized_role="button",
            bounds=Rect(200, 200, 100, 40),
            visibility=VisibilityObservation(
                attached=True,
                visible=True,  # DOM says visible!
                in_viewport=True,
                physically_occluded=False,
            ),
        )

        web_obs = WebObservation(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            target_id="target_1",
            target_title="Web Title",
            target_url="http://app/home",
            root_frame_id="frame_root",
            elements=(web_elem,),
        )

        reconcil = self.reconciler.reconcile(native_obs, web_obs)
        self.assertEqual(reconcil.confidence, Certainty.CONTRADICTORY)
        self.assertEqual(reconcil.physical_visibility_status, "MINIMIZED")
        self.assertTrue(any("minimized" in c.lower() for c in reconcil.contradictions))

    def test_hung_native_window_contradiction(self):
        """Unresponsive UI thread surfaces contradiction."""
        native_obs = NativeObservation(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            hwnd=0x1000,
            title="Frozen App",
            class_name="QtWindow",
            pid=2000,
            bounds=Rect(100, 100, 500, 400),
            client_bounds=Rect(100, 130, 500, 370),
            is_visible=True,
            is_minimized=False,
            is_cloaked=False,
            is_responsive=False,  # HUNG!
        )

        web_obs = WebObservation(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            target_id="target_1",
            target_title="Web Title",
            target_url="http://app/home",
            root_frame_id="frame_root",
            elements=(),
        )

        reconcil = self.reconciler.reconcile(native_obs, web_obs)
        self.assertTrue(any("hung" in c.lower() for c in reconcil.contradictions))


if __name__ == "__main__":
    unittest.main()
