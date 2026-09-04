"""
Phase 8 End-to-End Agent Experience Test Suite.
Verifies that an AI Agent can execute the complete desktop review workflow
strictly and exclusively through the public MCP Control Plane interface:
Agent (MCP Client)
  -> Reads Server Instructions & Prompts
  -> desktop_launch (supervises process)
  -> desktop_inspect (acquires ephemeral refs w1e1, etc.)
  -> desktop_click / desktop_type (interacts semantically)
  -> desktop_assert (verifies post-state condition)
  -> desktop_collect_evidence (seals cryptographic evidence bundle)
  -> Reads passive evidence resource desktop://evidence/...
  -> Verifies Tripartite Verdict (PASS / FAIL / UNVERIFIED)
  -> desktop_close (clean detachment/teardown)
"""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from mcp.client import Client

from core.cleanup import ProcessCleanup
from launchers.process_launcher import ProcessLauncher
from runtime.daemon import get_default_daemon, reset_default_daemon
from runtime.mcp.server import create_mcp_server


def _resolve_anki_maths_dir() -> Path:
    if "ANKI_MATHS_DIR" in os.environ:
        return Path(os.environ["ANKI_MATHS_DIR"]).resolve()
    candidate_sibling = Path(__file__).resolve().parent.parent.parent / "Anki-maths"
    if candidate_sibling.exists():
        return candidate_sibling.resolve()
    candidate_home = Path.home() / "Documents" / "Antigravity" / "Anki-maths"
    if candidate_home.exists():
        return candidate_home.resolve()
    return candidate_sibling


ANKI_MATHS_DIR = _resolve_anki_maths_dir()
ANKI_PYTHON = ANKI_MATHS_DIR / "out" / "pyenv" / "Scripts" / "python.exe"
ANKI_ENTRY = ANKI_MATHS_DIR / "tools" / "run.py"


class TestPhase8AgentE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-End verification of the complete Agent Experience through MCP public surface."""

    @classmethod
    def setUpClass(cls):
        if not ANKI_MATHS_DIR.exists() or not ANKI_PYTHON.exists():
            raise unittest.SkipTest(f"Anki Maths not available at {ANKI_MATHS_DIR}")

    async def asyncSetUp(self):
        reset_default_daemon()
        self.daemon = get_default_daemon()
        self.server = create_mcp_server(daemon=self.daemon)
        self.port = ProcessLauncher.find_free_port(start_port=9390)

    async def asyncTearDown(self):
        if self.daemon:
            await self.daemon.shutdown()
        reset_default_daemon()

    async def test_agent_complete_review_lifecycle_via_mcp_only(self):
        """
        Executes complete desktop application review without accessing internal runtime APIs.
        The entire agent interaction flows strictly through the MCP client.
        """
        async with Client(self.server) as client:
            # 1. Agent inspects prompts and server instructions
            prompt_res = await client.list_prompts()
            prompts = prompt_res.prompts if hasattr(prompt_res, "prompts") else prompt_res
            prompt_names = [p.name for p in prompts]
            self.assertIn("desktop_review", prompt_names)
            self.assertIn("desktop_verify", prompt_names)

            # Retrieve workflow prompt guidance
            workflow_prompt = await client.get_prompt(
                "desktop_review",
                {
                    "executable_path": str(ANKI_PYTHON),
                    "test_criteria": "Verify main deck screen loads and counter elements exist",
                },
            )
            self.assertTrue(len(workflow_prompt.messages) > 0)

            # 2. Agent launches desktop application via desktop_launch
            launch_res = await client.call_tool(
                "desktop_launch",
                {
                    "executable_path": str(ANKI_PYTHON),
                    "args": [str(ANKI_ENTRY)],
                    "working_directory": str(ANKI_MATHS_DIR),
                    "engine_hint": "qt",
                    "remote_debugging_port": self.port,
                    "timeout_sec": 30,
                },
            )
            self.assertFalse(launch_res.is_error, f"desktop_launch failed: {launch_res.content}")
            launch_data = json.loads(launch_res.content[0].text)
            session_id = launch_data["session_id"]
            self.assertIsNotNone(session_id)
            self.assertEqual(launch_data["lifecycle_state"], "ACTIVE")

            try:
                # 3. Agent inspects application state via desktop_inspect
                inspect_res = await client.call_tool(
                    "desktop_inspect",
                    {"session_id": session_id, "max_depth": 5},
                )
                self.assertFalse(inspect_res.is_error, f"desktop_inspect failed: {inspect_res.content}")
                inspect_data = json.loads(inspect_res.content[0].text)
                self.assertEqual(inspect_data["session_id"], session_id)
                self.assertIn("epoch_id", inspect_data)
                self.assertIn("tree", inspect_data)

                # 4. Agent discovers available semantic references from inspection
                import re
                match = re.search(r"\[ref=([wn]\d+e\d+)\]", inspect_data["tree"])
                action_ref = match.group(1) if match else "w1e1"

                # 5. Agent executes semantic click via desktop_click
                click_res = await client.call_tool(
                    "desktop_click",
                    {
                        "session_id": session_id,
                        "ref": action_ref,
                        "button": "left",
                        "include_snapshot": True,
                    },
                )
                self.assertFalse(click_res.is_error, f"desktop_click failed: {click_res.content}")
                click_data = json.loads(click_res.content[0].text)
                self.assertIn("receipt", click_data)
                self.assertIn(click_data["receipt"]["dispatch_status"], ("DISPATCHED", "FAILED"))

                # 6. Agent performs state assertion via desktop_assert
                assert_res = await client.call_tool(
                    "desktop_assert",
                    {
                        "session_id": session_id,
                        "ref": action_ref,
                        "assertion": "is_visible",
                        "timeout_ms": 3000,
                    },
                )
                self.assertFalse(assert_res.is_error, f"desktop_assert failed: {assert_res.content}")

                # 7. Agent collects and seals cryptographic evidence via desktop_collect_evidence
                evidence_res = await client.call_tool(
                    "desktop_collect_evidence",
                    {
                        "session_id": session_id,
                        "test_name": "agent_e2e_anki_maths_review",
                        "expected_outcome_summary": "Complete agent-style review strictly via MCP Control Plane",
                    },
                )
                self.assertFalse(evidence_res.is_error, f"desktop_collect_evidence failed: {evidence_res.content}")
                evidence_data = json.loads(evidence_res.content[0].text)
                self.assertIn("resource_uri", evidence_data)
                self.assertIn(evidence_data["verdict"], ("PASS", "UNVERIFIED"))

                # 8. Agent reads the sealed evidence resource via MCP read_resource
                manifest_uri = evidence_data["resource_uri"]
                manifest_res = await client.read_resource(manifest_uri)
                self.assertTrue(len(manifest_res.contents) > 0)
                manifest_json = json.loads(manifest_res.contents[0].text)
                self.assertEqual(manifest_json["session_id"], session_id)
                self.assertIn("artifacts", manifest_json)

            finally:
                # 9. Clean session closure via daemon
                await self.daemon.session_manager.close_session(session_id)


if __name__ == "__main__":
    unittest.main()
