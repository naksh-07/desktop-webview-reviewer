"""
Low-level CDP WebSocket session manager and JSON-RPC protocol transport.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional
import websockets

from .models import Target, NodeGeometry

logger = logging.getLogger("desktop_webview.session")


class CDPSession:
    """
    Manages an active Chrome DevTools Protocol (CDP) WebSocket connection.
    Supports asynchronous JSON-RPC command correlation and event listening.
    """

    def __init__(self, target: Target, timeout: float = 15.0):
        self.target = target
        self.timeout = timeout
        self.ws_url = target.websocket_endpoint
        if not self.ws_url:
            raise ValueError(f"Target '{target.id}' has no websocket_endpoint.")

        self._websocket: Any = None
        self._msg_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._event_listeners: Dict[str, List[Callable[[dict], Any]]] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self.console_events: List[Dict[str, Any]] = []
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self._websocket is not None

    async def connect(self) -> None:
        """Establishes WebSocket connection and starts background message listener."""
        if self.is_connected:
            return

        logger.debug(f"Connecting to CDP endpoint: {self.ws_url}")
        assert self.ws_url is not None
        # max_size=50MB to handle large screenshots or DOM dumps
        self._websocket = await websockets.connect(
            self.ws_url,
            max_size=50 * 1024 * 1024,
            ping_interval=None
        )
        self._is_connected = True
        self._listener_task = asyncio.create_task(self._read_messages())

        # Register default console and runtime listeners
        self.add_event_listener("Runtime.consoleAPICalled", self._on_console_event)
        self.add_event_listener("Runtime.exceptionThrown", self._on_exception_event)

        logger.debug("CDP connection established successfully.")

    async def close(self) -> None:
        """Closes the WebSocket connection cleanly."""
        self._is_connected = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except (asyncio.CancelledError, Exception):
                pass
            self._listener_task = None

        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

        # Resolve any pending requests with error
        for req_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(ConnectionError("CDP session closed while awaiting response."))
        self._pending_requests.clear()

    def add_event_listener(self, event_name: str, callback: Callable[[dict], Any]) -> None:
        """Registers a callback for CDP events (e.g. 'Runtime.consoleAPICalled')."""
        if event_name not in self._event_listeners:
            self._event_listeners[event_name] = []
        self._event_listeners[event_name].append(callback)

    def _on_console_event(self, event: dict) -> None:
        params = event.get("params", {})
        msg_type = params.get("type", "log")
        args = params.get("args", [])
        text_parts = []
        for arg in args:
            if "value" in arg:
                text_parts.append(str(arg["value"]))
            elif "description" in arg:
                text_parts.append(str(arg["description"]))
            else:
                text_parts.append(json.dumps(arg))
        text = " ".join(text_parts)
        self.console_events.append({
            "type": msg_type,
            "text": text,
            "timestamp": params.get("timestamp"),
            "raw": params
        })

    def _on_exception_event(self, event: dict) -> None:
        params = event.get("params", {})
        details = params.get("exceptionDetails", {})
        text = details.get("text", "Unknown runtime exception")
        if "exception" in details and "description" in details["exception"]:
            text = f"{text}: {details['exception']['description']}"
        self.console_events.append({
            "type": "error",
            "text": text,
            "raw": params
        })

    async def _read_messages(self) -> None:
        """Continuous background loop processing incoming WebSocket messages."""
        try:
            while self._is_connected and self._websocket:
                raw_msg = await self._websocket.recv()
                try:
                    data = json.loads(raw_msg)
                except Exception as e:
                    logger.warning(f"Malformed JSON received: {e}")
                    continue

                # Is this a response to a command?
                if "id" in data:
                    req_id = data["id"]
                    if req_id in self._pending_requests:
                        future = self._pending_requests.pop(req_id)
                        if not future.done():
                            if "error" in data:
                                future.set_exception(
                                    RuntimeError(f"CDP Error ({data['error'].get('code')}): {data['error'].get('message')}")
                                )
                            else:
                                future.set_result(data.get("result", {}))
                # Is this an asynchronous event?
                elif "method" in data:
                    method = data["method"]
                    listeners = self._event_listeners.get(method, [])
                    for cb in listeners:
                        try:
                            cb(data)
                        except Exception as e:
                            logger.error(f"Error in event listener for {method}: {e}")
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            pass
        except Exception as e:
            logger.debug(f"CDP reader loop terminated: {e}")

    async def send_command(self, method: str, params: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        """Sends a JSON-RPC command and waits for the matching response."""
        if not self.is_connected or not self._websocket:
            raise ConnectionError("Cannot send command: CDP WebSocket is not connected.")

        self._msg_id += 1
        req_id = self._msg_id
        payload = {
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_requests[req_id] = future

        await self._websocket.send(json.dumps(payload))

        eff_timeout = timeout if timeout is not None else self.timeout
        try:
            result = await asyncio.wait_for(future, timeout=eff_timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise TimeoutError(f"Timed out waiting for response to CDP command '{method}' (id={req_id}) after {eff_timeout}s.")

    # High-Level Helper Operations

    async def enable_domains(self, domains: Optional[List[str]] = None) -> None:
        """Enables common CDP domains (DOM, Runtime, Page)."""
        target_domains = domains or ["DOM", "Runtime", "Page"]
        for domain in target_domains:
            try:
                await self.send_command(f"{domain}.enable")
            except Exception as e:
                logger.warning(f"Could not enable domain {domain}: {e}")

    async def evaluate_js(self, expression: str, return_by_value: bool = True, await_promise: bool = True) -> Any:
        """Evaluates JavaScript in the target page context."""
        result = await self.send_command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": return_by_value,
            "awaitPromise": await_promise
        })
        if "exceptionDetails" in result:
            exc = result["exceptionDetails"]
            raise RuntimeError(f"JavaScript evaluation error: {exc.get('text', '')}")
        
        res_obj = result.get("result", {})
        if return_by_value:
            return res_obj.get("value")
        return res_obj

    async def get_document(self) -> dict:
        """Retrieves root DOM node."""
        result = await self.send_command("DOM.getDocument", {"depth": -1, "pierce": True})
        return result.get("root", {})

    async def query_selector(self, selector: str, node_id: Optional[int] = None) -> Optional[int]:
        """Resolves nodeId for a CSS selector."""
        if node_id is None:
            root = await self.get_document()
            node_id = root.get("nodeId", 1)

        result = await self.send_command("DOM.querySelector", {
            "nodeId": node_id,
            "selector": selector
        })
        target_id = result.get("nodeId", 0)
        return target_id if target_id > 0 else None

    async def get_bounding_rect(self, selector: str) -> Optional[NodeGeometry]:
        """Computes element bounding box via evaluate_js."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{ x: r.left, y: r.top, width: r.width, height: r.height }};
        }})()
        """
        rect = await self.evaluate_js(js)
        if not rect:
            return None
        return NodeGeometry(
            x=float(rect.get("x", 0)),
            y=float(rect.get("y", 0)),
            width=float(rect.get("width", 0)),
            height=float(rect.get("height", 0))
        )

    async def dispatch_mouse_click(self, x: float, y: float, button: str = "left", click_count: int = 1) -> None:
        """Dispatches mousePressed and mouseReleased events at (x, y)."""
        await self.send_command("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": int(x),
            "y": int(y),
            "button": button,
            "clickCount": click_count
        })
        await asyncio.sleep(0.05)
        await self.send_command("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": int(x),
            "y": int(y),
            "button": button,
            "clickCount": click_count
        })

    async def dispatch_key_event(self, event_type: str, key: str, text: Optional[str] = None) -> None:
        """Dispatches raw keyboard events (keyDown, keyUp, char)."""
        params: Dict[str, Any] = {
            "type": event_type,
            "key": key
        }
        if text is not None:
            params["text"] = text
        await self.send_command("Input.dispatchKeyEvent", params)

    async def capture_screenshot(self, format: str = "png") -> bytes:
        """Captures page screenshot and returns raw bytes."""
        import base64
        result = await self.send_command("Page.captureScreenshot", {"format": format})
        data_base64 = result.get("data", "")
        if not data_base64:
            raise RuntimeError("Empty screenshot data received from CDP Page.captureScreenshot.")
        return base64.b64decode(data_base64)


class MultiTargetSessionManager:
    """
    Manages multi-target sessions for desktop applications with multiple webview surfaces.
    Provides listing, filtering, selecting, and deterministic switching between targets.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9222, engine: str = "generic"):
        self.host = host
        self.port = port
        self.engine = engine
        self._active_session: Optional[CDPSession] = None
        self._target_cache: List[Target] = []

    @property
    def active_session(self) -> Optional[CDPSession]:
        return self._active_session

    @property
    def active_target(self) -> Optional[Target]:
        return self._active_session.target if self._active_session else None

    def list_targets(self, criteria: Optional[Any] = None) -> List[Target]:
        """Queries and ranks all available targets on the debug endpoint."""
        from .discovery import TargetDiscovery
        targets = TargetDiscovery.query_targets(host=self.host, port=self.port, engine=self.engine)
        for t in targets:
            TargetDiscovery.rank_target(t, criteria)
        self._target_cache = targets
        return targets

    def select_target(self, criteria: Optional[Any] = None) -> Optional[Target]:
        """Selects the best matching target using ranking heuristics."""
        from .discovery import TargetDiscovery
        targets = self.list_targets(criteria)
        return TargetDiscovery.select_target(targets, criteria)

    async def switch_target(self, target_or_id: Any, timeout: float = 15.0) -> CDPSession:
        """
        Detaches from the current target and attaches to the requested target.
        Explicitly logs and confirms the target switch without silent redirection.
        """
        target: Optional[Target] = None
        if isinstance(target_or_id, Target):
            target = target_or_id
        elif isinstance(target_or_id, str):
            targets = self.list_targets()
            for t in targets:
                if t.id == target_or_id or t.id.startswith(target_or_id):
                    target = t
                    break
            if not target:
                raise ValueError(f"Target ID '{target_or_id}' not found among active targets.")
        else:
            raise TypeError("target_or_id must be a Target instance or string target ID.")

        if not target.websocket_endpoint:
            # Try to populate websocket endpoint if missing
            targets = self.list_targets()
            matched = next((t for t in targets if t.id == target.id), None)
            if matched and matched.websocket_endpoint:
                target.websocket_endpoint = matched.websocket_endpoint
            else:
                raise ValueError(f"Target '{target.id}' ({target.title}) has no websocket_endpoint.")

        # If already attached to this target and healthy
        if self._active_session and self._active_session.target.id == target.id and self._active_session.is_connected:
            logger.info(f"Already connected to target: {target.id} ('{target.title}')")
            return self._active_session

        # Detach previous session
        if self._active_session:
            logger.info(f"Switching target: detaching from '{self._active_session.target.title}' (ID: {self._active_session.target.id})")
            await self._active_session.close()
            self._active_session = None

        logger.info(f"Attaching to target: '{target.title}' (ID: {target.id}, URL: {target.url})")
        session = CDPSession(target=target, timeout=timeout)
        await session.connect()
        await session.enable_domains(["DOM", "Runtime", "Page"])
        self._active_session = session
        return session

    async def close_all(self) -> None:
        """Closes any active target session."""
        if self._active_session:
            await self._active_session.close()
            self._active_session = None

