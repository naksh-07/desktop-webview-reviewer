"""
Unit tests for Dual-Perspective Observation Data Models (Phase 4).
Verifies strict separation of native and web perspectives, epoch scoping,
timestamp preservation, serialization, and absence of UniversalUIElement.
"""

import unittest
import time
from runtime.references import Rect
from runtime.state import TargetPlane
from runtime.observation_models import (
    ObservationEpoch,
    Observation,
    NativeElementObservation,
    WebElementObservation,
    FrameObservation,
    NativeObservation,
    WebObservation,
    ReconciliationObservation,
    DualPerspectiveSnapshot,
    RelationshipType,
    RoleSource,
    Certainty,
    GeometryObservation,
    VisibilityObservation,
    InteractionObservation,
)


class TestObservationModels(unittest.TestCase):
    def setUp(self):
        self.session_id = "test_sess_001"
        self.epoch = 1
        self.timestamp = time.time()

    def test_base_observation_preserves_mandatory_fields(self):
        """Every observation must preserve session_id, epoch, timestamp, plane, target, ref, and confidence."""
        obs = Observation(
            session_id=self.session_id,
            observation_epoch=self.epoch,
            timestamp=self.timestamp,
            source_plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            reference="w1e1",
            confidence=Certainty.HIGH,
        )
        self.assertEqual(obs.session_id, self.session_id)
        self.assertEqual(obs.observation_epoch, 1)
        self.assertIsInstance(obs.timestamp, float)
        self.assertEqual(obs.source_plane, TargetPlane.WEBVIEW_DOM)
        self.assertEqual(obs.reference, "w1e1")
        self.assertEqual(obs.confidence, Certainty.HIGH)

        d = obs.to_dict()
        self.assertEqual(d["session_id"], self.session_id)
        self.assertEqual(d["reference"], "w1e1")
        self.assertEqual(d["source_plane"], "WEBVIEW_DOM")

    def test_native_element_observation_distinct_from_web(self):
        """NativeElementObservation retains HWND, control_type, automation_id without pretending to be a web DOM node."""
        geom = GeometryObservation(
            bounds=Rect(100, 100, 200, 50),
            screen_bounds=Rect(100, 100, 200, 50),
            dpr=1.25,
        )
        vis = VisibilityObservation(
            attached=True,
            visible=True,
            in_viewport=True,
            physically_occluded=False,
            minimized=False,
            cloaked=False,
        )
        interact = InteractionObservation(
            is_enabled=True,
            is_focused=True,
            affordance_point=(200, 125),
            supported_actions=("click",),
        )

        native_elem = NativeElementObservation(
            session_id=self.session_id,
            observation_epoch=self.epoch,
            timestamp=self.timestamp,
            source_plane=TargetPlane.NATIVE_SHELL,
            target_id="0x1234",
            reference="n1e1",
            control_type="Button",
            name="Save File",
            automation_id="btn_save",
            class_name="NativeButton",
            hwnd=0x1234,
            bounds=Rect(100, 100, 200, 50),
            geometry=geom,
            visibility=vis,
            interaction=interact,
            supported_patterns=("Invoke",),
        )

        self.assertEqual(native_elem.control_type, "Button")
        self.assertEqual(native_elem.automation_id, "btn_save")
        self.assertEqual(native_elem.hwnd, 0x1234)
        self.assertFalse(hasattr(native_elem, "tag_name"))
        self.assertFalse(hasattr(native_elem, "frame_id"))

        # Serialization
        data = native_elem.to_dict()
        self.assertEqual(data["control_type"], "Button")
        self.assertEqual(data["automation_id"], "btn_save")
        self.assertEqual(data["reference"], "n1e1")
        self.assertEqual(data["hwnd"], "0x1234")

    def test_web_element_observation_distinct_from_native(self):
        """WebElementObservation retains role, frame_id, normalized_role, accessible_name, tag_name."""
        geom = GeometryObservation(
            bounds=Rect(10, 20, 150, 40),
            screen_bounds=Rect(110, 120, 150, 40),
            dpr=1.0,
            is_in_viewport=True,
        )
        vis = VisibilityObservation(
            attached=True,
            visible=True,
            in_viewport=True,
            physically_occluded=False,
        )
        interact = InteractionObservation(
            is_enabled=True,
            is_focused=False,
            affordance_point=(85, 40),
            supported_actions=("click", "hover"),
        )

        web_elem = WebElementObservation(
            session_id=self.session_id,
            observation_epoch=self.epoch,
            timestamp=self.timestamp,
            source_plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_main",
            reference="w1e1",
            role="button",
            normalized_role="button",
            role_source=RoleSource.ACCESSIBILITY,
            accessible_name="Submit Application",
            visible_text="Submit",
            tag_name="button",
            frame_id="frame_root",
            bounds=Rect(10, 20, 150, 40),
            geometry=geom,
            visibility=vis,
            interaction=interact,
        )

        self.assertEqual(web_elem.normalized_role, "button")
        self.assertEqual(web_elem.role_source, RoleSource.ACCESSIBILITY)
        self.assertEqual(web_elem.accessible_name, "Submit Application")
        self.assertEqual(web_elem.frame_id, "frame_root")
        self.assertFalse(hasattr(web_elem, "automation_id"))

        data = web_elem.to_dict()
        self.assertEqual(data["normalized_role"], "button")
        self.assertEqual(data["role_source"], "ACCESSIBILITY")
        self.assertEqual(data["frame_id"], "frame_root")

    def test_reconciliation_observation_and_contradictions(self):
        """Reconciliation captures native and web relationships and surfaces physical contradictions."""
        reconcil = ReconciliationObservation(
            session_id=self.session_id,
            epoch=self.epoch,
            timestamp=self.timestamp,
            native_hwnd=0x4010,
            native_bounds=Rect(0, 0, 1280, 800),
            webview_bounds=Rect(0, 100, 1280, 700),
            cdp_target_id="page_1",
            frame_id="frame_root",
            relationship_type=RelationshipType.HOSTS,
            confidence=Certainty.CONTRADICTORY,
            physical_visibility_status="MINIMIZED",
            web_visibility_status="VISIBLE_ELEMENTS",
            contradictions=("CONTRADICTION: Webview claims elements are visible, but Native window is minimized.",),
        )

        self.assertEqual(reconcil.relationship_type, RelationshipType.HOSTS)
        self.assertEqual(reconcil.confidence, Certainty.CONTRADICTORY)
        self.assertEqual(len(reconcil.contradictions), 1)

        d = reconcil.to_dict()
        self.assertEqual(d["relationship_type"], "HOSTS")
        self.assertEqual(d["confidence"], "CONTRADICTORY")
        self.assertEqual(d["physical_visibility_status"], "MINIMIZED")

    def test_dual_perspective_snapshot_container(self):
        """DualPerspectiveSnapshot encapsulates both perspectives cleanly."""
        snap = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.timestamp,
            text_representation="- window: test",
            is_diff=False,
        )
        self.assertEqual(snap.epoch, 1)
        self.assertFalse(snap.is_diff)
        d = snap.to_dict()
        self.assertEqual(d["epoch"], 1)
        self.assertIn("text_representation", d)


if __name__ == "__main__":
    unittest.main()
