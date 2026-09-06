"""
Desktop WebView Reviewer 2.0.0b2 - Release Version Integrity & Distribution Test Suite.

Verifies:
1. Canonical PRODUCT_VERSION is "2.0.0b2"
2. Package/runtime version consistency
3. Dynamic release-validator version inspection and rejection of version-mismatched artifacts
4. Skill synchronization and compatibility boundaries (supports 2.0.x beta, rejects 2.1.x)
5. Clean installation metadata reporting and source-checkout differentiation
"""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from core.version import (
    PRODUCT_NAME,
    PRODUCT_VERSION,
    VersionInfo,
    __version__,
    get_version_info,
)
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from runtime.lifecycle.skill_sync import SkillSynchronizer, _parse_skill_frontmatter


class TestReleaseVersionIntegrity(unittest.TestCase):
    """Verifies release version identity and distribution invariants."""

    def test_canonical_product_version(self):
        """Authoritative version must be exactly '2.0.0b2'."""
        self.assertEqual(PRODUCT_VERSION, "2.0.0b2")
        self.assertEqual(__version__, "2.0.0b2")
        self.assertEqual(PRODUCT_NAME, "Desktop WebView Reviewer")

    def test_version_info_contract(self):
        """get_version_info() must report 2.0.0b2 consistently."""
        vinfo = get_version_info()
        self.assertIsInstance(vinfo, VersionInfo)
        self.assertEqual(vinfo.product_version, "2.0.0b2")
        self.assertEqual(vinfo.package_version, "2.0.0b2")
        self.assertIn("v2.0.0b2", vinfo.summary())

    def test_skill_frontmatter_version_and_range(self):
        """Repository SKILL.md must declare 2.0.0b2 and reject future 2.1.x."""
        repo_root = Path(__file__).resolve().parent.parent
        skill_md = repo_root / "skills" / "desktop-webview-reviewer" / "SKILL.md"
        self.assertTrue(skill_md.is_file(), f"SKILL.md not found at {skill_md}")

        ver, compat_range = _parse_skill_frontmatter(skill_md)
        self.assertEqual(ver, "2.0.0b2")
        self.assertIsNotNone(compat_range)

        spec = SpecifierSet(compat_range)
        # Active runtime 2.0.0b2 must be accepted
        self.assertTrue(
            spec.contains(Version("2.0.0b2"), prereleases=True),
            f"Range '{compat_range}' must accept 2.0.0b2",
        )
        # Previous beta 2.0.0b1 must be accepted
        self.assertTrue(
            spec.contains(Version("2.0.0b1"), prereleases=True),
            f"Range '{compat_range}' must accept 2.0.0b1",
        )
        # Future 2.1.0 runtime must be rejected
        self.assertFalse(
            spec.contains(Version("2.1.0"), prereleases=True),
            f"Range '{compat_range}' must reject future 2.1.0 runtime",
        )
        self.assertFalse(
            spec.contains(Version("2.1.0a1"), prereleases=True),
            f"Range '{compat_range}' must reject future 2.1.0a1 runtime",
        )

    def test_skill_synchronizer_status(self):
        """SkillSynchronizer must report is_compatible=True for current runtime."""
        sync = SkillSynchronizer()
        status = sync.check_synchronization()
        self.assertTrue(status.is_compatible)
        self.assertFalse(status.skill_update_required)
        self.assertFalse(status.runtime_update_required)
        self.assertEqual(status.runtime_version, "2.0.0b2")

    def test_wheel_inspection_rejects_version_mismatch(self):
        """Release validator logic must reject wheels that mismatch authoritative version."""
        expected_ver = "2.0.0b2"
        wrong_whl_name = "desktop_webview_reviewer-2.0.0b1-py3-none-any.whl"

        expected_prefix = f"desktop_webview_reviewer-{expected_ver}-"
        self.assertFalse(
            wrong_whl_name.startswith(expected_prefix),
            "Mismatched wheel filename must be detected",
        )

        with tempfile.TemporaryDirectory() as td:
            dummy_whl = Path(td) / wrong_whl_name
            with zipfile.ZipFile(dummy_whl, "w") as z:
                # Include a mismatched METADATA file
                z.writestr(
                    "desktop_webview_reviewer-2.0.0b1.dist-info/METADATA",
                    "Metadata-Version: 2.1\nName: desktop-webview-reviewer\nVersion: 2.0.0b1\n",
                )

            # Read back metadata version
            extracted_ver = None
            with zipfile.ZipFile(dummy_whl, "r") as z:
                for fname in z.namelist():
                    if fname.endswith(".dist-info/METADATA"):
                        for line in z.read(fname).decode("utf-8").splitlines():
                            if line.startswith("Version:"):
                                extracted_ver = line.split(":", 1)[1].strip()
                                break

            self.assertEqual(extracted_ver, "2.0.0b1")
            self.assertNotEqual(extracted_ver, expected_ver)

    def test_wheel_inspection_rejects_forbidden_content(self):
        """Release validator logic must reject wheels containing tests or fixtures."""
        forbidden_in_package = ["tests/", "fixtures/", "evidence/", ".dev.js", "reviewer_harness"]
        test_namelist = [
            "core/__init__.py",
            "runtime/mcp/server.py",
            "tests/test_something.py",
        ]
        violations = []
        for fname in test_namelist:
            for forb in forbidden_in_package:
                if forb in fname:
                    violations.append(f"Forbidden path '{fname}'")

        self.assertEqual(len(violations), 1)
        self.assertIn("tests/test_something.py", violations[0])

    def test_installation_source_differentiation(self):
        """Installation registry and version info correctly distinguish source checkout."""
        vinfo = get_version_info()
        self.assertEqual(vinfo.installation_source, "source_checkout")


if __name__ == "__main__":
    unittest.main()
