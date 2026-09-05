"""
Unit and Contract Tests for Framework Adapters (Phase 13).
Validates Electron, WebView2, and Qt/QtWebEngine adapter implementations,
capability states, and client code generation.
"""

import unittest

from runtime.capability import CapabilityStatus
from runtime.harness.adapters import (
    get_adapter_for_framework,
    list_registered_adapters,
)
from runtime.harness.adapters.electron import ElectronHarnessAdapter
from runtime.harness.adapters.webview2 import WebView2HarnessAdapter
from runtime.harness.adapters.qt import QtHarnessAdapter


class TestHarnessFrameworkAdapters(unittest.TestCase):
    """Authoritative test suite for framework-specific adapters."""

    def test_adapter_registry(self):
        """Verifies that all three required adapters are registered."""
        adapters = list_registered_adapters()
        self.assertIn("electron", adapters)
        self.assertIn("webview2", adapters)
        self.assertIn("qt", adapters)
        self.assertIn("qtwebengine", adapters)

        self.assertIsInstance(get_adapter_for_framework("electron"), ElectronHarnessAdapter)
        self.assertIsInstance(get_adapter_for_framework("webview2"), WebView2HarnessAdapter)
        self.assertIsInstance(get_adapter_for_framework("qt"), QtHarnessAdapter)

    # -------------------------------------------------------------------------
    # 1. Electron Adapter
    # -------------------------------------------------------------------------
    def test_electron_adapter_capabilities_and_codegen(self):
        """Verifies Electron adapter capabilities and client code generation."""
        adapter = ElectronHarnessAdapter()
        self.assertEqual(adapter.adapter_name, "electron")
        self.assertEqual(adapter.framework, "electron")

        caps = adapter.get_supported_capabilities()
        self.assertEqual(caps["lifecycle"], CapabilityStatus.AVAILABLE)
        self.assertEqual(caps["diagnostics"], CapabilityStatus.AVAILABLE)
        self.assertEqual(caps["fixtures"], CapabilityStatus.AVAILABLE)
        self.assertEqual(caps["fault_injection"], CapabilityStatus.AVAILABLE)

        filename, code = adapter.generate_harness_client_file(".", {
            "app_id": "test_electron",
            "session_id": "s_el_1",
            "port": 9555,
        })
        self.assertEqual(filename, "reviewer_harness.dev.js")
        self.assertIn("initReviewerHarness", code)
        self.assertIn("sendHarnessMessage", code)
        self.assertIn("emitLifecycle", code)
        self.assertIn("emitDiagnostics", code)
        self.assertIn("9555", code)

        snippet = adapter.get_injection_snippet()
        self.assertIn("REVIEWER_HARNESS_DEV_ONLY_BEGIN", snippet)
        self.assertIn("REVIEWER_HARNESS_DEV_ONLY_END", snippet)
        self.assertIn("require('./reviewer_harness.dev.js')", snippet)

    # -------------------------------------------------------------------------
    # 2. WebView2 Adapter
    # -------------------------------------------------------------------------
    def test_webview2_adapter_capabilities_and_codegen(self):
        """Verifies WebView2 adapter capabilities and honest DEGRADED reporting."""
        adapter = WebView2HarnessAdapter()
        self.assertEqual(adapter.adapter_name, "webview2")
        self.assertEqual(adapter.framework, "webview2")

        caps = adapter.get_supported_capabilities()
        self.assertEqual(caps["lifecycle"], CapabilityStatus.AVAILABLE)
        self.assertEqual(caps["diagnostics"], CapabilityStatus.AVAILABLE)
        self.assertEqual(caps["fixtures"], CapabilityStatus.AVAILABLE)
        # Truthful degraded status for fault injection
        self.assertEqual(caps["fault_injection"], CapabilityStatus.DEGRADED)

        filename, code = adapter.generate_harness_client_file(".", {
            "app_id": "test_wv2",
            "session_id": "s_wv2_1",
            "port": 9666,
        })
        self.assertEqual(filename, "ReviewerHarness.cs")
        self.assertIn("#if DEBUG || REVIEWER_HARNESS", code)
        self.assertIn("ReviewerHarness", code)
        self.assertIn("EmitLifecycleAsync", code)
        self.assertIn("9666", code)

        snippet = adapter.get_injection_snippet()
        self.assertIn("#if DEBUG || REVIEWER_HARNESS", snippet)
        self.assertIn("ReviewerHarness.Initialize(this);", snippet)

    # -------------------------------------------------------------------------
    # 3. Qt / QtWebEngine Adapter
    # -------------------------------------------------------------------------
    def test_qt_adapter_capabilities_and_codegen(self):
        """Verifies Qt adapter capabilities and Python client code generation."""
        adapter = QtHarnessAdapter()
        self.assertEqual(adapter.adapter_name, "qtwebengine")
        self.assertEqual(adapter.framework, "qt")

        caps = adapter.get_supported_capabilities()
        self.assertEqual(caps["lifecycle"], CapabilityStatus.AVAILABLE)
        self.assertEqual(caps["diagnostics"], CapabilityStatus.AVAILABLE)
        self.assertEqual(caps["fixtures"], CapabilityStatus.AVAILABLE)
        self.assertEqual(caps["fault_injection"], CapabilityStatus.AVAILABLE)

        filename, code = adapter.generate_harness_client_file(".", {
            "app_id": "test_qt",
            "session_id": "s_qt_1",
            "port": 9777,
        })
        self.assertEqual(filename, "reviewer_harness_qt.py")
        self.assertIn("init_reviewer_harness", code)
        self.assertIn("send_harness_message", code)
        self.assertIn("emit_lifecycle", code)
        self.assertIn("9777", code)

        snippet = adapter.get_injection_snippet()
        self.assertIn("REVIEWER_HARNESS_DEV_ONLY_BEGIN", snippet)
        self.assertIn("reviewer_harness_qt", snippet)


if __name__ == "__main__":
    unittest.main()
