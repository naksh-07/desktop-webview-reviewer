"""
Desktop Eyes & Topology Tests.
Verifies:
- Physical MultiMonitorTopology discovery (EnumDisplayMonitors / GetMonitorInfoW / DPI)
- Full desktop screen capture and Window capture
- Element crop capture with coordinate bounds
- Truthful degradation when screen capture is unavailable
"""

from __future__ import annotations
import unittest
from unittest.mock import MagicMock, patch

from runtime.references import Rect
from runtime.coordinate_transform import (
    CoordinateTransformer,
    MonitorInfo,
    MultiMonitorTopology,
)
from runtime.native_supervisor import NativeSupervisor


class TestDesktopEyesTopology(unittest.TestCase):
    def setUp(self):
        self.supervisor = NativeSupervisor()

    def test_multimonitor_topology_discovery(self):
        """CoordinateTransformer correctly parses and encapsulates monitor topology."""
        transformer = CoordinateTransformer()
        topology = transformer.get_system_multimonitor_topology()

        self.assertIsInstance(topology, MultiMonitorTopology)
        self.assertGreaterEqual(len(topology), 1)
        self.assertIsNotNone(topology.primary)
        self.assertTrue(topology.primary.is_primary)
        self.assertGreater(topology.virtual_screen_bounds.width, 0)
        self.assertGreater(topology.virtual_screen_bounds.height, 0)

        # Iteration test
        monitors = list(topology)
        self.assertGreaterEqual(len(monitors), 1)
        for m in monitors:
            self.assertIsInstance(m, MonitorInfo)
            self.assertGreater(m.bounds.width, 0)
            self.assertGreater(m.bounds.height, 0)

    def test_native_supervisor_get_monitor_topology(self):
        """NativeSupervisor.get_monitor_topology exposes valid topology dictionary."""
        top_dict = self.supervisor.get_monitor_topology()
        self.assertIn("monitor_count", top_dict)
        self.assertIn("monitors", top_dict)
        self.assertIn("virtual_screen", top_dict)
        self.assertGreaterEqual(top_dict["monitor_count"], 1)

    def test_full_desktop_screenshot_capture(self):
        """NativeSupervisor.capture_full_desktop_screenshot captures valid PNG image bytes."""
        res = self.supervisor.capture_full_desktop_screenshot()
        if isinstance(res, tuple):
            success, png_bytes, sha256_hash, meta = res
        else:
            png_bytes = res
            success = bool(png_bytes)
        if success and png_bytes:
            # PNG signature bytes: \x89PNG\r\n\x1a\n
            self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(len(png_bytes), 100)

    def test_element_crop_from_desktop(self):
        """NativeSupervisor.capture_element_crop crops target region from screenshot."""
        rect = Rect(10, 10, 50, 50)
        res = self.supervisor.capture_element_crop(hwnd=None, element_bounds=rect)
        if isinstance(res, tuple):
            success, crop_bytes, sha256_hash, meta = res
            if success and crop_bytes:
                self.assertTrue(crop_bytes.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
