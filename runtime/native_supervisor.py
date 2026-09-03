"""
Native OS Supervisor Foundation for Desktop WebView Reviewer.
Python-side authority for physical desktop truth, HWND validation, DWM extended frame bounds,
pre-flight responsiveness checks via SendMessageTimeout(WM_NULL), and modal dialog detection.
Grounded in SP-01 and SP-03 architecture decisions.
"""

from __future__ import annotations
import ctypes
from ctypes import wintypes
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

from runtime.references import Rect
from runtime.state import HealthState
from runtime.errors import TargetHungException, WindowCloakedException, InvalidTargetException

logger = logging.getLogger("desktop_webview.native_supervisor")

# Win32 Constants
WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
SMTO_NORMAL = 0x0000

DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9

PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0


# Win32 Structures
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

    def to_rect(self) -> Rect:
        return Rect(
            x=self.left,
            y=self.top,
            width=max(0, self.right - self.left),
            height=max(0, self.bottom - self.top),
        )


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


@dataclass
class WindowForensicReport:
    """Forensic report capturing physical desktop truth for a window handle."""
    hwnd: int
    pid: int
    title: str
    class_name: str
    bounds: Rect                   # Canonical physical bounds via DWMWA_EXTENDED_FRAME_BOUNDS
    raw_window_rect: Rect          # Raw GetWindowRect (diagnostic; includes invisible drop-shadows)
    client_rect: Rect              # Client bounds
    client_origin_screen: Tuple[int, int] # Screen origin of client (0,0)
    is_valid_window: bool
    is_visible: bool
    is_iconic: bool                # Minimized
    is_cloaked: bool               # DWM virtual desktop / hidden
    is_hung: bool                  # SendMessageTimeout(WM_NULL) check failed
    health_state: HealthState
    dpi_scaling: float             # Per-Monitor V2 scaling factor (e.g. 1.25)
    shadow_margins: Dict[str, int] # Invisible drop shadow margins: left, top, right, bottom

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd),
            "pid": self.pid,
            "title": self.title,
            "class_name": self.class_name,
            "bounds": self.bounds.to_dict(),
            "raw_window_rect": self.raw_window_rect.to_dict(),
            "client_rect": self.client_rect.to_dict(),
            "client_origin_screen": {"x": self.client_origin_screen[0], "y": self.client_origin_screen[1]},
            "is_valid_window": self.is_valid_window,
            "is_visible": self.is_visible,
            "is_iconic": self.is_iconic,
            "is_cloaked": self.is_cloaked,
            "is_hung": self.is_hung,
            "health_state": self.health_state.value,
            "dpi_scaling": self.dpi_scaling,
            "shadow_margins": self.shadow_margins,
        }


