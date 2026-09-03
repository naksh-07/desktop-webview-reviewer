"""
Unit tests for runtime/coordinate_transform.py.
Validates coordinate conversion across Per-Monitor V2 DPI scaling matrix:
100%, 125%, 150%, 175%, and 200%.
Verifies round-trip accuracy from logical CSS -> screen physical -> SendInput normalized -> physical.
"""

import unittest
from runtime.references import Rect
from runtime.coordinate_transform import (
    CoordinateTransformer,
    CoordinateTransformContext,
    VirtualScreenBounds,
)
from runtime.errors import InvalidCoordinateSpaceException


class TestRuntimeCoordinates(unittest.TestCase):
    """Test suite for the authoritative coordinate transformation subsystem."""

    def setUp(self):
        # Standard virtual desktop layout (e.g. 4K or multi-monitor 3840x2160)
        self.virtual_screen = VirtualScreenBounds(left=0, top=0, width=3840, height=2160)


    def test_dpi_matrix_round_trip_accuracy(self):
        """
        Tests the 5 required DPI scaling factors: 100%, 125%, 150%, 175%, 200%.
        Verifies logical CSS error < 0.5px and SendInput physical delta <= 1.0px.
        """
        scale_factors = [1.0, 1.25, 1.5, 1.75, 2.0]
        test_points = [
            (10.0, 10.0),    # Small element origin
            (125.5, 45.5),   # Standard button center
            (333.3, 267.7),  # Nested text box center
            (800.0, 600.0),  # Viewport bottom-right
        ]

        for scale in scale_factors:
            context = CoordinateTransformContext(
                dpi_scale=scale,
                client_origin_screen=(100, 150),
                webview_client_offset=(0, 40),
                virtual_screen=self.virtual_screen,
            )

            for css_x, css_y in test_points:
                res = CoordinateTransformer.verify_round_trip(css_x, css_y, context)
                self.assertTrue(
                    res["is_safe"],
                    f"Scale {scale*100}% point ({css_x}, {css_y}) failed safe threshold: {res}"
                )
                self.assertLessEqual(
                    res["logical_css_error_px"],
                    0.5,
                    f"Scale {scale*100}% logical error exceeded 0.5px: {res['logical_css_error_px']}"
                )

                self.assertLessEqual(
                    res["sendinput_physical_delta_px"],
                    1.0,
                    f"Scale {scale*100}% SendInput delta exceeded 1.0px: {res['sendinput_physical_delta_px']}"
                )

    def test_css_to_webview_client_scaling(self):
        """Verifies direct scaling from Web CSS to Webview Client physical pixels."""
        # At 150% DPR, 100 CSS px -> 150 physical px
        client_x, client_y = CoordinateTransformer.css_to_webview_client(100.0, 200.0, dpr=1.5)
        self.assertEqual(client_x, 150)
        self.assertEqual(client_y, 300)

        # Inverse mapping
        css_x, css_y = CoordinateTransformer.webview_client_to_css(client_x, client_y, dpr=1.5)
        self.assertAlmostEqual(css_x, 100.0)
        self.assertAlmostEqual(css_y, 200.0)

    def test_invalid_dpr_rejection(self):
        """Verifies non-positive DPR raises InvalidCoordinateSpaceException."""
        with self.assertRaises(InvalidCoordinateSpaceException):
            CoordinateTransformer.css_to_webview_client(10, 10, dpr=0.0)
        with self.assertRaises(InvalidCoordinateSpaceException):
            CoordinateTransformer.css_to_webview_client(10, 10, dpr=-1.5)

    def test_sendinput_normalization_boundaries(self):
        """Verifies SendInput normalization clamps strictly to 0..65535."""
        v = VirtualScreenBounds(left=0, top=0, width=1920, height=1080)

        # Top-left corner (0, 0) -> (0, 0)
        norm_x, norm_y = CoordinateTransformer.screen_to_sendinput_normalized(0, 0, v)
        self.assertEqual(norm_x, 0)
        self.assertEqual(norm_y, 0)

        # Bottom-right corner (1919, 1079) -> (65535, 65535)
        norm_x, norm_y = CoordinateTransformer.screen_to_sendinput_normalized(1919, 1079, v)
        self.assertEqual(norm_x, 65535)
        self.assertEqual(norm_y, 65535)

        # Out of bounds clamping
        norm_x, norm_y = CoordinateTransformer.screen_to_sendinput_normalized(-500, 5000, v)
        self.assertEqual(norm_x, 0)
        self.assertEqual(norm_y, 65535)

    def test_affordance_center_calculation(self):
        """Verifies center targeting point computation."""
        bounds = Rect(x=100, y=200, width=80, height=40)
        center = CoordinateTransformer.calculate_affordance_center(bounds)
        self.assertEqual(center, (140, 220))


if __name__ == "__main__":
    unittest.main()
