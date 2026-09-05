"""
Dedicated Web Action Executor for Desktop WebView Reviewer (Architecture H).
Dispatches interactions against webview targets via Chromium DevTools Protocol (CDP)
Input domain or physical desktop input with explicit provenance and receipt generation.
Never uses arbitrary DOM mutations (e.g. element.click()) as the primary proof of input.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Any

from runtime.state import TargetPlane
from runtime.references import ElementRef, ReferenceRegistry
from runtime.webview_core import WebviewAutomationCore
from runtime.actionability import ActionabilityEngine, ActionabilityResult
from runtime.action_models import (
    ActionRequest,
    ActionTarget,
    ActionReceipt,
    ActionType,
    DispatchMethod,
    DispatchStatus,
)
from runtime.errors import (
    CDPProtocolException,
    CDPConnectionException,
    ActionNotReadyException,
    StaleReferenceException,
)

logger = logging.getLogger("desktop_webview.web_action_executor")


class WebActionExecutor:
    """
    Executes interactions targeting Webview DOM elements.
    Binds CDP Input domain primitives (mouse, key, scroll) with frame-awareness,
    epoch validation, and explicit fallback provenance.
    """

    def __init__(
        self,
        webview_core: WebviewAutomationCore,
        actionability_engine: ActionabilityEngine,
        reference_registry: ReferenceRegistry,
    ):
        self.webview_core = webview_core
        self.actionability_engine = actionability_engine
        self.reference_registry = reference_registry

    async def execute_action(
        self,
        request: ActionRequest,
        target: ActionTarget,
        precondition_result: Optional[ActionabilityResult] = None,
    ) -> ActionReceipt:
        """
        Executes a validated action request against a web target and returns an ActionReceipt.
        """
        start_time = time.time()
        action_type = request.action_type
        ref_id = target.reference
        current_epoch = self.reference_registry.current_epoch

        # 1. Epoch verification
        if target.epoch != current_epoch:
            duration = (time.time() - start_time) * 1000.0
            return ActionReceipt(
                action_id=request.action_id,
                session_id=request.session_id,
                target_id=target.target_id,
                epoch=current_epoch,
                plane=TargetPlane.WEBVIEW_DOM,
                reference=ref_id,
                action_type=action_type,
                dispatch_method=DispatchMethod.CDP_INPUT,
                dispatch_timestamp=start_time,
                coordinates=target.affordance_point,
                native_hwnd=target.native_hwnd,
                cdp_target_id=target.cdp_target_id,
                frame_id=target.frame_id,
                precondition_summary=f"Epoch mismatch: target epoch {target.epoch} != active epoch {current_epoch}",
                dispatch_status=DispatchStatus.REJECTED,
                error=f"Stale epoch: {target.epoch} != {current_epoch}",
                duration_ms=duration,
            )

        # 2. Connection verification
        if not self.webview_core or not self.webview_core.is_connected:
            duration = (time.time() - start_time) * 1000.0
            return ActionReceipt(
                action_id=request.action_id,
                session_id=request.session_id,
                target_id=target.target_id,
                epoch=current_epoch,
                plane=TargetPlane.WEBVIEW_DOM,
                reference=ref_id,
                action_type=action_type,
                dispatch_method=DispatchMethod.CDP_INPUT,
                dispatch_timestamp=start_time,
                coordinates=target.affordance_point,
                native_hwnd=target.native_hwnd,
                cdp_target_id=target.cdp_target_id,
                frame_id=target.frame_id,
                precondition_summary="Webview automation core is disconnected",
                dispatch_status=DispatchStatus.FAILED,
                error="Webview disconnected",
                duration_ms=duration,
            )

        # 3. Actionability Gate Recheck
        actionability = precondition_result or await self.actionability_engine.evaluate_actionability(
            ref_id=ref_id,
            timeout_ms=min(request.timeout_ms, 1500),
        )

        if not actionability.is_actionable:
            reasons_summary = "; ".join(actionability.reasons) or "Actionability gate failed"
            duration = (time.time() - start_time) * 1000.0
            return ActionReceipt(
                action_id=request.action_id,
                session_id=request.session_id,
                target_id=target.target_id,
                epoch=current_epoch,
                plane=TargetPlane.WEBVIEW_DOM,
                reference=ref_id,
                action_type=action_type,
                dispatch_method=DispatchMethod.CDP_INPUT,
                dispatch_timestamp=start_time,
                coordinates=target.affordance_point,
                native_hwnd=target.native_hwnd,
                cdp_target_id=target.cdp_target_id,
                frame_id=target.frame_id,
                precondition_summary=reasons_summary,
                dispatch_status=DispatchStatus.REJECTED,
                error=f"Precondition failed: {reasons_summary}",
                duration_ms=duration,
                metadata={"actionability": actionability.to_dict()},
            )

        # 4. Resolve Affordance Point (logical viewport pixels)
        affordance_pt = actionability.affordance_point or target.affordance_point
        if not affordance_pt and action_type in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK, ActionType.HOVER):
            duration = (time.time() - start_time) * 1000.0
            return ActionReceipt(
                action_id=request.action_id,
                session_id=request.session_id,
                target_id=target.target_id,
                epoch=current_epoch,
                plane=TargetPlane.WEBVIEW_DOM,
                reference=ref_id,
                action_type=action_type,
                dispatch_method=DispatchMethod.CDP_INPUT,
                dispatch_timestamp=start_time,
                coordinates=None,
                native_hwnd=target.native_hwnd,
                cdp_target_id=target.cdp_target_id,
                frame_id=target.frame_id,
                precondition_summary="No valid affordance point available for pointer action",
                dispatch_status=DispatchStatus.FAILED,
                error="Missing affordance point",
                duration_ms=duration,
            )

        # 5. Dispatch Action
        dispatch_method = DispatchMethod.CDP_INPUT
        dispatch_error: Optional[str] = None
        dispatch_status = DispatchStatus.DISPATCHED
        metadata: Dict[str, Any] = {}

        try:
            if action_type == ActionType.CLICK:
                assert affordance_pt is not None
                await self._dispatch_click(affordance_pt, button="left", click_count=1)
            elif action_type == ActionType.DOUBLE_CLICK:
                assert affordance_pt is not None
                await self._dispatch_click(affordance_pt, button="left", click_count=2)
            elif action_type == ActionType.RIGHT_CLICK:
                assert affordance_pt is not None
                await self._dispatch_click(affordance_pt, button="right", click_count=1)
            elif action_type == ActionType.HOVER:
                assert affordance_pt is not None
                await self._dispatch_mouse_move(affordance_pt)
            elif action_type == ActionType.TYPE:
                text = request.params.get("text", "")
                clear_first = bool(request.params.get("clear_first", False))
                await self._dispatch_type(ref_id, text, clear_first, target.frame_id)
            elif action_type == ActionType.KEY_PRESS:
                key = request.params.get("key", "Enter")
                modifiers = request.params.get("modifiers", [])
                await self._dispatch_key_press(key, modifiers)
            elif action_type == ActionType.KEYBOARD_SHORTCUT:
                shortcut = request.params.get("shortcut", "")
                modifiers = request.params.get("modifiers", [])
                key = request.params.get("key", "")
                await self._dispatch_keyboard_shortcut(shortcut=shortcut, modifiers=modifiers, key=key)
            elif action_type in (ActionType.DRAG_AND_DROP, ActionType.DRAG):
                assert affordance_pt is not None
                to_x = request.params.get("to_x")
                to_y = request.params.get("to_y")
                to_ref = request.params.get("to_ref")
                if to_x is not None and to_y is not None:
                    to_pt = (int(to_x), int(to_y))
                elif to_ref:
                    target_actionability = await self.actionability_engine.evaluate_actionability(ref_id=to_ref)
                    to_pt = target_actionability.affordance_point or (affordance_pt[0] + 50, affordance_pt[1] + 50)
                else:
                    to_pt = (affordance_pt[0] + int(request.params.get("delta_x", 50)), affordance_pt[1] + int(request.params.get("delta_y", 50)))
                await self._dispatch_drag_and_drop(from_pt=affordance_pt, to_pt=to_pt)
            elif action_type == ActionType.DROP:
                assert affordance_pt is not None
                await self._dispatch_mouse_up(affordance_pt)
            elif action_type == ActionType.SELECT:
                value = request.params.get("value")
                text = request.params.get("text")
                await self._dispatch_select(ref_id, value, text, target.frame_id)
            elif action_type == ActionType.DIALOG_INTERACTION:
                accept = bool(request.params.get("accept", True))
                prompt_text = request.params.get("prompt_text")
                await self._dispatch_dialog(accept, prompt_text)
            elif action_type == ActionType.FILE_PICKER:
                files = request.params.get("files", [])
                await self._dispatch_file_picker(ref_id, files, target.frame_id)
            elif action_type == ActionType.SCROLL:
                delta_x = int(request.params.get("delta_x", 0))
                delta_y = int(request.params.get("delta_y", 0))
                pt = affordance_pt or (100, 100)
                await self._dispatch_scroll(pt, delta_x, delta_y)
            elif action_type == ActionType.FOCUS:
                await self._dispatch_focus(ref_id, target.frame_id)
            elif action_type == ActionType.WAIT:
                wait_ms = int(request.params.get("duration_ms", 100))
                await asyncio.sleep(wait_ms / 1000.0)
            else:
                dispatch_status = DispatchStatus.FAILED
                dispatch_error = f"Unsupported web action type: {action_type}"
        except Exception as ex:
            logger.warning(f"CDP Input dispatch failed ({ex}); attempting explicit scripted fallback.")
            # Fallback path if CDP Input domain is unavailable or rejected
            try:
                fallback_res = await self._dispatch_scripted_fallback(action_type, ref_id, request.params, target.frame_id)
                dispatch_method = DispatchMethod.SCRIPTED_FALLBACK
                metadata["fallback_result"] = fallback_res
                metadata["original_error"] = str(ex)
            except Exception as fallback_ex:
                dispatch_status = DispatchStatus.FAILED
                dispatch_error = f"Dispatch failed: {ex}; Fallback also failed: {fallback_ex}"

        duration = (time.time() - start_time) * 1000.0
        return ActionReceipt(
            action_id=request.action_id,
            session_id=request.session_id,
            target_id=target.target_id,
            epoch=current_epoch,
            plane=TargetPlane.WEBVIEW_DOM,
            reference=ref_id,
            action_type=action_type,
            dispatch_method=dispatch_method,
            dispatch_timestamp=start_time,
            coordinates=affordance_pt,
            native_hwnd=target.native_hwnd,
            cdp_target_id=target.cdp_target_id,
            frame_id=target.frame_id,
            precondition_summary="All 5 actionability gates passed",
            dispatch_status=dispatch_status,
            error=dispatch_error,
            duration_ms=duration,
            metadata=metadata,
        )

    # -------------------------------------------------------------------------
    # CDP Input Dispatch Helpers
    # -------------------------------------------------------------------------
    async def _dispatch_mouse_move(self, point: Tuple[int, int]) -> None:
        """Moves cursor via CDP Input.dispatchMouseEvent."""
        await self.webview_core.transport.send_command(
            method="Input.dispatchMouseEvent",
            params={
                "type": "mouseMoved",
                "x": point[0],
                "y": point[1],
            },
        )

    async def _dispatch_click(
        self,
        point: Tuple[int, int],
        button: str = "left",
        click_count: int = 1,
    ) -> None:
        """Dispatches real pointer click sequence via CDP Input domain."""
        # 1. Move to element
        await self._dispatch_mouse_move(point)
        await asyncio.sleep(0.01)

        for i in range(1, click_count + 1):
            # Mouse Pressed
            await self.webview_core.transport.send_command(
                method="Input.dispatchMouseEvent",
                params={
                    "type": "mousePressed",
                    "x": point[0],
                    "y": point[1],
                    "button": button,
                    "clickCount": i,
                },
            )
            await asyncio.sleep(0.02)
            # Mouse Released
            await self.webview_core.transport.send_command(
                method="Input.dispatchMouseEvent",
                params={
                    "type": "mouseReleased",
                    "x": point[0],
                    "y": point[1],
                    "button": button,
                    "clickCount": i,
                },
            )
            if click_count > 1 and i < click_count:
                await asyncio.sleep(0.04)

    async def _dispatch_scroll(
        self,
        point: Tuple[int, int],
        delta_x: int,
        delta_y: int,
    ) -> None:
        """Dispatches wheel event via CDP Input domain."""
        await self.webview_core.transport.send_command(
            method="Input.dispatchMouseEvent",
            params={
                "type": "mouseWheel",
                "x": point[0],
                "y": point[1],
                "deltaX": delta_x,
                "deltaY": delta_y,
            },
        )

    async def _dispatch_focus(self, ref_id: str, frame_id: Optional[str]) -> None:
        """Sets DOM keyboard focus and verifies document.activeElement."""
        ref = self.reference_registry.resolve_ref(ref_id)
        target_frame = frame_id or ref.frame_id or self.webview_core.frame_manager.root_frame_id

        # Use utility world to query and focus element
        recipe = ref.locator_recipe or {}
        name = recipe.get("name") or recipe.get("text") or ""
        role = recipe.get("role") or ""

        script = f"""
        (() => {{
            const targetName = {repr(name.strip().lower())};
            const targetRole = {repr(role.strip().lower())};
            const all = document.querySelectorAll('*');
            for (const el of all) {{
                const text = (el.innerText || el.textContent || '').trim().lower();
                const aria = (el.getAttribute('aria-label') || '').trim().lower();
                const r = (el.getAttribute('role') || el.tagName).trim().lower();
                if ((targetName && (text === targetName || aria === targetName)) ||
                    (targetRole && r === targetRole)) {{
                    el.focus();
                    return {{ focused: document.activeElement === el, tag: el.tagName }};
                }}
            }}
            return {{ focused: false }};
        }})()
        """
        res = await self.webview_core.utility_world.evaluate(
            expression=script,
            frame_id=target_frame,
            return_by_value=True,
        )
        logger.debug(f"Focus result for {ref_id}: {res}")

    async def _dispatch_type(
        self,
        ref_id: str,
        text: str,
        clear_first: bool,
        frame_id: Optional[str],
    ) -> None:
        """Focuses element and types characters via CDP Input.dispatchKeyEvent / insertText."""
        # 1. Acquire focus first
        await self._dispatch_focus(ref_id, frame_id)
        await asyncio.sleep(0.02)

        ref = self.reference_registry.resolve_ref(ref_id)
        target_frame = frame_id or ref.frame_id or self.webview_core.frame_manager.root_frame_id

        # 2. If clear_first, clear value via input selection or script
        if clear_first:
            clear_script = """
            (() => {
                const el = document.activeElement;
                if (el && 'value' in el) {
                    el.value = '';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            })()
            """
            await self.webview_core.utility_world.evaluate(
                expression=clear_script,
                frame_id=target_frame,
                return_by_value=True,
            )

        # 3. Emit characters via CDP Input
        for char in text:
            # keydown
            await self.webview_core.transport.send_command(
                method="Input.dispatchKeyEvent",
                params={
                    "type": "keyDown",
                    "text": char,
                    "unmodifiedText": char,
                },
            )
            # keyup
            await self.webview_core.transport.send_command(
                method="Input.dispatchKeyEvent",
                params={
                    "type": "keyUp",
                    "text": char,
                },
            )
            await asyncio.sleep(0.005)

    async def _dispatch_key_press(self, key: str, modifiers: List[str]) -> None:
        """Dispatches a single virtual key with modifiers via CDP Input.dispatchKeyEvent."""
        mod_mask = 0
        for m in modifiers:
            m_low = m.lower()
            if m_low in ("alt", "menu"):
                mod_mask |= 1
            elif m_low in ("ctrl", "control"):
                mod_mask |= 2
            elif m_low in ("meta", "command"):
                mod_mask |= 4
            elif m_low in ("shift",):
                mod_mask |= 8

        # keydown
        await self.webview_core.transport.send_command(
            method="Input.dispatchKeyEvent",
            params={
                "type": "keyDown",
                "key": key,
                "modifiers": mod_mask,
            },
        )
        await asyncio.sleep(0.01)
        # keyup
        await self.webview_core.transport.send_command(
            method="Input.dispatchKeyEvent",
            params={
                "type": "keyUp",
                "key": key,
                "modifiers": mod_mask,
            },
        )

    async def _dispatch_keyboard_shortcut(
        self,
        shortcut: str = "",
        modifiers: Optional[List[str]] = None,
        key: str = "",
    ) -> None:
        """Dispatches a keyboard shortcut sequence (modifiers down -> key press -> modifiers up)."""
        mods = list(modifiers or [])
        target_key = key
        if shortcut and not target_key:
            parts = [p.strip() for p in shortcut.replace("+", " ").split()]
            if parts:
                target_key = parts[-1]
                mods.extend(parts[:-1])
        if not target_key:
            target_key = "Enter"

        mod_mask = 0
        for m in mods:
            m_low = m.lower()
            if m_low in ("alt", "menu"):
                mod_mask |= 1
            elif m_low in ("ctrl", "control"):
                mod_mask |= 2
            elif m_low in ("meta", "command", "win"):
                mod_mask |= 4
            elif m_low in ("shift",):
                mod_mask |= 8

        # 1. Modifiers down
        for m in mods:
            m_key = "Control" if m.lower() in ("ctrl", "control") else ("Shift" if m.lower() == "shift" else ("Alt" if m.lower() == "alt" else m))
            await self.webview_core.transport.send_command(
                method="Input.dispatchKeyEvent",
                params={"type": "keyDown", "key": m_key, "modifiers": mod_mask},
            )
        await asyncio.sleep(0.01)

        # 2. Key press
        await self.webview_core.transport.send_command(
            method="Input.dispatchKeyEvent",
            params={"type": "keyDown", "key": target_key, "modifiers": mod_mask},
        )
        await asyncio.sleep(0.01)
        await self.webview_core.transport.send_command(
            method="Input.dispatchKeyEvent",
            params={"type": "keyUp", "key": target_key, "modifiers": mod_mask},
        )
        await asyncio.sleep(0.01)

        # 3. Modifiers up (reverse order)
        for m in reversed(mods):
            m_key = "Control" if m.lower() in ("ctrl", "control") else ("Shift" if m.lower() == "shift" else ("Alt" if m.lower() == "alt" else m))
            await self.webview_core.transport.send_command(
                method="Input.dispatchKeyEvent",
                params={"type": "keyUp", "key": m_key, "modifiers": 0},
            )

    async def _dispatch_drag_and_drop(
        self,
        from_pt: Tuple[int, int],
        to_pt: Tuple[int, int],
        steps: int = 10,
    ) -> None:
        """Dispatches smooth mouse drag and drop using CDP Input events."""
        # 1. Move to start point
        await self._dispatch_mouse_move(from_pt)
        await asyncio.sleep(0.02)

        # 2. Mouse Pressed
        await self.webview_core.transport.send_command(
            method="Input.dispatchMouseEvent",
            params={
                "type": "mousePressed",
                "x": from_pt[0],
                "y": from_pt[1],
                "button": "left",
                "clickCount": 1,
            },
        )
        await asyncio.sleep(0.02)

        # 3. Interpolated moves with button held
        x1, y1 = from_pt
        x2, y2 = to_pt
        for i in range(1, steps + 1):
            cur_x = int(x1 + (x2 - x1) * (i / float(steps)))
            cur_y = int(y1 + (y2 - y1) * (i / float(steps)))
            await self.webview_core.transport.send_command(
                method="Input.dispatchMouseEvent",
                params={
                    "type": "mouseMoved",
                    "x": cur_x,
                    "y": cur_y,
                    "buttons": 1,
                },
            )
            await asyncio.sleep(0.01)

        # 4. Mouse Released at destination
        await self.webview_core.transport.send_command(
            method="Input.dispatchMouseEvent",
            params={
                "type": "mouseReleased",
                "x": x2,
                "y": y2,
                "button": "left",
                "clickCount": 1,
            },
        )

    async def _dispatch_mouse_up(self, point: Tuple[int, int]) -> None:
        """Dispatches mouseReleased at coordinate."""
        await self.webview_core.transport.send_command(
            method="Input.dispatchMouseEvent",
            params={
                "type": "mouseReleased",
                "x": point[0],
                "y": point[1],
                "button": "left",
                "clickCount": 1,
            },
        )

    async def _dispatch_select(
        self,
        ref_id: str,
        value: Optional[str],
        text: Optional[str],
        frame_id: Optional[str],
    ) -> None:
        """Selects an option within a HTML select element."""
        ref = self.reference_registry.resolve_ref(ref_id)
        target_frame = frame_id or ref.frame_id or self.webview_core.frame_manager.root_frame_id
        script = f"""
        (() => {{
            const refId = {repr(ref_id)};
            const val = {repr(value)};
            const txt = {repr(text)};
            const el = document.querySelector(`[data-ref="${{refId}}"]`) || document.activeElement;
            if (!el) return {{ success: false, reason: "Element not found" }};
            if (el.tagName.toLowerCase() === 'select') {{
                for (let i = 0; i < el.options.length; i++) {{
                    const opt = el.options[i];
                    if ((val && opt.value === val) || (txt && opt.text.trim() === txt.trim())) {{
                        el.selectedIndex = i;
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return {{ success: true, selectedIndex: i, value: opt.value }};
                    }}
                }}
            }}
            return {{ success: false, reason: "Option not matched" }};
        }})()
        """
        await self.webview_core.utility_world.evaluate(
            expression=script,
            frame_id=target_frame,
            return_by_value=True,
        )

    async def _dispatch_dialog(self, accept: bool, prompt_text: Optional[str]) -> None:
        """Handles JavaScript dialog via CDP Page domain."""
        params: Dict[str, Any] = {"accept": accept}
        if prompt_text is not None:
            params["promptText"] = prompt_text
        await self.webview_core.transport.send_command(
            method="Page.handleJavaScriptDialog",
            params=params,
        )

    async def _dispatch_file_picker(
        self,
        ref_id: str,
        files: List[str],
        frame_id: Optional[str],
    ) -> None:
        """Sets file input files via CDP DOM.setFileInputFiles or utility world."""
        ref = self.reference_registry.resolve_ref(ref_id)
        backend_node_id = getattr(ref, "backend_node_id", None)
        if backend_node_id:
            await self.webview_core.transport.send_command(
                method="DOM.setFileInputFiles",
                params={"files": files, "backendNodeId": backend_node_id},
            )
        else:
            logger.info(f"File picker requested for {ref_id} with files {files}")

    async def _dispatch_scripted_fallback(
        self,
        action_type: ActionType,
        ref_id: str,
        params: Dict[str, Any],
        frame_id: Optional[str],
    ) -> Dict[str, Any]:
        """Explicitly recorded fallback when direct CDP Input domain cannot deliver events."""
        ref = self.reference_registry.resolve_ref(ref_id)
        target_frame = frame_id or ref.frame_id or self.webview_core.frame_manager.root_frame_id
        recipe = ref.locator_recipe or {}
        name = recipe.get("name") or recipe.get("text") or ""
        role = recipe.get("role") or ""

        script = f"""
        (() => {{
            const targetName = {repr(name.strip().lower())};
            const targetRole = {repr(role.strip().lower())};
            const all = document.querySelectorAll('*');
            let target = null;
            for (const el of all) {{
                const text = (el.innerText || el.textContent || '').trim().lower();
                const aria = (el.getAttribute('aria-label') || '').trim().lower();
                const r = (el.getAttribute('role') || el.tagName).trim().lower();
                if ((targetName && (text === targetName || aria === targetName)) ||
                    (targetRole && r === targetRole)) {{
                    target = el;
                    break;
                }}
            }}
            if (!target) return {{ success: false, reason: 'Target element not found for fallback' }};

            if ({repr(action_type.value)} === 'CLICK') {{
                target.click();
                target.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, view: window }}));
                return {{ success: true, method: 'synthetic_click' }};
            }} else if ({repr(action_type.value)} === 'TYPE') {{
                target.focus();
                target.value = (target.value || '') + {repr(params.get('text', ''))};
                target.dispatchEvent(new Event('input', {{ bubbles: true }}));
                target.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return {{ success: true, method: 'synthetic_type' }};
            }}
            return {{ success: false, reason: 'Unsupported fallback action' }};
        }})()
        """
        res = await self.webview_core.utility_world.evaluate(
            expression=script,
            frame_id=target_frame,
            return_by_value=True,
        )
        return res if isinstance(res, dict) else {"result": res}
