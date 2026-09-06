"""
Local Development Transport for Reviewer Test Harness (Architecture H).
Provides a lightweight, loopback-only (127.0.0.1) async HTTP transport server
for bi-directional diagnostic and control telemetry between the Application Harness
and the Reviewer Runtime.
"""

from __future__ import annotations
import asyncio
import json
import logging
import secrets
import urllib.parse
from typing import Callable, Dict, Optional, Any, Tuple, Awaitable

from runtime.harness.protocol import (
    HarnessMessage,
    HarnessMessageType,
    HarnessProtocolError,
    HarnessSecurityError,
    HarnessMessageValidator,
    MAX_HARNESS_MESSAGE_BYTES,
)

logger = logging.getLogger("desktop_webview.harness.transport")


class HarnessTransportServer:
    """
    Loopback-only HTTP server handling in-process harness communication.
    Guarantees isolation to 127.0.0.1 with session-scoped cryptographic auth tokens.
    """

    def __init__(
        self,
        session_id: str,
        host: str = "127.0.0.1",
        port: int = 0,
        auth_token: Optional[str] = None,
        on_message: Optional[Callable[[HarnessMessage], Awaitable[Dict[str, Any]]]] = None,
    ):
        if host not in ("127.0.0.1", "localhost"):
            raise ValueError("SECURITY VIOLATION: Harness transport must be strictly confined to loopback (127.0.0.1).")

        self.session_id = session_id
        self.host = "127.0.0.1"
        self.requested_port = port
        self.port: Optional[int] = None
        self.auth_token = auth_token or secrets.token_hex(16)
        self.on_message = on_message
        self.validator = HarnessMessageValidator(
            expected_session_id=self.session_id,
            expected_auth_token=self.auth_token,
        )
        self._server: Optional[asyncio.Server] = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running and self._server is not None

    @property
    def endpoint_url(self) -> str:
        if not self.port:
            raise RuntimeError("Transport server is not running or port not assigned.")
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> Tuple[str, int]:
        """Starts the loopback TCP server and discovers the bound port."""
        if self._is_running:
            return (self.host, self.port or 0)

        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.requested_port,
        )
        # Extract assigned port
        sockets = self._server.sockets
        if sockets:
            self.port = sockets[0].getsockname()[1]
        else:
            self.port = self.requested_port

        self._is_running = True
        logger.info(f"Reviewer Harness Transport active on {self.endpoint_url} (session: {self.session_id})")
        assert self.port is not None
        return (self.host, self.port)

    async def stop(self) -> None:
        """Shuts down the transport server cleanly."""
        if not self._is_running or not self._server:
            return
        self._is_running = False
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        logger.info("Reviewer Harness Transport stopped cleanly.")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Processes an incoming HTTP connection from local application harness."""
        peername = writer.get_extra_info("peername")
        client_ip = peername[0] if peername else ""

        # Enforce loopback check
        if client_ip not in ("127.0.0.1", "::1"):
            logger.warning(f"Rejected non-loopback connection from {client_ip}")
            writer.close()
            await writer.wait_closed()
            return

        try:
            # Read HTTP request line
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            line_str = request_line.decode("utf-8", errors="replace").strip()
            parts = line_str.split(" ")
            if len(parts) < 2:
                await self._send_response(writer, 400, {"error": "Invalid HTTP request line."})
                return

            method, path = parts[0], parts[1]

            # Read HTTP headers
            headers: Dict[str, str] = {}
            content_length = 0
            while True:
                header_line = await reader.readline()
                if not header_line or header_line == b"\r\n":
                    break
                h_str = header_line.decode("utf-8", errors="replace").strip()
                if ":" in h_str:
                    k, v = h_str.split(":", 1)
                    k_clean = k.strip().lower()
                    v_clean = v.strip()
                    headers[k_clean] = v_clean
                    if k_clean == "content-length":
                        try:
                            content_length = int(v_clean)
                        except ValueError:
                            content_length = 0

            # Guard against oversized bodies
            if content_length > MAX_HARNESS_MESSAGE_BYTES:
                await self._send_response(writer, 413, {
                    "error": f"Payload Too Large: exceeds {MAX_HARNESS_MESSAGE_BYTES} bytes."
                })
                return

            # Read body if present
            body_bytes = b""
            if content_length > 0:
                body_bytes = await reader.readexactly(content_length)

            # Route requests
            await self._route_request(method, path, headers, body_bytes, writer)

        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            logger.error(f"Error handling harness request: {e}")
            try:
                await self._send_response(writer, 500, {"error": str(e)})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _route_request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        body_bytes: bytes,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Dispatches request to appropriate endpoint."""
        clean_path = urllib.parse.urlparse(path).path

        # Health endpoint (public loopback probe)
        if clean_path in ("/harness/v1/health", "/health") and method == "GET":
            await self._send_response(writer, 200, {
                "status": "HEALTHY",
                "session_id": self.session_id,
                "running": self._is_running,
            })
            return

        # All other endpoints require POST and message parsing
        if method != "POST":
            await self._send_response(writer, 405, {"error": "Method Not Allowed"})
            return

        # Check authorization token from header or body
        token_header = headers.get("x-reviewer-harness-token") or headers.get("authorization", "").replace("Bearer ", "")

        try:
            body_text = body_bytes.decode("utf-8")
            raw_msg = HarnessMessage.from_json(body_text)

            # Fallback token from message body if header not supplied
            effective_token = token_header or raw_msg.auth_token
            msg_with_token = HarnessMessage(
                session_id=raw_msg.session_id,
                application_id=raw_msg.application_id,
                harness_instance_id=raw_msg.harness_instance_id,
                message_type=raw_msg.message_type,
                payload=raw_msg.payload,
                timestamp=raw_msg.timestamp,
                correlation_id=raw_msg.correlation_id,
                sequence=raw_msg.sequence,
                auth_token=effective_token,
            )

            # Validate message
            self.validator.validate(msg_with_token)

            # Delegate to handler
            if self.on_message:
                res_payload = await self.on_message(msg_with_token)
                await self._send_response(writer, 200, res_payload)
            else:
                await self._send_response(writer, 200, {"status": "RECEIVED", "correlation_id": raw_msg.correlation_id})

        except HarnessProtocolError as e:
            await self._send_response(writer, 400, {"error": "PROTOCOL_ERROR", "message": str(e)})
        except HarnessSecurityError as e:
            await self._send_response(writer, 403, {"error": "SECURITY_ERROR", "message": str(e)})
        except Exception as e:
            await self._send_response(writer, 500, {"error": "INTERNAL_ERROR", "message": str(e)})

    async def _send_response(self, writer: asyncio.StreamWriter, status_code: int, data: Dict[str, Any]) -> None:
        """Writes standard HTTP/1.1 JSON response."""
        body = json.dumps(data).encode("utf-8")
        status_text = {
            200: "OK",
            400: "Bad Request",
            403: "Forbidden",
            405: "Method Not Allowed",
            413: "Payload Too Large",
            500: "Internal Server Error",
        }.get(status_code, "OK")

        header_lines = [
            f"HTTP/1.1 {status_code} {status_text}",
            "Content-Type: application/json; charset=utf-8",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "",
            "",
        ]
        header_bytes = "\r\n".join(header_lines).encode("ascii")
        writer.write(header_bytes + body)
        await writer.drain()


