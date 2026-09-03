"""
Asynchronous Chrome DevTools Protocol (CDP) Transport Layer.
Provides high-performance, concurrent WebSocket communication with request-response
correlation, isolated event dispatching, structured exception translation, and reconnect recovery.
"""

from __future__ import annotations
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    import websockets
    import websockets.exceptions
except ImportError:
    websockets = None

from runtime.state import CDPConnectionStatus
from runtime.errors import (
    CDPConnectionException,
    CDPProtocolException,
    CDPTimeoutException,
)

logger = logging.getLogger("desktop_webview.cdp_transport")


class ICDPTransport(ABC):
    """Abstract interface for Chrome DevTools Protocol transport."""

    @abstractmethod
    async def connect(self, timeout: float = 10.0) -> None:
        """Establishes connection to the CDP WebSocket endpoint."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanly closes the transport connection and terminates read loops."""
        ...

    @abstractmethod
    async def send_command(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Sends a JSON-RPC command and awaits the correlated response.
        Supports concurrent outstanding requests safely.
        """
        ...

    @abstractmethod
    def add_event_listener(
        self,
        event_name: str,
        callback: Callable[[Dict[str, Any]], Any],
        session_id: Optional[str] = None,
    ) -> None:
        """Registers a callback for an asynchronous CDP event (e.g. 'Page.frameNavigated')."""
        ...

    @abstractmethod
    def remove_event_listener(
        self,
        event_name: str,
        callback: Callable[[Dict[str, Any]], Any],
        session_id: Optional[str] = None,
    ) -> None:
        """Removes a previously registered event callback."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Returns True if WebSocket connection is active."""
        ...

    @property
    @abstractmethod
    def endpoint_url(self) -> str:
        """The WebSocket URL of this transport."""
        ...

    @property
    @abstractmethod
    def status(self) -> CDPConnectionStatus:
        """Current connection lifecycle status."""
        ...


class WebSocketCDPTransport(ICDPTransport):
    """
    Production-grade asynchronous CDP WebSocket transport.
    Ensures:
    1. Independent background message reader.
    2. Strict separation of command responses (by integer ID) from async events (by method).
    3. Events are NEVER matched by request ID.
    4. Thread-safe and asyncio-safe concurrency for multiple simultaneous commands.
    5. Automatic protocol error and timeout mapping to structured platform exceptions.
    6. Controlled reconnection with backoff.
    """

    def __init__(
        self,
        ws_url: str = "",
        endpoint_url: Optional[str] = None,
        default_timeout: float = 15.0,
    ):
        self._ws_url = endpoint_url or ws_url
        if not self._ws_url:
            raise ValueError("WebSocket endpoint URL must be provided via ws_url or endpoint_url.")
        self._default_timeout = default_timeout
        self._websocket: Optional[Any] = None
        self._status = CDPConnectionStatus.DISCONNECTED
        self._msg_id = 0
        self._id_lock = asyncio.Lock()
        self._pending_requests: Dict[int, Tuple[asyncio.Future, str]] = {}
        # Global event listeners: event_name -> list of callbacks
        self._global_listeners: Dict[str, List[Callable[[Dict[str, Any]], Any]]] = {}
        # Session-scoped event listeners: (session_id, event_name) -> list of callbacks
        self._session_listeners: Dict[Tuple[str, str], List[Callable[[Dict[str, Any]], Any]]] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._close_requested = False

    @property
    def is_connected(self) -> bool:
        return self._status == CDPConnectionStatus.CONNECTED and self._websocket is not None

    @property
    def endpoint_url(self) -> str:
        return self._ws_url

    @property
    def status(self) -> CDPConnectionStatus:
        return self._status

    async def connect(self, timeout: float = 10.0) -> None:
        """Establishes WebSocket connection to Chromium CDP endpoint."""
        if websockets is None:
            raise CDPConnectionException("The 'websockets' library is not installed in the environment.")

        if self.is_connected:
            return

        self._status = CDPConnectionStatus.CONNECTING
        self._close_requested = False
        logger.debug(f"Connecting to CDP endpoint: {self._ws_url}")

        try:
            # 50MB max_size for large screenshots and full DOM dumps
            self._websocket = await asyncio.wait_for(
                websockets.connect(
                    self._ws_url,
                    max_size=50 * 1024 * 1024,
                    ping_interval=None,
                ),
                timeout=timeout,
            )
            self._status = CDPConnectionStatus.CONNECTED
            self._read_task = asyncio.create_task(self._read_loop())
            logger.info(f"CDP transport connected to {self._ws_url}")
        except asyncio.TimeoutError:
            self._status = CDPConnectionStatus.DISCONNECTED
            raise CDPConnectionException(
                f"Timed out connecting to CDP endpoint {self._ws_url} after {timeout}s",
                endpoint=self._ws_url,
            )
        except Exception as e:
            self._status = CDPConnectionStatus.DISCONNECTED
            raise CDPConnectionException(
                f"Failed to connect to CDP endpoint {self._ws_url}: {e}",
                endpoint=self._ws_url,
                details={"error": str(e)},
            )

    async def disconnect(self) -> None:
        """Closes the WebSocket connection cleanly and flushes pending requests."""
        self._close_requested = True
        self._status = CDPConnectionStatus.CLOSED

        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):
                pass
            self._read_task = None

        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

        # Fail any remaining in-flight requests cleanly
        for req_id, (future, method) in list(self._pending_requests.items()):
            if not future.done():
                future.set_exception(
                    CDPConnectionException(
                        f"CDP transport disconnected while waiting for response to '{method}' (id={req_id}).",
                        endpoint=self._ws_url,
                    )
                )
        self._pending_requests.clear()
        logger.debug(f"CDP transport to {self._ws_url} disconnected.")

    async def reconnect(self, max_attempts: int = 3, backoff_base: float = 0.2) -> bool:
        """
        Attempts controlled recovery of a dropped CDP connection.
        Advances connection state through RECONNECTING -> CONNECTED or DEGRADED.
        """
        if self._close_requested:
            return False

        self._status = CDPConnectionStatus.RECONNECTING
        logger.warning(f"Attempting reconnection to CDP endpoint: {self._ws_url}")

        for attempt in range(1, max_attempts + 1):
            delay = backoff_base * (2 ** (attempt - 1))
            await asyncio.sleep(delay)
            try:
                if self._websocket:
                    try:
                        await self._websocket.close()
                    except Exception:
                        pass
                self._websocket = await asyncio.wait_for(
                    websockets.connect(
                        self._ws_url,
                        max_size=50 * 1024 * 1024,
                        ping_interval=None,
                    ),
                    timeout=5.0,
                )
                self._status = CDPConnectionStatus.CONNECTED
                self._read_task = asyncio.create_task(self._read_loop())
                logger.info(f"CDP transport reconnected successfully on attempt {attempt}")
                self._dispatch_event("transport.reconnected", {"endpoint": self._ws_url, "attempt": attempt})
                return True
            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt}/{max_attempts} failed: {e}")

        self._status = CDPConnectionStatus.DEGRADED
        return False

    async def send_command(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Sends a JSON-RPC 2.0 command and awaits the correlated response.
        Assigns unique request IDs safely across concurrent coroutines.
        """
        if not self.is_connected or not self._websocket:
            raise CDPConnectionException(
                f"Cannot send command '{method}': CDP transport is not connected (status: {self._status.value}).",
                endpoint=self._ws_url,
            )

        async with self._id_lock:
            self._msg_id += 1
            req_id = self._msg_id

        payload: Dict[str, Any] = {
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        if session_id:
            payload["sessionId"] = session_id

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_requests[req_id] = (future, method)

        raw_msg = json.dumps(payload)
        try:
            await self._websocket.send(raw_msg)
        except Exception as e:
            self._pending_requests.pop(req_id, None)
            raise CDPConnectionException(
                f"Failed to send CDP command '{method}' over socket: {e}",
                endpoint=self._ws_url,
                details={"error": str(e)},
            )

        eff_timeout = timeout if timeout is not None else self._default_timeout
        try:
            result = await asyncio.wait_for(future, timeout=eff_timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise CDPTimeoutException(method=method, req_id=req_id, timeout_sec=eff_timeout)

    def add_event_listener(
        self,
        event_name: str,
        callback: Callable[[Dict[str, Any]], Any],
        session_id: Optional[str] = None,
    ) -> None:
        """Registers callback for event routing."""
        if session_id:
            key = (session_id, event_name)
            self._session_listeners.setdefault(key, []).append(callback)
        else:
            self._global_listeners.setdefault(event_name, []).append(callback)

    def remove_event_listener(
        self,
        event_name: str,
        callback: Callable[[Dict[str, Any]], Any],
        session_id: Optional[str] = None,
    ) -> None:
        """Removes previously registered callback."""
        if session_id:
            key = (session_id, event_name)
            listeners = self._session_listeners.get(key, [])
            if callback in listeners:
                listeners.remove(callback)
        else:
            listeners = self._global_listeners.get(event_name, [])
            if callback in listeners:
                listeners.remove(callback)

    async def _read_loop(self) -> None:
        """
        Background listener loop: reads raw WebSocket messages.
        Dispatches responses to matching futures by ID.
        Dispatches events by method name.
        NEVER matches events by request ID.
        """
        try:
            while self._status == CDPConnectionStatus.CONNECTED and self._websocket:
                try:
                    raw_msg = await self._websocket.recv()
                except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                    break

                try:
                    data = json.loads(raw_msg)
                except Exception as e:
                    logger.warning(f"Malformed JSON received over CDP WebSocket: {e}")
                    continue

                # 1. Command Response: matched by 'id'
                if "id" in data:
                    req_id = data["id"]
                    pending = self._pending_requests.pop(req_id, None)
                    if pending:
                        future, method = pending
                        if not future.done():
                            if "error" in data:
                                err = data["error"]
                                future.set_exception(
                                    CDPProtocolException(
                                        error_code=err.get("code", -32000),
                                        message=err.get("message", "Unknown CDP error"),
                                        method=method,
                                        details=err.get("data"),
                                    )
                                )
                            else:
                                future.set_result(data.get("result", {}))

                # 2. Asynchronous Event: matched by 'method'
                elif "method" in data:
                    self._dispatch_incoming_event(data)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"CDP read loop exception: {e}")
        finally:
            if not self._close_requested and self._status == CDPConnectionStatus.CONNECTED:
                logger.warning(f"CDP connection lost unexpectedly to {self._ws_url}")
                self._status = CDPConnectionStatus.DEGRADED
                # Schedule background reconnect if appropriate
                asyncio.create_task(self.reconnect())

    def _dispatch_incoming_event(self, data: Dict[str, Any]) -> None:
        """Dispatches incoming event to matching global and session-scoped listeners."""
        method = data.get("method", "")
        session_id = data.get("sessionId")

        # 1. Session-scoped callbacks
        if session_id:
            callbacks = self._session_listeners.get((session_id, method), [])
            for cb in callbacks:
                try:
                    cb(data)
                except Exception as e:
                    logger.error(f"Error in session event callback for '{method}': {e}")

            # Wildcard session callbacks
            wildcard_callbacks = self._session_listeners.get((session_id, "*"), [])
            for cb in wildcard_callbacks:
                try:
                    cb(data)
                except Exception as e:
                    logger.error(f"Error in wildcard session event callback: {e}")

        # 2. Global callbacks
        callbacks = self._global_listeners.get(method, [])
        for cb in callbacks:
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Error in global event callback for '{method}': {e}")

        # Wildcard global callbacks
        for cb in self._global_listeners.get("*", []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Error in wildcard global event callback: {e}")

    def _dispatch_event(self, method: str, params: Dict[str, Any]) -> None:
        """Internal helper to synthesize an event for registered listeners."""
        payload = {"method": method, "params": params}
        self._dispatch_incoming_event(payload)


class MockCDPTransport(ICDPTransport):
    """
    Deterministic In-Memory Mock Transport for CDP.
    Enables unit testing of concurrency, timeouts, protocol errors, event routing,
    and reconnection without requiring a live Chromium process.
    """

    def __init__(self, endpoint_url: str = "ws://127.0.0.1:9222/devtools/page/mock"):
        self._endpoint_url = endpoint_url
        self._connected = False
        self._status = CDPConnectionStatus.DISCONNECTED
        self._msg_id = 0
        self._sent_commands: List[Dict[str, Any]] = []
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
        self._global_listeners: Dict[str, List[Callable[[Dict[str, Any]], Any]]] = {}
        self._session_listeners: Dict[Tuple[str, str], List[Callable[[Dict[str, Any]], Any]]] = {}
        self._register_default_handlers()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def endpoint_url(self) -> str:
        return self._endpoint_url

    @property
    def status(self) -> CDPConnectionStatus:
        return self._status

    @property
    def sent_commands(self) -> List[Dict[str, Any]]:
        return self._sent_commands

    def _register_default_handlers(self) -> None:
        """Registers default standard CDP domain responses."""
        self._handlers["DOM.enable"] = lambda p: {}
        self._handlers["Page.enable"] = lambda p: {}
        self._handlers["Runtime.enable"] = lambda p: {}
        self._handlers["Accessibility.enable"] = lambda p: {}
        self._handlers["Accessibility.disable"] = lambda p: {}
        self._handlers["Target.setDiscoverTargets"] = lambda p: {}
        self._handlers["Page.getFrameTree"] = lambda p: {
            "frameTree": {
                "frame": {
                    "id": "root_frame_1",
                    "loaderId": "loader_1",
                    "url": "http://127.0.0.1:8000/index.html",
                    "securityOrigin": "http://127.0.0.1:8000",
                    "mimeType": "text/html",
                },
                "childFrames": [],
            }
        }
        self._handlers["Page.createIsolatedWorld"] = lambda p: {"executionContextId": 99}
        self._handlers["Runtime.evaluate"] = lambda p: {
            "result": {"type": "string", "value": "mock_result"}
        }
        self._handlers["Accessibility.getFullAXTree"] = lambda p: {
            "nodes": [
                {
                    "nodeId": "ax_1",
                    "role": {"type": "role", "value": "RootWebArea"},
                    "name": {"type": "computedString", "value": "Mock Page"},
                }
            ]
        }
        self._handlers["Input.dispatchMouseEvent"] = lambda p: {}
        self._handlers["Input.dispatchKeyEvent"] = lambda p: {}
        self._handlers["Input.insertText"] = lambda p: {}
        self._handlers["DOM.focus"] = lambda p: {}


    def register_handler(self, method: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Overrides or adds a command handler."""
        self._handlers[method] = handler

    async def connect(self, timeout: float = 10.0) -> None:
        self._connected = True
        self._status = CDPConnectionStatus.CONNECTED

    async def disconnect(self) -> None:
        self._connected = False
        self._status = CDPConnectionStatus.CLOSED

    async def send_command(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self._connected:
            raise CDPConnectionException("MockCDPTransport is not connected", endpoint=self._endpoint_url)

        self._msg_id += 1
        req_id = self._msg_id

        entry = {
            "id": req_id,
            "method": method,
            "params": params or {},
            "sessionId": session_id,
        }
        self._sent_commands.append(entry)

        # Simulation: Timeout
        if method == "simulate_timeout":
            eff_timeout = timeout or 0.1
            await asyncio.sleep(eff_timeout + 0.05)
            raise CDPTimeoutException(method=method, req_id=req_id, timeout_sec=eff_timeout)

        # Simulation: Protocol Error
        if method == "simulate_protocol_error":
            raise CDPProtocolException(
                error_code=-32000,
                message="Simulated CDP Protocol Error",
                method=method,
            )

        if method in self._handlers:
            handler = self._handlers[method]
            result = handler(params or {})
            return result

        # Default empty result
        return {}

    def emit_event(self, method: str, params: Dict[str, Any], session_id: Optional[str] = None) -> None:
        """Simulates an asynchronous CDP event arrival."""
        payload: Dict[str, Any] = {"method": method, "params": params}
        if session_id:
            payload["sessionId"] = session_id

        # 1. Session callbacks
        if session_id:
            for cb in self._session_listeners.get((session_id, method), []):
                cb(payload)
            for cb in self._session_listeners.get((session_id, "*"), []):
                cb(payload)

        # 2. Global callbacks
        for cb in self._global_listeners.get(method, []):
            cb(payload)
        for cb in self._global_listeners.get("*", []):
            cb(payload)

    def add_event_listener(
        self,
        event_name: str,
        callback: Callable[[Dict[str, Any]], Any],
        session_id: Optional[str] = None,
    ) -> None:
        if session_id:
            self._session_listeners.setdefault((session_id, event_name), []).append(callback)
        else:
            self._global_listeners.setdefault(event_name, []).append(callback)

    def remove_event_listener(
        self,
        event_name: str,
        callback: Callable[[Dict[str, Any]], Any],
        session_id: Optional[str] = None,
    ) -> None:
        if session_id:
            listeners = self._session_listeners.get((session_id, event_name), [])
            if callback in listeners:
                listeners.remove(callback)
        else:
            listeners = self._global_listeners.get(event_name, [])
            if callback in listeners:
                listeners.remove(callback)
