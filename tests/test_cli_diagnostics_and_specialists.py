"""
Unit tests for CLI diagnostic, specialist, and recovery subcommands (Phase 16 - Prompt P4).
"""
import io
import json
import unittest
from contextlib import redirect_stdout
from scripts.cli import main


class TestCliDiagnosticsAndSpecialists(unittest.TestCase):
    def test_cli_specialists_list(self):
        """CLI specialists list outputs all 5 canonical specialist roles."""
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                main(["specialists", "list"])
            except SystemExit:
                pass
        out = f.getvalue()
        self.assertIn("EXPLORER", out)
        self.assertIn("TESTER", out)
        self.assertIn("REALITY_INSPECTOR", out)
        self.assertIn("DEBUGGER", out)
        self.assertIn("EVIDENCE_SPECIALIST", out)

    def test_cli_specialists_contract_json(self):
        """CLI specialists contract outputs valid JSON contract details."""
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                main(["specialists", "contract", "EXPLORER", "--json"])
            except SystemExit:
                pass
        out = f.getvalue()
        data = json.loads(out)
        self.assertEqual(data["role"], "EXPLORER")
        self.assertTrue(data["is_read_only"])
        self.assertIn("desktop_inspect", data["permitted_tools"])

    def test_cli_recovery_candidates(self):
        """CLI recovery candidates outputs bounded actions for a failure category."""
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                main(["recovery", "candidates", "WINDOW_CLOAKED", "--json"])
            except SystemExit:
                pass
        out = f.getvalue()
        data = json.loads(out)
        self.assertEqual(data["failure_category"], "WINDOW_CLOAKED")
        self.assertIn("REFRESH_OBSERVATION", data["recovery_candidates"])

    def test_cli_recovery_status(self):
        """CLI recovery status prints circuit breaker information."""
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                main(["recovery", "status", "--json"])
            except SystemExit:
                pass
        out = f.getvalue()
        data = json.loads(out)
        self.assertIn("state", data)
        self.assertIn(data["state"], ["CLOSED", "OPEN", "HALF_OPEN"])


if __name__ == "__main__":
    unittest.main()