class HarnessClient:
    """
    Lightweight client used by application fixtures or adapters
    to communicate with the local Reviewer Harness transport.
    """

    def __init__(self, endpoint_url: str, session_id: str, application_id: str, auth_token: str):
        self.endpoint_url = endpoint_url.rstrip("/")
        self.session_id = session_id
        self.application_id = application_id
        self.auth_token = auth_token
        self.harness_instance_id = f"inst_{secrets.token_hex(6)}"
        self._sequence = 0

    async def send_message(self, message_type: HarnessMessageType | str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a validated HarnessMessage over local HTTP transport."""
        import urllib.request
        self._sequence += 1
        mtype = HarnessMessageType(message_type) if not isinstance(message_type, HarnessMessageType) else message_type
        msg = HarnessMessage(
            session_id=self.session_id,
            application_id=self.application_id,
            harness_instance_id=self.harness_instance_id,
            message_type=mtype,
            payload=payload,
            sequence=self._sequence,
            auth_token=self.auth_token,
        )
        url = f"{self.endpoint_url}/harness/v1/{mtype.value.lower()}"
        data = msg.to_json().encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "X-Reviewer-Harness-Token": self.auth_token,
        }

        loop = asyncio.get_event_loop()

        def _sync_post():
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                resp_bytes = resp.read()
                return json.loads(resp_bytes.decode("utf-8"))

        return await loop.run_in_executor(None, _sync_post)

    async def emit_lifecycle(self, signal: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.send_message(
            HarnessMessageType.LIFECYCLE,
            {"signal": signal, "details": details or {}},
        )

    async def emit_diagnostics(self, diagnostics: Dict[str, Any]) -> Dict[str, Any]:
        return await self.send_message(
            HarnessMessageType.DIAGNOSTICS,
            {"diagnostics": diagnostics},
        )
