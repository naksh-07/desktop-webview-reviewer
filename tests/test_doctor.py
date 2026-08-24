"""
Unit tests for doctor.py diagnostic tool.
"""

import json
import os
import subprocess
import sys
import unittest

try:
    from .env_config import CORE_SKILL_DIR, get_python_exe
except ImportError:
    from env_config import CORE_SKILL_DIR, get_python_exe


class TestDoctorDiagnostics(unittest.TestCase):
    def setUp(self):
        self.doctor_script = os.path.join(CORE_SKILL_DIR, "scripts", "doctor.py")
        self.python_exe = get_python_exe()

    def test_doctor_script_exists(self):
        self.assertTrue(os.path.isfile(self.doctor_script), f"doctor.py not found at {self.doctor_script}")

    def test_doctor_execution_default(self):
        res = subprocess.run(
            [self.python_exe, self.doctor_script],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"Doctor failed with stderr: {res.stderr}")
        self.assertIn("Desktop WebView Reviewer v1.0.0 - Doctor Check", res.stdout)
        self.assertIn("Python Environment:", res.stdout)
        self.assertIn("Core Dependencies:", res.stdout)
        self.assertIn("Overall Health:", res.stdout)
        self.assertIn("READY", res.stdout)

    def test_doctor_json_output(self):
        res = subprocess.run(
            [self.python_exe, self.doctor_script, "--json"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"Doctor --json failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["version"], "1.0.0")
        self.assertTrue(data["overall_ready"])
        self.assertIn("environment", data)
        self.assertIn("dependencies", data)
        self.assertIn("engines", data)
        self.assertIn("QtWebEngine", data["engines"])
        self.assertIn("WebView2", data["engines"])
        self.assertIn("Electron", data["engines"])
        self.assertIn("Generic Chromium", data["engines"])
        self.assertIn("CEF", data["engines"])
        self.assertIn("WebKit", data["engines"])

    def test_doctor_verbose_output(self):
        res = subprocess.run(
            [self.python_exe, self.doctor_script, "--verbose"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Diagnostic Details:", res.stdout)
        self.assertIn("Skill Root:", res.stdout)


if __name__ == "__main__":
    unittest.main()
