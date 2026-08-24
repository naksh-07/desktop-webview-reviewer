"""
Universal CLI end-to-end lifecycle verification test.
Tests launch.py -> discover.py -> review.py -> stop.py -> doctor.py CLI execution.
"""

import json
import os
import subprocess
import sys
import time
import unittest

try:
    from .env_config import CORE_SKILL_DIR, get_python_exe
except ImportError:
    from env_config import CORE_SKILL_DIR, get_python_exe


class TestCLILifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import PyQt6.QtWebEngineWidgets
        except ImportError:
            raise unittest.SkipTest("PyQt6 and PyQt6-WebEngine required for live Qt CLI test.")

    def setUp(self):
        self.python_exe = get_python_exe()
        self.scripts_dir = os.path.join(CORE_SKILL_DIR, "scripts")
        self.test_app = os.path.join(CORE_SKILL_DIR, "examples", "test_app.py")
        self.port = 9255

    def tearDown(self):
        stop_script = os.path.join(self.scripts_dir, "stop.py")
        subprocess.run([self.python_exe, stop_script, "--pid-file", "cli_test_app.pid"], capture_output=True)
        for f in ("cli_test_app.pid", "cli_test_ws.txt", "cli_test_shot.png", "cli_test_evidence.json", "desktop_ownership.json"):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def test_full_cli_lifecycle(self):
        launch_script = os.path.join(self.scripts_dir, "launch.py")
        discover_script = os.path.join(self.scripts_dir, "discover.py")
        review_script = os.path.join(self.scripts_dir, "review.py")
        stop_script = os.path.join(self.scripts_dir, "stop.py")

        # 1. Launch CLI
        launch_res = subprocess.run(
            [
                self.python_exe, launch_script, self.test_app,
                "--engine", "qtwebengine",
                "--port", str(self.port),
                "--pid-file", "cli_test_app.pid",
                "--init-delay", "3.0"
            ],
            capture_output=True,
            text=True
        )
        self.assertEqual(launch_res.returncode, 0, f"Launch failed: {launch_res.stderr}")
        self.assertIn("Application launched successfully", launch_res.stdout)
        self.assertTrue(os.path.exists("cli_test_app.pid"))

        # 2. Discover CLI
        discover_res = subprocess.run(
            [
                self.python_exe, discover_script,
                "--engine", "qtwebengine",
                "--port", str(self.port),
                "--out-ws", "cli_test_ws.txt",
                "--timeout", "10.0"
            ],
            capture_output=True,
            text=True
        )
        self.assertEqual(discover_res.returncode, 0, f"Discover failed: {discover_res.stderr}\nStdout: {discover_res.stdout}")
        self.assertTrue(os.path.exists("cli_test_ws.txt"))
        with open("cli_test_ws.txt", "r") as f:
            ws_url = f.read().strip()
        self.assertTrue(ws_url.startswith("ws://127.0.0.1:"))

        # 3. Review CLI
        review_res = subprocess.run(
            [
                self.python_exe, review_script,
                "--ws-file", "cli_test_ws.txt",
                "--engine", "qtwebengine",
                "--click", "#incrementButton",
                "--assert-selector", "#counter",
                "--assert-text", "1",
                "--screenshot", "cli_test_shot.png",
                "--evidence", "cli_test_evidence.json"
            ],
            capture_output=True,
            text=True
        )
        self.assertEqual(review_res.returncode, 0, f"Review failed: {review_res.stderr}\nStdout: {review_res.stdout}")
        self.assertTrue(os.path.exists("cli_test_shot.png"))
        self.assertTrue(os.path.exists("cli_test_evidence.json"))

        # Validate Evidence
        with open("cli_test_evidence.json", "r", encoding="utf-8") as f:
            ev = json.load(f)
        self.assertEqual(ev["engine"], "qtwebengine")
        self.assertEqual(ev["verification_level"], "runtime_verified")
        self.assertTrue(len(ev["actions"]) >= 1)
        self.assertTrue(len(ev["state_assertions"]) >= 1)
        self.assertTrue(ev["state_assertions"][0]["passed"])

        # 4. Stop CLI
        stop_res = subprocess.run(
            [self.python_exe, stop_script, "--pid-file", "cli_test_app.pid"],
            capture_output=True,
            text=True
        )
        self.assertEqual(stop_res.returncode, 0, f"Stop failed: {stop_res.stderr}")
        self.assertIn("Cleanup completed successfully", stop_res.stdout)


if __name__ == "__main__":
    unittest.main()
