"""
Unit tests for engine detection heuristics and FrameworkRouter.
"""

import sys
import unittest
import tempfile
import os
import json

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from detectors.engine_detector import EngineDetector, FrameworkRouter
from adapters import QtWebEngineAdapter, WebView2Adapter, ElectronAdapter, ChromiumAdapter, WebKitAdapter


class TestEngineDetection(unittest.TestCase):
    def test_resolve_adapter_with_hint(self):
        self.assertIsInstance(EngineDetector.resolve_adapter("electron"), ElectronAdapter)
        self.assertIsInstance(EngineDetector.resolve_adapter("webview2"), WebView2Adapter)
        self.assertIsInstance(EngineDetector.resolve_adapter("chromium"), ChromiumAdapter)
        self.assertIsInstance(EngineDetector.resolve_adapter("webkit"), WebKitAdapter)
        self.assertIsInstance(EngineDetector.resolve_adapter("qtwebengine"), QtWebEngineAdapter)

    def test_detect_from_package_json_electron(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_path = os.path.join(tmpdir, "package.json")
            with open(pkg_path, "w") as f:
                json.dump({"name": "test-app", "devDependencies": {"electron": "^28.0.0"}}, f)

            adapter = EngineDetector.resolve_adapter(target_path_or_pid=tmpdir)
            self.assertIsInstance(adapter, ElectronAdapter)

    def test_detect_from_tauri_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tauri_dir = os.path.join(tmpdir, "src-tauri")
            os.makedirs(tauri_dir, exist_ok=True)
            with open(os.path.join(tauri_dir, "tauri.conf.json"), "w") as f:
                json.dump({"package": {"productName": "tauri-app"}}, f)

            adapter = EngineDetector.resolve_adapter(target_path_or_pid=tmpdir)
            if sys.platform == "win32":
                self.assertIsInstance(adapter, WebView2Adapter)
            else:
                self.assertIsInstance(adapter, WebKitAdapter)

    def test_detect_from_wails_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            wails_path = os.path.join(tmpdir, "wails.json")
            with open(wails_path, "w") as f:
                json.dump({"name": "wails-app"}, f)

            adapter = EngineDetector.resolve_adapter(target_path_or_pid=tmpdir)
            if sys.platform == "win32":
                self.assertIsInstance(adapter, WebView2Adapter)
            else:
                self.assertIsInstance(adapter, WebKitAdapter)

    def test_detect_from_python_qt_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, "my_qt_app.py")
            with open(script_path, "w") as f:
                f.write("from PyQt6.QtWebEngineWidgets import QWebEngineView\n")

            adapter = EngineDetector.resolve_adapter(target_path_or_pid=script_path)
            self.assertIsInstance(adapter, QtWebEngineAdapter)


if __name__ == "__main__":
    unittest.main()
