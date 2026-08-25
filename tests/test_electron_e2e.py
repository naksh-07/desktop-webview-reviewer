"""
Real runtime E2E test for Electron application testing.
"""

import asyncio
import json
import os
import shutil
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


class TestElectronRealRuntimeE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Check npx / electron availability
        npx_path = shutil.which("npx") or shutil.which("npx.cmd")
        if not npx_path:
            raise unittest.SkipTest("npx is not available on this host.")
        cls.npx_cmd = npx_path

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.port = 9234
        self.fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", "electron_app"))
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

    def test_electron_full_lifecycle(self):
        adapter = get_adapter("electron")
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.engine_name, "electron")

        if sys.platform == "win32" and self.npx_cmd.lower().endswith((".cmd", ".bat")):
            cmd = ["cmd.exe", "/c", self.npx_cmd, "electron", os.path.join(self.fixture_dir, "main.js"), f"--remote-debugging-port={self.port}"]
        else:
            cmd = [self.npx_cmd, "electron", os.path.join(self.fixture_dir, "main.js"), f"--remote-debugging-port={self.port}"]

        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        self.assertIsNotNone(self.proc.pid)

        async def run_lifecycle():
            # 1. Discover targets
            targets = adapter.discover_targets(port=self.port, timeout=15.0)
            self.assertTrue(len(targets) > 0, "Should discover Electron targets")

            # Select application target
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
                await actions.type_text("#test-input", "Electron Verified!")
                input_val = await actions.get_value("#test-input")
                self.assertEqual(input_val, "Electron Verified!")

                # 6. Screenshot & Evidence
                shot_path = os.path.join(self.temp_dir.name, "electron_shot.png")
                sha256 = await collector.capture_screenshot_file(shot_path)
                self.assertTrue(os.path.isfile(shot_path))
                self.assertTrue(len(sha256) == 64)

                evidence_path = os.path.join(self.temp_dir.name, "electron_evidence.json")
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
                    self.assertEqual(evidence_data["engine"], "electron")
                    self.assertEqual(evidence_data["verification_level"], "runtime_verified")
                    self.assertTrue(len(evidence_data["actions"]) >= 2)
            finally:
                await adapter.detach(session)

        asyncio.run(run_lifecycle())

        # Cleanup
        clean_ok = ProcessCleanup.terminate_process_tree(self.proc.pid)
        self.assertTrue(clean_ok)
        self.proc = None


if __name__ == "__main__":
    unittest.main()
