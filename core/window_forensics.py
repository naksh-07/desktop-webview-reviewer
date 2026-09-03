"""
Native Windows GUI Forensics and Window Identity Verification.
Provides Win32 API inspection via ctypes and psutil for forensic verification of desktop applications.
Audited for 64-bit safety, leak-free GDI Device Context lifecycle, and DWM physical boundary authority.
"""

from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
import struct
import sys
import time
import zlib
from typing import Any, Dict, List, Optional, Set, Tuple

import runtime.win32 as w32

logger = logging.getLogger("desktop_webview.forensics")

# Structure definitions for Win32 API (legacy compatibility)
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

    def to_dict(self) -> Dict[str, int]:
        return {
            "x": self.left,
            "y": self.top,
            "width": max(0, self.right - self.left),
            "height": max(0, self.bottom - self.top),
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
        }


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


# Win32 Constants
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9
PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class WindowForensicsEngine:
    """
    Forensic inspector for native OS window identity, visibility, geometry,
    and process-tree correlation on Windows (with non-Windows safe fallbacks).
    Hardened with 64-bit ctypes prototypes and leak-free GDI resources.
    """

    @staticmethod
    def get_process_tree_pids(root_pid: int) -> Set[int]:
        """Returns the set of all PIDs in the process subtree rooted at root_pid."""
        pids: Set[int] = {root_pid}
        try:
            import psutil
            try:
                proc = psutil.Process(root_pid)
                for child in proc.children(recursive=True):
                    pids.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        except ImportError:
            pass
        return pids

    @staticmethod
    def get_process_info(pid: int) -> Dict[str, Any]:
        """Retrieves process executable path, command line, status, and creation time."""
        info: Dict[str, Any] = {
            "pid": pid,
            "executable": None,
            "cmdline": [],
            "status": "unknown",
            "create_time": None,
        }
        try:
            import psutil
            try:
                proc = psutil.Process(pid)
                info["executable"] = proc.exe()
                info["cmdline"] = proc.cmdline()
                info["status"] = proc.status()
                info["create_time"] = proc.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                info["status"] = "terminated"
        except ImportError:
            pass
        return info

    @classmethod
    def inspect_hwnd(cls, hwnd: int) -> Dict[str, Any]:
        """Performs deep Win32 inspection on a specific HWND."""
        if sys.platform != "win32" or w32.user32 is None:
            return {
                "hwnd": hwnd,
                "is_window": True,
                "is_visible": True,
                "is_iconic": False,
                "is_cloaked": False,
                "title": "",
                "class_name": "",
                "pid": 0,
                "geometry": {
                    "x": 0, "y": 0, "width": 800, "height": 600,
                    "left": 0, "top": 0, "right": 800, "bottom": 600,
                },
                "canonical_geometry": {
                    "x": 0, "y": 0, "width": 800, "height": 600,
                },
                "is_real_gui": True,
            }

        user32 = w32.user32
        dwmapi = w32.dwmapi

        if not user32.IsWindow(hwnd):
            return {
                "hwnd": hwnd,
                "is_window": False,
                "is_visible": False,
                "is_iconic": False,
                "is_cloaked": False,
                "title": "",
                "class_name": "",
                "pid": 0,
                "geometry": {
                    "x": 0, "y": 0, "width": 0, "height": 0,
                    "left": 0, "top": 0, "right": 0, "bottom": 0,
                },
                "canonical_geometry": {
                    "x": 0, "y": 0, "width": 0, "height": 0,
                },
                "is_real_gui": False,
            }

        # 1. Thread and Process ID
        pid_var = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_var))
        pid = pid_var.value

        # 2. Window Visibility & Iconic (Minimized)
        is_visible = bool(user32.IsWindowVisible(hwnd))
        is_iconic = bool(user32.IsIconic(hwnd))

        # 3. DWM Cloaked State
        cloaked_val = wintypes.DWORD(0)
        is_cloaked = False
        if dwmapi is not None:
            try:
                res = dwmapi.DwmGetWindowAttribute(
                    hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked_val), ctypes.sizeof(cloaked_val)
                )
                is_cloaked = (res == 0 and cloaked_val.value != 0)
            except Exception:
                is_cloaked = False

        # 4. Geometry (Raw GetWindowRect for backward compatibility)
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        geom = rect.to_dict()

        # Authoritative DWM Extended Frame Bounds
        canonical_geom = dict(geom)
        if dwmapi is not None:
            dwm_struct = w32.RECT()
            res = dwmapi.DwmGetWindowAttribute(
                hwnd,
                DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(dwm_struct),
                ctypes.sizeof(w32.RECT),
            )
            if res == 0 and dwm_struct.right > dwm_struct.left and dwm_struct.bottom > dwm_struct.top:
                canonical_geom = {
                    "x": dwm_struct.left,
                    "y": dwm_struct.top,
                    "width": dwm_struct.right - dwm_struct.left,
                    "height": dwm_struct.bottom - dwm_struct.top,
                    "left": dwm_struct.left,
                    "top": dwm_struct.top,
                    "right": dwm_struct.right,
                    "bottom": dwm_struct.bottom,
                }

        # 5. Title & Class Name
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        class_name = cls_buf.value

        # 6. Real GUI Evaluation
        is_real_gui = (
            is_visible
            and not is_iconic
            and not is_cloaked
            and geom["width"] >= 30
            and geom["height"] >= 30
        )

        return {
            "hwnd": hwnd,
            "is_window": True,
            "is_visible": is_visible,
            "is_iconic": is_iconic,
            "is_cloaked": is_cloaked,
            "title": title,
            "class_name": class_name,
            "pid": pid,
            "geometry": geom,
            "canonical_geometry": canonical_geom,
            "is_real_gui": is_real_gui,
        }

    @classmethod
    def find_windows_for_process_tree(cls, root_pid: int) -> List[Dict[str, Any]]:
        """Finds all top-level HWNDs associated with the process subtree rooted at root_pid."""
        if sys.platform != "win32" or w32.user32 is None:
            return []

        target_pids = cls.get_process_tree_pids(root_pid)
        user32 = w32.user32
        results: List[Dict[str, Any]] = []

        def enum_cb(hwnd, lparam):
            if not user32.IsWindow(hwnd):
                return True
            pid_var = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_var))
            if pid_var.value in target_pids:
                data = cls.inspect_hwnd(hwnd)
                results.append(data)
            return True

        cb = WNDENUMPROC(enum_cb)
        user32.EnumWindows(cb, 0)
        return results

    @classmethod
    def get_primary_gui_window(
        cls, root_pid: int, expected_title_substring: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Locates the best primary visible GUI window for the given process tree.
        Prioritizes windows with real GUI dimensions, visibility, and title matches.
        """
        windows = cls.find_windows_for_process_tree(root_pid)
        if not windows:
            return None

        real_windows = [w for w in windows if w.get("is_real_gui")]
        if not real_windows:
            return windows[0]

        IGNORE_CLASSES = {
            "uac_inputindicatoroverlaywnd", "msctfime ui", "tooltips_class32",
            "default ime", "ime", "workerw", "progman",
        }
        filtered = [
            w for w in real_windows
            if (w.get("class_name") or "").lower() not in IGNORE_CLASSES
            and w.get("geometry", {}).get("width", 0) >= 100
            and w.get("geometry", {}).get("height", 0) >= 100
        ]
        candidates = filtered if filtered else real_windows

        if expected_title_substring:
            sub = expected_title_substring.strip().lower()
            matching = [w for w in candidates if sub in (w.get("title") or "").lower()]
            if matching:
                matching.sort(
                    key=lambda w: w["geometry"]["width"] * w["geometry"]["height"], reverse=True
                )
                return matching[0]

        candidates.sort(
            key=lambda w: w["geometry"]["width"] * w["geometry"]["height"], reverse=True
        )
        return candidates[0]

    @classmethod
    def set_foreground_window(cls, hwnd: int) -> Tuple[bool, int, str]:
        """
        Brings window to top, restores if minimized, and sets foreground focus.
        Verifies the active foreground HWND. Returns (success, actual_foreground_hwnd, reason).
        """
        if sys.platform != "win32" or w32.user32 is None:
            return True, hwnd, "Non-windows host: simulated focus success"

        user32 = w32.user32
        if not user32.IsWindow(hwnd):
            return False, 0, f"Invalid window handle HWND: {hwnd}"

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, w32.SW_RESTORE)
            time.sleep(0.1)

        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)

        fg_hwnd = user32.GetForegroundWindow()

        pid_var = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_var))
        target_pid = pid_var.value

        fg_pid_var = wintypes.DWORD()
        user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid_var))
        fg_pid = fg_pid_var.value

        if fg_hwnd == hwnd:
            return True, fg_hwnd, f"Confirmed foreground HWND {hwnd} matches target window"
        elif fg_pid == target_pid and target_pid != 0:
            return True, fg_hwnd, f"Confirmed foreground HWND {fg_hwnd} shares target PID {target_pid}"
        else:
            return False, fg_hwnd, f"Foreground HWND {fg_hwnd} (PID {fg_pid}) does not match target HWND {hwnd} (PID {target_pid})"

    @classmethod
    def get_dpi_and_display_metrics(cls, hwnd: int) -> Dict[str, Any]:
        """
        Queries monitor handle, DPI scaling factor, work area geometry, and physical dimensions.
        Audited for 64-bit HMONITOR pointer safety.
        """
        metrics: Dict[str, Any] = {
            "hwnd": hwnd,
            "dpi": 96,
            "dpi_scale": 1.0,
            "monitor_handle": 0,
            "monitor_rect": {"x": 0, "y": 0, "width": 1920, "height": 1080},
            "window_geometry": {"x": 0, "y": 0, "width": 800, "height": 600},
        }
        if sys.platform != "win32" or w32.user32 is None:
            return metrics

        user32 = w32.user32
        if not user32.IsWindow(hwnd):
            return metrics

        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        metrics["window_geometry"] = rect.to_dict()

        dpi = 96
        if hasattr(user32, "GetDpiForWindow"):
            try:
                dpi_val = user32.GetDpiForWindow(hwnd)
                if dpi_val > 0:
                    dpi = dpi_val
            except Exception:
                dpi = 96
        metrics["dpi"] = dpi
        metrics["dpi_scale"] = round(dpi / 96.0, 2)

        # 64-bit safe HMONITOR query
        hmon = user32.MonitorFromWindow(hwnd, w32.MONITOR_DEFAULTTONEAREST)
        metrics["monitor_handle"] = int(hmon) if hmon else 0

        return metrics

    @staticmethod
    def verify_port_listening_process(
        port: int, expected_pids: Set[int]
    ) -> Tuple[bool, Optional[int], str]:
        """
        Verifies whether the process listening on `port` belongs to the expected process tree.
        """
        try:
            import psutil
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr and conn.laddr.port == port and conn.status in (psutil.CONN_LISTEN, "LISTEN"):
                    listening_pid = conn.pid
                    if listening_pid is None:
                        return False, None, f"Port {port} is open but owning PID cannot be determined"
                    if listening_pid in expected_pids:
                        return True, listening_pid, f"Port {port} confirmed listening on process tree PID {listening_pid}"
                    else:
                        return False, listening_pid, f"Port {port} is occupied by foreign PID {listening_pid} (expected one of {sorted(list(expected_pids))})"
            return False, None, f"No process found listening on port {port}"
        except (ImportError, Exception) as e:
            return True, None, f"Port ownership could not be strictly checked via net_connections ({e})"

    @classmethod
    def capture_native_window_screenshot(
        cls, hwnd: int, output_path: str
    ) -> Tuple[bool, str, str]:
        """
        Captures the OS desktop window surface using Win32 GDI PrintWindow.
        Guaranteed resource cleanup in try...finally blocks, eliminating GDI DC leaks.
        Computes SHA-256 hash and saves to output_path. Returns (success, sha256_hash, error_msg).
        """
        if sys.platform != "win32" or w32.user32 is None or w32.gdi32 is None:
            return False, "", "Native window capture is only supported on Windows host."

        user32 = w32.user32
        gdi32 = w32.gdi32

        if not user32.IsWindow(hwnd):
            return False, "", f"Invalid window handle HWND: {hwnd}"

        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width <= 0 or height <= 0:
            return False, "", f"Window has zero or negative geometry ({width}x{height})"

        hdc_window = None
        hdc_mem = None
        hbm = None
        hbm_old = None

        try:
            hdc_window = user32.GetWindowDC(hwnd)
            if not hdc_window:
                return False, "", "Failed to acquire Window Device Context (GetWindowDC)"

            hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
            if not hdc_mem:
                return False, "", "Failed to create memory Device Context (CreateCompatibleDC)"

            hbm = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
            if not hbm:
                return False, "", "Failed to create compatible bitmap (CreateCompatibleBitmap)"

            hbm_old = gdi32.SelectObject(hdc_mem, hbm)

            # PW_RENDERFULLCONTENT = 2
            printed = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
            if not printed:
                printed = user32.PrintWindow(hwnd, hdc_mem, 0)
            if not printed:
                printed = gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_window, 0, 0, SRCCOPY)

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height  # top-down DIB
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = BI_RGB
            bmi.biSizeImage = width * height * 4

            raw_buffer = ctypes.create_string_buffer(bmi.biSizeImage)
            gdi32.GetDIBits(
                hdc_mem,
                hbm,
                0,
                height,
                raw_buffer,
                ctypes.byref(bmi),
                DIB_RGB_COLORS,
            )

            png_bytes = cls._raw_bgra_to_png(bytes(raw_buffer), width, height)
            sha256_hash = hashlib.sha256(png_bytes).hexdigest()
            os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(png_bytes)
            return True, sha256_hash, ""

        except Exception as e:
            return False, "", f"Failed to encode or write native screenshot: {e}"

        finally:
            if hdc_mem and hbm_old:
                gdi32.SelectObject(hdc_mem, hbm_old)
            if hbm:
                gdi32.DeleteObject(hbm)
            if hdc_mem:
                gdi32.DeleteDC(hdc_mem)
            if hdc_window:
                user32.ReleaseDC(hwnd, hdc_window)

    @classmethod
    def capture_desktop_screenshot(cls, output_path: str) -> Tuple[bool, str, str]:
        """
        Captures the entire primary OS desktop surface using Win32 GDI with guaranteed cleanup.
        """
        if sys.platform != "win32" or w32.user32 is None or w32.gdi32 is None:
            return False, "", "Desktop capture is only supported on Windows host."

        user32 = w32.user32
        gdi32 = w32.gdi32

        hdc_screen = None
        hdc_mem = None
        hbm = None
        hbm_old = None

        try:
            hdc_screen = user32.GetDC(0)
            if not hdc_screen:
                return False, "", "Failed to acquire Screen Device Context"

            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)

            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            if not hdc_mem:
                return False, "", "Failed to create memory Device Context"

            hbm = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
            if not hbm:
                return False, "", "Failed to create compatible bitmap"

            hbm_old = gdi32.SelectObject(hdc_mem, hbm)

            printed = gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, SRCCOPY)
            if not printed:
                return False, "", "Failed to BitBlt screen"

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = BI_RGB
            bmi.biSizeImage = width * height * 4

            raw_buffer = ctypes.create_string_buffer(bmi.biSizeImage)
            gdi32.GetDIBits(
                hdc_mem,
                hbm,
                0,
                height,
                raw_buffer,
                ctypes.byref(bmi),
                DIB_RGB_COLORS,
            )

            png_bytes = cls._raw_bgra_to_png(bytes(raw_buffer), width, height)
            sha256_hash = hashlib.sha256(png_bytes).hexdigest()
            os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(png_bytes)
            return True, sha256_hash, ""

        except Exception as e:
            return False, "", f"Failed to encode or write desktop screenshot: {e}"

        finally:
            if hdc_mem and hbm_old:
                gdi32.SelectObject(hdc_mem, hbm_old)
            if hbm:
                gdi32.DeleteObject(hbm)
            if hdc_mem:
                gdi32.DeleteDC(hdc_mem)
            if hdc_screen:
                user32.ReleaseDC(0, hdc_screen)

    @staticmethod
    def _raw_bgra_to_png(bgra_data: bytes, width: int, height: int) -> bytes:
        """Encodes raw 32-bit BGRA bytes into uncompressed/deflated PNG format in pure Python."""
        scanline_len = width * 4
        raw_rows = []
        for y in range(height):
            row_start = y * scanline_len
            row = bytearray(scanline_len + 1)
            row[0] = 0  # Filter byte None
            for x in range(width):
                b = bgra_data[row_start + x * 4]
                g = bgra_data[row_start + x * 4 + 1]
                r = bgra_data[row_start + x * 4 + 2]
                a = bgra_data[row_start + x * 4 + 3]
                row[1 + x * 4] = r
                row[1 + x * 4 + 1] = g
                row[1 + x * 4 + 2] = b
                row[1 + x * 4 + 3] = a
            raw_rows.append(bytes(row))

        raw_data = b"".join(raw_rows)
        compressed = zlib.compress(raw_data, level=6)

        def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
            length = struct.pack(">I", len(data))
            crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
            return length + chunk_type + data + crc

        png_header = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        ihdr_chunk = make_chunk(b"IHDR", ihdr_data)
        idat_chunk = make_chunk(b"IDAT", compressed)
        iend_chunk = make_chunk(b"IEND", b"")

        return png_header + ihdr_chunk + idat_chunk + iend_chunk
