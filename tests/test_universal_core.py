"""
Complete end-to-end regression suite for desktop-webview-reviewer core and qtwebengine adapter.
"""

import asyncio
import os
import sys
import time
import psutil

# Add desktop-webview-reviewer to sys.path
try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from core.capabilities import CapabilityRegistry
from core.cleanup import ProcessCleanup
from core.models import CapabilityName, CapabilityStatus, TargetCriteria
from detectors.engine_detector import EngineDetector
from launchers.process_launcher import ProcessLauncher


async def run_e2e_verification():
    print("=" * 70)
    print("STARTING UNIVERSAL DESKTOP WEBVIEW REVIEWER E2E VERIFICATION")
    print("=" * 70)

    # 1. Clean previous state
    ProcessCleanup.clean_state_files([
        "desktop_app.pid", "desktop_ws_url.txt", "qt_app.pid", "qt_ws_url.txt", "e2e_screenshot.png", "e2e_evidence.json"
    ])

    test_app_path = os.path.join(CORE_SKILL_DIR, "examples", "test_app.py")
    assert os.path.exists(test_app_path), f"Test app not found at {test_app_path}"

    # 2. Detect adapter
    adapter = EngineDetector.resolve_adapter(target_path_or_pid=test_app_path)
    print(f"Step 1: Detected engine adapter -> '{adapter.engine_name}'")
    assert adapter.engine_name == "qtwebengine", f"Expected qtwebengine, got {adapter.engine_name}"

    # 3. Check capabilities
    engine_info = adapter.get_engine_info()
    assert CapabilityRegistry.is_supported(engine_info, CapabilityName.DOM)
    assert CapabilityRegistry.is_supported(engine_info, CapabilityName.INPUT)
    assert CapabilityRegistry.is_supported(engine_info, CapabilityName.SCREENSHOT)
    print("Step 2: Capabilities verified successfully.")

    # 4. Launch App
    print("Step 3: Launching desktop application...")
    pid = ProcessLauncher.launch(
        executable_or_script=test_app_path,
        adapter=adapter,
        port=9222,
        pid_file="desktop_app.pid",
        log_file="desktop_app.log",
        init_delay=2.0
    )
    print(f"  Launched successfully with PID: {pid}")
    assert psutil.pid_exists(pid), f"PID {pid} is not running"

    session = None
    try:
        # 5. Target Discovery
        print("Step 4: Discovering targets via adapter...")
        targets = adapter.discover_targets(host="127.0.0.1", port=9222, timeout=10.0)
        assert len(targets) > 0, "No targets discovered at 127.0.0.1:9222"
        print(f"  Found {len(targets)} target(s).")

        selected = adapter.select_target(targets, TargetCriteria(target_type="page"))
        assert selected is not None and selected.websocket_endpoint is not None, "Target selection failed"
        print(f"  Selected target: '{selected.title}' ({selected.websocket_endpoint})")

        # 6. CDP Attachment & Domain Initialization
        print("Step 5: Attaching CDP session...")
        session = await adapter.attach(selected)
        assert session.is_connected, "CDP session failed to connect"
        print("  Attached successfully to page-level WebSocket.")

        actions = adapter.create_actions(session)
        assertions = adapter.create_assertions(session)
        collector = adapter.create_evidence_collector(session)

        # 7. DOM Inspection & Initial Assertions
        print("Step 6: Inspecting DOM structure and initial state...")
        doc = await session.get_document()
        assert doc.get("nodeId", 0) > 0, "Failed to retrieve DOM document root"

        await assertions.assert_exists("#counter", "Element #counter exists")
        await assertions.assert_exists("#incrementButton", "Element #incrementButton exists")
        await assertions.assert_text_equals("#counter", "0", "Initial counter value is 0")
        await assertions.assert_text_contains("#status", "Ready", "Initial status is Ready")

        # 8. Real UI Interaction: Click #incrementButton
        print("Step 7: Dispatching real mouse interaction to #incrementButton...")
        geom = await actions.click("#incrementButton")
        print(f"  Clicked at center ({geom.center_x:.1f}, {geom.center_y:.1f})")
        await asyncio.sleep(0.3)

        # 9. State Verification Post-Click
        print("Step 8: Verifying DOM mutation after interaction...")
        await assertions.assert_text_equals("#counter", "1", "Counter value updated to 1")
        await assertions.assert_text_contains("#status", "Counter updated to 1", "Status text updated")

        assert assertions.all_passed, "One or more DOM state assertions failed"
        print("  All DOM state assertions PASSED.")

        # 10. Screenshot Capture & Validation
        print("Step 9: Capturing screenshot and validating artifact...")
        screenshot_path = "e2e_screenshot.png"
        sha256 = await collector.capture_screenshot_file(screenshot_path)
        assert os.path.exists(screenshot_path), "Screenshot file was not created"
        assert os.path.getsize(screenshot_path) > 1000, "Screenshot file size unexpectedly small"
        print(f"  Screenshot validated ({os.path.getsize(screenshot_path)} bytes, SHA-256: {sha256})")

        # 11. Evidence Report Generation
        print("Step 10: Building structured evidence report...")
        report = await collector.build_report(
            screenshot_path=screenshot_path,
            assertions=[r.to_dict() for r in assertions.history],
            extra_metadata={"suite": "Universal Core E2E Verification"}
        )
        collector.save_report_json(report, "e2e_evidence.json")
        assert os.path.exists("e2e_evidence.json"), "e2e_evidence.json was not created"
        print("  e2e_evidence.json generated and validated.")

    finally:
        # 12. Teardown and Process Cleanup
        print("Step 11: Detaching session and tearing down process tree...")
        if session:
            await adapter.detach(session)

        stopped = adapter.cleanup_process(pid, timeout=3.0)
        assert stopped, f"Failed to stop PID {pid}"
        time.sleep(1.0)
        assert not psutil.pid_exists(pid), f"PID {pid} is still alive after cleanup"
        ProcessCleanup.clean_state_files(["desktop_app.pid", "desktop_ws_url.txt", "qt_app.pid", "qt_ws_url.txt"])
        print("  Process tree and state files cleanly terminated.")

    print("\n" + "=" * 70)
    print("E2E VERIFICATION COMPLETED WITH 100% PASS RATE!")
    print("=" * 70)


import unittest


class TestUniversalCoreE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import PyQt6.QtWebEngineWidgets
        except ImportError:
            raise unittest.SkipTest("PyQt6 and PyQt6-WebEngine are required for QtWebEngine E2E verification.")

    def test_e2e_verification(self):
        asyncio.run(run_e2e_verification())



if __name__ == "__main__":
    unittest.main()
