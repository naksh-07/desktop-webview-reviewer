"""
Unit and Integration Tests for Project Detection, Surgical Injection & Reversal (Phase 13).
Verifies framework detection, dry-run, minimal marker-based injection, manifest generation,
and safe reversible uninstallation.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from runtime.harness.detector import ProjectDetector
from runtime.harness.injector import (
    HarnessInjector,
    HarnessInjectionError,
    UnsafeReversalError,
)
from runtime.harness.manifest import IntegrationManifest, MANIFEST_FILENAME


class TestHarnessInjection(unittest.TestCase):
    """Authoritative test suite for project detection and surgical injection/removal."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="reviewer_test_proj_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. Project Framework Detection
    # -------------------------------------------------------------------------
    def test_detect_electron_project(self):
        """Verifies accurate detection of Electron project from package.json and entry point."""
        pkg = {
            "name": "sample-electron-app",
            "version": "1.0.0",
            "main": "main.js",
            "dependencies": {
                "electron": "^28.0.0",
            },
        }
        (self.temp_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        (self.temp_dir / "main.js").write_text("const { app } = require('electron');\nconsole.log('App starting');\n", encoding="utf-8")

        res = ProjectDetector.detect(self.temp_dir)
        self.assertTrue(res.is_supported)
        self.assertEqual(res.framework, "electron")
        self.assertEqual(res.adapter, "electron")
        self.assertGreater(res.confidence, 0.7)
        self.assertIn("main.js", res.entry_points)

    def test_detect_webview2_project(self):
        """Verifies accurate detection of WebView2 C# project."""
        csproj = """<Project Sdk="Microsoft.NET.Sdk">
  <ItemGroup>
    <PackageReference Include="Microsoft.Web.WebView2" Version="1.0.2210.55" />
  </ItemGroup>
</Project>"""
        (self.temp_dir / "App.csproj").write_text(csproj, encoding="utf-8")
        (self.temp_dir / "MainWindow.xaml.cs").write_text("using Microsoft.Web.WebView2;\npublic class MainWindow {}\n", encoding="utf-8")

        res = ProjectDetector.detect(self.temp_dir)
        self.assertTrue(res.is_supported)
        self.assertEqual(res.framework, "webview2")
        self.assertEqual(res.adapter, "webview2")
        self.assertGreater(res.confidence, 0.7)

    def test_detect_qt_project(self):
        """Verifies accurate detection of PyQt/PySide QtWebEngine project."""
        reqs = "PyQt6>=6.5.0\nPyQt6-WebEngine>=6.5.0\n"
        (self.temp_dir / "requirements.txt").write_text(reqs, encoding="utf-8")
        (self.temp_dir / "main.py").write_text("from PyQt6.QtWebEngineWidgets import QWebEngineView\n", encoding="utf-8")

        res = ProjectDetector.detect(self.temp_dir)
        self.assertTrue(res.is_supported)
        self.assertEqual(res.framework, "qt")
        self.assertGreater(res.confidence, 0.7)

    def test_detect_unsupported_project_fails_safely(self):
        """Verifies that an unsupported project directory returns is_supported=False."""
        (self.temp_dir / "README.md").write_text("# Plain Documentation Project\n", encoding="utf-8")

        res = ProjectDetector.detect(self.temp_dir)
        self.assertFalse(res.is_supported)
        self.assertIsNone(res.framework)

    # -------------------------------------------------------------------------
    # 2. Dry Run Preview
    # -------------------------------------------------------------------------
    def test_dry_run_produces_no_filesystem_changes(self):
        """Verifies that --dry-run reports the planned modifications without touching files."""
        pkg = {"name": "dry-app", "dependencies": {"electron": "^28.0.0"}, "main": "index.js"}
        (self.temp_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        entry_file = self.temp_dir / "index.js"
        orig_content = "console.log('Original content');\n"
        entry_file.write_text(orig_content, encoding="utf-8")

        plan = HarnessInjector.plan(self.temp_dir)
        manifest, report = HarnessInjector.apply(plan, dry_run=True)

        self.assertTrue(report["dry_run"])
        # Original file unchanged
        self.assertEqual(entry_file.read_text(encoding="utf-8"), orig_content)
        # Manifest not saved
        self.assertFalse((self.temp_dir / MANIFEST_FILENAME).exists())
        # Added files not created
        self.assertFalse((self.temp_dir / "reviewer_harness.dev.js").exists())

    # -------------------------------------------------------------------------
    # 3. Live Surgical Injection & Manifest Generation
    # -------------------------------------------------------------------------
    def test_live_injection_and_manifest_generation(self):
        """Verifies surgical injection into entry point and manifest creation."""
        pkg = {"name": "live-app", "dependencies": {"electron": "^28.0.0"}, "main": "main.js"}
        (self.temp_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        entry_file = self.temp_dir / "main.js"
        orig_content = "const { app } = require('electron');\napp.on('ready', () => {});\n"
        entry_file.write_text(orig_content, encoding="utf-8")

        plan = HarnessInjector.plan(self.temp_dir)
        manifest, report = HarnessInjector.apply(plan, dry_run=False)

        # Manifest created
        manifest_path = self.temp_dir / MANIFEST_FILENAME
        self.assertTrue(manifest_path.exists())
        loaded = IntegrationManifest.load(self.temp_dir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.framework, "electron")

        # Added client file exists
        client_file = self.temp_dir / "reviewer_harness.dev.js"
        self.assertTrue(client_file.exists())
        self.assertIn("initReviewerHarness", client_file.read_text(encoding="utf-8"))

        # Target entry point modified with markers
        mod_content = entry_file.read_text(encoding="utf-8")
        self.assertIn("REVIEWER_HARNESS_DEV_ONLY_BEGIN", mod_content)
        self.assertIn("REVIEWER_HARNESS_DEV_ONLY_END", mod_content)
        self.assertIn(orig_content, mod_content)

    # -------------------------------------------------------------------------
    # 4. Reversible Uninstallation
    # -------------------------------------------------------------------------
    def test_reversible_removal_restores_original_code(self):
        """Verifies that harness remove cleanly restores files to exact original state."""
        pkg = {"name": "rev-app", "dependencies": {"electron": "^28.0.0"}, "main": "main.js"}
        (self.temp_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        entry_file = self.temp_dir / "main.js"
        orig_content = "const { app } = require('electron');\napp.on('ready', () => {});\n"
        entry_file.write_text(orig_content, encoding="utf-8")

        # Inject
        plan = HarnessInjector.plan(self.temp_dir)
        HarnessInjector.apply(plan, dry_run=False)

        # Remove
        rem_report = HarnessInjector.remove(self.temp_dir)
        self.assertEqual(rem_report["status"], "REMOVED")

        # Added file deleted
        self.assertFalse((self.temp_dir / "reviewer_harness.dev.js").exists())
        # Manifest deleted
        self.assertFalse((self.temp_dir / MANIFEST_FILENAME).exists())
        # Entry point cleanly restored
        restored = entry_file.read_text(encoding="utf-8").strip()
        self.assertEqual(restored, orig_content.strip())

    def test_unsafe_reversal_aborts_if_markers_corrupted(self):
        """Verifies that removal refuses destructive changes if markers were altered."""
        pkg = {"name": "corrupt-app", "dependencies": {"electron": "^28.0.0"}, "main": "main.js"}
        (self.temp_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        entry_file = self.temp_dir / "main.js"
        entry_file.write_text("console.log('App');\n", encoding="utf-8")

        plan = HarnessInjector.plan(self.temp_dir)
        HarnessInjector.apply(plan, dry_run=False)

        # Corrupt the markers manually
        content = entry_file.read_text(encoding="utf-8")
        corrupted = content.replace("REVIEWER_HARNESS_DEV_ONLY_END", "TAMPERED_MARKER")
        entry_file.write_text(corrupted, encoding="utf-8")

        # Removal must refuse
        with self.assertRaises(UnsafeReversalError):
            HarnessInjector.remove(self.temp_dir)


if __name__ == "__main__":
    unittest.main()