class NativeOSSupervisor:
    """
    Physical Desktop Truth Authority for Windows targets.
    Enforces DWM extended frame bounds and pre-flight SendMessageTimeout responsiveness checks.
    """

    @staticmethod
    def is_window_valid(hwnd: int) -> bool:
        """Verifies if an HWND is a currently valid operating system window."""
        if sys.platform != "win32":
            return True
        try:
            return bool(ctypes.windll.user32.IsWindow(hwnd))
        except Exception:
            return False

    @staticmethod
    def get_window_pid(hwnd: int) -> int:
        """Retrieves the owning Process ID for a given window handle."""
        if sys.platform != "win32":
            return 0
        try:
            user32 = ctypes.windll.user32
            pid_var = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_var))
            return int(pid_var.value)
        except Exception:
            return 0

    @classmethod
    def check_responsiveness(cls, hwnd: int, timeout_ms: int = 500) -> HealthState:
        """
        Executes pre-flight SendMessageTimeout(WM_NULL, SMTO_ABORTIFHUNG, timeout_ms).
        Returns HealthState.HEALTHY or HealthState.HUNG.
        Mandatory invariant: prevents native UIA queries from blocking on hung applications.
        """
        if sys.platform != "win32":
            return HealthState.HEALTHY

        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return HealthState.TERMINATED

        result = wintypes.DWORD(0)
        # SendMessageTimeoutW returns 0 on failure or timeout
        res = user32.SendMessageTimeoutW(
            hwnd,
            WM_NULL,
            0,
            0,
            SMTO_ABORTIFHUNG,
            timeout_ms,
            ctypes.byref(result),
        )
        if res == 0:
            err = ctypes.GetLastError()
            logger.warning(f"HWND {hex(hwnd)} failed SendMessageTimeout (err={err}) -> HUNG")
            return HealthState.HUNG

        return HealthState.HEALTHY

    @classmethod
    def get_canonical_window_bounds(cls, hwnd: int) -> Tuple[Rect, Rect, Dict[str, int]]:
        """
        Canonical Window Boundary Authority (SP-03):
        Returns:
            canonical_bounds: Physical display pixels via DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS).
            raw_rect: Raw GetWindowRect (diagnostic).
            shadow_margins: Delta between raw rect and DWM frame bounds.
        """
        if sys.platform != "win32":
            default_rect = Rect(100, 100, 800, 600)
            return default_rect, default_rect, {"left": 0, "top": 0, "right": 0, "bottom": 0}

        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

        # 1. Raw GetWindowRect (includes invisible drop shadows)
        raw_struct = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(raw_struct))
        raw_rect = raw_struct.to_rect()

        # 2. Authoritative DWM extended frame bounds (actual visual pixels on screen)
        dwm_struct = RECT()
        res = dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(dwm_struct),
            ctypes.sizeof(RECT),
        )

        if res == 0 and dwm_struct.right > dwm_struct.left and dwm_struct.bottom > dwm_struct.top:
            canonical_rect = dwm_struct.to_rect()
        else:
            # Fallback to raw rect if DWM call is unavailable
            canonical_rect = raw_rect

        shadow_margins = {
            "left": canonical_rect.left - raw_rect.left,
            "top": canonical_rect.top - raw_rect.top,
            "right": raw_rect.right - canonical_rect.right,
            "bottom": raw_rect.bottom - canonical_rect.bottom,
        }

        return canonical_rect, raw_rect, shadow_margins

    @classmethod
    def inspect_window(cls, hwnd: int, check_health: bool = True) -> WindowForensicReport:
        """
        Performs comprehensive physical inspection of a target window.
        Inspects DWM bounds, client rect, cloaking, DPI scaling, and responsiveness.
        """
        if sys.platform != "win32":
            return WindowForensicReport(
                hwnd=hwnd,
                pid=0,
                title="Mock Window",
                class_name="MockClass",
                bounds=Rect(100, 100, 800, 600),
                raw_window_rect=Rect(100, 100, 800, 600),
                client_rect=Rect(0, 0, 800, 600),
                client_origin_screen=(100, 100),
                is_valid_window=True,
                is_visible=True,
                is_iconic=False,
                is_cloaked=False,
                is_hung=False,
                health_state=HealthState.HEALTHY,
                dpi_scaling=1.0,
                shadow_margins={"left": 0, "top": 0, "right": 0, "bottom": 0},
            )

        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

        if not user32.IsWindow(hwnd):
            raise InvalidTargetException(f"Invalid window handle HWND: {hex(hwnd)} (or {hwnd})")

        pid = cls.get_window_pid(hwnd)
        is_visible = bool(user32.IsWindowVisible(hwnd))
        is_iconic = bool(user32.IsIconic(hwnd))

        # DWM cloaked state
        cloaked_val = wintypes.DWORD(0)
        try:
            res = dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked_val), ctypes.sizeof(cloaked_val)
            )
            is_cloaked = (res == 0 and cloaked_val.value != 0)
        except Exception:
            is_cloaked = False

        # Canonical and raw bounds
        bounds, raw_rect, shadow_margins = cls.get_canonical_window_bounds(hwnd)

        # Client rect
        client_struct = RECT()
        user32.GetClientRect(hwnd, ctypes.byref(client_struct))
        client_rect = client_struct.to_rect()

        # Client to screen origin
        origin_pt = POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin_pt))
        client_origin = (origin_pt.x, origin_pt.y)

        # Title and class name
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        class_name = cls_buf.value

        # DPI scaling
        dpi = 96
        try:
            if hasattr(user32, "GetDpiForWindow"):
                d = user32.GetDpiForWindow(hwnd)
                if d > 0:
                    dpi = d
        except Exception:
            dpi = 96
        dpi_scaling = round(dpi / 96.0, 3)

        # Responsiveness check
        health = HealthState.HEALTHY
        is_hung = False
        if check_health:
            health = cls.check_responsiveness(hwnd, timeout_ms=500)
            is_hung = (health == HealthState.HUNG)

        return WindowForensicReport(
            hwnd=hwnd,
            pid=pid,
            title=title,
            class_name=class_name,
            bounds=bounds,
            raw_window_rect=raw_rect,
            client_rect=client_rect,
            client_origin_screen=client_origin,
            is_valid_window=True,
            is_visible=is_visible,
            is_iconic=is_iconic,
            is_cloaked=is_cloaked,
            is_hung=is_hung,
            health_state=health,
            dpi_scaling=dpi_scaling,
            shadow_margins=shadow_margins,
        )

    @classmethod
    def set_foreground(cls, hwnd: int) -> bool:
        """Brings the window to top and restores if minimized."""
        if sys.platform != "win32":
            return True

        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            time.sleep(0.05)

        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        return True

    @classmethod
    def find_modal_dialogs(cls, target_pid: int) -> List[Dict[str, Any]]:
        """
        Scans desktop for Win32 modal dialogs (#32770) owned by the target PID tree.
        Detects blocking dialogs that could impede automation.
        """
        if sys.platform != "win32":
            return []

        user32 = ctypes.windll.user32
        modals: List[Dict[str, Any]] = []

        def enum_cb(hwnd, lparam):
            if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
                return True

            pid_var = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_var))
            if pid_var.value == target_pid:
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buf, 256)
                c_name = cls_buf.value

                if c_name == "#32770":  # Standard Win32 Dialog Box Class
                    length = user32.GetWindowTextLengthW(hwnd)
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value

                    bounds, _, _ = cls.get_canonical_window_bounds(hwnd)
                    modals.append({
                        "hwnd": hwnd,
                        "pid": target_pid,
                        "title": title,
                        "class_name": c_name,
                        "bounds": bounds.to_dict(),
                    })
            return True

        cb = WNDENUMPROC(enum_cb)
        user32.EnumWindows(cb, 0)
        return modals
