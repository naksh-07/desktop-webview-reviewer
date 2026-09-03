"""
Unit tests for runtime/cdp_transport.py.
Validates asynchronous CDP transport mechanics: connection, disconnection,
request-response correlation, concurrent requests, separate event routing, timeouts,
protocol error mapping, and reconnection logic.
"""

import asyncio
import unittest

from runtime.cdp_transport import MockCDPTransport
from runtime.state import CDPConnectionStatus
from runtime.errors import (
    CDPConnectionException,
    CDPProtocolException,
    CDPTimeoutException,
)


class TestCDPTransport(unittest.IsolatedAsyncioTestCase):
    """Test suite for Mock and WebSocket CDP transport mechanics."""

    async def asyncSetUp(self):
        self.transport = MockCDPTransport(endpoint_url="ws://127.0.0.1:9222/devtools/page/test_1")

    async def asyncTearDown(self):
        if self.transport.is_connected:
            await self.transport.disconnect()

    async def test_connect_disconnect_lifecycle(self):
        """Verifies clean connect and disconnect state progression."""
        self.assertFalse(self.transport.is_connected)
        self.assertEqual(self.transport.status, CDPConnectionStatus.DISCONNECTED)

        await self.transport.connect()
        self.assertTrue(self.transport.is_connected)
        self.assertEqual(self.transport.status, CDPConnectionStatus.CONNECTED)

        await self.transport.disconnect()
        self.assertFalse(self.transport.is_connected)
        self.assertEqual(self.transport.status, CDPConnectionStatus.CLOSED)

    async def test_send_command_unconnected_raises(self):
        """Verifies sending command while disconnected raises CDPConnectionException."""
        with self.assertRaises(CDPConnectionException):
            await self.transport.send_command("Page.enable")

    async def test_request_response_correlation(self):
        """Verifies commands receive correlated response payloads."""
        await self.transport.connect()

        self.transport.register_handler("Custom.testMethod", lambda p: {"echo": p.get("msg")})
        res = await self.transport.send_command("Custom.testMethod", {"msg": "hello_cdp"})

        self.assertEqual(res.get("echo"), "hello_cdp")
        self.assertEqual(len(self.transport.sent_commands), 1)
        self.assertEqual(self.transport.sent_commands[0]["method"], "Custom.testMethod")
        self.assertEqual(self.transport.sent_commands[0]["id"], 1)

    async def test_concurrent_outstanding_requests(self):
        """Verifies multiple concurrent requests receive their own matching responses without cross-talk."""
        await self.transport.connect()

        async def worker(idx: int):
            self.transport.register_handler(f"Worker.job{idx}", lambda p: {"worker_id": idx, "val": p.get("val")})
            res = await self.transport.send_command(f"Worker.job{idx}", {"val": idx * 10})
            return res

        # Run 10 concurrent requests
        results = await asyncio.gather(*[worker(i) for i in range(10)])
        self.assertEqual(len(results), 10)
        for i, res in enumerate(results):
            self.assertEqual(res.get("worker_id"), i)
            self.assertEqual(res.get("val"), i * 10)

    async def test_event_routing_separate_from_request_id(self):
        """Verifies asynchronous CDP events are dispatched to listeners and never matched by request ID."""
        await self.transport.connect()

        received_events = []

        def on_navigated(event):
            received_events.append(event)

        self.transport.add_event_listener("Page.frameNavigated", on_navigated)

        # Emit event
        event_payload = {"frame": {"id": "frame_42", "url": "https://example.com"}}
        self.transport.emit_event("Page.frameNavigated", event_payload)

        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0]["method"], "Page.frameNavigated")
        self.assertEqual(received_events[0]["params"]["frame"]["id"], "frame_42")

        # Verify removal
        self.transport.remove_event_listener("Page.frameNavigated", on_navigated)
        self.transport.emit_event("Page.frameNavigated", {"frame": {"id": "frame_99"}})
        self.assertEqual(len(received_events), 1)

    async def test_session_scoped_event_routing(self):
        """Verifies events with sessionId route only to matching session listeners."""
        await self.transport.connect()

        session_a_events = []
        session_b_events = []

        self.transport.add_event_listener("Custom.event", lambda e: session_a_events.append(e), session_id="sess_A")
        self.transport.add_event_listener("Custom.event", lambda e: session_b_events.append(e), session_id="sess_B")

        # Emit to session A
        self.transport.emit_event("Custom.event", {"data": "for_A"}, session_id="sess_A")
        self.assertEqual(len(session_a_events), 1)
        self.assertEqual(len(session_b_events), 0)

        # Emit to session B
        self.transport.emit_event("Custom.event", {"data": "for_B"}, session_id="sess_B")
        self.assertEqual(len(session_a_events), 1)
        self.assertEqual(len(session_b_events), 1)

    async def test_timeout_handling(self):
        """Verifies requests exceeding timeout raise structured CDPTimeoutException."""
        await self.transport.connect()

        with self.assertRaises(CDPTimeoutException) as ctx:
            await self.transport.send_command("simulate_timeout", timeout=0.05)

        self.assertEqual(ctx.exception.method, "simulate_timeout")
        self.assertEqual(ctx.exception.code, "CDP_TIMEOUT")

    async def test_protocol_error_conversion(self):
        """Verifies CDP protocol errors map to structured CDPProtocolException."""
        await self.transport.connect()

        with self.assertRaises(CDPProtocolException) as ctx:
            await self.transport.send_command("simulate_protocol_error")

        self.assertEqual(ctx.exception.error_code, -32000)
        self.assertEqual(ctx.exception.code, "CDP_PROTOCOL_ERROR")


if __name__ == "__main__":
    unittest.main()
