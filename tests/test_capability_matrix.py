"""
Unit tests for multi-engine capability negotiation and matrix compliance.
"""

import sys
import unittest

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from adapters import get_adapter
from core.models import CapabilityName, CapabilityStatus
from core.capabilities import CapabilityRegistry


class TestCapabilityMatrix(unittest.TestCase):
    def test_qtwebengine_capabilities(self):
        adapter = get_adapter("qtwebengine")
        info = adapter.get_engine_info()
        self.assertEqual(info.capabilities[CapabilityName.DOM.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.INPUT.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.RUNTIME.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.SCREENSHOT.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.TARGETS.value], CapabilityStatus.DEGRADED)

    def test_webview2_capabilities(self):
        adapter = get_adapter("webview2")
        info = adapter.get_engine_info()
        self.assertEqual(info.capabilities[CapabilityName.DOM.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.NETWORK.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.KEYBOARD.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.MOUSE.value], CapabilityStatus.SUPPORTED)

    def test_electron_capabilities(self):
        adapter = get_adapter("electron")
        info = adapter.get_engine_info()
        self.assertEqual(info.capabilities[CapabilityName.DOM.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.TARGETS.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.MULTI_TARGET.value], CapabilityStatus.SUPPORTED)

    def test_chromium_capabilities(self):
        adapter = get_adapter("chromium")
        info = adapter.get_engine_info()
        self.assertEqual(info.capabilities[CapabilityName.DOM.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.SCREENSHOT.value], CapabilityStatus.SUPPORTED)

    def test_webkit_capabilities(self):
        adapter = get_adapter("webkit")
        info = adapter.get_engine_info()
        self.assertEqual(info.capabilities[CapabilityName.DOM.value], CapabilityStatus.SUPPORTED)
        # WebKit lacks native CDP Input domain -> declared DEGRADED for synthetic DOM events
        self.assertEqual(info.capabilities[CapabilityName.INPUT.value], CapabilityStatus.DEGRADED)
        self.assertEqual(info.capabilities[CapabilityName.KEYBOARD.value], CapabilityStatus.DEGRADED)
        self.assertEqual(info.capabilities[CapabilityName.MOUSE.value], CapabilityStatus.DEGRADED)

    def test_capability_helpers(self):
        adapter = get_adapter("webview2")
        info = adapter.get_engine_info()
        self.assertTrue(CapabilityRegistry.is_supported(info, CapabilityName.DOM))
        self.assertTrue(CapabilityRegistry.is_supported(info, CapabilityName.RUNTIME))

        summary = CapabilityRegistry.format_capability_summary(info)
        self.assertIn("Engine: webview2", summary)
        self.assertIn("DOM", summary)


if __name__ == "__main__":
    unittest.main()
