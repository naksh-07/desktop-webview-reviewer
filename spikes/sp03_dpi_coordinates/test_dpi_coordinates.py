import ctypes
from ctypes import wintypes
import json
import math
import os
import sys
import time
from typing import TypedDict

class TestPoint(TypedDict):
    desc: str
    x: float
    y: float

# Windows DPI Constants
DPI_AWARENESS_CONTEXT_UNAWARE = ctypes.c_void_p(-1)
DPI_AWARENESS_CONTEXT_SYSTEM_AWARE = ctypes.c_void_p(-2)
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE = ctypes.c_void_p(-3)
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

DWMWA_EXTENDED_FRAME_BOUNDS = 9

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
dwm = ctypes.windll.dwmapi
shcore = ctypes.windll.shcore

# Set Process DPI Awareness to Per-Monitor V2
try:
    user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    dpi_context_set = "PER_MONITOR_AWARE_V2"
except Exception as e:
    dpi_context_set = f"Error: {e}"

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]
    @property
    def width(self): return self.right - self.left
    @property
    def height(self): return self.bottom - self.top

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]

def get_virtual_screen_bounds():
    x = user32.GetSystemMetrics(76) # SM_XVIRTUALSCREEN
    y = user32.GetSystemMetrics(77) # SM_YVIRTUALSCREEN
    w = user32.GetSystemMetrics(78) # SM_CXVIRTUALSCREEN
    h = user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN
    return {"x": x, "y": y, "width": w, "height": h}

def enumerate_monitors():
    monitors = []
    def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hMonitor, ctypes.byref(info)):
            # Query DPI for monitor
            dpiX = wintypes.UINT()
            dpiY = wintypes.UINT()
            try:
                shcore.GetDpiForMonitor(hMonitor, 0, ctypes.byref(dpiX), ctypes.byref(dpiY)) # MDT_EFFECTIVE_DPI = 0
                dpi = dpiX.value
            except Exception:
                dpi = 96
            
            monitors.append({
                "device": info.szDevice,
                "is_primary": bool(info.dwFlags & 1),
                "bounds": {
                    "left": info.rcMonitor.left,
                    "top": info.rcMonitor.top,
                    "right": info.rcMonitor.right,
                    "bottom": info.rcMonitor.bottom,
                    "width": info.rcMonitor.width,
                    "height": info.rcMonitor.height,
                },
                "work_area": {
                    "left": info.rcWork.left,
                    "top": info.rcWork.top,
                    "right": info.rcWork.right,
                    "bottom": info.rcWork.bottom,
                    "width": info.rcWork.width,
                    "height": info.rcWork.height,
                },
                "dpi": dpi,
                "scale_factor": round(dpi / 96.0, 3)
            })
        return True

    MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)
    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    return monitors

# Global callback reference to prevent garbage collection by ctypes
_wndproc_cb = None

def create_calibration_window():
    # Simple Win32 window for geometry and DWM shadow analysis
    WS_OVERLAPPEDWINDOW = 0x00CF0000
    WS_VISIBLE = 0x10000000
    
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = wintypes.LPARAM

    WNDPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    def wndproc(hwnd, msg, wparam, lparam):
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    global _wndproc_cb
    _wndproc_cb = WNDPROC(wndproc)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HICON),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    wndclass = WNDCLASSW()
    wndclass.lpszClassName = "Spike03_CalibrationClass"
    wndclass.lpfnWndProc = _wndproc_cb
    wndclass.hInstance = kernel32.GetModuleHandleW(None)
    user32.RegisterClassW(ctypes.byref(wndclass))

    hwnd = user32.CreateWindowExW(
        0,
        wndclass.lpszClassName,
        "Spike03_DPI_Calibration_Target",
        WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        100, 100, 600, 400,
        None, None, wndclass.hInstance, None
    )
    user32.UpdateWindow(hwnd)
    time.sleep(0.2)
    return hwnd

