"""
High-level DOM querying, interaction, and input actions.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from .models import ActionReceipt, NodeGeometry
from .session import CDPSession

logger = logging.getLogger("desktop_webview.actions")


class WebviewActions:
    """Provides high-level action primitives over a CDPSession with state verification."""

    def __init__(self, session: CDPSession):
        self.session = session
        self.history: List[ActionReceipt] = []

    async def get_text(self, selector: str) -> Optional[str]:
        """Gets textContent of the matched element."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            return el ? el.textContent : null;
        }})()
        """
        val = await self.session.evaluate_js(js)
        return str(val) if val is not None else None

    async def get_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """Gets attribute or property value of the matched element."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            if ({json.dumps(attribute)} === 'value' && 'value' in el) {{
                return el.value;
            }}
            return el.getAttribute({json.dumps(attribute)});
        }})()
        """
        val = await self.session.evaluate_js(js)
        return str(val) if val is not None else None

    async def get_value(self, selector: str) -> Optional[str]:
        """Gets current input value property of the matched element."""
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            return (el && 'value' in el) ? el.value : null;
        }})()
        """
        val = await self.session.evaluate_js(js)
        return str(val) if val is not None else None


    async def _capture_element_state(self, selector: Optional[str]) -> Optional[Dict[str, Any]]:
        """Helper to capture snapshot of an element state."""
        if not selector:
            return None
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{
                "tagName": el.tagName,
                "textContent": el.textContent,
                "value": el.value || null,
                "disabled": el.disabled || false,
                "visible": (r.width > 0 && r.height > 0),
                "rect": {{ "x": r.left, "y": r.top, "width": r.width, "height": r.height }}
            }};
        }})()
        """
        try:
            return await self.session.evaluate_js(js)
        except Exception:
            return None

    async def click(self, selector_or_geometry: Any) -> NodeGeometry:
        """
        Clicks an element by resolving its bounding rectangle and dispatching real mouse events.
        Automatically falls back to synthetic DOM event if native CDP input is unavailable.
        Records an ActionReceipt with before and after state.
        """
        start_time = time.time()
        selector = selector_or_geometry if isinstance(selector_or_geometry, str) else None
        before_state = await self._capture_element_state(selector)

        if isinstance(selector_or_geometry, NodeGeometry):
            geom = selector_or_geometry
        elif isinstance(selector_or_geometry, str):
            geom = await self.session.get_bounding_rect(selector_or_geometry)
            if not geom:
                receipt = ActionReceipt(
                    action_type="click",
                    selector=selector,
                    before_state=before_state,
                    duration_ms=(time.time() - start_time) * 1000.0,
                    success=False,
                    error=f"Element '{selector_or_geometry}' not found or has zero bounding rect."
                )
                self.history.append(receipt)
                raise ValueError(receipt.error)
        else:
            raise TypeError("selector_or_geometry must be a CSS selector string or NodeGeometry.")

        fallback_used = None
        try:
            logger.debug(f"Dispatching native click at ({geom.center_x}, {geom.center_y})")
            await self.session.dispatch_mouse_click(geom.center_x, geom.center_y)
        except Exception as native_err:
            logger.warning(f"Native input click failed ({native_err}); attempting synthetic DOM dispatch.")
            if selector:
                js_synth = f"""
                (() => {{
                    const el = document.querySelector({json.dumps(selector)});
                    if (!el) return false;
                    el.click();
                    el.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, view: window }}));
                    return true;
                }})()
                """
                await self.session.evaluate_js(js_synth)
                fallback_used = "synthetic_dom_click"
            else:
                raise native_err

        await asyncio.sleep(0.05)
        after_state = await self._capture_element_state(selector)
        duration_ms = (time.time() - start_time) * 1000.0

        receipt = ActionReceipt(
            action_type="click",
            selector=selector,
            before_state=before_state,
            after_state=after_state,
            duration_ms=duration_ms,
            success=True,
            fallback_used=fallback_used
        )
        self.history.append(receipt)
        return geom

    async def type_text(self, selector: str, text: str, clear_first: bool = True) -> None:
        """Focuses element, optionally clears, and inputs text via evaluate_js and input events."""
        start_time = time.time()
        before_state = await self._capture_element_state(selector)

        # Focus and update value
        js_focus = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.focus();
            if ({json.dumps(clear_first)}) {{
                el.value = '';
            }}
            el.value += {json.dumps(text)};
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return true;
        }})()
        """
        success = await self.session.evaluate_js(js_focus)
        duration_ms = (time.time() - start_time) * 1000.0

        if not success:
            receipt = ActionReceipt(
                action_type="type_text",
                selector=selector,
                before_state=before_state,
                duration_ms=duration_ms,
                success=False,
                error=f"Cannot type into '{selector}': element not found."
            )
            self.history.append(receipt)
            raise ValueError(receipt.error)

        await asyncio.sleep(0.05)
        after_state = await self._capture_element_state(selector)
        receipt = ActionReceipt(
            action_type="type_text",
            selector=selector,
            before_state=before_state,
            after_state=after_state,
            duration_ms=duration_ms,
            success=True
        )
        self.history.append(receipt)

    async def scroll(self, dx: int = 0, dy: int = 0, selector: Optional[str] = None) -> None:
        """Scrolls window or specific element."""
        start_time = time.time()
        if selector:
            js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (el) el.scrollBy({dx}, {dy});
            }})()
            """
        else:
            js = f"window.scrollBy({dx}, {dy});"
        await self.session.evaluate_js(js)
        duration_ms = (time.time() - start_time) * 1000.0
        self.history.append(ActionReceipt(
            action_type="scroll",
            selector=selector,
            duration_ms=duration_ms,
            success=True
        ))

    async def wait_for_selector(self, selector: str, timeout: float = 10.0, interval: float = 0.2) -> bool:
        """Polls until selector is present in DOM or timeout expires."""
        start = time.time()
        while time.time() - start < timeout:
            js = f"document.querySelector({json.dumps(selector)}) !== null"
            res = await self.session.evaluate_js(js)
            if res is True:
                return True
            await asyncio.sleep(interval)
        return False

    async def wait_for_condition(self, expression: str, timeout: float = 10.0, interval: float = 0.2) -> bool:
        """Polls until expression returns truthy."""
        start = time.time()
        while time.time() - start < timeout:
            res = await self.session.evaluate_js(expression)
            if bool(res):
                return True
            await asyncio.sleep(interval)
        return False

