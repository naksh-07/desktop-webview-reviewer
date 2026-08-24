"""
Tests for MultiTargetSessionManager and target ranking diagnostics.
"""

import unittest
import sys

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from core.models import Target, TargetCriteria
from core.discovery import TargetDiscovery
from core.session import MultiTargetSessionManager


class TestMultiTargetManager(unittest.TestCase):
    def setUp(self):
        self.mock_targets = [
            Target(
                id="t_main",
                type="page",
                title="Primary Desktop Application",
                url="app://index.html",
                engine="webview2",
                websocket_endpoint="ws://127.0.0.1:9222/devtools/page/t_main"
            ),
            Target(
                id="t_settings",
                type="page",
                title="Application Settings Window",
                url="app://settings.html",
                engine="webview2",
                websocket_endpoint="ws://127.0.0.1:9222/devtools/page/t_settings"
            ),
            Target(
                id="t_devtools",
                type="page",
                title="Developer Tools - app://index.html",
                url="devtools://devtools/bundled/inspector.html",
                engine="webview2",
                websocket_endpoint="ws://127.0.0.1:9222/devtools/page/t_devtools"
            ),
            Target(
                id="t_worker",
                type="service_worker",
                title="Background Sync Worker",
                url="app://sw.js",
                engine="webview2",
                websocket_endpoint="ws://127.0.0.1:9222/devtools/page/t_worker"
            ),
            Target(
                id="t_ext",
                type="background_page",
                title="Edge Extension Background",
                url="chrome-extension://xyz123/bg.html",
                engine="webview2",
                websocket_endpoint="ws://127.0.0.1:9222/devtools/page/t_ext"
            )
        ]

    def test_target_ranking_and_diagnostics_formatting(self):
        for t in self.mock_targets:
            TargetDiscovery.rank_target(t)

        selected = TargetDiscovery.select_target(self.mock_targets)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "t_main")

        diagnostics = TargetDiscovery.format_ranking_diagnostics(self.mock_targets, selected_target=selected)
        self.assertIn("Target ranking diagnostics:", diagnostics)
        self.assertIn("Primary Desktop Application", diagnostics)
        self.assertIn("[SELECTED]", diagnostics)
        self.assertIn("filtered", diagnostics)
        self.assertIn("Ignored type: 'service_worker'", diagnostics)
        self.assertIn("Ignored URL prefix: 'devtools://devtools/bundled/in...'", diagnostics)

    def test_select_specific_secondary_target(self):
        criteria = TargetCriteria(title_pattern="Settings")
        selected = TargetDiscovery.select_target(self.mock_targets, criteria=criteria)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "t_settings")
        self.assertEqual(selected.title, "Application Settings Window")

    def test_manager_target_filtering_and_ranking(self):
        manager = MultiTargetSessionManager(host="127.0.0.1", port=9222, engine="webview2")
        filtered = TargetDiscovery.filter_targets(self.mock_targets)
        self.assertEqual(len(filtered), 5)
        # First candidate must be highest scored application target
        self.assertEqual(filtered[0].id, "t_main")
        self.assertTrue(filtered[0].is_application)
        self.assertFalse(filtered[-1].is_application)


if __name__ == "__main__":
    unittest.main()
