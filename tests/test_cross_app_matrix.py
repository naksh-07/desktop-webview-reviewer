"""
Phase 8: Cross-Application Hybrid Architecture Validation Matrix.
Verifies engine detection, framework routing, capability boundaries,
and plane mismatch handling across:
- QtWebEngine (Anki / PyQt)
- WebView2 (Tauri / WinUI3 / .NET)
- Electron (Slack / VSCode / custom)
- Chromium / CEF (CefSharp / Spotify)
- WebKit (Unsupported on Windows -> explicit boundary)
- Native-Only Windows App (Notepad / Win32 / WPF without webview)
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from adapters import get_adapter, list_adapters
from detectors.engine_detector import EngineDetector, FrameworkRouter
from core.models import CapabilityName, CapabilityStatus
from core.capabilities import CapabilityRegistry
from runtime.session_manager import TargetPlane, SessionState
from runtime.mcp.errors import McpErrorCode, McpControlPlaneException
from runtime.mcp.tools.evaluation import desktop_evaluate_impl
from runtime.mcp.runtime_bridge import RuntimeBridge


class TestCrossAppMatrix(unittest.IsolatedAsyncioTestCase):
    """Validates cross-architecture behavior and capability boundaries."""

    def test_adapter_ecosystem_coverage(self):
        """Verifies that all 5 supported web/hybrid adapters are registered and typed."""
        adapters = list_adapters()
        expected = ["chromium", "electron", "qtwebengine", "webkit", "webview2"]
        for exp in expected:
            self.assertIn(exp, adapters)
            adapter = get_adapter(exp)
            self.assertEqual(adapter.engine_name, exp)

    def test_qtwebengine_hybrid_architecture(self):
        """Validates QtWebEngine environment setup and capability boundaries."""
        adapter = get_adapter("qtwebengine")
        info = adapter.get_engine_info()
        self.assertEqual(info.engine, "qtwebengine")
        self.assertEqual(info.capabilities[CapabilityName.DOM.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.RUNTIME.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.TARGETS.value], CapabilityStatus.DEGRADED)

        env = adapter.prepare_environment({"EXISTING_VAR": "1"}, port=9222)
        self.assertEqual(env["QTWEBENGINE_REMOTE_DEBUGGING"], "9222")
        self.assertIn("QTWEBENGINE_REMOTE_DEBUGGING", env)
        self.assertIn("QTWEBENGINE_CHROMIUM_FLAGS", env)
        flags = adapter.get_launch_args(port=9222)
        self.assertEqual(flags, [])

    def test_webview2_hybrid_architecture(self):
        """Validates WebView2 environment setup and capability boundaries."""
        adapter = get_adapter("webview2")
        info = adapter.get_engine_info()
        self.assertEqual(info.engine, "webview2")
        self.assertEqual(info.capabilities[CapabilityName.DOM.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.NETWORK.value], CapabilityStatus.SUPPORTED)

        flags = adapter.get_launch_args(port=9333)
        self.assertTrue(any("remote-debugging-port=9333" in f for f in flags))

    def test_electron_hybrid_architecture(self):
        """Validates Electron multi-target capabilities and arguments."""
        adapter = get_adapter("electron")
        info = adapter.get_engine_info()
        self.assertEqual(info.engine, "electron")
        self.assertEqual(info.capabilities[CapabilityName.MULTI_TARGET.value], CapabilityStatus.SUPPORTED)
        self.assertEqual(info.capabilities[CapabilityName.TARGETS.value], CapabilityStatus.SUPPORTED)

        flags = adapter.get_launch_args(port=9444)
        self.assertIn("--remote-debugging-port=9444", flags)

    def test_chromium_cef_hybrid_architecture(self):
        """Validates CEF / Chromium framework resolution and arguments."""
        eng, fw = FrameworkRouter.resolve_framework("cef")
        self.assertEqual(eng, "chromium")
        self.assertEqual(fw, "cef")

        adapter = get_adapter(eng)
        info = adapter.get_engine_info()
        self.assertEqual(info.engine, "chromium")
        flags = adapter.get_launch_args(port=9555)
        self.assertIn("--remote-debugging-port=9555", flags)

    def test_webkit_capability_boundary_explicit(self):
        """Validates that WebKit explicitly declares degraded input/CDP capabilities."""
        adapter = get_adapter("webkit")
        info = adapter.get_engine_info()
        self.assertEqual(info.engine, "webkit")
        # WebKit lacks standard CDP input domain -> degraded
        self.assertEqual(info.capabilities[CapabilityName.INPUT.value], CapabilityStatus.DEGRADED)
        self.assertEqual(info.capabilities[CapabilityName.KEYBOARD.value], CapabilityStatus.DEGRADED)
        self.assertEqual(info.capabilities[CapabilityName.MOUSE.value], CapabilityStatus.DEGRADED)

    async def test_native_only_windows_app_plane_mismatch_guard(self):
        """
        Validates that a Native-Only Windows App (TargetPlane.NATIVE_SHELL without webview core)
        fails explicitly when web-specific operations (e.g. desktop_evaluate) are attempted.
        """
        bridge = MagicMock(spec=RuntimeBridge)
        bridge.ensure_initialized = AsyncMock()

        # Mock a session running on NATIVE_SHELL plane with no webview core
        mock_session = MagicMock(spec=SessionState)
        mock_session.session_id = "mock-native-session-12345"
        mock_session.active_plane = TargetPlane.NATIVE_SHELL
        mock_session.webview_core = None
        bridge.get_session.return_value = mock_session

        import json
        from mcp.server.mcpserver.exceptions import ToolError

        # Attempting JS evaluation on a native-only app must raise ToolError with CAPABILITY_UNAVAILABLE
        with self.assertRaises(ToolError) as ctx:
            await desktop_evaluate_impl(
                bridge=bridge,
                session_id="mock-native-session-12345",
                expression="document.title",
            )
        err_data = json.loads(str(ctx.exception))
        self.assertEqual(err_data["code"], McpErrorCode.CAPABILITY_UNAVAILABLE.value)
        self.assertIn("NATIVE_SHELL", err_data["message"])
        self.assertIn("does not host an active webview", err_data["message"])


if __name__ == "__main__":
    unittest.main()
