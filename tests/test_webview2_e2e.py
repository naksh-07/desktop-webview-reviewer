"""
Real runtime E2E test for Microsoft Edge / WebView2 on Windows.
"""

import asyncio
import glob
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from adapters import get_adapter
from core.cleanup import ProcessCleanup
from core.models import TargetCriteria, VerificationLevel


def find_edge_or_webview2_binary():
    if sys.platform != "win32":
        return None

    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    # Check WebView2 application folder
    wv2_matches = glob.glob(r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe")
    if wv2_matches:
        candidates.extend(wv2_matches)

    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


class TestWebView2RealRuntimeE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edge_binary = find_edge_or_webview2_binary()
        if not cls.edge_binary:
            raise unittest.SkipTest("Microsoft Edge / WebView2 runtime binary not found on this host.")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.port = 9232
        self.fixture_html = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", "webview2_app.html"))
        self.assertTrue(os.path.isfile(self.fixture_html), f"Fixture HTML missing: {self.fixture_html}")
        self.proc = None

    def tearDown(self):
        if self.proc:
            ProcessCleanup.terminate_process_tree(self.proc.pid)
            try:
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self.proc = None
        self.temp_dir.cleanup()

    def test_webview2_full_lifecycle(self):
        adapter = get_adapter("webview2")
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.engine_name, "webview2")

        # Launch Edge in standalone app mode on isolated debug port
        user_data = os.path.join(self.temp_dir.name, "user_data")
        os.makedirs(user_data, exist_ok=True)

        cmd = [
            self.edge_binary,
            f"--app=file:///{self.fixture_html.replace(os.sep, '/')}",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={user_data}",
            "--no-first-run",
            "--no-default-browser-check"
        ]

        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        self.assertIsNotNone(self.proc.pid)

        # Run async lifecycle inspection
        async def run_lifecycle():
            # 1. Discover targets
            targets = adapter.discover_targets(port=self.port, timeout=12.0)
            self.assertTrue(len(targets) > 0, "Should discover at least one target")

            # Select application target (must filter extensions/workers)
            criteria = TargetCriteria(target_type="page")
            selected = adapter.select_target(targets, criteria)
            self.assertIsNotNone(selected)
            self.assertTrue(selected.is_application)
            self.assertIsNotNone(selected.websocket_endpoint)

            # 2. Attach
            session = await adapter.attach(selected)
            actions = adapter.create_actions(session)
            assertions = adapter.create_assertions(session)
            collector = adapter.create_evidence_collector(session)

            try:
                # 3. DOM & State Assertions
                await assertions.assert_exists("#counter-value", "Counter element exists")
                await assertions.assert_text_contains("#counter-value", "0", "Initial counter value is 0")

                # 4. Click Interaction
                geom = await actions.click("#increment-btn")
                self.assertIsNotNone(geom)
                await asyncio.sleep(0.3)

                # Verify counter incremented to 1
                await assertions.assert_text_contains("#counter-value", "1", "Counter value incremented to 1")

                # 5. Type Interaction
                await actions.type_text("#test-input", "WebView2 Verified!")
                input_val = await actions.get_attribute("#test-input", "value")
                self.assertEqual(input_val, "WebView2 Verified!")

                # 6. Screenshot & Evidence
                shot_path = os.path.join(self.temp_dir.name, "wv2_shot.png")
                sha256 = await collector.capture_screenshot_file(shot_path)
                self.assertTrue(os.path.isfile(shot_path))
                self.assertTrue(len(sha256) == 64)

                evidence_path = os.path.join(self.temp_dir.name, "wv2_evidence.json")
                report = await collector.build_report(
                    screenshot_path=shot_path,
                    assertions=[r.to_dict() for r in assertions.history],
                    actions=actions.history,
                    verification_level=VerificationLevel.RUNTIME_VERIFIED
                )
                collector.save_report_json(report, evidence_path)
                self.assertTrue(os.path.isfile(evidence_path))

                with open(evidence_path, "r", encoding="utf-8") as f:
                    evidence_data = json.load(f)
                    self.assertEqual(evidence_data["engine"], "webview2")
                    self.assertEqual(evidence_data["verification_level"], "runtime_verified")
                    self.assertTrue(len(evidence_data["actions"]) >= 2)
                    self.assertTrue(len(evidence_data["state_assertions"]) >= 3)
            finally:
                await adapter.detach(session)

        asyncio.run(run_lifecycle())

        # 7. Cleanup
        clean_ok = ProcessCleanup.terminate_process_tree(self.proc.pid)
        self.assertTrue(clean_ok)
        self.proc = None


if __name__ == "__main__":
    unittest.main()
