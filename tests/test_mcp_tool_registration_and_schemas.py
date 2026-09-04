"""
Test Suite: MCP Tool Registration & Schema Contracts (Phase 7).
Validates that exactly 12 cohesive tools, passive resources, and prompts
are registered with rigorous input/output schemas matching Document 14.
"""

import asyncio
import unittest
from typing import Dict, Any

from runtime.mcp.server import create_mcp_server
from runtime.daemon import DesktopDaemon


class TestMcpToolRegistrationAndSchemas(unittest.IsolatedAsyncioTestCase):
    """Verifies tool registration, schema structure, and resource/prompt models."""

    async def asyncSetUp(self):
        self.daemon = DesktopDaemon()
        self.server = create_mcp_server(daemon=self.daemon)

    async def test_tool_count_and_names(self):
        """Invariant D: Exactly 12 primary tools exist unless explicitly justified."""
        tools = await self.server.list_tools()
        tool_names = [t.name for t in tools]

        expected_12_tools = [
            "desktop_launch",
            "desktop_attach",
            "desktop_inspect",
            "desktop_click",
            "desktop_type",
            "desktop_press_key",
            "desktop_hover",
            "desktop_scroll",
            "desktop_handle_dialog",
            "desktop_evaluate",
            "desktop_assert",
            "desktop_collect_evidence",
        ]

        self.assertEqual(len(tools), 12, f"Expected exactly 12 tools, got {len(tools)}: {tool_names}")
        for expected in expected_12_tools:
            self.assertIn(expected, tool_names, f"Missing required tool: {expected}")

    def _get_schema(self, tool) -> Dict[str, Any]:
        return getattr(tool, "input_schema", getattr(tool, "inputSchema", {}))

    async def test_desktop_launch_schema(self):
        """Validates desktop_launch input schema parameters and requirements."""
        tools = {t.name: t for t in await self.server.list_tools()}
        tool = tools["desktop_launch"]
        schema = self._get_schema(tool)

        self.assertEqual(schema.get("type"), "object")
        props = schema.get("properties", {})
        self.assertIn("executable_path", props)
        self.assertIn("args", props)
        self.assertIn("working_directory", props)
        self.assertIn("engine_hint", props)
        self.assertIn("remote_debugging_port", props)
        self.assertIn("timeout_sec", props)

        required = schema.get("required", [])
        self.assertIn("executable_path", required)

    async def test_desktop_attach_schema(self):
        """Validates desktop_attach schema."""
        tools = {t.name: t for t in await self.server.list_tools()}
        tool = tools["desktop_attach"]
        schema = self._get_schema(tool)
        props = schema.get("properties", {})

        self.assertIn("hwnd", props)
        self.assertIn("pid", props)
        self.assertIn("window_title_pattern", props)
        self.assertIn("cdp_port", props)
        self.assertIn("timeout_sec", props)

    async def test_desktop_inspect_schema(self):
        """Validates desktop_inspect schema requiring session_id."""
        tools = {t.name: t for t in await self.server.list_tools()}
        tool = tools["desktop_inspect"]
        schema = self._get_schema(tool)
        props = schema.get("properties", {})

        self.assertIn("session_id", props)
        self.assertIn("perspective", props)
        self.assertIn("diff_only", props)
        self.assertIn("max_depth", props)

        required = schema.get("required", [])
        self.assertIn("session_id", required)

    async def test_action_tool_schemas(self):
        """Validates action tool schemas (click, type, key, hover, scroll)."""
        tools = {t.name: t for t in await self.server.list_tools()}

        # desktop_click
        click_schema = self._get_schema(tools["desktop_click"])
        click_props = click_schema.get("properties", {})
        self.assertIn("session_id", click_props)
        self.assertIn("ref", click_props)
        self.assertIn("include_snapshot", click_props)
        self.assertIn("session_id", click_schema.get("required", []))
        self.assertIn("ref", click_schema.get("required", []))

        # desktop_type
        type_schema = self._get_schema(tools["desktop_type"])
        type_props = type_schema.get("properties", {})
        self.assertIn("session_id", type_props)
        self.assertIn("ref", type_props)
        self.assertIn("text", type_props)
        self.assertIn("clear_existing", type_props)
        self.assertIn("press_enter", type_props)

        # desktop_press_key
        key_schema = self._get_schema(tools["desktop_press_key"])
        key_props = key_schema.get("properties", {})
        self.assertIn("session_id", key_props)
        self.assertIn("key", key_props)

        # desktop_hover
        hover_schema = self._get_schema(tools["desktop_hover"])
        hover_props = hover_schema.get("properties", {})
        self.assertIn("session_id", hover_props)
        self.assertIn("ref", hover_props)

        # desktop_scroll
        scroll_schema = self._get_schema(tools["desktop_scroll"])
        scroll_props = scroll_schema.get("properties", {})
        self.assertIn("session_id", scroll_props)
        self.assertIn("direction", scroll_props)
        self.assertIn("delta_y", scroll_props)

    async def test_dialog_eval_assert_evidence_schemas(self):
        """Validates dialog, evaluate, assert, and evidence collection schemas."""
        tools = {t.name: t for t in await self.server.list_tools()}

        # desktop_handle_dialog
        dialog_schema = self._get_schema(tools["desktop_handle_dialog"])
        dialog_props = dialog_schema.get("properties", {})
        self.assertIn("session_id", dialog_props)
        self.assertIn("action", dialog_props)

        # desktop_evaluate
        eval_schema = self._get_schema(tools["desktop_evaluate"])
        eval_props = eval_schema.get("properties", {})
        self.assertIn("session_id", eval_props)
        self.assertIn("expression", eval_props)
        self.assertIn("in_main_world", eval_props)

        # desktop_assert
        assert_schema = self._get_schema(tools["desktop_assert"])
        assert_props = assert_schema.get("properties", {})
        self.assertIn("session_id", assert_props)
        self.assertIn("ref", assert_props)
        self.assertIn("assertion", assert_props)

        # desktop_collect_evidence
        ev_schema = self._get_schema(tools["desktop_collect_evidence"])
        ev_props = ev_schema.get("properties", {})
        self.assertIn("session_id", ev_props)
        self.assertIn("test_name", ev_props)

    async def test_resource_registration(self):
        """Validates MCP resource endpoints."""
        resources = await self.server.list_resources()
        res_uris = [str(r.uri) for r in resources]

        self.assertTrue(any("desktop://sessions" in u for u in res_uris))
        self.assertTrue(any("desktop://windows" in u for u in res_uris))

        # Check resource templates if exposed
        templates = await self.server.list_resource_templates()
        template_uris = [str(t.uri_template) for t in templates]
        self.assertTrue(any("desktop://sessions/{session_id}" in t for t in template_uris))
        self.assertTrue(any("desktop://evidence/{evidence_id}" in t for t in template_uris))

    async def test_prompt_registration(self):
        """Validates MCP prompt templates."""
        prompts = await self.server.list_prompts()
        prompt_names = [p.name for p in prompts]

        self.assertIn("desktop_review", prompt_names)
        self.assertIn("desktop_debug", prompt_names)
        self.assertIn("desktop_verify", prompt_names)


if __name__ == "__main__":
    unittest.main()
