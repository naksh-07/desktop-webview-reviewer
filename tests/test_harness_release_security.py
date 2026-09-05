"""
Release CI Security Gate & Zero Backdoor Test Suite (Phase 14).
Validates that release production builds containing any harness modules,
endpoints, symbols, markers, or production bypass switches are strictly rejected.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from runtime.harness_contracts import (
    BuildMode,
    HarnessSecurityValidator,
    HarnessSecurityViolationException,
)
from runtime.harness.build_pipeline import (
    ReleaseSecurityValidator,
    ReleaseValidationResult,
)


class TestHarnessReleaseSecurity(unittest.TestCase):
    """Authoritative test suite for the Release CI Security Gate."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="reviewer_release_audit_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. Build Mode Enforcement
    # -------------------------------------------------------------------------
    def test_build_mode_boundary_enforcement(self):
        """Verifies that harness access is allowed in DEV/REVIEW and forbidden in RELEASE."""
        self.assertTrue(HarnessSecurityValidator.validate_harness_access(BuildMode.DEV))
        self.assertTrue(HarnessSecurityValidator.validate_harness_access(BuildMode.REVIEW))
        self.assertTrue(HarnessSecurityValidator.validate_harness_access("DEV"))
        self.assertTrue(HarnessSecurityValidator.validate_harness_access("REVIEW"))

        with self.assertRaises(HarnessSecurityViolationException):
            HarnessSecurityValidator.validate_harness_access(BuildMode.RELEASE)

        with self.assertRaises(HarnessSecurityViolationException):
            HarnessSecurityValidator.validate_harness_access("RELEASE")

    # -------------------------------------------------------------------------
    # 2. Clean Release Artifact Scanning
    # -------------------------------------------------------------------------
    def test_clean_release_artifact_passes(self):
        """Verifies that an artifact without any harness files or symbols receives PASS."""
        (self.temp_dir / "index.html").write_text("<!DOCTYPE html><html><body>Production App</body></html>", encoding="utf-8")
        (self.temp_dir / "app.js").write_text("console.log('Production clean bundle');\n", encoding="utf-8")
        (self.temp_dir / "styles.css").write_text("body { background: #fff; }\n", encoding="utf-8")

        result = ReleaseSecurityValidator.scan_artifact(self.temp_dir)
        self.assertEqual(result.verdict, "PASS")
        self.assertTrue(result.is_clean)
        self.assertEqual(len(result.findings), 0)
        self.assertEqual(result.scanned_files_count, 3)

    # -------------------------------------------------------------------------
    # 3. Contaminated Release Artifact Scenarios
    # -------------------------------------------------------------------------
    def test_contaminated_with_harness_module_fails(self):
        """Verifies failure if reviewer_harness.dev.js exists in release package."""
        (self.temp_dir / "reviewer_harness.dev.js").write_text("// leaked harness", encoding="utf-8")
        (self.temp_dir / "app.js").write_text("console.log('App');", encoding="utf-8")

        result = ReleaseSecurityValidator.scan_artifact(self.temp_dir)
        self.assertEqual(result.verdict, "FAIL")
        self.assertFalse(result.is_clean)
        types = [f.finding_type for f in result.findings]
        self.assertIn("HARNESS_MODULE_NAME", types)

    def test_contaminated_with_manifest_fails(self):
        """Verifies failure if .reviewer_harness.json is present in release."""
        (self.temp_dir / ".reviewer_harness.json").write_text("{}", encoding="utf-8")

        result = ReleaseSecurityValidator.scan_artifact(self.temp_dir)
        self.assertEqual(result.verdict, "FAIL")
        types = [f.finding_type for f in result.findings]
        self.assertIn("HARNESS_MANIFEST_FILE", types)

    def test_contaminated_with_endpoint_fails(self):
        """Verifies failure if /harness/v1/lifecycle endpoint string is embedded in release scripts."""
        (self.temp_dir / "bundle.js").write_text("const url = 'http://127.0.0.1:9444/harness/v1/lifecycle';", encoding="utf-8")

        result = ReleaseSecurityValidator.scan_artifact(self.temp_dir)
        self.assertEqual(result.verdict, "FAIL")
        types = [f.finding_type for f in result.findings]
        self.assertIn("HARNESS_ENDPOINT", types)

    def test_contaminated_with_dev_markers_fails(self):
        """Verifies failure if REVIEWER_HARNESS_DEV_ONLY markers leak into release build."""
        (self.temp_dir / "main.js").write_text("/* REVIEWER_HARNESS_DEV_ONLY_BEGIN */\ninit();\n", encoding="utf-8")

        result = ReleaseSecurityValidator.scan_artifact(self.temp_dir)
        self.assertEqual(result.verdict, "FAIL")
        types = [f.finding_type for f in result.findings]
        self.assertIn("HARNESS_DEV_MARKER", types)

    def test_contaminated_with_fake_production_switch_fails(self):
        """Verifies failure if dormant runtime backdoor switch (ENABLE_HARNESS) is present."""
        (self.temp_dir / "config.js").write_text("const enable = process.env.ENABLE_HARNESS || false;", encoding="utf-8")

        result = ReleaseSecurityValidator.scan_artifact(self.temp_dir)
        self.assertEqual(result.verdict, "FAIL")
        types = [f.finding_type for f in result.findings]
        self.assertIn("FORBIDDEN_PRODUCTION_SWITCH", types)


if __name__ == "__main__":
    unittest.main()
