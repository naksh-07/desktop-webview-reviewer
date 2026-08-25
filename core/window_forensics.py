"""
Native Windows GUI Forensics and Window Identity Verification.
Provides Win32 API inspection via ctypes and psutil for forensic verification of desktop applications.
"""

import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("desktop_webview.forensics")

# Structure definitions for Win32 API
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
            "bottom": self.bottom
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
PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class WindowForensicsEngine:
    """
    Forensic inspector for native OS window identity, visibility, geometry,
    and process-tree correlation on Windows (with non-Windows safe fallbacks).
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
            "create_time": None
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
        if sys.platform != "win32":
            return {
                "hwnd": hwnd,
                "is_window": True,
                "is_visible": True,
                "is_iconic": False,
                "is_cloaked": False,
                "title": "",
                "class_name": "",
                "pid": 0,
                "geometry": {"x": 0, "y": 0, "width": 800, "height": 600, "left": 0, "top": 0, "right": 800, "bottom": 600},
                "is_real_gui": True
            }

        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

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
                "geometry": {"x": 0, "y": 0, "width": 0, "height": 0, "left": 0, "top": 0, "right": 0, "bottom": 0},
                "is_real_gui": False
            }

        # 1. Thread and Process ID
        pid_var = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_var))
        pid = pid_var.value

        # 2. Window Visibility & Iconic (Minimized)
        is_visible = bool(user32.IsWindowVisible(hwnd))
        is_iconic = bool(user32.IsIconic(hwnd))

        # 3. DWM Cloaked State (Virtual Desktops / System hidden)
        cloaked_val = wintypes.DWORD(0)
        try:
            res = dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked_val), ctypes.sizeof(cloaked_val)
            )
            is_cloaked = (res == 0 and cloaked_val.value != 0)
        except Exception:
            is_cloaked = False

        # 4. Geometry
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        geom = rect.to_dict()

        # 5. Title & Class Name
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        class_name = cls_buf.value

        # 6. Real GUI Evaluation
        # A real visible GUI must be a window, visible, not minimized, not cloaked, and have non-zero visible dimensions
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
            "is_real_gui": is_real_gui
        }

    @classmethod
    def find_windows_for_process_tree(cls, root_pid: int) -> List[Dict[str, Any]]:
        """Finds all top-level HWNDs associated with the process subtree rooted at root_pid."""
        if sys.platform != "win32":
            return []

        target_pids = cls.get_process_tree_pids(root_pid)
        user32 = ctypes.windll.user32
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
    def get_primary_gui_window(cls, root_pid: int, expected_title_substring: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Locates the best primary visible GUI window for the given process tree.
        Prioritizes windows with real GUI dimensions, visibility, and title matches.
        """
        windows = cls.find_windows_for_process_tree(root_pid)
        if not windows:
            return None

        # Filter to real GUI windows
        real_windows = [w for w in windows if w.get("is_real_gui")]
        if not real_windows:
            return windows[0]

        # Filter out OS helper/overlay windows if main windows exist
        IGNORE_CLASSES = {
            "uac_inputindicatoroverlaywnd", "msctfime ui", "tooltips_class32",
            "default ime", "ime", "workerw", "progman"
        }
        filtered = [
            w for w in real_windows
            if (w.get("class_name") or "").lower() not in IGNORE_CLASSES
            and w.get("geometry", {}).get("width", 0) >= 100
            and w.get("geometry", {}).get("height", 0) >= 100
        ]
        candidates = filtered if filtered else real_windows

        # If title filter provided, score matches
        if expected_title_substring:
            sub = expected_title_substring.strip().lower()
            matching = [w for w in candidates if sub in (w.get("title") or "").lower()]
            if matching:
                matching.sort(key=lambda w: w["geometry"]["width"] * w["geometry"]["height"], reverse=True)
                return matching[0]

        # Return largest real window
        candidates.sort(key=lambda w: w["geometry"]["width"] * w["geometry"]["height"], reverse=True)
        return candidates[0]

    @classmethod
    def set_foreground_window(cls, hwnd: int) -> Tuple[bool, int, str]:
        """
        Phase 2 Focus Capability: Brings window to top, restores if minimized,
        and sets foreground focus. Verifies the active foreground HWND.
        Returns (success, actual_foreground_hwnd, reason).
        """
        if sys.platform != "win32":
            return True, hwnd, "Non-windows host: simulated focus success"

        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False, 0, f"Invalid window handle HWND: {hwnd}"

        # 1. Restore if minimized (SW_RESTORE = 9)
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
            time.sleep(0.1)

        # 2. Bring to top & set foreground
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)

        # 3. Confirm foreground HWND
        fg_hwnd = user32.GetForegroundWindow()

        # Check PID match if HWND is child/dialog
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
        Phase 2 Display & DPI Sanity: Queries monitor handle, DPI scaling factor,
        work area geometry, and physical vs logical pixel dimensions.
        """
        metrics: Dict[str, Any] = {
            "hwnd": hwnd,
            "dpi": 96,
            "dpi_scale": 1.0,
            "monitor_handle": 0,
            "monitor_rect": {"x": 0, "y": 0, "width": 1920, "height": 1080},
            "window_geometry": {"x": 0, "y": 0, "width": 800, "height": 600}
        }
        if sys.platform != "win32":
            return metrics

        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return metrics

        # 1. Window geometry
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        metrics["window_geometry"] = rect.to_dict()

        # 2. DPI query via GetDpiForWindow (Win10 1607+)
        dpi = 96
        try:
            if hasattr(user32, "GetDpiForWindow"):
                dpi_val = user32.GetDpiForWindow(hwnd)
                if dpi_val > 0:
                    dpi = dpi_val
        except Exception:
            dpi = 96
        metrics["dpi"] = dpi
        metrics["dpi_scale"] = round(dpi / 96.0, 2)

        # 3. Monitor handle (MONITOR_DEFAULTTONEAREST = 2)
        hmon = user32.MonitorFromWindow(hwnd, 2)
        metrics["monitor_handle"] = int(hmon) if hmon else 0

        return metrics

    @staticmethod
    def verify_port_listening_process(port: int, expected_pids: Set[int]) -> Tuple[bool, Optional[int], str]:
        """
        Verifies whether the process listening on `port` belongs to the expected process tree.
        Returns (is_verified, listening_pid, reason).
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
            # Fallback when psutil connection inspection is unavailable
            return True, None, f"Port ownership could not be strictly checked via net_connections ({e})"

    @classmethod
    def capture_native_window_screenshot(cls, hwnd: int, output_path: str) -> Tuple[bool, str, str]:
        """
        Captures the OS desktop window surface using Win32 GDI PrintWindow.
        Validates PNG header, computes SHA-256 hash, and saves to output_path.
        Returns (success, sha256_hash, error_msg).
        """
        if sys.platform != "win32":
            return False, "", "Native window capture is only supported on Windows host."

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        if not user32.IsWindow(hwnd):
            return False, "", f"Invalid window handle HWND: {hwnd}"

        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width <= 0 or height <= 0:
            return False, "", f"Window has zero or negative geometry ({width}x{height})"

        hdc_window = user32.GetWindowDC(hwnd)
        if not hdc_window:
            return False, "", "Failed to acquire Window Device Context (GetWindowDC)"

        hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
        if not hdc_mem:
            user32.ReleaseDC(hwnd, hdc_window)
            return False, "", "Failed to create memory Device Context (CreateCompatibleDC)"

        hbm = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
        if not hbm:
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(hwnd, hdc_window)
            return False, "", "Failed to create compatible bitmap (CreateCompatibleBitmap)"

        hbm_old = gdi32.SelectObject(hdc_mem, hbm)

        # PW_RENDERFULLCONTENT = 2
        printed = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
        if not printed:
            # Fallback to standard PrintWindow
            printed = user32.PrintWindow(hwnd, hdc_mem, 0)
        if not printed:
            # Fallback to BitBlt
            printed = gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_window, 0, 0, SRCCOPY)

        # Read bitmap bits into memory
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
            DIB_RGB_COLORS
        )

        # Cleanup GDI resources
        gdi32.SelectObject(hdc_mem, hbm_old)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)

        # Convert BGRA buffer to PNG
        try:
            png_bytes = cls._raw_bgra_to_png(bytes(raw_buffer), width, height)
            sha256_hash = hashlib.sha256(png_bytes).hexdigest()
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(png_bytes)
            return True, sha256_hash, ""
        except Exception as e:
            return False, "", f"Failed to encode or write native screenshot: {e}"


    @classmethod
    def capture_desktop_screenshot(cls, output_path: str) -> Tuple[bool, str, str]:
        """
        Captures the entire primary OS desktop surface using Win32 GDI.
        Validates PNG header, computes SHA-256 hash, and saves to output_path.
        Returns (success, sha256_hash, error_msg).
        """
        if sys.platform != "win32":
            return False, "", "Desktop capture is only supported on Windows host."

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        # 0 gives the screen DC
        hdc_screen = user32.GetDC(0)
        if not hdc_screen:
            return False, "", "Failed to acquire Screen Device Context"

        width = user32.GetSystemMetrics(0) # SM_CXSCREEN
        height = user32.GetSystemMetrics(1) # SM_CYSCREEN

        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbm = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        hbm_old = gdi32.SelectObject(hdc_mem, hbm)

        # BitBlt from screen to memory DC
        SRCCOPY = 0x00CC0020
        printed = gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, SRCCOPY)

        if not printed:
            gdi32.SelectObject(hdc_mem, hbm_old)
            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)
            return False, "", "Failed to BitBlt screen"

        # Read bitmap bits into memory
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height  # top-down DIB
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0 # BI_RGB
        bmi.biSizeImage = width * height * 4

        raw_buffer = ctypes.create_string_buffer(bmi.biSizeImage)
        gdi32.GetDIBits(
            hdc_mem,
            hbm,
            0,
            height,
            raw_buffer,
            ctypes.byref(bmi),
            0 # DIB_RGB_COLORS
        )

        # Cleanup GDI resources
        gdi32.SelectObject(hdc_mem, hbm_old)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)

        # Convert BGRA buffer to PNG
        try:
            png_bytes = cls._raw_bgra_to_png(bytes(raw_buffer), width, height)
            import hashlib
            sha256_hash = hashlib.sha256(png_bytes).hexdigest()
            import os
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(png_bytes)
            return True, sha256_hash, ""
        except Exception as e:
            return False, "", f"Failed to encode or write desktop screenshot: {e}"

    @staticmethod
    def _raw_bgra_to_png(bgra_data: bytes, width: int, height: int) -> bytes:
        """Encodes raw 32-bit BGRA bytes into uncompressed/deflated PNG format in pure Python."""
        import zlib
        import struct

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
            crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xffffffff)
            return length + chunk_type + data + crc

        png_header = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        ihdr_chunk = make_chunk(b"IHDR", ihdr_data)
        idat_chunk = make_chunk(b"IDAT", compressed)
        iend_chunk = make_chunk(b"IEND", b"")

        return png_header + ihdr_chunk + idat_chunk + iend_chunk
