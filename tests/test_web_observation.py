"""
Unit tests for Web Semantic Observation Extractor (Phase 4).
Verifies extraction of webview candidates, role normalization, frame contexts,
sequential reference assignment, and selective compact filtering.
"""

import unittest
from unittest.mock import MagicMock, AsyncMock
from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane, AXFreshnessStatus
from runtime.webview_core import WebviewAutomationCore
from runtime.ax_runtime import AXSnapshot, AXNodeInfo
from runtime.frame_manager import FrameContext
from runtime.web_observation import WebObservationExtractor


class TestWebObservation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_id = "test_sess_web"
        self.registry = ReferenceRegistry(self.session_id, initial_epoch=1)
        self.core = MagicMock(spec=WebviewAutomationCore)
        self.core.is_connected = True
        self.core.native_hwnd = 0x5000

        # Target Manager mock
        self.core.target_manager = MagicMock()
        target_info = MagicMock()
        target_info.title = "Maths Deck Review"
        target_info.url = "http://127.0.0.1:8000/deck"
        self.core.target_manager.get_target.return_value = target_info

        # Frame Manager mock
        self.core.frame_manager = MagicMock()
        self.core.frame_manager.root_frame_id = "root_f1"
        self.core.frame_manager.frames = {
            "root_f1": FrameContext(
                frame_id="root_f1",
                parent_frame_id=None,
                loader_id="loader_1",
                url="http://127.0.0.1:8000/deck",
                security_origin="http://127.0.0.1:8000",
                is_accessible=True,
                is_root=True,
            ),
            "child_f2": FrameContext(
                frame_id="child_f2",
                parent_frame_id="root_f1",
                loader_id="loader_2",
                url="http://127.0.0.1:8000/inner",
                security_origin="http://127.0.0.1:8000",
                is_accessible=True,
                is_root=False,
            )
        }

        # Accessibility Runtime mock
        self.core.ax_runtime = MagicMock()
        self.core.ax_runtime.acquire_snapshot = AsyncMock(return_value=AXSnapshot(
            nodes=[
                AXNodeInfo(node_id="ax_1", role="Button", name="Next Card"),
                AXNodeInfo(node_id="ax_2", role="Heading", name="Card 1 of 20"),
            ],
            node_count=2,
            dom_element_count=10,
            ratio=0.2,
            freshness=AXFreshnessStatus.FRESH,
            captured_at=100.0,
            loader_id="loader_1",
            epoch=1,
        ))

        # Utility World mock
        self.core.utility_world = MagicMock()
        self.core.utility_world.evaluate = AsyncMock(return_value={
            "dpr": 1.5,
            "innerWidth": 1024,
            "innerHeight": 768,
            "candidates": [
                {
                    "tag": "h1",
                    "text": "Card 1 of 20",
                    "rect": {"x": 20, "y": 20, "width": 300, "height": 40},
                    "display": "block",
                    "visibility": "visible",
                    "opacity": 1.0,
                    "in_viewport": True,
                },
                {
                    "tag": "button",
                    "text": "Next Card",
                    "rect": {"x": 20, "y": 100, "width": 120, "height": 35},
                    "display": "inline-block",
                    "visibility": "visible",
                    "opacity": 1.0,
                    "in_viewport": True,
                    "is_disabled": False,
                    "is_focused": True,
                },
                {
                    "tag": "input",
                    "type": "text",
                    "placeholder": "Enter your answer...",
                    "rect": {"x": 20, "y": 150, "width": 250, "height": 30},
                    "display": "block",
                    "visibility": "visible",
                    "opacity": 1.0,
                    "in_viewport": True,
                    "is_disabled": False,
                }
            ]
        })

    async def test_observe_webview_creates_elements_and_refs(self):
        """Extracts web elements, applies role normalization, and registers sequential w1eN refs."""
        extractor = WebObservationExtractor(
            webview_core=self.core,
            reference_registry=self.registry,
        )

        obs = await extractor.observe_webview(self.session_id, target_id="target_01")
        self.assertEqual(obs.target_title, "Maths Deck Review")
        self.assertEqual(len(obs.frames), 2)
        self.assertEqual(len(obs.elements), 3)

        # Check references
        refs = [e.reference for e in obs.elements]
        self.assertEqual(refs, ["w1e1", "w1e2", "w1e3"])

        # Heading
        h1 = obs.elements[0]
        self.assertEqual(h1.normalized_role, "heading")
        self.assertEqual(h1.accessible_name, "Card 1 of 20")

        # Button
        btn = obs.elements[1]
        self.assertEqual(btn.normalized_role, "button")
        self.assertEqual(btn.accessible_name, "Next Card")
        self.assertTrue(btn.interaction.is_enabled)
        self.assertTrue(btn.interaction.is_focused)

        # Textbox
        tb = obs.elements[2]
        self.assertEqual(tb.normalized_role, "textbox")
        self.assertEqual(tb.placeholder, "Enter your answer...")

        # Registry checks
        btn_ref = self.registry.resolve_ref("w1e2")
        self.assertEqual(btn_ref.role, "button")
        self.assertEqual(btn_ref.plane, TargetPlane.WEBVIEW_DOM)

    async def test_actionable_only_filtering(self):
        """When actionable_only=True, headings and non-actionable elements are filtered out."""
        extractor = WebObservationExtractor(
            webview_core=self.core,
            reference_registry=self.registry,
        )

        obs = await extractor.observe_webview(
            self.session_id,
            target_id="target_01",
            actionable_only=True,
        )
        roles = [e.normalized_role for e in obs.elements]
        self.assertNotIn("heading", roles)
        self.assertIn("button", roles)
        self.assertIn("textbox", roles)


if __name__ == "__main__":
    unittest.main()
