"""
Stateful Webview Automation Core Facade.
Coordinates direct CDP transport, target discovery and multiplexing, hierarchical frame
management, isolated utility world script execution, accessibility inspection with freeze detection,
epoch-scoped reference invalidation, and canonical coordinate integration.
"""

from __future__ import annotations
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Callable

from runtime.state import TargetPlane, AXFreshnessStatus, TargetLifecycleState
from runtime.cdp_transport import ICDPTransport, WebSocketCDPTransport, MockCDPTransport
from runtime.cdp_target import CDPTargetManager, CDPTargetInfo, EndpointProcessCorrelation
from runtime.frame_manager import FrameManager, FrameContext
from runtime.utility_world import UtilityWorldManager, UTILITY_WORLD_NAME
from runtime.ax_runtime import AccessibilityRuntime, AXSnapshot
from runtime.references import Rect, ElementRef, ReferenceRegistry
from runtime.coordinate_transform import CoordinateTransformer, CoordinateTransformContext
from runtime.logging_events import UntrustedUIText
from runtime.errors import (
    CDPConnectionException,
    InvalidTargetException,
    TargetNotFoundException,
    StaleReferenceException,
    FrameDetachedException,
)

logger = logging.getLogger("desktop_webview.webview_core")


@dataclass(frozen=True)
class WebviewGeometry:
    """Canonical geometric metrics of an element in a webview."""
    css_rect: Rect
    screen_rect: Rect
    client_width: float
    client_height: float
    scroll_left: float
    scroll_top: float
    dpr: float
    is_in_viewport: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "css_rect": self.css_rect.to_dict(),
            "screen_rect": self.screen_rect.to_dict(),
            "client_width": self.client_width,
            "client_height": self.client_height,
            "scroll_left": self.scroll_left,
            "scroll_top": self.scroll_top,
            "dpr": self.dpr,
            "is_in_viewport": self.is_in_viewport,
        }


