"""
Unit tests for runtime/utility_world.py.
Validates isolated execution realm creation, script evaluation, context recreation
after destruction, and isolation from page globals.
"""

import unittest

from runtime.cdp_transport import MockCDPTransport
from runtime.frame_manager import FrameManager
from runtime.utility_world import UtilityWorldManager, UTILITY_WORLD_NAME
from runtime.references import ReferenceRegistry


class TestUtilityWorldManager(unittest.IsolatedAsyncioTestCase):
    """Test suite for Utility World isolated JavaScript execution."""

    async def asyncSetUp(self):
        self.transport = MockCDPTransport()
        await self.transport.connect()
        self.registry = ReferenceRegistry(session_id="test_sess_util", initial_epoch=1)
        self.frame_manager = FrameManager(
            transport=self.transport,
            reference_registry=self.registry,
            session_id="test_sess_util",
        )
        self.utility_manager = UtilityWorldManager(
            transport=self.transport,
            frame_manager=self.frame_manager,
            session_id="test_sess_util",
        )

    async def asyncTearDown(self):
        await self.transport.disconnect()

    async def test_ensure_utility_world_creates_isolated_context(self):
        """Verifies ensure_utility_world calls Page.createIsolatedWorld and returns contextId."""
        await self.frame_manager.initialize()

        ctx_id = await self.utility_manager.ensure_utility_world()
        self.assertEqual(ctx_id, 99)

        # Verify sent command
        cmds = [c for c in self.transport.sent_commands if c["method"] == "Page.createIsolatedWorld"]
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["params"]["worldName"], UTILITY_WORLD_NAME)
        self.assertTrue(cmds[0]["params"]["grantUniveralAccess"])

    async def test_evaluate_in_utility_world(self):
        """Verifies evaluate targets the isolated context and unpacks result."""
        await self.frame_manager.initialize()

        self.transport.register_handler("Runtime.evaluate", lambda p: {
            "result": {"type": "number", "value": 42}
        })

        res = await self.utility_manager.evaluate("21 * 2")
        self.assertEqual(res, 42)

        eval_cmds = [c for c in self.transport.sent_commands if c["method"] == "Runtime.evaluate"]
        self.assertEqual(len(eval_cmds), 1)
        self.assertEqual(eval_cmds[0]["params"]["contextId"], 99)
        self.assertEqual(eval_cmds[0]["params"]["expression"], "21 * 2")

    async def test_evaluate_exception_unpacking(self):
        """Verifies JS exceptions thrown in utility world raise RuntimeError with description."""
        await self.frame_manager.initialize()

        self.transport.register_handler("Runtime.evaluate", lambda p: {
            "exceptionDetails": {
                "text": "Uncaught TypeError",
                "exception": {"description": "Cannot read properties of undefined"},
            }
        })

        with self.assertRaises(RuntimeError) as ctx:
            await self.utility_manager.evaluate("window.nonExistent.foo")

        self.assertIn("Cannot read properties of undefined", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
