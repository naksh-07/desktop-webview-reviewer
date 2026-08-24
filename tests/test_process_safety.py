"""
Tests for process safety, ownership tracking, and tree termination.
"""

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

from core.cleanup import ProcessCleanup
from core.models import ProcessOwnership


class TestProcessSafety(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_attach_mode_does_not_terminate_external_process(self):
        # Spawn a benign sleep subprocess
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        pid = proc.pid

        ownership_file = os.path.join(self.temp_dir.name, "ownership.json")
        pid_file = os.path.join(self.temp_dir.name, "app.pid")

        with open(ownership_file, "w") as f:
            json.dump({
                "pid": pid,
                "create_time": time.time(),
                "launched_by_reviewer": False,  # Attached mode
                "port": 9222
            }, f)

        # Run safe cleanup
        success = ProcessCleanup.safe_cleanup(pid_file=pid_file, ownership_file=ownership_file)
        self.assertTrue(success)

        # External process should still be alive!
        poll_status = proc.poll()
        self.assertIsNone(poll_status, "External attached process must NOT be terminated by reviewer cleanup!")

        # Clean up test process
        proc.kill()
        proc.wait()

    def test_create_time_mismatch_prevents_accidental_kill(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        pid = proc.pid

        # Pass a bogus expected create time (e.g. 1000 seconds in past)
        bogus_time = time.time() - 1000.0
        success = ProcessCleanup.terminate_process_tree(pid, expected_create_time=bogus_time)
        self.assertFalse(success, "ProcessCleanup must refuse termination on create_time mismatch")

        # Process should still be alive
        self.assertIsNone(proc.poll())

        proc.kill()
        proc.wait()

    def test_reviewer_launched_process_is_cleanly_terminated(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        pid = proc.pid

        ownership_file = os.path.join(self.temp_dir.name, "ownership.json")
        pid_file = os.path.join(self.temp_dir.name, "app.pid")

        with open(ownership_file, "w") as f:
            json.dump({
                "pid": pid,
                "create_time": time.time(),
                "launched_by_reviewer": True,
                "port": 9222
            }, f)

        success = ProcessCleanup.safe_cleanup(pid_file=pid_file, ownership_file=ownership_file)
        self.assertTrue(success)
        time.sleep(0.3)
        self.assertIsNotNone(proc.poll(), "Reviewer-launched process must be terminated")


if __name__ == "__main__":
    unittest.main()
