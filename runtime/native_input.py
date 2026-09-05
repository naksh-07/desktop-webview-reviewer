"""
Authoritative Native Input Dispatch Subsystem for Desktop WebView Reviewer (Architecture H).
Single centralized authority for Windows SendInput dispatch, coordinate normalization,
timing control, error handling, and physical input validation.
Enforces coordinate conversion via CoordinateTransformer.
"""

from __future__ import annotations
import asyncio
import ctypes
from ctypes import wintypes
import logging
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any

import runtime.win32 as w32
from runtime.coordinate_transform import CoordinateTransformer, VirtualScreenBounds
from runtime.errors import NativeBridgeException

logger = logging.getLogger("desktop_webview.native_input")


class MouseButton(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    MIDDLE = "MIDDLE"


class KeyAction(str, Enum):
    DOWN = "DOWN"
    UP = "UP"
    PRESS = "PRESS"


@dataclass(frozen=True)
class DispatchedInputRecord:
    """Forensic record of physical input dispatched to the OS message pump."""
    input_type: str               # "MOUSE", "KEYBOARD", "TEXT", "SCROLL"
    coordinates: Optional[Tuple[int, int]] = None
    normalized_coordinates: Optional[Tuple[int, int]] = None
    button: Optional[str] = None
    key_code: Optional[int] = None
    key_name: Optional[str] = None
    text: Optional[str] = None
    scroll_delta: Optional[int] = None
    timestamp: float = field(default_factory=time.time)
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_type": self.input_type,
            "coordinates": list(self.coordinates) if self.coordinates else None,
            "normalized_coordinates": list(self.normalized_coordinates) if self.normalized_coordinates else None,
            "button": self.button,
            "key_code": self.key_code,
            "key_name": self.key_name,
            "text": self.text,
            "scroll_delta": self.scroll_delta,
            "timestamp": self.timestamp,
            "success": self.success,
            "error": self.error,
        }


# Mapping for common key names to Virtual Key codes
KEY_NAME_TO_VK: Dict[str, int] = {
    "enter": w32.VK_RETURN,
    "return": w32.VK_RETURN,
    "tab": w32.VK_TAB,
    "space": w32.VK_SPACE,
    "backspace": w32.VK_BACK,
    "escape": w32.VK_ESCAPE,
    "esc": w32.VK_ESCAPE,
    "delete": w32.VK_DELETE,
    "del": w32.VK_DELETE,
    "insert": w32.VK_INSERT,
    "home": w32.VK_HOME,
    "end": w32.VK_END,
    "pageup": w32.VK_PRIOR,
    "pagedown": w32.VK_NEXT,
    "left": w32.VK_LEFT,
    "up": w32.VK_UP,
    "right": w32.VK_RIGHT,
    "down": w32.VK_DOWN,
    "shift": w32.VK_SHIFT,
    "control": w32.VK_CONTROL,
    "ctrl": w32.VK_CONTROL,
    "alt": w32.VK_MENU,
    "menu": w32.VK_MENU,
    "capslock": w32.VK_CAPITAL,
    "f1": w32.VK_F1,
    "f2": w32.VK_F2,
    "f3": w32.VK_F3,
    "f4": w32.VK_F4,
    "f5": w32.VK_F5,
    "f6": w32.VK_F6,
    "f7": w32.VK_F7,
    "f8": w32.VK_F8,
    "f9": w32.VK_F9,
    "f10": w32.VK_F10,
    "f11": w32.VK_F11,
    "f12": w32.VK_F12,
}