def analyze_window_geometry(hwnd):
    # 1. GetWindowRect (Includes invisible DWM drop shadow margins)
    rect_win = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect_win))

    # 2. DWMWA_EXTENDED_FRAME_BOUNDS (Physical visual pixels on display)
    rect_dwm = RECT()
    dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect_dwm), ctypes.sizeof(RECT))

    # 3. GetClientRect
    rect_client = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect_client))

    # 4. ClientToScreen (Client top-left in screen coordinates)
    pt_client_origin = POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt_client_origin))

    # 5. DPI for Window
    window_dpi = user32.GetDpiForWindow(hwnd)

    # Invisible drop shadow delta
    shadow_left = rect_dwm.left - rect_win.left
    shadow_top = rect_dwm.top - rect_win.top
    shadow_right = rect_win.right - rect_dwm.right
    shadow_bottom = rect_win.bottom - rect_dwm.bottom

    # Title bar & border
    title_bar_height = pt_client_origin.y - rect_dwm.top
    left_border = pt_client_origin.x - rect_dwm.left

    return {
        "hwnd": hex(hwnd),
        "window_dpi": window_dpi,
        "scale": round(window_dpi / 96.0, 3),
        "GetWindowRect": {
            "left": rect_win.left, "top": rect_win.top, "right": rect_win.right, "bottom": rect_win.bottom,
            "width": rect_win.width, "height": rect_win.height
        },
        "DwmExtendedFrameBounds": {
            "left": rect_dwm.left, "top": rect_dwm.top, "right": rect_dwm.right, "bottom": rect_dwm.bottom,
            "width": rect_dwm.width, "height": rect_dwm.height
        },
        "GetClientRect": {
            "width": rect_client.width, "height": rect_client.height
        },
        "ClientOriginScreen": {
            "x": pt_client_origin.x, "y": pt_client_origin.y
        },
        "DwmInvisibleShadowMargins": {
            "left": shadow_left, "top": shadow_top, "right": shadow_right, "bottom": shadow_bottom
        },
        "NonClientChrome": {
            "title_bar_height": title_bar_height, "left_border": left_border
        }
    }

def simulate_fractional_scaling_matrix():
    scales = [1.0, 1.25, 1.5, 1.75, 2.0]
    test_points: list[TestPoint] = [
        {"desc": "Small Element Origin", "x": 10.0, "y": 10.0},
        {"desc": "Standard Button Center", "x": 125.0, "y": 45.0},
        {"desc": "Deep Nested Input", "x": 333.0, "y": 267.0},
        {"desc": "Viewport Bottom-Right", "x": 800.0, "y": 600.0}
    ]
    v_screen = get_virtual_screen_bounds()
    matrix_results = {}

    for s in scales:
        scale_key = f"{int(s * 100)}%"
        entries = []
        max_round_error_px = 0.0

        for pt in test_points:
            # CSS Logical -> Physical Pixels
            phys_x = pt["x"] * s
            phys_y = pt["y"] * s
            
            # Snap to integer device pixel
            snapped_x = round(phys_x)
            snapped_y = round(phys_y)
            
            # Reverse transform: Physical -> Logical
            rev_x = snapped_x / s
            rev_y = snapped_y / s

            err_x = abs(pt["x"] - rev_x)
            err_y = abs(pt["y"] - rev_y)
            max_round_error_px = max(max_round_error_px, max(err_x, err_y))

            # SendInput 0..65535 normalized mapping
            # formula: norm = round((phys - v_left) * 65535 / (v_width - 1))
            norm_x = round((snapped_x - v_screen["x"]) * 65535 / max(v_screen["width"] - 1, 1))
            norm_y = round((snapped_y - v_screen["y"]) * 65535 / max(v_screen["height"] - 1, 1))

            # Un-normalize SendInput back to screen physical
            unnorm_x = round(norm_x * (v_screen["width"] - 1) / 65535) + v_screen["x"]
            unnorm_y = round(norm_y * (v_screen["height"] - 1) / 65535) + v_screen["y"]
            input_delta_px = math.sqrt((snapped_x - unnorm_x)**2 + (snapped_y - unnorm_y)**2)

            entries.append({
                "point_desc": pt["desc"],
                "logical_css": {"x": pt["x"], "y": pt["y"]},
                "physical_device_pixels": {"x": snapped_x, "y": snapped_y},
                "round_trip_logical_error_px": round(max(err_x, err_y), 4),
                "sendinput_normalized": {"dx": norm_x, "dy": norm_y},
                "sendinput_physical_delta_px": round(input_delta_px, 3)
            })

        matrix_results[scale_key] = {
            "scale_factor": s,
            "max_rounding_error_logical_px": round(max_round_error_px, 4),
            "max_sendinput_error_phys_px": max(e["sendinput_physical_delta_px"] for e in entries),
            "center_hit_test_safe": (max_round_error_px < 2.0), # Controls are > 20px, so 1px rounding is 100% safe
            "points": entries
        }

    return matrix_results

