"""
Unit tests for adapter registry and cross-platform framework routing.
"""

import sys
import unittest
import os

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from adapters import (
    list_adapters,
    get_adapter,
    get_default_adapter,
    BaseEngineAdapter,
    QtWebEngineAdapter,
    WebView2Adapter,
    ElectronAdapter,
    ChromiumAdapter,
    WebKitAdapter,
)
from detectors.engine_detector import FrameworkRouter, EngineDetector


class TestAdapterRegistry(unittest.TestCase):
    def test_all_five_adapters_registered(self):
        adapters = list_adapters()
        self.assertIn("qtwebengine", adapters)
        self.assertIn("webview2", adapters)
        self.assertIn("electron", adapters)
        self.assertIn("chromium", adapters)
        self.assertIn("webkit", adapters)
        self.assertEqual(len(adapters), 5)

    def test_get_adapter_direct_names(self):
        self.assertIsInstance(get_adapter("qtwebengine"), QtWebEngineAdapter)
        self.assertIsInstance(get_adapter("webview2"), WebView2Adapter)
        self.assertIsInstance(get_adapter("electron"), ElectronAdapter)
        self.assertIsInstance(get_adapter("chromium"), ChromiumAdapter)
        self.assertIsInstance(get_adapter("webkit"), WebKitAdapter)

    def test_framework_alias_routing(self):
        # CEF aliases
        self.assertIsInstance(get_adapter("cef"), ChromiumAdapter)
        self.assertIsInstance(get_adapter("cefsharp"), ChromiumAdapter)

        # Qt aliases
        self.assertIsInstance(get_adapter("pyqt"), QtWebEngineAdapter)
        self.assertIsInstance(get_adapter("pyside"), QtWebEngineAdapter)
        self.assertIsInstance(get_adapter("pyqt6"), QtWebEngineAdapter)

        # WebKit aliases
        self.assertIsInstance(get_adapter("webkitgtk"), WebKitAdapter)
        self.assertIsInstance(get_adapter("wkwebview"), WebKitAdapter)

        # OS-dependent aliases (Tauri / Wails)
        if sys.platform == "win32":
            self.assertIsInstance(get_adapter("tauri"), WebView2Adapter)
            self.assertIsInstance(get_adapter("wails"), WebView2Adapter)
            self.assertIsInstance(get_adapter("pywebview"), WebView2Adapter)
        else:
            self.assertIsInstance(get_adapter("tauri"), WebKitAdapter)
            self.assertIsInstance(get_adapter("wails"), WebKitAdapter)
            self.assertIsInstance(get_adapter("pywebview"), WebKitAdapter)

    def test_framework_router_resolution(self):
        engine, fw = FrameworkRouter.resolve_framework("tauri")
        if sys.platform == "win32":
            self.assertEqual(engine, "webview2")
            self.assertEqual(fw, "tauri")
        else:
            self.assertEqual(engine, "webkit")
            self.assertEqual(fw, "tauri")

        engine_cef, fw_cef = FrameworkRouter.resolve_framework("cef")
        self.assertEqual(engine_cef, "chromium")
        self.assertEqual(fw_cef, "cef")

    def test_adapter_contracts(self):
        for name in list_adapters():
            adapter = get_adapter(name)
            self.assertIsInstance(adapter, BaseEngineAdapter)
            self.assertTrue(hasattr(adapter, "engine_name"))
            self.assertTrue(hasattr(adapter, "get_engine_info"))
            self.assertTrue(hasattr(adapter, "detect"))
            self.assertTrue(hasattr(adapter, "prepare_environment"))
            self.assertTrue(hasattr(adapter, "get_launch_args"))
            self.assertTrue(hasattr(adapter, "discover_targets"))
            self.assertTrue(hasattr(adapter, "select_target"))
            self.assertTrue(hasattr(adapter, "attach"))
            self.assertTrue(hasattr(adapter, "detach"))

            info = adapter.get_engine_info()
            self.assertEqual(info.engine, name)
            self.assertIsNotNone(info.protocol)
            self.assertTrue(len(info.capabilities) > 0)


if __name__ == "__main__":
    unittest.main()
