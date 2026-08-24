"""
Unit tests for intelligent multi-target ranking and filtering.
"""

import sys
import unittest

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from core.models import Target, TargetCriteria
from core.discovery import TargetDiscovery


class TestTargetRanking(unittest.TestCase):
    def setUp(self):
        self.app_target = Target(
            id="target_main_window",
            type="page",
            title="My Desktop App - Home",
            url="file:///C:/app/index.html",
            engine="electron",
            websocket_endpoint="ws://127.0.0.1:9222/devtools/page/1"
        )
        self.devtools_target = Target(
            id="target_devtools",
            type="page",
            title="DevTools - file:///C:/app/index.html",
            url="devtools://devtools/bundled/inspector.html",
            engine="electron",
            websocket_endpoint="ws://127.0.0.1:9222/devtools/page/2"
        )
        self.service_worker_target = Target(
            id="target_sw",
            type="service_worker",
            title="SW",
            url="file:///C:/app/sw.js",
            engine="electron",
            websocket_endpoint="ws://127.0.0.1:9222/devtools/page/3"
        )
        self.blank_target = Target(
            id="target_blank",
            type="page",
            title="",
            url="about:blank",
            engine="electron",
            websocket_endpoint="ws://127.0.0.1:9222/devtools/page/4"
        )
        self.extension_target = Target(
            id="target_ext",
            type="page",
            title="Extension",
            url="chrome-extension://abcdefg/popup.html",
            engine="electron",
            websocket_endpoint="ws://127.0.0.1:9222/devtools/page/5"
        )

    def test_application_target_filtering(self):
        self.assertTrue(TargetDiscovery.is_application_target(self.app_target))
        self.assertFalse(TargetDiscovery.is_application_target(self.devtools_target))
        self.assertFalse(TargetDiscovery.is_application_target(self.service_worker_target))
        self.assertFalse(TargetDiscovery.is_application_target(self.blank_target))
        self.assertFalse(TargetDiscovery.is_application_target(self.extension_target))

    def test_target_ranking_order(self):
        targets = [
            self.blank_target,
            self.service_worker_target,
            self.devtools_target,
            self.extension_target,
            self.app_target,
        ]
        ranked = TargetDiscovery.filter_targets(targets)
        # The main app window must be first
        self.assertEqual(ranked[0].id, self.app_target.id)

    def test_select_target_with_title_criteria(self):
        secondary_target = Target(
            id="target_settings_dialog",
            type="page",
            title="App Settings",
            url="file:///C:/app/settings.html",
            engine="electron",
            websocket_endpoint="ws://127.0.0.1:9222/devtools/page/6"
        )
        targets = [self.app_target, secondary_target, self.devtools_target]

        criteria = TargetCriteria(title_pattern="Settings")
        selected = TargetDiscovery.select_target(targets, criteria)
        self.assertEqual(selected.id, secondary_target.id)

    def test_fallback_selection_when_criteria_unmatched(self):
        targets = [self.devtools_target, self.app_target]
        criteria = TargetCriteria(title_pattern="NonExistentTitle")
        # Should gracefully fall back to the best available application target
        selected = TargetDiscovery.select_target(targets, criteria)
        self.assertEqual(selected.id, self.app_target.id)


if __name__ == "__main__":
    unittest.main()
