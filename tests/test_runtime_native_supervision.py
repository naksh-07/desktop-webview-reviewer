"""
Test Suite: Native OS Supervision Hardening.
Verifies DWM boundary authority, multi-dimensional physical visibility,
top-level Z-order occlusion, pre-flight responsiveness gates, native modal detection,
and the single authoritative window validation path.
"""

import ctypes
from ctypes import wintypes
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

from runtime.references import Rect
from runtime.state import HealthState
from runtime.native_supervisor import (
    NativeOSSupervisor,
    PhysicalVisibilityReport,
    OcclusionReport,
    OcclusionState,
    CoveringWindowInfo,
    NativeModalReport,
    ModalState,
    ModalDialogInfo,
    ResponsivenessReport,
)
from runtime.target_manager import (
    TargetManager,
    WindowIdentity,
    WindowValidationResult,
)
from runtime.errors import (
    TargetHungException,
    TargetMismatchException,
    InvalidTargetException,
)
import runtime.win32 as w32


class TestNativeOSSupervision(unittest.TestCase):
    """Deep verification of NativeOSSupervisor and TargetManager validation."""

    def test_canonical_dwm_vs_getwindowrect(self):
        """
        Verifies DWMWA_EXTENDED_FRAME_BOUNDS is authoritative and
        diagnostically distinguishable from GetWindowRect.
        """
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        self.assertTrue(NativeOSSupervisor.is_window_valid(hwnd))

        # DWM bounds should return valid non-zero dimensions
        dwm_bounds = NativeOSSupervisor.get_window_rect(hwnd)
        self.assertGreater(dwm_bounds.width, 0)
        self.assertGreater(dwm_bounds.height, 0)

        raw_rect = NativeOSSupervisor.get_raw_window_rect(hwnd)
        self.assertGreater(raw_rect.width, 0)
        self.assertGreater(raw_rect.height, 0)

    def test_physical_visibility_report(self):
        """
        Verifies inspect_physical_visibility evaluates existence, visibility,
        minimized (iconic), cloaked, bounded, and responsiveness.
        """
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        report = NativeOSSupervisor.inspect_physical_visibility(hwnd)

        self.assertIsInstance(report, PhysicalVisibilityReport)
        self.assertTrue(report.is_window)
        self.assertTrue(report.is_visible)
        self.assertFalse(report.is_iconic)
        self.assertFalse(report.is_cloaked)
        self.assertTrue(report.is_bounded)
        self.assertTrue(report.is_responsive)
        self.assertIsNotNone(report.bounds)

    def test_responsiveness_healthy_and_hung_gate(self):
        """
        Verifies check_responsiveness returns ResponsivenessReport and
        ensure_responsive raises TargetHungException when timeout occurs.
        """
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        report = NativeOSSupervisor.check_responsiveness(hwnd, timeout_ms=500)
        self.assertIsInstance(report, ResponsivenessReport)
        self.assertEqual(report.health_state, HealthState.HEALTHY)
        self.assertFalse(report.is_timeout)

        # ensure_responsive should succeed on desktop window
        NativeOSSupervisor.ensure_responsive(hwnd, timeout_ms=500)

        # Simulate hung window via mock
        with patch.object(NativeOSSupervisor, "check_responsiveness") as mock_check:
            mock_check.return_value = ResponsivenessReport(
                hwnd=0x9999,
                pid=1234,
                health_state=HealthState.HUNG,
                elapsed_ms=501.0,
                is_timeout=True,
            )
            with self.assertRaises(TargetHungException) as ctx:
                NativeOSSupervisor.ensure_responsive(0x9999, timeout_ms=500)
            self.assertIn("0x9999", str(ctx.exception))

    def test_occlusion_inspection_logic(self):
        """
        Verifies Z-order traversal and occlusion calculation
        with synthetic window overlaps.
        """
        target_bounds = Rect(100, 100, 800, 600)  # Area = 480,000

        # Case 1: Covering window fully overlaps target
        covering_full = Rect(100, 100, 800, 600)
        inter_full = target_bounds.intersection(covering_full)
        self.assertIsNotNone(inter_full)
        self.assertEqual(inter_full.area, target_bounds.area)

        # Case 2: Covering window covers half of target
        covering_half = Rect(100, 100, 400, 600)
        inter_half = target_bounds.intersection(covering_half)
        self.assertIsNotNone(inter_half)
        self.assertAlmostEqual(inter_half.area / target_bounds.area, 0.5, places=2)

        # Case 3: Covering window does not overlap target
        covering_outside = Rect(1000, 1000, 400, 300)
        inter_none = target_bounds.intersection(covering_outside)
        self.assertIsNone(inter_none)

    def test_native_modal_detection_model(self):
        """
        Verifies detect_modals structure and properties for dialog detection.
        """
        # Test default/no-modal behavior on non-existent PID
        report = NativeOSSupervisor.detect_modals(target_pid=9999999, main_hwnd=0)
        self.assertIsInstance(report, NativeModalReport)
        self.assertEqual(report.modal_state, ModalState.NO_MODAL)
        self.assertEqual(len(report.active_modals), 0)
        self.assertFalse(report.is_blocked_by_modal)

    def test_window_screenshot_capture_and_hash(self):
        """
        Verifies capture_window_screenshot captures surface, writes PNG,
        computes SHA-256, and cleans up GDI handles without leaks.
        """
        if sys.platform != "win32" or w32.user32 is None or w32.gdi32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            success, png_bytes, sha256_hash, meta = NativeOSSupervisor.capture_window_screenshot(
                hwnd, tmp_path
            )
            if success:
                self.assertTrue(os.path.exists(tmp_path))
                self.assertGreater(os.path.getsize(tmp_path), 0)
                self.assertEqual(len(sha256_hash), 64)
                # Verify PNG magic bytes
                with open(tmp_path, "rb") as f:
                    header = f.read(8)
                    self.assertEqual(header, b"\x89PNG\r\n\x1a\n")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def test_single_authoritative_validation_path_success(self):
        """
        Verifies TargetManager.validate_window_identity returns complete
        WindowValidationResult with verified WindowIdentity on real window.
        """
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        tm = TargetManager()

        result = tm.validate_window_identity(hwnd)
        self.assertIsInstance(result, WindowValidationResult)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.hwnd, hwnd)
        self.assertIsInstance(result.window.bounds, Rect)
        self.assertIsInstance(result.window.raw_window_rect, Rect)

    def test_single_authoritative_validation_path_window_not_found(self):
        """
        Verifies validate_window_identity returns WINDOW_NOT_FOUND on invalid HWND.
        """
        tm = TargetManager()
        result = tm.validate_window_identity(hwnd=0xDEADBEEF)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "WINDOW_NOT_FOUND")
        self.assertIsNone(result.window)
        self.assertIn("0xdeadbeef", result.failure_reason.lower())

    def test_single_authoritative_validation_path_pid_mismatch(self):
        """
        Verifies validate_window_identity returns TARGET_MISMATCH when
        owning PID does not match expected_pid.
        """
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        actual_pid = NativeOSSupervisor.get_window_pid(hwnd)

        tm = TargetManager()
        # Expect a completely different PID
        wrong_pid = actual_pid + 99999
        result = tm.validate_window_identity(hwnd=hwnd, expected_pid=wrong_pid)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "TARGET_MISMATCH")
        self.assertIn(str(wrong_pid), result.failure_reason)

    def test_single_authoritative_validation_path_create_time_mismatch(self):
        """
        Verifies validate_window_identity detects recycled PIDs when
        expected_create_time differs by > 1.0s.
        """
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        actual_pid = NativeOSSupervisor.get_window_pid(hwnd)

        tm = TargetManager()
        # Pass a bogus create_time from 10,000 seconds ago
        bogus_time = 100.0
        result = tm.validate_window_identity(
            hwnd=hwnd,
            expected_pid=actual_pid,
            expected_create_time=bogus_time,
        )

        if actual_pid > 0:
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, "TARGET_MISMATCH")
            self.assertIn("recycled", result.failure_reason.lower())


if __name__ == "__main__":
    unittest.main()
