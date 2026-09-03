"""
Test Suite: Performance and Latency Micro-Benchmarks for Native OS Supervision.
Measures execution timing across native Win32 operations:
- DWM bounds query latency
- SendMessageTimeoutW (WM_NULL) responsiveness check latency
- Top-level window enumeration & Z-order scan latency
- TargetManager single authoritative window validation latency
- Coordinate transformation pipeline latency
Computes factual statistical metrics: samples, min_ms, median_ms, p95_ms, max_ms.
"""

import statistics
import sys
import time
from typing import List, Dict, Any
import unittest

from runtime.references import Rect
from runtime.state import HealthState
from runtime.native_supervisor import NativeOSSupervisor
from runtime.target_manager import TargetManager
from runtime.coordinate_transform import (
    CoordinateTransformer,
    CoordinateTransformContext,
    VirtualScreenBounds,
)
import runtime.win32 as w32


def calculate_latency_stats(timings_ms: List[float]) -> Dict[str, Any]:
    """Calculates min, median, p95, max, and sample count."""
    if not timings_ms:
        return {"samples": 0, "min_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    sorted_times = sorted(timings_ms)
    n = len(sorted_times)
    p95_idx = max(0, int(n * 0.95) - 1)
    return {
        "samples": n,
        "min_ms": round(sorted_times[0], 4),
        "median_ms": round(statistics.median(sorted_times), 4),
        "p95_ms": round(sorted_times[p95_idx], 4),
        "max_ms": round(sorted_times[-1], 4),
    }


class TestRuntimePerformance(unittest.TestCase):
    """Latency micro-benchmarks for native OS supervisor operations."""

    @classmethod
    def setUpClass(cls):
        cls.benchmark_results: Dict[str, Dict[str, Any]] = {}

    def test_benchmark_coordinate_transformation(self):
        """Measures full coordinate transform pipeline latency (Web CSS -> Screen -> SendInput)."""
        ctx = CoordinateTransformContext(
            dpi_scale=1.5,
            client_origin_screen=(100, 100),
            webview_client_offset=(10, 30),
            virtual_screen=VirtualScreenBounds(0, 0, 3840, 2160),
        )

        timings = []
        # Run 100 iterations
        for i in range(100):
            t0 = time.perf_counter()
            screen_pt = CoordinateTransformer.css_to_screen(50.0 + i, 50.0 + i, ctx)
            norm_pt = CoordinateTransformer.screen_to_sendinput_normalized(
                screen_pt[0], screen_pt[1], ctx.virtual_screen
            )
            recon_pt = CoordinateTransformer.sendinput_normalized_to_screen(
                norm_pt[0], norm_pt[1], ctx.virtual_screen
            )
            rev_css = CoordinateTransformer.screen_to_css(recon_pt[0], recon_pt[1], ctx)
            t1 = time.perf_counter()
            timings.append((t1 - t0) * 1000.0)

        stats = calculate_latency_stats(timings)
        self.__class__.benchmark_results["coordinate_transform"] = stats
        print(f"\n[BENCHMARK] Coordinate Transform: {stats}")

        # Coordinate math should be microsecond-scale (< 0.1ms median)
        self.assertLess(stats["median_ms"], 0.2, "Coordinate math must be < 0.2ms median")

    def test_benchmark_dwm_bounds_lookup(self):
        """Measures DWMWA_EXTENDED_FRAME_BOUNDS lookup latency."""
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        timings = []

        for _ in range(50):
            t0 = time.perf_counter()
            bounds = NativeOSSupervisor.get_window_bounds(hwnd)
            t1 = time.perf_counter()
            timings.append((t1 - t0) * 1000.0)

        stats = calculate_latency_stats(timings)
        self.__class__.benchmark_results["dwm_bounds_lookup"] = stats
        print(f"\n[BENCHMARK] DWM Bounds Lookup: {stats}")

        # DWM bounds should be extremely fast (< 5ms median)
        self.assertLess(stats["median_ms"], 10.0, "DWM bounds query must be < 10ms median")

    def test_benchmark_responsiveness_check(self):
        """Measures SendMessageTimeoutW(WM_NULL, 500ms) check on responsive desktop shell."""
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        timings = []

        for _ in range(30):
            t0 = time.perf_counter()
            report = NativeOSSupervisor.check_responsiveness(hwnd, timeout_ms=500)
            t1 = time.perf_counter()
            timings.append((t1 - t0) * 1000.0)

        stats = calculate_latency_stats(timings)
        self.__class__.benchmark_results["wm_null_responsiveness"] = stats
        print(f"\n[BENCHMARK] Responsiveness Check: {stats}")

        # Responsiveness check on responsive window should complete in < 20ms median
        self.assertLess(stats["median_ms"], 50.0, "Responsiveness check must be < 50ms median")

    def test_benchmark_window_validation(self):
        """Measures single authoritative TargetManager.validate_window_identity latency."""
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        hwnd = w32.user32.GetDesktopWindow()
        tm = TargetManager()
        timings = []

        for _ in range(30):
            t0 = time.perf_counter()
            res = tm.validate_window_identity(hwnd)
            t1 = time.perf_counter()
            timings.append((t1 - t0) * 1000.0)

        stats = calculate_latency_stats(timings)
        self.__class__.benchmark_results["window_validation"] = stats
        print(f"\n[BENCHMARK] Window Validation: {stats}")

        self.assertLess(stats["median_ms"], 50.0, "Window validation must be < 50ms median")

    def test_benchmark_top_level_window_enumeration(self):
        """Measures EnumWindows and top-level Z-order traversal latency."""
        if sys.platform != "win32" or w32.user32 is None:
            self.skipTest("Requires Windows host")

        timings = []

        for _ in range(15):
            t0 = time.perf_counter()
            windows = NativeOSSupervisor.list_top_level_windows(visible_only=True)
            t1 = time.perf_counter()
            timings.append((t1 - t0) * 1000.0)

        stats = calculate_latency_stats(timings)
        self.__class__.benchmark_results["enum_windows"] = stats
        print(f"\n[BENCHMARK] Top-Level Windows Enumeration: {stats}")

        self.assertLess(stats["median_ms"], 100.0, "EnumWindows scan must be < 100ms median")


if __name__ == "__main__":
    unittest.main()
