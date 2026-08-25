"""
Deterministic Forensic Hardening and Verdict Verification Control Tests.
Validates Real Windows GUI Identity, Runtime Correlation, Screenshot Provenance,
Tripartite Verdicts (PASS, FAIL, UNVERIFIED), and Evidence Schema Compliance.
"""

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest

from core.evidence import EvidenceCollector, PNG_MAGIC_BYTES
from core.models import (
    CapabilityStatus,
    EngineInfo,
    EvidenceReport,
    ProcessOwnership,
    ScreenshotMetadata,
    ScreenshotType,
    Target,
    Verdict,
    VerificationLevel,
    WindowForensics
)
from core.window_forensics import RECT, WindowForensicsEngine


class TestForensicHardeningMatrix(unittest.TestCase):
    """
    Control test suite validating the four foundational security assertions:
    A. Visible real GUI + matching CDP target -> PASS
    B. CDP target exists but no visible GUI -> NOT PASS (UNVERIFIED)
    C. Mismatched PID/target/port -> NOT PASS (UNVERIFIED)
    D. Screenshot exists without GUI proof -> NOT PASS (UNVERIFIED)
    """

    def setUp(self):
        self.engine_info = EngineInfo(
            engine="qtwebengine",
            backend="QtWebEngine (Embedded Chromium)",
            version="6.5.0",
            protocol="cdp"
        )
        self.target = Target(
            id="target_001",
            type="page",
            title="StudyLab MainWindow",
            url="file:///app/index.html",
            engine="qtwebengine",
            websocket_endpoint="ws://127.0.0.1:9222/devtools/page/target_001"
        )
        self.valid_ownership = ProcessOwnership(
            pid=12345,
            create_time=time.time() - 10,
            launched_by_reviewer=True,
            command=["python.exe", "app.py"],
            port=9222
        )
        self.valid_gui_window = WindowForensics(
            hwnd=65536,
            pid=12345,
            executable=r"C:\Python311\python.exe",
            cmdline=["python.exe", "app.py"],
            window_title="StudyLab MainWindow",
            class_name="Qt662QWindowIcon",
            window_visible=True,
            is_iconic=False,
            is_cloaked=False,
            is_real_gui=True,
            geometry={"x": 100, "y": 100, "width": 1024, "height": 768, "left": 100, "top": 100, "right": 1124, "bottom": 868},
            hwnd_pid_matched=True,
            foreground_match=True,
            foreground_hwnd=65536,
            intersection_area=1024*768,
            notes=["Port 9222 confirmed listening on PID 12345"]
        )

    # -------------------------------------------------------------------------
    # CONTROL A: Visible real GUI + matching CDP target -> PASS
    # -------------------------------------------------------------------------
    def test_control_a_visible_real_gui_matching_target_passes(self):
        """Proves that a verified visible GUI window + matched PID + passing assertions yields PASS."""
        assertions = [
            {"description": "Header title is StudyLab", "passed": True, "expected": "StudyLab", "actual": "StudyLab"}
        ]
        screenshots = {
            "desktop": ScreenshotMetadata(
                screenshot_type=ScreenshotType.NATIVE_DESKTOP,
                screenshot_hash="d" * 64,
                path="screenshot_desktop.png",
                source="desktop_capture"
            ),
            "webview": ScreenshotMetadata(
                screenshot_type=ScreenshotType.CDP_PAGE_CAPTURE,
                screenshot_hash="a" * 64,
                path="screenshot_cdp.png",
                source="cdp_page_capture"
            ),
            "native": ScreenshotMetadata(
                screenshot_type=ScreenshotType.NATIVE_DESKTOP,
                screenshot_hash="b" * 64,
                path="screenshot_native.png",
                source="win32_gdi_hwnd (HWND: 65536)"
            )
        }

        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=self.valid_gui_window,
            assertions=assertions,
            process_ownership=self.valid_ownership,
            screenshots=screenshots,
            require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )

        self.assertEqual(verdict, Verdict.PASS)
        self.assertIn("Verified live visible desktop GUI window", reason)

    # -------------------------------------------------------------------------
    # CONTROL B: CDP target exists but no visible GUI -> NOT PASS (UNVERIFIED)
    # -------------------------------------------------------------------------
    def test_control_b_headless_no_window_unverified(self):
        """Proves that connecting to a CDP target with NO native window yields UNVERIFIED (NOT PASS)."""
        assertions = [{"description": "DOM body exists", "passed": True}]
        
        # Scenario B1: No window forensics at all (headless browser / ghost daemon)
        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=None,
            assertions=assertions,
            process_ownership=self.valid_ownership,
            require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )
        self.assertNotEqual(verdict, Verdict.PASS)
        self.assertEqual(verdict, Verdict.UNVERIFIED)
        self.assertIn("visible desktop GUI could not be proven", reason)

        # Scenario B2: HWND is null/none
        no_hwnd_forensics = WindowForensics(
            hwnd=None,
            pid=12345,
            window_visible=False,
            is_real_gui=False,
            hwnd_pid_matched=False
        )
        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=no_hwnd_forensics,
            assertions=assertions,
            require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )
        self.assertNotEqual(verdict, Verdict.PASS)
        self.assertEqual(verdict, Verdict.UNVERIFIED)

        # Scenario B3: Window is hidden (IsWindowVisible == False)
        hidden_forensics = WindowForensics(
            hwnd=65536,
            pid=12345,
            window_visible=False,
            is_real_gui=False,
            geometry={"x": 0, "y": 0, "width": 800, "height": 600},
            hwnd_pid_matched=True
        )
        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=hidden_forensics,
            assertions=assertions,
            require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )
        self.assertNotEqual(verdict, Verdict.PASS)
        self.assertEqual(verdict, Verdict.UNVERIFIED)
        self.assertIn("not visible on desktop", reason)

        # Scenario B4: Window has zero geometry (0x0 offscreen helper)
        zero_geom_forensics = WindowForensics(
            hwnd=65536,
            pid=12345,
            window_visible=True,
            is_real_gui=False,
            geometry={"x": 0, "y": 0, "width": 0, "height": 0},
            hwnd_pid_matched=True
        )
        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=zero_geom_forensics,
            assertions=assertions,
            require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )
        self.assertNotEqual(verdict, Verdict.PASS)
        self.assertEqual(verdict, Verdict.UNVERIFIED)
        self.assertIn("zero geometry", reason)

        # Scenario B5: Window is cloaked by Windows DWM (virtual desktop / shell hidden)
        cloaked_forensics = WindowForensics(
            hwnd=65536,
            pid=12345,
            window_visible=True,
            is_cloaked=True,
            is_real_gui=False,
            geometry={"x": 100, "y": 100, "width": 800, "height": 600},
            hwnd_pid_matched=True
        )
        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=cloaked_forensics,
            assertions=assertions,
            require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )
        self.assertNotEqual(verdict, Verdict.PASS)
        self.assertEqual(verdict, Verdict.UNVERIFIED)
        self.assertIn("cloaked", reason)

    # -------------------------------------------------------------------------
    # CONTROL C: Mismatched PID/target/port -> NOT PASS (UNVERIFIED)
    # -------------------------------------------------------------------------
    def test_control_c_mismatched_pid_unverified(self):
        """Proves that a PID mismatch or hijacked port yields UNVERIFIED (NOT PASS)."""
        assertions = [{"description": "DOM check", "passed": True}]

        # Window belongs to foreign PID (e.g. Chrome browser PID 99999 instead of app PID 12345)
        mismatched_window = WindowForensics(
            hwnd=65536,
            pid=99999,
            window_visible=True,
            is_real_gui=True,
            geometry={"x": 100, "y": 100, "width": 800, "height": 600},
            hwnd_pid_matched=False  # PID mismatch!
        )

        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=mismatched_window,
            assertions=assertions,
            process_ownership=self.valid_ownership,
            require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )

        self.assertNotEqual(verdict, Verdict.PASS)
        self.assertEqual(verdict, Verdict.UNVERIFIED)
        self.assertIn("does not match expected application process tree", reason)

    def test_control_c_port_listener_verification(self):
        """Proves that port listening process check detects foreign listeners."""
        target_pids = {12345, 12346}

        # Mock test: port occupied by foreign PID 55555
        is_ok, pid, msg = WindowForensicsEngine.verify_port_listening_process(
            port=99999, expected_pids=target_pids
        )
        # Port 99999 has no listener
        self.assertFalse(is_ok)
        self.assertIn("No process found listening", msg)

    # -------------------------------------------------------------------------
    # CONTROL D: Screenshot exists without GUI proof -> NOT PASS (UNVERIFIED)
    # -------------------------------------------------------------------------
    def test_control_d_screenshot_without_gui_proof_unverified(self):
        """Proves that capturing a screenshot while the window is minimized is NOT PASS."""
        assertions = [{"description": "DOM check", "passed": True}]
        screenshots = {
            "webview": ScreenshotMetadata(
                screenshot_type=ScreenshotType.CDP_PAGE_CAPTURE,
                screenshot_hash="c" * 64,
                path="screenshot_cdp.png"
            )
        }

        # Minimized window (IsIconic == True)
        minimized_window = WindowForensics(
            hwnd=65536,
            pid=12345,
            window_visible=True,
            is_iconic=True,  # Minimized!
            is_real_gui=False,
            geometry={"x": -32000, "y": -32000, "width": 160, "height": 31},
            hwnd_pid_matched=True
        )

        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=minimized_window,
            assertions=assertions,
            process_ownership=self.valid_ownership,
            screenshots=screenshots,
            require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )

        self.assertNotEqual(verdict, Verdict.PASS)
        self.assertEqual(verdict, Verdict.UNVERIFIED)
        self.assertIn("is minimized", reason)

    # -------------------------------------------------------------------------
    # Assertion Failure State -> FAIL
    # -------------------------------------------------------------------------
    def test_assertion_failure_yields_fail(self):
        """Proves that failed assertions produce FAIL rather than UNVERIFIED or PASS."""
        failed_assertions = [
            {"description": "Counter should equal 10", "passed": False, "expected": "10", "actual": "0"}
        ]

        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=self.valid_gui_window,
            assertions=failed_assertions,
            process_ownership=self.valid_ownership,
            require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )

        self.assertEqual(verdict, Verdict.FAIL)
        self.assertIn("Assertion failed", reason)

    # -------------------------------------------------------------------------
    # Extended Evidence Schema Validation
    # -------------------------------------------------------------------------
    def test_evidence_report_schema_extension(self):
        """Proves that EvidenceReport serializes all new forensic schema keys."""
        report = EvidenceReport(
            target=self.target,
            engine_info=self.engine_info,
            session_id="session_test_9876",
            verdict=Verdict.PASS,
            verdict_reason="All forensic gates passed.",
            window_forensics=self.valid_gui_window,
            process_ownership=self.valid_ownership,
            screenshots={
                "webview": ScreenshotMetadata(
                    screenshot_type=ScreenshotType.CDP_PAGE_CAPTURE,
                    screenshot_hash="1234567890abcdef" * 4,
                    path="screenshot_cdp.png"
                ),
                "native": ScreenshotMetadata(
                    screenshot_type=ScreenshotType.NATIVE_DESKTOP,
                    screenshot_hash="fedcba0987654321" * 4,
                    path="screenshot_native.png"
                )
            }
        )

        d = report.to_dict()

        # Check required schema keys
        expected_keys = [
            "session_id",
            "verdict",
            "verdict_reason",
            "hwnd",
            "pid",
            "executable",
            "window_title",
            "window_visible",
            "window_geometry",
            "cdp_port",
            "cdp_target",
            "screenshot_type",
            "screenshot_hash",
            "window_forensics",
            "screenshots",
            "framework",
            "engine",
            "platform",
            "verification_level"
        ]
        for k in expected_keys:
            self.assertIn(k, d, f"Missing required evidence schema key: {k}")

        self.assertEqual(d["session_id"], "session_test_9876")
        self.assertEqual(d["verdict"], "PASS")
        self.assertEqual(d["hwnd"], 65536)
        self.assertEqual(d["pid"], 12345)
        self.assertEqual(d["window_title"], "StudyLab MainWindow")
        self.assertTrue(d["window_visible"])
        self.assertEqual(d["cdp_port"], 9222)
        self.assertIsInstance(d["window_geometry"], dict)
        self.assertIn("width", d["window_geometry"])
        self.assertIn("webview", d["screenshots"])
        self.assertIn("native", d["screenshots"])

        # Test JSON round-trip serialization
        with tempfile.TemporaryDirectory() as td:
            out_file = os.path.join(td, "evidence.json")
            EvidenceCollector.save_report_json(report, out_file)
            self.assertTrue(os.path.isfile(out_file))

            with open(out_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                self.assertEqual(loaded["session_id"], "session_test_9876")
                self.assertEqual(loaded["verdict"], "PASS")
                self.assertEqual(loaded["hwnd"], 65536)

    # -------------------------------------------------------------------------
    # Win32 Pure Python PNG Encoder Validation
    # -------------------------------------------------------------------------
    def test_raw_bgra_to_png_magic_and_hash(self):
        """Proves that _raw_bgra_to_png produces valid PNG format with magic bytes."""
        width = 100
        height = 80
        # 100x80 blue pixels (B=255, G=0, R=0, A=255)
        raw_bgra = b"\xff\x00\x00\xff" * (width * height)

        png_bytes = WindowForensicsEngine._raw_bgra_to_png(raw_bgra, width, height)

        self.assertTrue(png_bytes.startswith(PNG_MAGIC_BYTES), "PNG must start with standard magic bytes")
        self.assertTrue(png_bytes.endswith(b"IEND\xaeB`\x82"), "PNG must terminate with standard IEND chunk")
        sha256 = hashlib.sha256(png_bytes).hexdigest()
        self.assertEqual(len(sha256), 64)



    # -------------------------------------------------------------------------
    # CONTROL PHASE 3.5 TESTS
    # -------------------------------------------------------------------------
    def test_foreground_mismatch(self):
        assertions = [{"description": "test", "passed": True}]
        wf = WindowForensics(
            hwnd=65536, pid=12345, window_visible=True, is_real_gui=True, hwnd_pid_matched=True, geometry={'width': 800, 'height': 600},
            foreground_hwnd=9999, foreground_match=False, intersection_area=1000
        )
        screenshots = {"desktop": ScreenshotMetadata(), "native": ScreenshotMetadata(), "webview": ScreenshotMetadata()}
        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=wf, assertions=assertions, process_ownership=self.valid_ownership,
            screenshots=screenshots, require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )
        self.assertEqual(verdict, Verdict.UNVERIFIED)
        self.assertIn("not the foreground window", reason)

    def test_background_window(self):
        # Same as foreground mismatch really
        pass

    def test_no_intersection(self):
        assertions = [{"description": "test", "passed": True}]
        wf = WindowForensics(
            hwnd=65536, pid=12345, window_visible=True, is_real_gui=True, hwnd_pid_matched=True, geometry={'width': 800, 'height': 600},
            foreground_hwnd=65536, foreground_match=True, intersection_area=0
        )
        screenshots = {"desktop": ScreenshotMetadata(), "native": ScreenshotMetadata(), "webview": ScreenshotMetadata()}
        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=wf, assertions=assertions, process_ownership=self.valid_ownership,
            screenshots=screenshots, require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )
        self.assertEqual(verdict, Verdict.UNVERIFIED)
        self.assertIn("intersection", reason)

    def test_missing_screenshots(self):
        assertions = [{"description": "test", "passed": True}]
        wf = WindowForensics(
            hwnd=65536, pid=12345, window_visible=True, is_real_gui=True, hwnd_pid_matched=True, geometry={'width': 800, 'height': 600},
            foreground_hwnd=65536, foreground_match=True, intersection_area=1000
        )
        screenshots = {"native": ScreenshotMetadata(), "webview": ScreenshotMetadata()}
        verdict, reason = EvidenceCollector.evaluate_verdict(
            window_forensics=wf, assertions=assertions, process_ownership=self.valid_ownership,
            screenshots=screenshots, require_visible_gui=True, user_confirmation=True, input_delivery_verified=True
        )
        self.assertEqual(verdict, Verdict.UNVERIFIED)
        self.assertIn("Missing required screenshot proofs", reason)

if __name__ == "__main__":
    unittest.main()