class NativeInputDispatcher:
    """
    Centralized controller for Windows physical input dispatch.
    Emits raw OS inputs via Win32 SendInput or records mock dispatches.
    All coordinate conversions pass through canonical CoordinateTransformer.
    """

    def __init__(
        self,
        dry_run: bool = False,
        virtual_screen: Optional[VirtualScreenBounds] = None,
        event_delay_ms: float = 10.0,
    ):
        self.dry_run = dry_run
        self.virtual_screen = virtual_screen
        self.event_delay_ms = event_delay_ms
        self.history: List[DispatchedInputRecord] = []
        self._lock = asyncio.Lock()

    def _resolve_virtual_screen(self) -> VirtualScreenBounds:
        return self.virtual_screen or CoordinateTransformer.get_system_virtual_screen()

    # -------------------------------------------------------------------------
    # 1. Mouse Dispatch
    # -------------------------------------------------------------------------
    async def move_mouse(self, screen_x: int, screen_y: int) -> DispatchedInputRecord:
        """
        Moves the physical mouse cursor to (screen_x, screen_y) using SendInput MOUSEEVENTF_ABSOLUTE.
        """
        async with self._lock:
            v_screen = self._resolve_virtual_screen()
            norm_x, norm_y = CoordinateTransformer.screen_to_sendinput_normalized(
                screen_x, screen_y, v_screen
            )

            flags = w32.MOUSEEVENTF_MOVE | w32.MOUSEEVENTF_ABSOLUTE | w32.MOUSEEVENTF_VIRTUALDESK
            inp = w32.INPUT()
            inp.type = w32.INPUT_MOUSE
            inp.mi = w32.MOUSEINPUT(
                dx=norm_x,
                dy=norm_y,
                mouseData=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )

            err = None
            success = True
            if not self.dry_run and sys.platform == "win32" and w32.user32 is not None:
                try:
                    sent = w32.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(w32.INPUT))
                    if sent != 1:
                        err = f"SendInput failed: sent {sent} of 1 inputs"
                        success = False
                except Exception as ex:
                    err = str(ex)
                    success = False

            rec = DispatchedInputRecord(
                input_type="MOUSE_MOVE",
                coordinates=(screen_x, screen_y),
                normalized_coordinates=(norm_x, norm_y),
                success=success,
                error=err,
            )
            self.history.append(rec)
            if self.event_delay_ms > 0:
                await asyncio.sleep(self.event_delay_ms / 1000.0)
            return rec

    async def click(
        self,
        screen_x: int,
        screen_y: int,
        button: MouseButton = MouseButton.LEFT,
        click_count: int = 1,
    ) -> List[DispatchedInputRecord]:
        """
        Moves mouse to target and clicks button click_count times (1=click, 2=double-click).
        """
        results: List[DispatchedInputRecord] = []
        # First move cursor
        move_rec = await self.move_mouse(screen_x, screen_y)
        results.append(move_rec)

        down_flag, up_flag = self._get_mouse_flags_for_button(button)
        v_screen = self._resolve_virtual_screen()
        norm_x, norm_y = CoordinateTransformer.screen_to_sendinput_normalized(
            screen_x, screen_y, v_screen
        )

        for i in range(click_count):
            # Mouse DOWN
            inp_down = w32.INPUT()
            inp_down.type = w32.INPUT_MOUSE
            inp_down.mi = w32.MOUSEINPUT(
                dx=norm_x,
                dy=norm_y,
                mouseData=0,
                dwFlags=down_flag | w32.MOUSEEVENTF_ABSOLUTE | w32.MOUSEEVENTF_VIRTUALDESK,
                time=0,
                dwExtraInfo=0,
            )

            # Mouse UP
            inp_up = w32.INPUT()
            inp_up.type = w32.INPUT_MOUSE
            inp_up.mi = w32.MOUSEINPUT(
                dx=norm_x,
                dy=norm_y,
                mouseData=0,
                dwFlags=up_flag | w32.MOUSEEVENTF_ABSOLUTE | w32.MOUSEEVENTF_VIRTUALDESK,
                time=0,
                dwExtraInfo=0,
            )

            async with self._lock:
                err = None
                success = True
                if not self.dry_run and sys.platform == "win32" and w32.user32 is not None:
                    try:
                        inputs_arr = (w32.INPUT * 2)(inp_down, inp_up)
                        sent = w32.user32.SendInput(2, inputs_arr, ctypes.sizeof(w32.INPUT))
                        if sent != 2:
                            err = f"SendInput click #{i+1} failed: sent {sent} of 2 inputs"
                            success = False
                    except Exception as ex:
                        err = str(ex)
                        success = False

                rec = DispatchedInputRecord(
                    input_type="MOUSE_CLICK",
                    coordinates=(screen_x, screen_y),
                    normalized_coordinates=(norm_x, norm_y),
                    button=button.value,
                    success=success,
                    error=err,
                )
                self.history.append(rec)
                results.append(rec)

            if click_count > 1 and i < click_count - 1:
                # Inter-click delay for double-click registration (typically 50ms)
                await asyncio.sleep(0.05)

        if self.event_delay_ms > 0:
            await asyncio.sleep(self.event_delay_ms / 1000.0)
        return results

    async def double_click(
        self,
        screen_x: int,
        screen_y: int,
        button: MouseButton = MouseButton.LEFT,
    ) -> List[DispatchedInputRecord]:
        """Dispatches a rapid double-click sequence at (screen_x, screen_y)."""
        return await self.click(screen_x, screen_y, button=button, click_count=2)

    async def right_click(
        self,
        screen_x: int,
        screen_y: int,
    ) -> List[DispatchedInputRecord]:
        """Dispatches a context menu right-click at (screen_x, screen_y)."""
        return await self.click(screen_x, screen_y, button=MouseButton.RIGHT, click_count=1)

    async def hover(
        self,
        screen_x: int,
        screen_y: int,
        settle_ms: int = 100,
    ) -> List[DispatchedInputRecord]:
        """Moves cursor to (screen_x, screen_y) and settles for hover triggers."""
        rec = await self.move_mouse(screen_x, screen_y)
        if settle_ms > 0:
            await asyncio.sleep(settle_ms / 1000.0)
        return [rec]

    async def drag_and_drop(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        steps: int = 10,
        delay_between_steps_ms: int = 20,
    ) -> List[DispatchedInputRecord]:
        """
        Dispatches smooth mouse drag-and-drop from (start_x, start_y) to (end_x, end_y).
        Linear interpolation across steps with mouse down held throughout.
        """
        results: List[DispatchedInputRecord] = []
        v_screen = self._resolve_virtual_screen()

        # 1. Move to start position
        move_start = await self.move_mouse(start_x, start_y)
        results.append(move_start)

        # 2. Mouse DOWN at start
        norm_start_x, norm_start_y = CoordinateTransformer.screen_to_sendinput_normalized(
            start_x, start_y, v_screen
        )
        inp_down = w32.INPUT()
        inp_down.type = w32.INPUT_MOUSE
        inp_down.mi = w32.MOUSEINPUT(
            dx=norm_start_x,
            dy=norm_start_y,
            mouseData=0,
            dwFlags=w32.MOUSEEVENTF_LEFTDOWN | w32.MOUSEEVENTF_ABSOLUTE | w32.MOUSEEVENTF_VIRTUALDESK,
            time=0,
            dwExtraInfo=0,
        )

        async with self._lock:
            err = None
            success = True
            if not self.dry_run and sys.platform == "win32" and w32.user32 is not None:
                try:
                    sent = w32.user32.SendInput(1, (w32.INPUT * 1)(inp_down), ctypes.sizeof(w32.INPUT))
                    if sent != 1:
                        err = f"SendInput drag start failed: sent {sent} of 1"
                        success = False
                except Exception as ex:
                    err = str(ex)
                    success = False
            rec_down = DispatchedInputRecord(
                input_type="MOUSE_DRAG_START",
                coordinates=(start_x, start_y),
                normalized_coordinates=(norm_start_x, norm_start_y),
                button=MouseButton.LEFT.value,
                success=success,
                error=err,
            )
            self.history.append(rec_down)
            results.append(rec_down)

        # 3. Intermediate interpolated move steps
        total_steps = max(1, steps)
        for i in range(1, total_steps + 1):
            t = i / total_steps
            curr_x = round(start_x + (end_x - start_x) * t)
            curr_y = round(start_y + (end_y - start_y) * t)
            norm_curr_x, norm_curr_y = CoordinateTransformer.screen_to_sendinput_normalized(
                curr_x, curr_y, v_screen
            )

            inp_move = w32.INPUT()
            inp_move.type = w32.INPUT_MOUSE
            inp_move.mi = w32.MOUSEINPUT(
                dx=norm_curr_x,
                dy=norm_curr_y,
                mouseData=0,
                dwFlags=w32.MOUSEEVENTF_MOVE | w32.MOUSEEVENTF_ABSOLUTE | w32.MOUSEEVENTF_VIRTUALDESK,
                time=0,
                dwExtraInfo=0,
            )
            async with self._lock:
                err = None
                success = True
                if not self.dry_run and sys.platform == "win32" and w32.user32 is not None:
                    try:
                        w32.user32.SendInput(1, (w32.INPUT * 1)(inp_move), ctypes.sizeof(w32.INPUT))
                    except Exception as ex:
                        err = str(ex)
                        success = False
                rec_move = DispatchedInputRecord(
                    input_type="MOUSE_DRAG_STEP",
                    coordinates=(curr_x, curr_y),
                    normalized_coordinates=(norm_curr_x, norm_curr_y),
                    button=MouseButton.LEFT.value,
                    success=success,
                    error=err,
                )
                self.history.append(rec_move)
                results.append(rec_move)

            if delay_between_steps_ms > 0:
                await asyncio.sleep(delay_between_steps_ms / 1000.0)

        # 4. Mouse UP at destination
        norm_end_x, norm_end_y = CoordinateTransformer.screen_to_sendinput_normalized(
            end_x, end_y, v_screen
        )
        inp_up = w32.INPUT()
        inp_up.type = w32.INPUT_MOUSE
        inp_up.mi = w32.MOUSEINPUT(
            dx=norm_end_x,
            dy=norm_end_y,
            mouseData=0,
            dwFlags=w32.MOUSEEVENTF_LEFTUP | w32.MOUSEEVENTF_ABSOLUTE | w32.MOUSEEVENTF_VIRTUALDESK,
            time=0,
            dwExtraInfo=0,
        )
        async with self._lock:
            err = None
            success = True
            if not self.dry_run and sys.platform == "win32" and w32.user32 is not None:
                try:
                    sent = w32.user32.SendInput(1, (w32.INPUT * 1)(inp_up), ctypes.sizeof(w32.INPUT))
                    if sent != 1:
                        err = f"SendInput drop failed: sent {sent} of 1"
                        success = False
                except Exception as ex:
                    err = str(ex)
                    success = False
            rec_up = DispatchedInputRecord(
                input_type="MOUSE_DROP",
                coordinates=(end_x, end_y),
                normalized_coordinates=(norm_end_x, norm_end_y),
                button=MouseButton.LEFT.value,
                success=success,
                error=err,
            )
            self.history.append(rec_up)
            results.append(rec_up)

        return results

    async def scroll(
        self,
        screen_x: int,
        screen_y: int,
        delta_y: int = 0,
        delta_x: int = 0,
    ) -> List[DispatchedInputRecord]:
        """
        Dispatches vertical and/or horizontal mouse wheel scroll at (screen_x, screen_y).
        """
        results: List[DispatchedInputRecord] = []
        move_rec = await self.move_mouse(screen_x, screen_y)
        results.append(move_rec)

        v_screen = self._resolve_virtual_screen()
        norm_x, norm_y = CoordinateTransformer.screen_to_sendinput_normalized(
            screen_x, screen_y, v_screen
        )

        inputs: List[w32.INPUT] = []
        if delta_y != 0:
            inp_v = w32.INPUT()
            inp_v.type = w32.INPUT_MOUSE
            inp_v.mi = w32.MOUSEINPUT(
                dx=norm_x,
                dy=norm_y,
                mouseData=delta_y,
                dwFlags=w32.MOUSEEVENTF_WHEEL | w32.MOUSEEVENTF_ABSOLUTE | w32.MOUSEEVENTF_VIRTUALDESK,
                time=0,
                dwExtraInfo=0,
            )
            inputs.append(inp_v)

        if delta_x != 0:
            inp_h = w32.INPUT()
            inp_h.type = w32.INPUT_MOUSE
            inp_h.mi = w32.MOUSEINPUT(
                dx=norm_x,
                dy=norm_y,
                mouseData=delta_x,
                dwFlags=w32.MOUSEEVENTF_HWHEEL | w32.MOUSEEVENTF_ABSOLUTE | w32.MOUSEEVENTF_VIRTUALDESK,
                time=0,
                dwExtraInfo=0,
            )
            inputs.append(inp_h)

        if inputs:
            async with self._lock:
                err = None
                success = True
                if not self.dry_run and sys.platform == "win32" and w32.user32 is not None:
                    try:
                        n = len(inputs)
                        arr = (w32.INPUT * n)(*inputs)
                        sent = w32.user32.SendInput(n, arr, ctypes.sizeof(w32.INPUT))
                        if sent != n:
                            err = f"SendInput scroll failed: sent {sent} of {n}"
                            success = False
                    except Exception as ex:
                        err = str(ex)
                        success = False

                rec = DispatchedInputRecord(
                    input_type="MOUSE_SCROLL",
                    coordinates=(screen_x, screen_y),
                    normalized_coordinates=(norm_x, norm_y),
                    scroll_delta=delta_y if delta_y != 0 else delta_x,
                    success=success,
                    error=err,
                )
                self.history.append(rec)
                results.append(rec)

        if self.event_delay_ms > 0:
            await asyncio.sleep(self.event_delay_ms / 1000.0)
        return results

    # -------------------------------------------------------------------------
    # 2. Keyboard Dispatch
    # -------------------------------------------------------------------------
    async def press_key(
        self,
        key: str,
        modifiers: Optional[List[str]] = None,
    ) -> List[DispatchedInputRecord]:
        """
        Presses a virtual key with optional modifier keys (e.g. key='s', modifiers=['ctrl']).
        """
        results: List[DispatchedInputRecord] = []
        mods = [m.lower() for m in (modifiers or [])]

        mod_vks: List[int] = []
        for mod in mods:
            if mod in ("ctrl", "control"):
                mod_vks.append(w32.VK_CONTROL)
            elif mod in ("shift",):
                mod_vks.append(w32.VK_SHIFT)
            elif mod in ("alt", "menu"):
                mod_vks.append(w32.VK_MENU)
            elif mod in ("win", "lwin", "meta"):
                mod_vks.append(w32.VK_LWIN)

        target_vk = self._resolve_vk(key)

        inputs: List[w32.INPUT] = []
        # 1. Modifiers DOWN
        for m_vk in mod_vks:
            inp = w32.INPUT()
            inp.type = w32.INPUT_KEYBOARD
            inp.ki = w32.KEYBDINPUT(wVk=m_vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
            inputs.append(inp)

        # 2. Target Key DOWN
        inp_target_down = w32.INPUT()
        inp_target_down.type = w32.INPUT_KEYBOARD
        inp_target_down.ki = w32.KEYBDINPUT(wVk=target_vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
        inputs.append(inp_target_down)

        # 3. Target Key UP
        inp_target_up = w32.INPUT()
        inp_target_up.type = w32.INPUT_KEYBOARD
        inp_target_up.ki = w32.KEYBDINPUT(wVk=target_vk, wScan=0, dwFlags=w32.KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
        inputs.append(inp_target_up)

        # 4. Modifiers UP (reverse order)
        for m_vk in reversed(mod_vks):
            inp = w32.INPUT()
            inp.type = w32.INPUT_KEYBOARD
            inp.ki = w32.KEYBDINPUT(wVk=m_vk, wScan=0, dwFlags=w32.KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
            inputs.append(inp)

        async with self._lock:
            err = None
            success = True
            if not self.dry_run and sys.platform == "win32" and w32.user32 is not None:
                try:
                    n = len(inputs)
                    arr = (w32.INPUT * n)(*inputs)
                    sent = w32.user32.SendInput(n, arr, ctypes.sizeof(w32.INPUT))
                    if sent != n:
                        err = f"SendInput press_key failed: sent {sent} of {n}"
                        success = False
                except Exception as ex:
                    err = str(ex)
                    success = False

            for mod, m_vk in zip(mods, mod_vks):
                rec_mod = DispatchedInputRecord(
                    input_type="KEYBOARD",
                    key_code=m_vk,
                    key_name=mod,
                    success=success,
                    error=err,
                )
                self.history.append(rec_mod)
                results.append(rec_mod)

            rec = DispatchedInputRecord(
                input_type="KEYBOARD",
                key_code=target_vk,
                key_name=key,
                success=success,
                error=err,
            )
            self.history.append(rec)
            results.append(rec)

        if self.event_delay_ms > 0:
            await asyncio.sleep(self.event_delay_ms / 1000.0)
        return results

    async def type_text(self, text: str) -> List[DispatchedInputRecord]:
        """
        Types Unicode text via SendInput using KEYEVENTF_UNICODE for high-fidelity character delivery.
        """
        results: List[DispatchedInputRecord] = []
        if not text:
            return results

        inputs: List[w32.INPUT] = []
        for ch in text:
            code = ord(ch)
            # Char DOWN
            inp_down = w32.INPUT()
            inp_down.type = w32.INPUT_KEYBOARD
            inp_down.ki = w32.KEYBDINPUT(
                wVk=0,
                wScan=code,
                dwFlags=w32.KEYEVENTF_UNICODE,
                time=0,
                dwExtraInfo=0,
            )
            inputs.append(inp_down)

            # Char UP
            inp_up = w32.INPUT()
            inp_up.type = w32.INPUT_KEYBOARD
            inp_up.ki = w32.KEYBDINPUT(
                wVk=0,
                wScan=code,
                dwFlags=w32.KEYEVENTF_UNICODE | w32.KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=0,
            )
            inputs.append(inp_up)

        async with self._lock:
            err = None
            success = True
            if not self.dry_run and sys.platform == "win32" and w32.user32 is not None:
                try:
                    n = len(inputs)
                    arr = (w32.INPUT * n)(*inputs)
                    sent = w32.user32.SendInput(n, arr, ctypes.sizeof(w32.INPUT))
                    if sent != n:
                        err = f"SendInput type_text failed: sent {sent} of {n}"
                        success = False
                except Exception as ex:
                    err = str(ex)
                    success = False

            for ch in text:
                rec = DispatchedInputRecord(
                    input_type="KEYBOARD",
                    key_code=ord(ch),
                    text=ch,
                    success=success,
                    error=err,
                )
                self.history.append(rec)
                results.append(rec)

        if self.event_delay_ms > 0:
            await asyncio.sleep(self.event_delay_ms / 1000.0)
        return results

    # -------------------------------------------------------------------------
    # 3. Helpers
    # -------------------------------------------------------------------------
    def _get_mouse_flags_for_button(self, button: MouseButton) -> Tuple[int, int]:
        if button == MouseButton.RIGHT:
            return (w32.MOUSEEVENTF_RIGHTDOWN, w32.MOUSEEVENTF_RIGHTUP)
        elif button == MouseButton.MIDDLE:
            return (w32.MOUSEEVENTF_MIDDLEDOWN, w32.MOUSEEVENTF_MIDDLEUP)
        return (w32.MOUSEEVENTF_LEFTDOWN, w32.MOUSEEVENTF_LEFTUP)

    def _resolve_vk(self, key_name: str) -> int:
        norm = key_name.strip().lower()
        if norm in KEY_NAME_TO_VK:
            return KEY_NAME_TO_VK[norm]
        if len(norm) == 1:
            # Single character A-Z or 0-9
            ch = norm.upper()
            return ord(ch)
        return w32.VK_RETURN

    def clear_history(self) -> None:
        """Clears the history of dispatched inputs."""
        self.history.clear()
