"""
Unit tests for runtime/target_manager.py.
Validates multi-dimensional target identity separation, PID create_time validation,
stale HWND reuse prevention, and process exit detection.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

from runtime.target_manager import (
    TargetManager,
    ProcessIdentity,
    WindowIdentity,
    WebviewRuntimeIdentity,
    DebuggingEndpointIdentity,
    NativeAutomationContext,
)
from runtime.references import Rect
from runtime.errors import (
    InvalidTargetException,
    TargetExitedException,
    TargetMismatchException,
)


class TestRuntimeTarget(unittest.TestCase):
    """Test suite for target identity separation and verification."""

    def setUp(self):
        self.manager = TargetManager()

    def test_identity_separation(self):
        """Verifies process, window, webview runtime, endpoint, and native context remain distinct types."""
        proc = ProcessIdentity(pid=1234, creation_time=1000.0, binary_path="C:\\app.exe")
        win = WindowIdentity(
            hwnd=0x4A12,
            pid=1234,
            title="Target Window",
            class_name="NativeClass",
            bounds=Rect(100, 100, 800, 600),
            is_visible=True,
            is_cloaked=False,
            is_minimized=False,
            is_hung=False,
        )
        runtime = WebviewRuntimeIdentity(engine_type="qtwebengine", detected_confidence="high")
        endpoint = DebuggingEndpointIdentity(port=9222, target_id="page_1", ws_url="ws://127.0.0.1:9222/devtools/page/1")
        native = NativeAutomationContext(hwnd=0x4A12, pid=1234, uia_supported=True)

        self.assertIsInstance(proc, ProcessIdentity)
        self.assertIsInstance(win, WindowIdentity)
        self.assertIsInstance(runtime, WebviewRuntimeIdentity)
        self.assertIsInstance(endpoint, DebuggingEndpointIdentity)
        self.assertIsInstance(native, NativeAutomationContext)

        self.assertEqual(proc.pid, win.pid)
        self.assertEqual(win.hwnd, native.hwnd)
        self.assertEqual(endpoint.port, 9222)
        self.assertEqual(runtime.engine_type, "qtwebengine")

    def test_correlate_current_process(self):
        """Verifies correlation of currently executing Python test process."""
        current_pid = os.getpid()
        identity = self.manager.correlate_process(current_pid)

        self.assertEqual(identity.pid, current_pid)
        self.assertGreater(identity.creation_time, 0)
        self.assertTrue(len(identity.binary_path) > 0)

        # Verifying live process does not throw
        self.manager.verify_process_identity(identity)

    def test_process_exit_detection(self):
        """Verifies querying or verifying a terminated PID raises TargetExitedException."""
        dead_pid = 9999999  # Guaranteed non-existent PID
        with self.assertRaises((TargetExitedException, InvalidTargetException)):
            self.manager.correlate_process(dead_pid)

        fake_identity = ProcessIdentity(pid=dead_pid, creation_time=100.0, binary_path="fake.exe")
        with self.assertRaises(TargetExitedException):
            self.manager.verify_process_identity(fake_identity)

    def test_pid_recreation_mismatch(self):
        """Verifies create_time mismatch raises TargetMismatchException (PID recycling protection)."""
        current_pid = os.getpid()
        # Create identity with deliberately mismatched creation time
        mismatched_identity = ProcessIdentity(
            pid=current_pid,
            creation_time=1.0,  # Far in the past
            binary_path="fake.exe",
        )
        with self.assertRaises(TargetMismatchException):
            self.manager.verify_process_identity(mismatched_identity)

    def test_stale_hwnd_ownership_mismatch(self):
        """Verifies correlate_window checks owning PID and rejects stale HWND reuse."""
        with patch("runtime.native_supervisor.NativeOSSupervisor.is_window_valid", return_value=True), \
             patch("runtime.native_supervisor.NativeOSSupervisor.get_window_pid", return_value=1234):
            # Target HWND owned by PID 1234, but session expects PID 5678
            with self.assertRaises(TargetMismatchException):
                self.manager.correlate_window(hwnd=0x9999, expected_pid=5678)

    def test_match_window_to_cdp_by_title(self):
        """Verifies window title matching against CDP page targets."""
        win = WindowIdentity(
            hwnd=0x111,
            pid=100,
            title="StudyLab Deck Reviewer",
            class_name="QtClass",
            bounds=Rect(0, 0, 800, 600),
            is_visible=True,
            is_cloaked=False,
            is_minimized=False,
            is_hung=False,
        )
        endpoints = [
            DebuggingEndpointIdentity(port=9222, target_id="t1", title="top toolbar", ws_url="ws://toolbar"),
            DebuggingEndpointIdentity(port=9222, target_id="t2", title="studylab deck reviewer - main", ws_url="ws://main"),
            DebuggingEndpointIdentity(port=9222, target_id="t3", title="inspector", ws_url="ws://dev"),
        ]

        matched = self.manager.match_window_to_cdp(win, endpoints)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.target_id, "t2")
        self.assertEqual(matched.ws_url, "ws://main")


if __name__ == "__main__":
    unittest.main()
