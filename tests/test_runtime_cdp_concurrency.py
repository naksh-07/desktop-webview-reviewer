"""
Unit tests for multi-target concurrency (runtime/webview_core.py & runtime/cdp_target.py).
Validates that at least two simultaneous webview targets operate concurrently with zero cross-talk,
independent request IDs, and isolated event delivery.
"""

import asyncio
import unittest

from runtime.cdp_transport import MockCDPTransport
from runtime.references import ReferenceRegistry
from runtime.webview_core import WebviewAutomationCore


class TestCDPMultiTargetConcurrency(unittest.IsolatedAsyncioTestCase):
    """Test suite ensuring zero cross-talk between multiple active webview targets."""

    async def asyncSetUp(self):
        # Target 1
        self.transport_1 = MockCDPTransport(endpoint_url="ws://127.0.0.1:9222/devtools/page/target_1")
        self.registry_1 = ReferenceRegistry(session_id="session_alpha", initial_epoch=1)
        self.core_1 = WebviewAutomationCore(
            session_id="session_alpha",
            transport=self.transport_1,
            reference_registry=self.registry_1,
            native_pid=1001,
            native_hwnd=2001,
        )

        # Target 2
        self.transport_2 = MockCDPTransport(endpoint_url="ws://127.0.0.1:9222/devtools/page/target_2")
        self.registry_2 = ReferenceRegistry(session_id="session_beta", initial_epoch=1)
        self.core_2 = WebviewAutomationCore(
            session_id="session_beta",
            transport=self.transport_2,
            reference_registry=self.registry_2,
            native_pid=1002,
            native_hwnd=2002,
        )

        await self.core_1.connect()
        await self.core_2.connect()

    async def asyncTearDown(self):
        await self.core_1.disconnect()
        await self.core_2.disconnect()

    async def test_simultaneous_independent_evaluations(self):
        """Verifies concurrent script evaluations on Target 1 and Target 2 return distinct results."""
        self.transport_1.register_handler("Runtime.evaluate", lambda p: {
            "result": {"value": f"result_target_1: {p.get('expression')}"}
        })
        self.transport_2.register_handler("Runtime.evaluate", lambda p: {
            "result": {"value": f"result_target_2: {p.get('expression')}"}
        })

        async def eval_target_1():
            return await self.core_1.evaluate_script("document.title")

        async def eval_target_2():
            return await self.core_2.evaluate_script("location.href")

        res_1, res_2 = await asyncio.gather(eval_target_1(), eval_target_2())

        self.assertEqual(res_1, "result_target_1: document.title")
        self.assertEqual(res_2, "result_target_2: location.href")

    async def test_isolated_event_delivery(self):
        """Verifies events emitted to Target 1 are never received by Target 2."""
        # Emit console event on Target 1
        self.transport_1.emit_event("Runtime.consoleAPICalled", {
            "type": "info",
            "args": [{"value": "Message from Target 1"}],
            "timestamp": 1234567.89,
        })

        # Target 1 should capture it
        self.assertEqual(len(self.core_1.console_events), 1)
        self.assertIn("Message from Target 1", self.core_1.console_events[0]["text"])

        # Target 2 should have 0 console events
        self.assertEqual(len(self.core_2.console_events), 0)

    async def test_isolated_navigation_and_epoch_invalidation(self):
        """Verifies navigation on Target 1 increments its epoch without touching Target 2."""
        self.assertEqual(self.core_1.current_epoch, 1)
        self.assertEqual(self.core_2.current_epoch, 1)

        # Emit top-level navigation on Target 1
        self.transport_1.emit_event("Page.frameNavigated", {
            "frame": {
                "id": "root_frame_default",
                "loaderId": "loader_new",
                "url": "https://alpha.example.com/navigated",
            }
        })

        self.assertEqual(self.core_1.current_epoch, 2)
        self.assertEqual(self.core_2.current_epoch, 1)  # Untouched!


if __name__ == "__main__":
    unittest.main()
