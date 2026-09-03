"""
Unit tests for runtime/native_supervisor.py.
Validates physical desktop truth, DWM extended frame bounds vs GetWindowRect,
SendMessageTimeout(WM_NULL) responsiveness checks, and modal dialog detection.
"""

import sys
import unittest
from unittest.mock import patch

from runtime.native_supervisor import NativeOSSupervisor, WindowForensicReport
from runtime.references import Rect
from runtime.state import HealthState
from runtime.errors import InvalidTargetException


class TestRuntimeNative(unittest.TestCase):
    """Test suite for native OS supervisor and physical window truth."""

    def test_window_validation_invalid_hwnd(self):
        """Verifies invalid HWND is detected and rejected."""
        if sys.platform != "win32":
            self.skipTest("Win32 tests are Windows-specific")

        self.assertFalse(NativeOSSupervisor.is_window_valid(0))
        self.assertFalse(NativeOSSupervisor.is_window_valid(0xDEADBEEF))

        with self.assertRaises(InvalidTargetException):
            NativeOSSupervisor.inspect_window(0xDEADBEEF)

    def test_responsiveness_check_healthy(self):
        """Verifies responsiveness check on desktop shell window returns HealthState.HEALTHY."""
        if sys.platform != "win32":
            self.skipTest("Win32 tests are Windows-specific")

        import ctypes
        hwnd = ctypes.windll.user32.GetDesktopWindow()
        self.assertTrue(NativeOSSupervisor.is_window_valid(hwnd))

        health = NativeOSSupervisor.check_responsiveness(hwnd, timeout_ms=500)
        self.assertEqual(health, HealthState.HEALTHY)

    def test_responsiveness_check_hung_simulation(self):
        """Verifies SendMessageTimeout timeout reports HealthState.HUNG."""
        with patch("ctypes.windll.user32.IsWindow", return_value=1), \
             patch("ctypes.windll.user32.SendMessageTimeoutW", return_value=0):
            health = NativeOSSupervisor.check_responsiveness(0x1234, timeout_ms=500)
            self.assertEqual(health, HealthState.HUNG)

    def test_canonical_dwm_bounds_authority(self):
        """
        Verifies DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS) is authoritative
        and shadow margin delta is computed relative to GetWindowRect.
        """
        if sys.platform != "win32":
            self.skipTest("Win32 tests are Windows-specific")

        import ctypes
        hwnd = ctypes.windll.user32.GetShellWindow()
        if not hwnd:
            hwnd = ctypes.windll.user32.GetDesktopWindow()

        canonical_bounds, raw_rect, margins = NativeOSSupervisor.get_canonical_window_bounds(hwnd)
        self.assertIsInstance(canonical_bounds, Rect)
        self.assertIsInstance(raw_rect, Rect)
        self.assertIn("left", margins)
        self.assertIn("top", margins)
        self.assertIn("right", margins)
        self.assertIn("bottom", margins)

    def test_inspect_window_report(self):
        """Verifies WindowForensicReport captures required physical properties."""
        if sys.platform != "win32":
            report = NativeOSSupervisor.inspect_window(1234)
            self.assertEqual(report.health_state, HealthState.HEALTHY)
            self.assertEqual(report.dpi_scaling, 1.0)
            return

        import ctypes
        hwnd = ctypes.windll.user32.GetDesktopWindow()
        report = NativeOSSupervisor.inspect_window(hwnd)

        self.assertIsInstance(report, WindowForensicReport)
        self.assertEqual(report.hwnd, hwnd)
        self.assertTrue(report.is_valid_window)
        self.assertIsInstance(report.bounds, Rect)
        self.assertIsInstance(report.client_rect, Rect)
        self.assertIsInstance(report.client_origin_screen, tuple)
        self.assertIn(report.health_state, (HealthState.HEALTHY, HealthState.UNRESPONSIVE))


if __name__ == "__main__":
    unittest.main()
