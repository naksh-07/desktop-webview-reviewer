"""
Internal Transport Foundation for Desktop WebView Reviewer.
Implements JSON-RPC 2.0 protocol envelopes, request-response correlation,
timeout management, and Named Pipe IPC for the .NET UIA3 sidecar worker.
"""

from __future__ import annotations
import asyncio
import json
import logging
import sys
import uuid
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable

from runtime.errors import (
    TransportErrorException,
    TransportTimeoutException,
    ProtocolErrorException,
)

logger = logging.getLogger("desktop_webview.transport")

PROTOCOL_VERSION = "1.0"


class ITransport(ABC):
    """Abstract interface for sidecar IPC communication."""

    @abstractmethod
    async def connect(self, timeout: float = 5.0) -> None:
        """Establishes connection to the worker."""
        ...

    @abstractmethod
    async def send_request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> Any:
        """Sends a JSON-RPC 2.0 request and awaits the correlated response."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanly disconnects the transport."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Returns True if the transport connection is live."""
        ...


class MockTransport(ITransport):
    """
    In-memory mock transport for deterministic testing of sidecar protocol mechanics
    without requiring external binaries.
    """

    def __init__(self):
        self._connected = False
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
        self._sent_requests: list[Dict[str, Any]] = []
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        self._handlers["handshake"] = lambda params: {
            "protocol_version": PROTOCOL_VERSION,
            "sidecar_version": "1.0.0",
            "status": "READY",
            "apartment_state": "MTA",
        }
        self._handlers["ping"] = lambda params: {"pong": True}
        self._handlers["health"] = lambda params: {"status": "HEALTHY", "memory_mb": 24.5}
        self._handlers["shutdown"] = lambda params: {"acknowledged": True}

    def register_handler(self, method: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Registers a custom handler for testing specific sidecar methods."""
        self._handlers[method] = handler

    async def connect(self, timeout: float = 5.0) -> None:
        self._connected = True

    async def send_request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> Any:
        if not self._connected:
            raise TransportErrorException("Transport is not connected", endpoint="mock")

        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        self._sent_requests.append(payload)

        # Simulate timeout if requested
        if method == "simulate_timeout":
            await asyncio.sleep(timeout + 0.1)
            raise TransportTimeoutException(f"Request {method} timed out after {timeout}s", timeout_sec=timeout)

        # Simulate malformed response if requested
        if method == "simulate_malformed":
            raise ProtocolErrorException("Malformed JSON-RPC payload received from worker", raw_payload="INVALID")

        if method not in self._handlers:
            raise TransportErrorException(f"Method '{method}' not handled by mock", endpoint="mock")

        handler = self._handlers[method]
        result = handler(params or {})
        return result

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def sent_requests(self) -> list[Dict[str, Any]]:
        return self._sent_requests


class NamedPipeTransport(ITransport):
    """
    Asynchronous Windows Named Pipe transport for communication with DesktopBridge.UIA3.exe.
    """

    def __init__(self, pipe_name: str):
        self.pipe_name = pipe_name
        self.pipe_path = f"\\\\.\\pipe\\{pipe_name}" if not pipe_name.startswith("\\\\.\\pipe\\") else pipe_name
        self._connected = False
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._listen_task: Optional[asyncio.Task] = None

    async def connect(self, timeout: float = 5.0) -> None:
        if sys.platform != "win32":
            # On non-Windows, mark as mock-connected for development safety
            self._connected = True
            return

        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                # Open pipe connection via asyncio
                # In Windows asyncio, named pipes can be connected via open_connection or proactor
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(path=self.pipe_path),
                    timeout=1.0,
                )
                self._connected = True
                self._listen_task = asyncio.create_task(self._read_loop())
                logger.info(f"Connected to Named Pipe: {self.pipe_path}")
                return
            except (FileNotFoundError, OSError, asyncio.TimeoutError):
                await asyncio.sleep(0.1)

        raise TransportTimeoutException(
            f"Timed out connecting to Named Pipe {self.pipe_path} after {timeout}s",
            timeout_sec=timeout,
            endpoint=self.pipe_path,
        )

    async def _read_loop(self) -> None:
        """Reads incoming newline-delimited JSON-RPC messages from pipe."""
        if not self._reader:
            return
        try:
            while self._connected:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.decode("utf-8"))
                    req_id = data.get("id")
                    if req_id and req_id in self._pending_requests:
                        future = self._pending_requests.pop(req_id)
                        if not future.done():
                            if "error" in data and data["error"]:
                                err = data["error"]
                                future.set_exception(
                                    TransportErrorException(
                                        err.get("message", "Unknown RPC error"),
                                        endpoint=self.pipe_path,
                                        details=err,
                                    )
                                )
                            else:
                                future.set_result(data.get("result"))
                except json.JSONDecodeError as e:
                    logger.error(f"Malformed JSON from pipe: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in named pipe read loop: {e}")
        finally:
            self._connected = False

    async def send_request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> Any:
        if not self._connected:
            raise TransportErrorException("Named pipe is not connected", endpoint=self.pipe_path)

        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        raw_msg = json.dumps(payload) + "\n"

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests[req_id] = future

        try:
            if self._writer:
                self._writer.write(raw_msg.encode("utf-8"))
                await self._writer.drain()
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise TransportTimeoutException(
                f"Request '{method}' (id: {req_id}) timed out after {timeout}s",
                timeout_sec=timeout,
                endpoint=self.pipe_path,
            )
        except Exception as e:
            self._pending_requests.pop(req_id, None)
            raise TransportErrorException(f"Failed to send request '{method}': {e}", endpoint=self.pipe_path)

    async def disconnect(self) -> None:
        self._connected = False
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    @property
    def is_connected(self) -> bool:
        return self._connected
