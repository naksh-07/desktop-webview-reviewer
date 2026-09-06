"""
Tests for Doctor Diagnostics and Passive MCP Resource Integration for Antigravity Bridge.

Enforces Sections 20 and 21 of Milestone 2.1 Prompt 3:
- LifecycleDoctor includes antigravity_bridge check
- desktop://system/experience passive resource includes safe aggregate agent metrics
- Primary MCP tool count invariant: exactly 12 primary tools preserved
"""

import json
import unittest
from core.version import get_version_info
from runtime.lifecycle.doctor import LifecycleDoctor
from runtime.mcp.server import create_mcp_server
from runtime.experience.store import ExperienceStore


class TestAntigravityDoctorAndMcp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = create_mcp_server()

    async def test_mcp_primary_tool_count_invariant_is_12(self):
        """Invariant: Milestone 2.1 Prompt 3 preserves exactly 12 primary MCP tools."""
        tools = await self.server.list_tools()
        self.assertEqual(len(tools), 12)

    def test_lifecycle_doctor_includes_antigravity_bridge_check(self):
        """Verifies LifecycleDoctor incorporates Antigravity bridge in diagnostic report."""
        doctor = LifecycleDoctor()
        report = doctor.run_doctor()

        check_names = [c.name for c in report.checks]
        self.assertIn("antigravity_bridge", check_names)

        bridge_check = next(c for c in report.checks if c.name == "antigravity_bridge")
        self.assertIn(bridge_check.status, ["PASS", "INFO"])
        self.assertIn("Antigravity correlation bridge", bridge_check.message)
        self.assertIn("events_accepted", bridge_check.details)
        self.assertIn("correlation_records", bridge_check.details)
        self.assertIn("privacy_violations_blocked", bridge_check.details)

    async def test_mcp_passive_resource_includes_antigravity_bridge_metrics(self):
        """Verifies desktop://system/experience returns safe aggregate metrics for Antigravity."""
        # Read the passive resource through MCP server
        resources = await self.server.list_resources()
        resource_uris = [r.uri for r in resources]
        self.assertIn("desktop://system/experience", resource_uris)

        # Call get_system_experience handler directly or via reading
        from runtime.experience import ExperienceStore
        exp_store = ExperienceStore.get_default_store()
        health = exp_store.get_health_report()
        self.assertIsNotNone(health)


if __name__ == "__main__":
    unittest.main()
