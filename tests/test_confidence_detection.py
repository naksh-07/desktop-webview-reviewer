"""
Tests for multi-signal engine detection, confidence scoring, and framework vs engine separation.
"""

import os
import sys
import unittest
import tempfile
import json

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from core.models import ConfidenceLevel, DetectionSignal, EngineInfo, VerificationLevel
from detectors.engine_detector import EngineDetector, FrameworkRouter
from adapters import get_adapter


class TestConfidenceDetection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tauri_project_detection_signals_and_confidence(self):
        # Create mock Tauri structure
        src_tauri = os.path.join(self.temp_dir.name, "src-tauri")
        os.makedirs(src_tauri, exist_ok=True)
        with open(os.path.join(src_tauri, "tauri.conf.json"), "w") as f:
            json.dump({"package": {"productName": "MyTauriApp"}}, f)

        adapter, info = EngineDetector.detect_with_details(self.temp_dir.name)
        self.assertIsNotNone(adapter)
        self.assertIsNotNone(info)
        if sys.platform == "win32":
            self.assertEqual(adapter.engine_name, "webview2")
            self.assertEqual(info.engine, "webview2")
        else:
            self.assertEqual(adapter.engine_name, "webkit")
            self.assertEqual(info.engine, "webkit")

        self.assertEqual(info.framework, "tauri")
        self.assertEqual(info.confidence, ConfidenceLevel.HIGH)
        self.assertTrue(len(info.signals) > 0)
        self.assertEqual(info.signals[0].indicator, "tauri.conf.json")
        self.assertEqual(info.signals[0].source, "manifest")

    def test_wails_project_detection(self):
        with open(os.path.join(self.temp_dir.name, "wails.json"), "w") as f:
            json.dump({"name": "MyWailsApp"}, f)

        adapter, info = EngineDetector.detect_with_details(self.temp_dir.name)
        self.assertIsNotNone(adapter)
        self.assertIsNotNone(info)
        self.assertEqual(info.framework, "wails")
        self.assertEqual(info.confidence, ConfidenceLevel.HIGH)
        self.assertEqual(info.signals[0].indicator, "wails.json")

    def test_electron_package_json_detection(self):
        with open(os.path.join(self.temp_dir.name, "package.json"), "w") as f:
            json.dump({"name": "my-electron-app", "devDependencies": {"electron": "^28.0.0"}}, f)

        adapter, info = EngineDetector.detect_with_details(self.temp_dir.name)
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.engine_name, "electron")
        self.assertEqual(info.framework, "electron")
        self.assertEqual(info.confidence, ConfidenceLevel.HIGH)

    def test_dotnet_csproj_webview2_detection(self):
        with open(os.path.join(self.temp_dir.name, "App.csproj"), "w") as f:
            f.write('<Project><PackageReference Include="Microsoft.Web.WebView2" Version="1.0.0" /></Project>')

        adapter, info = EngineDetector.detect_with_details(self.temp_dir.name)
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.engine_name, "webview2")
        self.assertEqual(info.framework, "dotnet")
        self.assertEqual(info.confidence, ConfidenceLevel.HIGH)

    def test_python_qt_script_detection(self):
        script_path = os.path.join(self.temp_dir.name, "gui.py")
        with open(script_path, "w") as f:
            f.write("from PyQt6.QtWebEngineWidgets import QWebEngineView\napp = None\n")

        adapter, info = EngineDetector.detect_with_details(script_path)
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.engine_name, "qtwebengine")
        self.assertEqual(info.framework, "qt")
        self.assertEqual(info.confidence, ConfidenceLevel.HIGH)

    def test_explicit_override_precedence(self):
        # Passing an explicit override should bypass detection
        adapter = EngineDetector.resolve_adapter(engine_name_or_hint="webview2", target_path_or_pid="nonexistent_path")
        self.assertEqual(adapter.engine_name, "webview2")

        adapter_cef = EngineDetector.resolve_adapter(engine_name_or_hint="cef")
        self.assertEqual(adapter_cef.engine_name, "chromium")


if __name__ == "__main__":
    unittest.main()