class WebviewAutomationCore:
    """
    Central stateful Webview Automation Core.
    Underneath observation, actionability, and MCP layers.
    Binds:
    1. CDP Connection Manager (ICDPTransport)
    2. Target Manager & Multiplexer (CDPTargetManager)
    3. Frame Context Manager (FrameManager)
    4. Utility World Manager (UtilityWorldManager)
    5. Accessibility Runtime (AccessibilityRuntime)
    6. Epoch / Reference Invalidator (ReferenceRegistry)
    7. Coordinate Subsystem (CoordinateTransformer)
    """

    def __init__(
        self,
        session_id: str,
        transport: ICDPTransport,
        reference_registry: ReferenceRegistry,
        native_pid: Optional[int] = None,
        native_hwnd: Optional[int] = None,
        cdp_port: Optional[int] = None,
        trace_engine: Optional[Any] = None,
    ):
        self.session_id = session_id
        self.transport = transport
        self.reference_registry = reference_registry
        self.native_pid = native_pid
        self.native_hwnd = native_hwnd
        self.cdp_port = cdp_port
        self.trace_engine = trace_engine

        # Subsystems
        self.target_manager = CDPTargetManager(transport=self.transport, session_id=self.session_id)
        self.frame_manager = FrameManager(
            transport=self.transport,
            reference_registry=self.reference_registry,
            session_id=self.session_id,
        )
        self.utility_world = UtilityWorldManager(
            transport=self.transport,
            frame_manager=self.frame_manager,
            session_id=self.session_id,
        )
        self.ax_runtime = AccessibilityRuntime(
            transport=self.transport,
            session_id=self.session_id,
        )

        # Diagnostics
        self.console_events: List[Dict[str, Any]] = []
        self.runtime_exceptions: List[Dict[str, Any]] = []
        self._connected = False
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connected and self.transport.is_connected

    @property
    def current_epoch(self) -> int:
        return self.reference_registry.current_epoch

    # -------------------------------------------------------------------------
    # 1. Lifecycle: Connect & Teardown
    # -------------------------------------------------------------------------
    async def connect(self, timeout: float = 10.0) -> None:
        """
        Connects transport, initializes target discovery, frame management, and event listeners.
        """
        async with self._lock:
            if self._connected:
                return

            # 1. Connect transport
            await self.transport.connect(timeout=timeout)

            # 2. Register diagnostic listeners (console and exceptions)
            self.transport.add_event_listener("Runtime.consoleAPICalled", self._on_console_event)
            self.transport.add_event_listener("Runtime.exceptionThrown", self._on_exception_event)

            # 3. Initialize target manager
            await self.target_manager.initialize()

            # 4. Initialize frame hierarchy
            await self.frame_manager.initialize()

            self._connected = True
            logger.info(f"WebviewAutomationCore connected for session {self.session_id}")

    async def disconnect(self) -> None:
        """Cleanly closes all webview subsystems and terminates WebSocket transport."""
        async with self._lock:
            self._connected = False
            try:
                await self.ax_runtime.disable()
            except Exception:
                pass
            try:
                await self.transport.disconnect()
            except Exception:
                pass
            self.utility_world.invalidate_frame_contexts()
            logger.info(f"WebviewAutomationCore disconnected for session {self.session_id}")

    # -------------------------------------------------------------------------
    # 2. Diagnostic Listeners & Untrusted Content Handling
    # -------------------------------------------------------------------------
    def _on_console_event(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        msg_type = params.get("type", "log")
        args = params.get("args", [])
        text_parts = []
        for a in args:
            if isinstance(a, dict):
                text_parts.append(str(a.get("value", a.get("description", ""))))
            else:
                text_parts.append(str(a))
        raw_text = " ".join(text_parts)
        # Wrap in UntrustedUIText to enforce security boundary
        untrusted = UntrustedUIText(raw_text, source_plane="console")
        self.console_events.append({
            "type": msg_type,
            "text": untrusted.sanitized,
            "timestamp": params.get("timestamp"),
        })
        if getattr(self, "trace_engine", None):
            try:
                active_target = self.target_manager.active_target_id if self.target_manager else None
                self.trace_engine.ingest_console_message(
                    level=msg_type,
                    message=untrusted.sanitized,
                    source="console",
                    cdp_target_id=active_target,
                )
            except Exception as e:
                logger.debug(f"Failed ingesting console message into trace_engine: {e}")

    def _on_exception_event(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        details = params.get("exceptionDetails", {})
        text = details.get("text", "Runtime exception")
        if "exception" in details and "description" in details["exception"]:
            text = f"{text}: {details['exception']['description']}"
        untrusted = UntrustedUIText(text, source_plane="runtime_exception")
        self.runtime_exceptions.append({
            "type": "error",
            "text": untrusted.sanitized,
            "timestamp": details.get("exception", {}).get("timestamp"),
        })
        if getattr(self, "trace_engine", None):
            try:
                active_target = self.target_manager.active_target_id if self.target_manager else None
                self.trace_engine.ingest_console_message(
                    level="error",
                    message=untrusted.sanitized,
                    source="runtime_exception",
                    cdp_target_id=active_target,
                )
            except Exception as e:
                logger.debug(f"Failed ingesting exception into trace_engine: {e}")

    # -------------------------------------------------------------------------
    # 3. Script Execution Primitives
    # -------------------------------------------------------------------------
    async def evaluate_script(
        self,
        expression: str,
        in_utility_world: bool = True,
        frame_id: Optional[str] = None,
        return_by_value: bool = True,
        await_promise: bool = True,
        timeout: Optional[float] = None,
    ) -> Any:
        """
        Executes JavaScript in either the isolated utility world or the main world.
        """
        if not self.is_connected:
            raise CDPConnectionException("Cannot evaluate script: Webview core is not connected.")

        if in_utility_world:
            return await self.utility_world.evaluate(
                expression=expression,
                frame_id=frame_id,
                return_by_value=return_by_value,
                await_promise=await_promise,
                timeout=timeout,
            )
        else:
            params: Dict[str, Any] = {
                "expression": expression,
                "returnByValue": return_by_value,
                "awaitPromise": await_promise,
            }
            if frame_id:
                ctx_id = self.frame_manager.resolve_execution_context(frame_id=frame_id, use_utility_world=False)
                params["contextId"] = ctx_id

            target_sess = self.frame_manager.target_session_id
            result = await self.transport.send_command(
                "Runtime.evaluate",
                params=params,
                session_id=target_sess,
                timeout=timeout,
            )
            if "exceptionDetails" in result:
                exc = result["exceptionDetails"]
                text = exc.get("text", "JavaScript error")
                if "exception" in exc and "description" in exc["exception"]:
                    text = f"{text}: {exc['exception']['description']}"
                raise RuntimeError(text)
            res_obj = result.get("result", {})
            return res_obj.get("value") if return_by_value else res_obj

    async def get_dom_element_count(self, in_utility_world: bool = True, frame_id: Optional[str] = None) -> int:
        """Returns total DOM element count: document.querySelectorAll('*').length."""
        js = "document.querySelectorAll('*').length"
        count = await self.evaluate_script(js, in_utility_world=in_utility_world, frame_id=frame_id)
        return int(count) if isinstance(count, (int, float)) else 0

    async def query_element_geometry(
        self,
        selector: str,
        in_utility_world: bool = True,
        frame_id: Optional[str] = None,
    ) -> Optional[Dict[str, float]]:
        """
        Queries element bounding rect, viewport dimensions, and scroll offsets via JS.
        Returns CSS rect dictionary or None if element not found.
        """
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{
                x: r.left,
                y: r.top,
                width: r.width,
                height: r.height,
                clientWidth: document.documentElement.clientWidth,
                clientHeight: document.documentElement.clientHeight,
                scrollLeft: window.scrollX || document.documentElement.scrollLeft,
                scrollTop: window.scrollY || document.documentElement.scrollTop,
                dpr: window.devicePixelRatio || 1.0
            }};
        }})()
        """
        return await self.evaluate_script(js, in_utility_world=in_utility_world, frame_id=frame_id)

    async def query_element_styles(
        self,
        selector: str,
        properties: List[str],
        in_utility_world: bool = True,
        frame_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Queries computed CSS style values for an element."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return {{}};
            const s = window.getComputedStyle(el);
            const res = {{}};
            const props = {json.dumps(properties)};
            for (const p of props) {{
                res[p] = s.getPropertyValue(p);
            }}
            return res;
        }})()
        """
        res = await self.evaluate_script(js, in_utility_world=in_utility_world, frame_id=frame_id)
        return res if isinstance(res, dict) else {}

    async def check_element_visibility(
        self,
        selector: str,
        in_utility_world: bool = True,
        frame_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Performs comprehensive DOM visibility checks:
        attachment, CSS display, visibility, opacity, dimensions, and viewport overlap.
        """
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return {{ attached: false, visible: false, reason: "NOT_IN_DOM" }};
            const s = window.getComputedStyle(el);
            if (s.display === 'none') return {{ attached: true, visible: false, reason: "DISPLAY_NONE" }};
            if (s.visibility === 'hidden' || s.visibility === 'collapse') return {{ attached: true, visible: false, reason: "VISIBILITY_HIDDEN" }};
            if (parseFloat(s.opacity) === 0) return {{ attached: true, visible: false, reason: "OPACITY_ZERO" }};
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) return {{ attached: true, visible: false, reason: "ZERO_SIZE" }};
            const inViewport = (
                r.bottom > 0 &&
                r.right > 0 &&
                r.top < (window.innerHeight || document.documentElement.clientHeight) &&
                r.left < (window.innerWidth || document.documentElement.clientWidth)
            );
            return {{
                attached: true,
                visible: true,
                in_viewport: inViewport,
                rect: {{ x: r.left, y: r.top, width: r.width, height: r.height }}
            }};
        }})()
        """
        res = await self.evaluate_script(js, in_utility_world=in_utility_world, frame_id=frame_id)
        return res if isinstance(res, dict) else {"attached": False, "visible": False, "reason": "EVALUATION_FAILED"}

    # -------------------------------------------------------------------------
    # 4. Coordinate Integration: Web CSS -> Physical Screen
    # -------------------------------------------------------------------------
    def convert_css_to_screen(
        self,
        css_x: float,
        css_y: float,
        client_origin_screen: Tuple[int, int] = (0, 0),
        dpr: float = 1.0,
        webview_offset_in_native: Tuple[int, int] = (0, 0),
    ) -> Tuple[int, int]:
        """
        Translates Web CSS coordinates to physical screen pixels using CoordinateTransformer.
        Web CSS -> Webview Client -> Native Client -> Physical Screen.
        """
        context = CoordinateTransformContext(
            dpi_scale=dpr,
            client_origin_screen=client_origin_screen,
            webview_client_offset=webview_offset_in_native,
        )
        return CoordinateTransformer.css_to_screen(css_x, css_y, context)

    def convert_css_rect_to_screen_rect(
        self,
        css_rect: Rect,
        client_origin_screen: Tuple[int, int] = (0, 0),
        dpr: float = 1.0,
        webview_offset_in_native: Tuple[int, int] = (0, 0),
    ) -> Rect:
        """Transforms a Web CSS bounding rectangle to a physical display screen rectangle."""
        context = CoordinateTransformContext(
            dpi_scale=dpr,
            client_origin_screen=client_origin_screen,
            webview_client_offset=webview_offset_in_native,
        )
        top_left_x, top_left_y = CoordinateTransformer.css_to_screen(css_rect.x, css_rect.y, context)
        scaled_w = css_rect.width * dpr
        scaled_h = css_rect.height * dpr
        return Rect(x=float(top_left_x), y=float(top_left_y), width=float(scaled_w), height=float(scaled_h))

    # -------------------------------------------------------------------------
    # 5. Accessibility Inspection & Freeze Diagnosis (SP-02)
    # -------------------------------------------------------------------------
    async def capture_accessibility_snapshot(self, auto_recover: bool = True) -> AXSnapshot:
        """
        Acquires an accessibility snapshot, validates freshness against DOM count,
        and optionally executes SP-02 freeze recovery if suspected stale.
        """
        # 1. Query DOM count via utility world
        dom_count: Optional[int] = None
        try:
            dom_count = await self.get_dom_element_count(in_utility_world=True)
        except Exception as e:
            logger.debug(f"Could not retrieve DOM count for AX validation: {e}")

        # 2. Acquire AX snapshot
        root_loader = self.frame_manager.root_frame.loader_id if self.frame_manager.root_frame else ""
        snapshot = await self.ax_runtime.acquire_snapshot(
            loader_id=root_loader,
            epoch=self.current_epoch,
            dom_element_count=dom_count,
        )

        # 3. SP-02 Auto-Recovery if suspected stale
        if auto_recover and snapshot.freshness == AXFreshnessStatus.SUSPECTED_STALE:
            logger.warning(
                f"Accessibility tree flagged as {snapshot.freshness.value} (AX={snapshot.node_count}, DOM={dom_count}). Recovering..."
            )
            snapshot = await self.ax_runtime.recover_freeze(
                loader_id=root_loader,
                epoch=self.current_epoch,
                dom_element_count=dom_count,
            )

        return snapshot

    # -------------------------------------------------------------------------
    # 6. Epoch-Scoped Synthetic Reference Binding
    # -------------------------------------------------------------------------
    def register_element_ref(
        self,
        role: str,
        name: Optional[str],
        bounds: Rect,
        locator_recipe: Optional[Dict[str, Any]] = None,
    ) -> ElementRef:
        """
        Registers an element reference in the active observation epoch.
        Prevents raw browser nodeIds from becoming durable agent references.
        """
        return self.reference_registry.register_ref(
            plane=TargetPlane.WEBVIEW_DOM,
            role=role,
            name=name,
            bounds=bounds,
            locator_recipe=locator_recipe,
        )

    def resolve_ref(self, ref_id: str) -> ElementRef:
        """
        Resolves an element reference for the current epoch.
        Raises StaleReferenceException if the ref belongs to a prior epoch.
        """
        return self.reference_registry.resolve_ref(ref_id)
