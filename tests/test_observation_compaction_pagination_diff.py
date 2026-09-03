"""
Unit tests for Observation Compaction (YAML), Pagination, and Differential Snapshots (Phase 4).
"""

import unittest
import time
from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane
from runtime.errors import StaleReferenceException
from runtime.observation_models import (
    DualPerspectiveSnapshot,
    NativeObservation,
    WebObservation,
    WebElementObservation,
    NativeElementObservation,
    VisibilityObservation,
    InteractionObservation,
    ReconciliationObservation,
    RelationshipType,
    RoleSource,
)
from runtime.observation_compaction import format_observation_yaml
from runtime.observation_pagination import ObservationPaginator
from runtime.observation_diff import ObservationDiffer


class TestCompactionPaginationDiff(unittest.TestCase):
    def setUp(self):
        self.session_id = "test_cpd_sess"
        self.now = time.time()
        self.registry = ReferenceRegistry(self.session_id, initial_epoch=1)

    def _create_web_elem(self, ref: str, role: str, name: str, x: int = 10, y: int = 10, text: str = ""):
        return WebElementObservation(
            session_id=self.session_id,
            observation_epoch=1,
            timestamp=self.now,
            source_plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            reference=ref,
            role=role,
            normalized_role=role,
            role_source=RoleSource.DOM,
            accessible_name=name,
            visible_text=text or name,
            frame_id="frame_root",
            bounds=Rect(x, y, 100, 30),
            visibility=VisibilityObservation(attached=True, visible=True, in_viewport=True, physically_occluded=False),
            interaction=InteractionObservation(is_enabled=True, is_focused=False, affordance_point=(x + 50, y + 15), supported_actions=("click",)),
        )

    def test_observation_compaction_yaml(self):
        """Observation formats to concise, token-efficient YAML following Section 14."""
        web_elem1 = self._create_web_elem("w1e1", "button", "Start Quiz")
        web_elem2 = self._create_web_elem("w1e2", "textbox", "Search...", text="")

        web_obs = WebObservation(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            target_id="target_01",
            target_title="Deck Quiz",
            target_url="http://app/quiz",
            root_frame_id="frame_root",
            elements=(web_elem1, web_elem2),
        )

        yaml_str = format_observation_yaml(native_obs=None, web_obs=web_obs, reconciliation=None)
        self.assertIn("# Observation Epoch: 1", yaml_str)
        self.assertIn("@@ webview: [target=target_01, title=\"Deck Quiz\"] @@", yaml_str)
        self.assertIn("- button \"Start Quiz\" [ref=w1e1] [role=button]", yaml_str)
        self.assertIn("- textbox \"Search...\" [ref=w1e2] [role=textbox]", yaml_str)

    def test_observation_pagination_pages_and_cursor(self):
        """Paginator correctly segments large trees and generates epoch-scoped cursors."""
        paginator = ObservationPaginator(self.registry)
        elements = [self._create_web_elem(f"w1e{i}", "button", f"Button {i}") for i in range(1, 51)]

        # Page 1 (25 elements)
        p1, cursor1, meta1 = paginator.paginate_web_elements(elements, page_size=25)
        self.assertEqual(len(p1), 25)
        self.assertEqual(meta1["page"], 1)
        self.assertEqual(meta1["total_pages"], 2)
        self.assertTrue(meta1["has_more"])
        self.assertIsNotNone(cursor1)

        # Page 2
        p2, cursor2, meta2 = paginator.paginate_web_elements(elements, page_size=25, cursor=cursor1)
        self.assertEqual(len(p2), 25)
        self.assertEqual(meta2["page"], 2)
        self.assertFalse(meta2["has_more"])
        self.assertIsNone(cursor2)

    def test_pagination_stale_cursor_rejected(self):
        """Cursor from previous epoch raises StaleReferenceException."""
        paginator = ObservationPaginator(self.registry)
        elements = [self._create_web_elem(f"w1e{i}", "button", f"Button {i}") for i in range(1, 10)]

        p1, cursor1, _ = paginator.paginate_web_elements(elements, page_size=5)
        self.assertIsNotNone(cursor1)

        # Increment epoch to 2
        self.registry.advance_epoch()
        self.assertEqual(self.registry.current_epoch, 2)

        # Presenting old cursor must fail
        with self.assertRaises(StaleReferenceException):
            paginator.paginate_web_elements(elements, page_size=5, cursor=cursor1)

    def test_observation_diff_computation(self):
        """Differ identifies added, removed, and modified elements."""
        differ = ObservationDiffer()

        e1 = self._create_web_elem("w1e1", "button", "Start Quiz")
        e2 = self._create_web_elem("w1e2", "textbox", "Name", text="Alice")

        snap1 = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now,
            web_observation=WebObservation(
                session_id=self.session_id, epoch=1, timestamp=self.now,
                target_id="t1", target_title="T", target_url="U", root_frame_id="f1",
                elements=(e1, e2),
            ),
        )

        # In epoch 2: e1 is removed, e2 text changed, e3 is added
        e2_mod = self._create_web_elem("w2e1", "textbox", "Name", text="Bob")
        e3 = self._create_web_elem("w2e2", "button", "Submit")

        snap2 = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=2,
            timestamp=self.now + 1.0,
            web_observation=WebObservation(
                session_id=self.session_id, epoch=2, timestamp=self.now + 1.0,
                target_id="t1", target_title="T", target_url="U", root_frame_id="f1",
                elements=(e2_mod, e3),
            ),
        )

        diff_res = differ.diff(snap1, snap2)
        self.assertEqual(diff_res.from_epoch, 1)
        self.assertEqual(diff_res.to_epoch, 2)

        self.assertEqual(len(diff_res.added), 1)
        self.assertEqual(diff_res.added[0].name, "Submit")

        self.assertEqual(len(diff_res.removed), 1)
        self.assertEqual(diff_res.removed[0].name, "Start Quiz")

        self.assertEqual(len(diff_res.modified), 1)
        self.assertEqual(diff_res.modified[0].name, "Name")
        self.assertTrue(any("text: 'Alice' -> 'Bob'" in c for c in diff_res.modified[0].changes))

        # Check diff syntax in rendered text
        self.assertIn("- button \"Start Quiz\"", diff_res.text_diff)
        self.assertIn("+ button \"Submit\"", diff_res.text_diff)
        self.assertIn("~ textbox \"Name\"", diff_res.text_diff)


if __name__ == "__main__":
    unittest.main()
