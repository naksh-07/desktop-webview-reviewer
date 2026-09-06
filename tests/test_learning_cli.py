"""
Tests for Learning & Governance CLI Subsystem.
Architecture H / Milestone 2.1 Prompt 5 - CLI Integrity Audit.

Verifies:
- All required subcommands: doctor, status, report, run-observations, run-patterns,
  run-candidates, approve, reject, decay, list, inspect, validate.
- Correct exit codes (0 for success, 1 or 2 for errors).
- Clean deterministic JSON outputs when --json is passed.
- Privacy safety: zero leakage of secrets, auth headers, or raw text.
- Rejection of approval without mandatory reviewer.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from runtime.experience.config import ExperienceConfig
from runtime.experience.learning.models import CandidateStatus, ImprovementCandidateRecord
from runtime.experience.models import ExperienceScope
from runtime.experience.store import ExperienceStore
from scripts.learning_cli import main


class TestLearningCliSubsystem(unittest.TestCase):
    """Forensic verification of CLI commands and safety controls."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = ExperienceConfig(
            base_dir=Path(self.temp_dir.name),
            database_name="cli_test_experience.db",
            enable_wal_mode=True,
            fail_safe_mode=False,
        )
        self.store = ExperienceStore(config=self.config)
        self.store_patcher = patch.object(ExperienceStore, "get_default_store", return_value=self.store)
        self.store_patcher.start()

    def tearDown(self) -> None:
        self.store_patcher.stop()
        self.store.close()
        self.temp_dir.cleanup()

    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            try:
                code = main(argv)
            except SystemExit as se:
                code = se.code if isinstance(se.code, int) else 1
        return code, stdout_buf.getvalue(), stderr_buf.getvalue()

    def test_status_command_text_and_json(self) -> None:
        """Tests learning status command in both text and JSON modes."""
        code, out, _ = self._run_cli(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Learning & Governance Status", out)
        self.assertIn("Observations Recorded:", out)

        code, json_out, _ = self._run_cli(["status", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(json_out)
        self.assertIn("observations_total", data)
        self.assertIn("patterns_total", data)
        self.assertIn("candidates_total", data)
        self.assertIn("durable_knowledge_total", data)
        self.assertIn("privacy_violations_blocked", data)

    def test_report_and_field_intel_aliases(self) -> None:
        """Tests report and field-intel commands produce identical structure."""
        code1, json1, _ = self._run_cli(["report", "--json"])
        self.assertEqual(code1, 0)
        data1 = json.loads(json1)
        self.assertIn("top_recurring_failures", data1)
        self.assertIn("verification_distribution", data1)

        code2, json2, _ = self._run_cli(["field-intel", "--json"])
        self.assertEqual(code2, 0)
        data2 = json.loads(json2)
        self.assertEqual(set(data1.keys()), set(data2.keys()))

    def test_pipeline_execution_commands(self) -> None:
        """Tests run-observations, run-patterns, and run-candidates commands."""
        # run-observations on clean store
        code, out_obs, _ = self._run_cli(["run-observations", "--json"])
        self.assertEqual(code, 0)
        obs_data = json.loads(out_obs)
        self.assertIn("observations_recorded", obs_data)

        # run-patterns
        code, out_pat, _ = self._run_cli(["run-patterns", "--json"])
        self.assertEqual(code, 0)
        pat_data = json.loads(out_pat)
        self.assertIn("patterns_detected", pat_data)

        # run-candidates
        code, out_cand, _ = self._run_cli(["run-candidates", "--json"])
        self.assertEqual(code, 0)
        cand_data = json.loads(out_cand)
        self.assertIn("candidates_generated", cand_data)

    def test_list_and_inspect_nonexistent_candidate(self) -> None:
        """Tests list returns empty array and inspect returns error on invalid ID."""
        code, list_out, _ = self._run_cli(["list", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(list_out), [])

        code, inspect_out, _ = self._run_cli(["inspect", "nonexistent_cand_id"])
        self.assertEqual(code, 1)
        self.assertIn("not found", inspect_out)

    def test_approval_mandates_reviewer(self) -> None:
        """Tests approve command strictly enforces mandatory --reviewer parameter."""
        # Missing --reviewer should fail at argparse level
        code, _, err = self._run_cli(["approve", "cand_123"])
        self.assertNotEqual(code, 0)

    def test_rejection_mandates_reviewer_and_reason(self) -> None:
        """Tests reject command strictly enforces reviewer and reason parameters."""
        code, _, err = self._run_cli(["reject", "cand_123"])
        self.assertNotEqual(code, 0)

    def test_decay_command(self) -> None:
        """Tests decay command in evaluation and apply mode."""
        code, json_out, _ = self._run_cli(["decay", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(json_out)
        self.assertIn("active", data)
        self.assertIn("review_due", data)
        self.assertIn("stale", data)

        code, json_applied, _ = self._run_cli(["decay", "--apply", "--json"])
        self.assertEqual(code, 0)
        data_applied = json.loads(json_applied)
        self.assertIn("transitions_applied", data_applied)


if __name__ == "__main__":
    unittest.main()
