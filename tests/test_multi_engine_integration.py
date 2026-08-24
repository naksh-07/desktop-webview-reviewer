"""
Multi-engine integration test suite verifying end-to-end adapter contracts,
framework routing, target ranking, and CLI commands.
"""

import os
import sys
import unittest
import subprocess

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from adapters import list_adapters, get_adapter
from detectors.engine_detector import EngineDetector, FrameworkRouter
from core.models import CapabilityName, CapabilityStatus, Target, TargetCriteria
from core.discovery import TargetDiscovery
from core.capabilities import CapabilityRegistry


class TestMultiEngineIntegration(unittest.TestCase):
    def test_all_adapters_initialized_and_typed(self):
        expected_engines = ["qtwebengine", "webview2", "electron", "chromium", "webkit"]
        self.assertEqual(sorted(list_adapters()), sorted(expected_engines))

        for eng in expected_engines:
            adapter = get_adapter(eng)
            self.assertIsNotNone(adapter)
            self.assertEqual(adapter.engine_name, eng)
            info = adapter.get_engine_info()
            self.assertEqual(info.engine, eng)
            self.assertIsInstance(info.capabilities, dict)
            self.assertIn(CapabilityName.DOM.value, info.capabilities)
            self.assertIn(CapabilityName.JS.value, info.capabilities)

    def test_framework_routing_cross_platform(self):
        # Tauri on Windows -> webview2
        tauri_win_eng, tauri_win_fw = FrameworkRouter.resolve_framework("tauri")
        if sys.platform == "win32":
            self.assertEqual(tauri_win_eng, "webview2")
        self.assertEqual(tauri_win_fw, "tauri")

        # CEF -> chromium
        cef_eng, cef_fw = FrameworkRouter.resolve_framework("cef")
        self.assertEqual(cef_eng, "chromium")
        self.assertEqual(cef_fw, "cef")

    def test_target_ranking_heuristics_complex(self):
        targets = [
            Target("t1", "service_worker", "SW", "file:///app/sw.js", "electron"),
            Target("t2", "page", "", "about:blank", "electron"),
            Target("t3", "page", "DevTools - App", "devtools://devtools/inspector.html", "electron"),
            Target("t4", "page", "App Main Window", "file:///app/index.html", "electron"),
            Target("t5", "page", "Dialog Window", "file:///app/dialog.html", "electron"),
        ]

        # Ranking without criteria should select Main Window
        ranked = TargetDiscovery.filter_targets(targets)
        self.assertIn(ranked[0].id, ("t4", "t5"))
        self.assertNotIn(ranked[0].id, ("t1", "t2", "t3"))

        # Ranking with criteria Dialog
        selected = TargetDiscovery.select_target(targets, TargetCriteria(title_pattern="Dialog"))
        self.assertEqual(selected.id, "t5")

    def test_cli_help_and_arguments(self):
        scripts = ["doctor.py", "launch.py", "discover.py", "attach.py", "review.py", "stop.py"]
        for s in scripts:
            script_path = os.path.join(CORE_SKILL_DIR, "scripts", s)
            res = subprocess.run([sys.executable, script_path, "--help"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Script {s} --help failed: {res.stderr}")
            self.assertIn("usage:", res.stdout.lower())


if __name__ == "__main__":
    unittest.main()
