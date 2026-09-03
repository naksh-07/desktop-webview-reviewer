"""
Unit and Integration tests for Python-side FlaUI UIA3 Bridge (Phase 4).
Verifies sidecar lifecycle, JSON-RPC communication, CacheRequest pre-fetching,
epoch-scoped caching, and graceful error recovery.
"""

import os
import unittest
from runtime.flaui_bridge import FlaUIBridge, UIAElementDTO, DEFAULT_SIDECAR_PATH
from runtime.references import Rect


class TestFlaUIBridge(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sidecar_path = DEFAULT_SIDECAR_PATH
        self.bridge = FlaUIBridge(sidecar_path=self.sidecar_path, use_stdio=True)

    async def asyncTearDown(self):
        await self.bridge.disconnect()

    async def test_sidecar_connect_and_handshake(self):
        """Spawns compiled DesktopBridge.UIA3.exe and verifies handshake in MTA mode."""
        if not os.path.exists(self.sidecar_path):
            self.skipTest("DesktopBridge.UIA3.exe not compiled")

        connected = await self.bridge.connect()
        self.assertTrue(connected)
        self.assertTrue(self.bridge.is_connected)

        # Ping
        pong = await self.bridge.ping()
        self.assertTrue(pong)

        # Health
        health = await self.bridge.health()
        self.assertTrue(health.get("healthy"))
        self.assertEqual(health.get("status"), "HEALTHY")

    async def test_find_children_with_cache_request(self):
        """Queries desktop or test window children with CacheRequest enabled."""
        if not os.path.exists(self.sidecar_path):
            self.skipTest("DesktopBridge.UIA3.exe not compiled")

        connected = await self.bridge.connect()
        self.assertTrue(connected)

        # Use desktop or shell window (HWND 0 or taskbar) to verify UIA query
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetDesktopWindow()

        children = await self.bridge.find_children(hwnd=hwnd, max_depth=1, use_cache=True, epoch=1)
        self.assertIsInstance(children, list)

        # Cache check: second call with same epoch returns cached list
        cached_children = await self.bridge.find_children(hwnd=hwnd, max_depth=1, use_cache=True, epoch=1)
        self.assertEqual(id(children), id(cached_children))

        # Cache invalidation on epoch transition
        self.bridge.invalidate_cache(new_epoch=2)
        new_children = await self.bridge.find_children(hwnd=hwnd, max_depth=1, use_cache=True, epoch=2)
        self.assertNotEqual(id(children), id(new_children))

    async def test_dto_serialization(self):
        """UIAElementDTO cleanly converts to/from dict with bounds and patterns."""
        dto = UIAElementDTO(
            automation_id="save_btn",
            name="Save",
            class_name="Button",
            control_type="Button",
            bounds=Rect(10, 20, 100, 30),
            is_enabled=True,
            is_offscreen=False,
            supported_patterns=("Invoke",),
            hwnd=0x1234,
            depth=1,
        )

        d = dto.to_dict()
        self.assertEqual(d["automation_id"], "save_btn")
        self.assertEqual(d["control_type"], "Button")
        self.assertEqual(d["bounds"]["width"], 100)

        restored = UIAElementDTO.from_dict(d)
        self.assertEqual(restored.automation_id, "save_btn")
        self.assertEqual(restored.bounds.width, 100)
        self.assertEqual(restored.supported_patterns, ("Invoke",))


if __name__ == "__main__":
    unittest.main()
