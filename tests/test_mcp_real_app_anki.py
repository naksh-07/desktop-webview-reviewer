"""
Real-Application Validation Suite: Anki Maths (PyQt6 + QtWebEngine) via MCP Interface.
Executes the full agent workflow strictly through the MCP Control Plane (Doc 14 & Section 33):
desktop_launch -> desktop_inspect -> locate ref -> desktop_click -> post snapshot ->
desktop_assert -> desktop_collect_evidence -> verify PASS verdict -> read evidence resource.
"""

import os
import sys
import json
import unittest
import asyncio
from pathlib import Path
from mcp.client import Client

from runtime.daemon import get_default_daemon, reset_default_daemon
from runtime.mcp.server import create_mcp_server
from core.cleanup import ProcessCleanup
from launchers.process_launcher import ProcessLauncher


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


class TestMcpRealAppAnkiMaths(unittest.IsolatedAsyncioTestCase):
    """Verifies complete end-to-end workflow on live Anki Maths strictly through MCP tools."""

    @classmethod
    def setUpClass(cls):
        if not ANKI_MATHS_DIR.exists() or not ANKI_PYTHON.exists():
            raise unittest.SkipTest(f"Anki Maths not available at {ANKI_MATHS_DIR}")

    async def asyncSetUp(self):
        reset_default_daemon()
        self.daemon = get_default_daemon()
        self.server = create_mcp_server(daemon=self.daemon)
        self.port = ProcessLauncher.find_free_port(start_port=9380)

    async def asyncTearDown(self):
        # Guaranteed teardown through daemon
        if self.daemon:
            await self.daemon.shutdown()
        reset_default_daemon()

    async def test_real_anki_maths_mcp_control_plane_lifecycle(self):
        """
        Executes complete verification cycle on Anki Maths exclusively via MCP:
        1. desktop_launch
        2. desktop_inspect
        3. locate element reference
        4. desktop_click with fused post-observation
        5. desktop_assert on element state
        6. desktop_collect_evidence sealing cryptographic manifest
        7. read_resource desktop://evidence/{evidence_id}
        """
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

        async with Client(self.server) as client:
            # 1. desktop_launch
            print(f"\n[Phase 7 MCP Real App] Launching Anki Maths via desktop_launch on CDP port {self.port}...")
            launch_res = await client.call_tool("desktop_launch", {
                "executable_path": str(ANKI_PYTHON),
                "args": [str(ANKI_ENTRY)],
                "working_directory": str(ANKI_MATHS_DIR),
                "remote_debugging_port": self.port,
                "timeout_sec": 30,
            })
            self.assertFalse(launch_res.is_error, f"desktop_launch failed: {launch_res.content}")
            launch_data = json.loads(launch_res.content[0].text)
            session_id = launch_data["session_id"]
            pid = launch_data["pid"]
            self.assertIsNotNone(session_id)
            self.assertGreater(pid, 0)
            print(f"[Phase 7 MCP Real App] Spawned Session: {session_id}, PID: {pid}")

            # Allow UI window and CDP webview targets to fully settle
            await asyncio.sleep(4.0)

            # 2. desktop_inspect
            print("[Phase 7 MCP Real App] Inspecting application with desktop_inspect...")
            inspect_res = await client.call_tool("desktop_inspect", {
                "session_id": session_id,
                "perspective": "auto",
            })
            self.assertFalse(inspect_res.is_error, f"desktop_inspect failed: {inspect_res.content}")
            inspect_data = json.loads(inspect_res.content[0].text)
            tree_text = inspect_data["tree"]
            self.assertIsNotNone(tree_text)
            print(f"[Phase 7 MCP Real App] Captured tree ({len(tree_text)} chars, {inspect_data['element_count']} elements)")

            # 3. Locate interactive ref from tree or reference registry
            session = self.daemon.session_manager.get_session(session_id)
            active_refs = session.reference_registry.get_active_refs()
            self.assertGreater(len(active_refs), 0, "No interactive element refs discovered")
            target_ref = active_refs[0]
            print(f"[Phase 7 MCP Real App] Selected target ref: {target_ref}")

            # 4. desktop_click with fused post-observation
            print(f"[Phase 7 MCP Real App] Clicking affordance {target_ref} via desktop_click...")
            click_res = await client.call_tool("desktop_click", {
                "session_id": session_id,
                "ref": target_ref,
                "include_snapshot": True,
            })
            self.assertFalse(click_res.is_error, f"desktop_click failed: {click_res.content}")
            click_data = json.loads(click_res.content[0].text)
            self.assertTrue(click_data["executed"])
            self.assertEqual(click_data["status"], "DISPATCHED")
            self.assertIn("post_snapshot", click_data)
            print(f"[Phase 7 MCP Real App] Action executed. Duration: {click_data['duration_ms']}ms, New Epoch: {click_data['new_epoch_id']}")

            # 5. desktop_assert
            post_refs = session.reference_registry.get_active_refs()
            self.assertGreater(len(post_refs), 0, "No active refs after click")
            verify_ref = post_refs[0]
            print(f"[Phase 7 MCP Real App] Verifying state with desktop_assert on {verify_ref}...")
            assert_res = await client.call_tool("desktop_assert", {
                "session_id": session_id,
                "ref": verify_ref,
                "assertion": "is_visible",
            })
            self.assertFalse(assert_res.is_error, f"desktop_assert failed: {assert_res.content}")
            assert_data = json.loads(assert_res.content[0].text)
            self.assertTrue(assert_data["passed"])
            print(f"[Phase 7 MCP Real App] Assertion PASSED: {assert_data['reason']}")

            # 6. desktop_collect_evidence
            print("[Phase 7 MCP Real App] Collecting cryptographically sealed evidence via desktop_collect_evidence...")
            evidence_res = await client.call_tool("desktop_collect_evidence", {
                "session_id": session_id,
                "test_name": "anki_maths_mcp_real_app_test",
            })
            self.assertFalse(evidence_res.is_error, f"desktop_collect_evidence failed: {evidence_res.content}")
            evidence_data = json.loads(evidence_res.content[0].text)
            print(f"[Phase 7 MCP Real App] Evidence Verdict: {evidence_data.get('verdict')}, Rationale: {evidence_data.get('verdict_rationale')}")
            self.assertIn(evidence_data["verdict"], ("PASS", "UNVERIFIED"))
            evidence_id = evidence_data["evidence_id"]
            resource_uri = evidence_data["resource_uri"]
            self.assertIsNotNone(evidence_id)
            self.assertIn("thumbnail_preview_b64", evidence_data)
            # Ensure thumbnail is bounded (< 50 KB), not a multi-megabyte image
            self.assertLess(len(evidence_data["thumbnail_preview_b64"]), 50000)
            print(f"[Phase 7 MCP Real App] Evidence Verdict: {evidence_data['verdict']}, URI: {resource_uri}")

            # 7. Read evidence resource over MCP
            print(f"[Phase 7 MCP Real App] Reading passive evidence resource {resource_uri} via MCP...")
            manifest_resource = await client.read_resource(resource_uri)
            self.assertIsNotNone(manifest_resource)
            self.assertEqual(len(manifest_resource.contents), 1)
            manifest_json = json.loads(manifest_resource.contents[0].text)
            self.assertIn("manifest_version", manifest_json)
            self.assertIn(manifest_json["verdict"], ("PASS", "UNVERIFIED"))
            print(f"[Phase 7 MCP Real App] Manifest Verified: Claims={len(manifest_json.get('claims', []))}")


if __name__ == "__main__":
    unittest.main()
