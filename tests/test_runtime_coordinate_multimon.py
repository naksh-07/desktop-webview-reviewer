"""
Test Suite: Deterministic Multi-Monitor Coordinate Transformation.
Verifies Per-Monitor V2 scaling (100%, 125%, 150%, 175%, 200%), negative screen origins,
SendInput 0..65535 normalization, and multi-display topology resolution.
"""

import math
import unittest

from runtime.references import Rect
from runtime.coordinate_transform import (
    CoordinateTransformer,
    CoordinateTransformContext,
    VirtualScreenBounds,
    MonitorDescriptor,
    MultiMonitorTopology,
)


class TestRuntimeCoordinateMultiMon(unittest.TestCase):
    """Deep verification of CoordinateTransformer across DPI scales and multi-monitor layouts."""

    def test_dpi_scalings_round_trip(self):
        """
        Verifies round-trip accuracy across all standard Windows scaling tiers:
        100% (1.0), 125% (1.25), 150% (1.5), 175% (1.75), 200% (2.0).
        Ensures logical error <= 0.5px and physical delta <= 1.0px.
        """
        scalings = [1.0, 1.25, 1.5, 1.75, 2.0]
        test_points = [
            (50.0, 50.0),
            (245.5, 180.25),
            (800.0, 600.0),
            (1200.0, 750.0),
        ]
        # Virtual desktop large enough to accommodate scaled window points
        v_screen = VirtualScreenBounds(left=0, top=0, width=3840, height=2160)

        for dpr in scalings:
            ctx = CoordinateTransformContext(
                dpi_scale=dpr,
                client_origin_screen=(100, 100),
                webview_client_offset=(10, 30),
                virtual_screen=v_screen,
            )
            for css_x, css_y in test_points:
                res = CoordinateTransformer.verify_round_trip(css_x, css_y, ctx)
                self.assertTrue(
                    res["is_safe"],
                    f"Scale {dpr} failed precision at ({css_x}, {css_y}): {res}",
                )
                self.assertLessEqual(res["logical_css_error_px"], 0.5)
                self.assertLessEqual(res["sendinput_physical_delta_px"], 1.0)

    def test_negative_multi_monitor_screen_coordinates(self):
        """
        Verifies SendInput normalization and reconstruction when the virtual desktop
        contains negative coordinates (e.g. secondary monitor to the left at x=-1920).
        """
        # Topology: Secondary on Left (-1920..0), Primary on Right (0..1920)
        # Virtual desktop: left=-1920, top=0, width=3840, height=1080
        v_screen = VirtualScreenBounds(left=-1920, top=0, width=3840, height=1080)

        test_screen_points = [
            (-1920, 0),       # Far-left top corner (Monitor 2)
            (-960, 540),      # Center of Monitor 2 (negative coords)
            (-1, 500),        # Left border edge
            (0, 0),           # Primary top-left origin
            (960, 540),       # Primary center
            (1919, 1079),     # Primary bottom-right corner
        ]

        for sx, sy in test_screen_points:
            # 1. Screen to SendInput normalized (0..65535)
            norm_x, norm_y = CoordinateTransformer.screen_to_sendinput_normalized(
                sx, sy, virtual_screen=v_screen
            )
            self.assertGreaterEqual(norm_x, 0)
            self.assertLessEqual(norm_x, 65535)
            self.assertGreaterEqual(norm_y, 0)
            self.assertLessEqual(norm_y, 65535)

            # 2. Reconstruct screen from normalized
            recon_x, recon_y = CoordinateTransformer.sendinput_normalized_to_screen(
                norm_x, norm_y, virtual_screen=v_screen
            )

            delta = math.sqrt((sx - recon_x) ** 2 + (sy - recon_y) ** 2)
            self.assertLessEqual(
                delta,
                1.0,
                f"Negative coordinate reconstruction failed for ({sx}, {sy}): got ({recon_x}, {recon_y})",
            )

    def test_stacked_vertical_multi_monitor_simulation(self):
        """
        Verifies stacked vertical monitors (secondary above primary at y=-1080).
        """
        # Topology: Secondary on Top (y=-1080..0), Primary below (y=0..1080)
        topology = CoordinateTransformer.create_simulated_dual_monitor_topology(
            primary_res=(1920, 1080),
            secondary_res=(1920, 1080),
            secondary_position="top",
        )
        v = topology.virtual_screen
        self.assertEqual(v.left, 0)
        self.assertEqual(v.top, -1080)
        self.assertEqual(v.width, 1920)
        self.assertEqual(v.height, 2160)

        # Point on top secondary display: (500, -500)
        norm_x, norm_y = CoordinateTransformer.screen_to_sendinput_normalized(
            500, -500, virtual_screen=v
        )
        self.assertGreaterEqual(norm_x, 0)
        self.assertGreaterEqual(norm_y, 0)

        recon_x, recon_y = CoordinateTransformer.sendinput_normalized_to_screen(
            norm_x, norm_y, virtual_screen=v
        )
        self.assertAlmostEqual(recon_x, 500, delta=1)
        self.assertAlmostEqual(recon_y, -500, delta=1)

    def test_multi_monitor_topology_resolution(self):
        """
        Verifies get_monitor_for_point correctly routes coordinates
        to primary vs secondary display descriptors.
        """
        topology = CoordinateTransformer.create_simulated_dual_monitor_topology(
            primary_res=(1920, 1080),
            primary_dpi=1.5,
            secondary_res=(1920, 1080),
            secondary_dpi=1.0,
            secondary_position="left",
        )

        primary_mon = topology.get_primary_monitor()
        self.assertIsNotNone(primary_mon)
        self.assertTrue(primary_mon.is_primary)
        self.assertEqual(primary_mon.dpi_scale, 1.5)

        # Point (100, 100) is on Primary
        m1 = topology.get_monitor_for_point(100, 100)
        self.assertIsNotNone(m1)
        self.assertEqual(m1.monitor_id, "DISPLAY_PRIMARY")

        # Point (-500, 300) is on Secondary Left
        m2 = topology.get_monitor_for_point(-500, 300)
        self.assertIsNotNone(m2)
        self.assertEqual(m2.monitor_id, "DISPLAY_SECONDARY_LEFT")
        self.assertEqual(m2.dpi_scale, 1.0)

        # Point outside all monitors
        m_outside = topology.get_monitor_for_point(5000, 5000)
        self.assertIsNone(m_outside)

    def test_window_movement_between_monitors(self):
        """
        Simulates dragging a window from Primary (150% DPI) to Secondary (100% DPI).
        Verifies coordinate transformation adjusts DPR and origins seamlessly.
        """
        # Context 1: Window on Primary at (200, 200) with 150% scaling
        ctx_primary = CoordinateTransformContext(
            dpi_scale=1.5,
            client_origin_screen=(200, 200),
            webview_client_offset=(0, 0),
        )
        # Button inside webview at CSS (50, 50)
        screen_x1, screen_y1 = CoordinateTransformer.css_to_screen(50, 50, ctx_primary)
        # CSS 50 * 1.5 = 75px client + 200 origin = 275 screen
        self.assertEqual(screen_x1, 275)
        self.assertEqual(screen_y1, 275)

        # Window dragged to Secondary (origin at -1500, 200, 100% DPI)
        ctx_secondary = CoordinateTransformContext(
            dpi_scale=1.0,
            client_origin_screen=(-1500, 200),
            webview_client_offset=(0, 0),
        )
        screen_x2, screen_y2 = CoordinateTransformer.css_to_screen(50, 50, ctx_secondary)
        # CSS 50 * 1.0 = 50px client + (-1500) origin = -1450 screen
        self.assertEqual(screen_x2, -1450)
        self.assertEqual(screen_y2, 250)


if __name__ == "__main__":
    unittest.main()
