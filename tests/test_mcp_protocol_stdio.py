"""
Protocol integration tests for MCP Control Plane over stdio transport.
Verifies end-to-end client-server protocol interaction: initialization, tool listing,
tool calls, error handling, resource reads, prompt rendering, and shutdown.
"""

import sys
import unittest
import json
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from runtime.session_manager import SessionState
from runtime.daemon import get_default_daemon, reset_default_daemon


class TestMcpProtocolStdio(unittest.IsolatedAsyncioTestCase):
    """Verifies stdio protocol exchange with MCP Server using the official MCP client."""

    async def asyncSetUp(self):
        self.params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "runtime.mcp"],
            env=None,
        )

    async def asyncTearDown(self):
        reset_default_daemon()

    async def test_stdio_initialize_and_tool_discovery(self):
        """Validates initialize handshake, server info, and 12-tool surface over stdio."""
        async with stdio_client(self.params) as (read, write):
            async with ClientSession(read, write) as session:
                init_res = await session.initialize()
                self.assertEqual(init_res.server_info.name, "desktop-webview-reviewer")
                self.assertEqual(init_res.server_info.version, "1.0.0")

                tools_res = await session.list_tools()
                tool_names = [t.name for t in tools_res.tools]
                self.assertEqual(len(tool_names), 12)
                expected_tools = [
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
                for exp in expected_tools:
                    self.assertIn(exp, tool_names)

    async def test_stdio_resource_discovery_and_read(self):
        """Validates reading passive MCP resources over stdio."""
        async with stdio_client(self.params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # List resources
                resources_res = await session.list_resources()
                uris = [str(r.uri) for r in resources_res.resources]
                self.assertTrue(any("desktop://sessions" in u for u in uris))
                self.assertTrue(any("desktop://windows" in u for u in uris))

                # Read desktop://sessions
                res = await session.read_resource("desktop://sessions")
                self.assertEqual(len(res.contents), 1)
                content_text = res.contents[0].text
                sessions_data = json.loads(content_text)
                self.assertIsInstance(sessions_data, list)

                # Read desktop://windows
                win_res = await session.read_resource("desktop://windows")
                self.assertEqual(len(win_res.contents), 1)
                win_data = json.loads(win_res.contents[0].text)
                self.assertIsInstance(win_data, list)
                self.assertGreater(len(win_data), 0)

    async def test_stdio_prompts_retrieval(self):
        """Validates MCP prompt template rendering over stdio."""
        async with stdio_client(self.params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                prompts_res = await session.list_prompts()
                prompt_names = [p.name for p in prompts_res.prompts]
                self.assertIn("desktop_review", prompt_names)
                self.assertIn("desktop_debug", prompt_names)
                self.assertIn("desktop_verify", prompt_names)

                # Render desktop_debug
                rendered = await session.get_prompt(
                    "desktop_debug",
                    {"session_id": "test-session-123", "description": "Element not clicking"},
                )
                self.assertGreater(len(rendered.messages), 0)
                msg_text = rendered.messages[0].content.text
                self.assertIn("test-session-123", msg_text)
                self.assertIn("Element not clicking", msg_text)

    async def test_stdio_error_mapping_enveloping(self):
        """Validates machine-readable error envelope returned on tool failure."""
        async with stdio_client(self.params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call inspect on invalid session
                result = await session.call_tool("desktop_inspect", {"session_id": "nonexistent_sess_999"})
                self.assertTrue(result.is_error)
                self.assertGreater(len(result.content), 0)
                err_text = result.content[0].text

                # Parse JSON payload from error
                self.assertIn("INVALID_SESSION", err_text)
                self.assertIn("agent_action_hint", err_text)
                # Verify no raw tracebacks leaked
                self.assertNotIn("Traceback (most recent call last)", err_text)


if __name__ == "__main__":
    unittest.main()
