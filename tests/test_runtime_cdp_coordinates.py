"""
Unit tests for WebviewAutomationCore coordinate transformations (runtime/webview_core.py).
Validates authoritative conversion: CSS -> Webview Client -> Native Client -> Physical Screen.
Enforces Invariant H and accounts for high-DPI scaling and multi-monitor topologies.
"""

import unittest

from runtime.references import Rect, ReferenceRegistry
from runtime.cdp_transport import MockCDPTransport
from runtime.webview_core import WebviewAutomationCore


class TestCDPCoordinateIntegration(unittest.TestCase):
    """Test suite for WebviewAutomationCore coordinate conversion pipeline."""

    def setUp(self):
        self.transport = MockCDPTransport()
        self.registry = ReferenceRegistry(session_id="test_coord_sess", initial_epoch=1)
        self.core = WebviewAutomationCore(
            session_id="test_coord_sess",
            transport=self.transport,
            reference_registry=self.registry,
            native_pid=1000,
            native_hwnd=2000,
        )

    def test_css_point_to_screen_standard_dpi(self):
        """Verifies point conversion at 100% DPI (dpr=1.0) with webview offset inside native window."""
        # Native client window at screen (100, 200)
        # Webview control offset inside native window at (10, 50)
        # CSS point inside webview at (30, 40)
        # Expected:
        # Webview client: (30, 40)
        # Native client: (30 + 10, 40 + 50) = (40, 90)
        # Screen: (40 + 100, 90 + 200) = (140, 290)
        screen_x, screen_y = self.core.convert_css_to_screen(
            css_x=30.0,
            css_y=40.0,
            client_origin_screen=(100, 200),
            dpr=1.0,
            webview_offset_in_native=(10, 50),
        )
        self.assertEqual((screen_x, screen_y), (140, 290))

    def test_css_point_to_screen_high_dpi_scaling(self):
        """Verifies point conversion with 150% DPI (dpr=1.5)."""
        # CSS point (100, 200)
        # At 1.5 DPR -> Webview client: (150, 300)
        # Webview offset: (0, 0)
        # Native window origin: (500, 100)
        # Screen: (150 + 500, 300 + 100) = (650, 400)
        screen_x, screen_y = self.core.convert_css_to_screen(
            css_x=100.0,
            css_y=200.0,
            client_origin_screen=(500, 100),
            dpr=1.5,
            webview_offset_in_native=(0, 0),
        )
        self.assertEqual((screen_x, screen_y), (650, 400))

    def test_css_rect_to_screen_rect(self):
        """Verifies full bounding box translation and scaling."""
        css_box = Rect(x=50.0, y=80.0, width=200.0, height=100.0)
        screen_box = self.core.convert_css_rect_to_screen_rect(
            css_rect=css_box,
            client_origin_screen=(200, 300),
            dpr=1.25,
            webview_offset_in_native=(20, 30),
        )

        # Expected:
        # width = 200 * 1.25 = 250
        # height = 100 * 1.25 = 125
        # x = 50 * 1.25 + 20 + 200 = 62.5 + 20 + 200 = 282.5 -> 282 (or round)
        # y = 80 * 1.25 + 30 + 300 = 100 + 30 + 300 = 430
        self.assertAlmostEqual(screen_box.width, 250.0, delta=1.0)
        self.assertAlmostEqual(screen_box.height, 125.0, delta=1.0)
        self.assertAlmostEqual(screen_box.x, 282.5, delta=1.0)
        self.assertAlmostEqual(screen_box.y, 430.0, delta=1.0)

    def test_multi_monitor_negative_origin(self):
        """Verifies conversion when native window is positioned on a secondary monitor with negative coordinates."""
        # Secondary monitor to the left: window client origin at (-1920, 0)
        screen_x, screen_y = self.core.convert_css_to_screen(
            css_x=100.0,
            css_y=100.0,
            client_origin_screen=(-1920, 100),
            dpr=1.0,
            webview_offset_in_native=(0, 0),
        )
        self.assertEqual((screen_x, screen_y), (-1820, 200))


if __name__ == "__main__":
    unittest.main()
