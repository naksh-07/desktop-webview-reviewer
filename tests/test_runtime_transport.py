"""
Unit tests for runtime/transport.py and out-of-process .NET sidecar.
Validates JSON-RPC 2.0 request/response correlation, timeout handling,
malformed message rejection, clean disconnection, and out-of-process sidecar execution.
"""

import asyncio
import os
import subprocess
import sys
import unittest

from runtime.transport import (
    MockTransport,
    NamedPipeTransport,
    PROTOCOL_VERSION,
)
from runtime.errors import (
    TransportErrorException,
    TransportTimeoutException,
    ProtocolErrorException,
)


class TestRuntimeTransport(unittest.IsolatedAsyncioTestCase):
    """Test suite for IPC transport abstraction and protocol envelopes."""

    async def asyncSetUp(self):
        self.transport = MockTransport()
        await self.transport.connect()

    async def asyncTearDown(self):
        if self.transport.is_connected:
            await self.transport.disconnect()

    async def test_request_response_correlation(self):
        """Verifies JSON-RPC 2.0 request envelope and correlated response delivery."""
        res = await self.transport.send_request("handshake", {"client": "python_daemon"})
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("protocol_version"), PROTOCOL_VERSION)
        self.assertEqual(res.get("status"), "READY")
        self.assertEqual(res.get("apartment_state"), "MTA")

        # Verify sent envelope
        self.assertEqual(len(self.transport.sent_requests), 1)
        req = self.transport.sent_requests[0]
        self.assertEqual(req["jsonrpc"], "2.0")
        self.assertEqual(req["method"], "handshake")
        self.assertIsNotNone(req["id"])

    async def test_ping_and_health_endpoints(self):
        """Verifies ping and health check responses."""
        ping_res = await self.transport.send_request("ping")
        self.assertEqual(ping_res, {"pong": True})

        health_res = await self.transport.send_request("health")
        self.assertEqual(health_res.get("status"), "HEALTHY")
        self.assertIn("memory_mb", health_res)

    async def test_timeout_handling(self):
        """Verifies slow requests trigger TransportTimeoutException."""
        with self.assertRaises(TransportTimeoutException):
            await self.transport.send_request("simulate_timeout", timeout=0.1)

    async def test_malformed_response_handling(self):
        """Verifies malformed responses raise ProtocolErrorException."""
        with self.assertRaises(ProtocolErrorException):
            await self.transport.send_request("simulate_malformed")

    async def test_unregistered_method_handling(self):
        """Verifies unknown methods raise TransportErrorException."""
        with self.assertRaises(TransportErrorException):
            await self.transport.send_request("nonexistent_method_xyz")

    async def test_disconnection_and_reconnection(self):
        """Verifies disconnect marks transport inactive and subsequent requests fail."""
        await self.transport.disconnect()
        self.assertFalse(self.transport.is_connected)

        with self.assertRaises(TransportErrorException):
            await self.transport.send_request("ping")

        # Reconnect
        await self.transport.connect()
        self.assertTrue(self.transport.is_connected)
        res = await self.transport.send_request("ping")
        self.assertEqual(res, {"pong": True})

    async def test_out_of_process_dotnet_sidecar_handshake(self):
        """
        Spawns DesktopBridge.UIA3.exe out-of-process via stdio and performs
        a live JSON-RPC 2.0 handshake to verify the compiled binary.
        """
        sidecar_exe = os.path.abspath(r"src\DesktopBridge.UIA3\DesktopBridge.UIA3.exe")
        if not os.path.exists(sidecar_exe):
            self.skipTest("DesktopBridge.UIA3.exe not compiled")

        # Run process via subprocess in stdio mode
        proc = subprocess.Popen(
            [sidecar_exe, "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            import json
            req = json.dumps({"jsonrpc": "2.0", "id": "test-1", "method": "handshake", "params": {}}) + "\n"
            proc.stdin.write(req)
            proc.stdin.flush()

            # Read response
            resp_line = proc.stdout.readline()
            self.assertTrue(len(resp_line) > 0, "No output received from sidecar")
            data = json.loads(resp_line)

            self.assertEqual(data.get("jsonrpc"), "2.0")
            self.assertEqual(data.get("id"), "test-1")
            result = data.get("result", {})
            self.assertEqual(result.get("protocol_version"), "1.0")
            self.assertEqual(result.get("sidecar_version"), "1.0.0")
            self.assertEqual(result.get("status"), "READY")
            self.assertEqual(result.get("apartment_state"), "MTA")

            # Send graceful shutdown
            shutdown_req = json.dumps({"jsonrpc": "2.0", "id": "test-2", "method": "shutdown", "params": {}}) + "\n"
            proc.stdin.write(shutdown_req)
            proc.stdin.flush()

            proc.wait(timeout=2.0)
            self.assertEqual(proc.returncode, 0)
        finally:
            try:
                proc.kill()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