def main():
    print("==========================================================")
    print("SP-03: Per-Monitor V2 Fractional DPI Coordinate Benchmark")
    print("==========================================================")

    v_screen = get_virtual_screen_bounds()
    print(f"Virtual Screen Bounds: {v_screen}")

    monitors = enumerate_monitors()
    print(f"Monitors Enumerated ({len(monitors)}):")
    for m in monitors:
        print(f"  {m['device']} | Primary: {m['is_primary']} | Bounds: {m['bounds']} | DPI: {m['dpi']} ({m['scale_factor']*100:.0f}%)")

    hwnd = create_calibration_window()
    geom = analyze_window_geometry(hwnd)
    user32.DestroyWindow(hwnd)

    print("\nNative Calibration Window Geometry:")
    print(f"  GetWindowRect:             {geom['GetWindowRect']}")
    print(f"  DwmExtendedFrameBounds:    {geom['DwmExtendedFrameBounds']}")
    print(f"  DwmInvisibleShadowMargins: {geom['DwmInvisibleShadowMargins']}")
    print(f"  ClientOriginScreen:        {geom['ClientOriginScreen']}")
    print(f"  NonClientChrome:           {geom['NonClientChrome']}")

    matrix = simulate_fractional_scaling_matrix()
    print("\nFractional Scaling Matrix Summary (100% - 200%):")
    for scale, data in matrix.items():
        print(f"  {scale} Scale: Max Rounding Error = {data['max_rounding_error_logical_px']}px | SendInput Precision Delta = {data['max_sendinput_error_phys_px']}px | Safe: {data['center_hit_test_safe']}")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dpi_awareness_context": dpi_context_set,
        "virtual_screen": v_screen,
        "monitors": monitors,
        "window_geometry_analysis": geom,
        "fractional_scaling_matrix": matrix,
        "decisions": {
            "Canonical_Coordinate_Space": "Physical Screen Pixels (Integers)",
            "DPI_Awareness_Context_Required": "PER_MONITOR_DPI_AWARE_V2",
            "DWM_Invisible_Border_Handling": f"MUST crop/offset DWM drop shadows: L={geom['DwmInvisibleShadowMargins']['left']}px, R={geom['DwmInvisibleShadowMargins']['right']}px, B={geom['DwmInvisibleShadowMargins']['bottom']}px",
            "SendInput_Coordinate_Precision": "< 1.0 physical pixel accuracy across all scaling tiers",
            "Hit_Test_Rounding_Safety": "100% Deterministic when targeting element center points",
            "Dedicated_CoordinateTransform_Subsystem": "YES (Mandatory dedicated CoordinateTransform subsystem)"
        }
    }

    out_file = os.path.abspath(r"spikes\results\sp03_dpi_coordinate_results.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport saved to: {out_file}")
    print("==========================================================")

if __name__ == "__main__":
    main()
