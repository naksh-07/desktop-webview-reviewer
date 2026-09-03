"""
Real-Application Validation Suite: Anki Maths (PyQt6 + QtWebEngine).
Tests Phase 3 Webview Automation Core against the genuine Anki Maths desktop application:
1. Process correlation & target discovery.
2. Frame hierarchy & reachable frames.
3. Isolated Utility World execution (geometry, computed styles, visibility).
4. Accessibility inspection & freeze detection.
5. Coordinate transformation (Web CSS -> Screen).
6. Performance benchmarks (min, median, p95, max latencies).
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
import unittest

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

if CORE_SKILL_DIR not in sys.path:
    sys.path.insert(0, CORE_SKILL_DIR)

from adapters import get_adapter
from core.cleanup import ProcessCleanup
from detectors.engine_detector import EngineDetector
from launchers.process_launcher import ProcessLauncher

from runtime.cdp_transport import WebSocketCDPTransport
from runtime.cdp_target import CDPTargetManager, CDPTargetInfo
from runtime.references import ReferenceRegistry, Rect
from runtime.webview_core import WebviewAutomationCore
from runtime.state import AXFreshnessStatus


def _resolve_anki_maths_dir() -> Path:
    if "ANKI_MATHS_DIR" in os.environ:
        return Path(os.environ["ANKI_MATHS_DIR"]).resolve()
    candidate_sibling = Path(__file__).resolve().parent.parent.parent / "Anki-maths"
    if candidate_sibling.exists():
        return candidate_sibling.resolve()
    candidate_home = Path.home() / "Documents" / "Antigravity" / "Anki-maths"
    if candidate_home.exists():
        return candidate_home.resolve()
    return candidate_sibling


ANKI_MATHS_DIR = _resolve_anki_maths_dir()
ANKI_PYTHON = ANKI_MATHS_DIR / "out" / "pyenv" / "Scripts" / "python.exe"
ANKI_ENTRY = ANKI_MATHS_DIR / "tools" / "run.py"


class TestWebviewCoreRealAppValidation(unittest.TestCase):
    """End-to-end integration test of WebviewAutomationCore against live Anki Maths."""

    @classmethod
    def setUpClass(cls):
        if not ANKI_MATHS_DIR.exists() or not ANKI_PYTHON.exists():
            raise unittest.SkipTest(f"Anki Maths not available at {ANKI_MATHS_DIR}")

    def setUp(self):
        ProcessCleanup.clean_state_files([
            "phase3_anki.pid", "phase3_anki.log", "phase3_benchmarks.json"
        ])

    def tearDown(self):
        ProcessCleanup.safe_cleanup(pid_file="phase3_anki.pid")

    def test_real_anki_maths_webview_core_integration(self):
        """Validates all Phase 3 WebviewAutomationCore subsystems on real Anki Maths."""
        async def run_integration():
            port = ProcessLauncher.find_free_port(start_port=9240)
            print(f"\n[Phase 3 Real App] Launching Anki Maths on CDP port {port}...")

            adapter, _ = EngineDetector.detect_with_details(str(ANKI_MATHS_DIR))
            self.assertEqual(adapter.engine_name, "qtwebengine")

            pid = ProcessLauncher.launch(
                executable_or_script=str(ANKI_PYTHON),
                args=[str(ANKI_ENTRY)],
                adapter=adapter,
                port=port,
                pid_file="phase3_anki.pid",
                log_file="phase3_anki.log",
                init_delay=4.0,
                cwd=str(ANKI_MATHS_DIR),
                env_overrides={
                    "ANKIDEV": "1",
                    "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-allow-origins=http://127.0.0.1:{port},http://localhost:{port}"
                }
            )
            self.assertGreater(pid, 0)
            print(f"[Phase 3 Real App] Anki Maths spawned with PID: {pid}")

            latencies = {
                "target_discovery_ms": [],
                "script_eval_ms": [],
                "geometry_query_ms": [],
                "visibility_check_ms": [],
                "ax_snapshot_ms": [],
                "coordinate_transform_us": [],
            }

            try:
                # 1. Endpoint & Process Correlation
                candidate_pids = {pid}
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    for child in proc.children(recursive=True):
                        candidate_pids.add(child.pid)
                except Exception:
                    pass

                corr = CDPTargetManager.verify_endpoint_ownership(
                    port=port,
                    expected_pids=candidate_pids,
                )
                print(f"[Phase 3 Real App] Endpoint Process Correlation: {corr.proof_status} (listening PID={corr.listening_pid}, candidate PIDs={candidate_pids})")

                # 2. Target Discovery via HTTP /json/list
                t0 = time.perf_counter()
                http_targets = CDPTargetManager.discover_http_targets(port=port)
                latencies["target_discovery_ms"].append((time.perf_counter() - t0) * 1000.0)
                self.assertGreater(len(http_targets), 0, "Expected at least one inspectable target")

                # Pick primary main webview target if available
                main_t = next((t for t in http_targets if t.type == "page" and "main" in t.title.lower() and t.ws_url), None)
                if not main_t:
                    main_t = next((t for t in http_targets if t.type == "page" and t.ws_url), http_targets[0])
                primary_t = main_t
                print(f"[Phase 3 Real App] Selected Target: ID={primary_t.target_id[:8]}... | Title='{primary_t.title}' | WS={primary_t.ws_url}")

                # 3. Create Transport & WebviewAutomationCore
                transport = WebSocketCDPTransport(endpoint_url=primary_t.ws_url)
                registry = ReferenceRegistry(session_id="anki_real_session", initial_epoch=1)

                core = WebviewAutomationCore(
                    session_id="anki_real_session",
                    transport=transport,
                    reference_registry=registry,
                    native_pid=pid,
                    cdp_port=port,
                )

                # Connect core
                await core.connect()
                self.assertTrue(core.is_connected)
                print("[Phase 3 Real App] WebviewAutomationCore connected successfully")

                # 4. Hierarchical Frame Tree Inspection
                frames = core.frame_manager.get_reachable_frames()
                self.assertGreater(len(frames), 0)
                root_f = core.frame_manager.root_frame
                self.assertIsNotNone(root_f)
                print(f"[Phase 3 Real App] Root Frame: ID={root_f.frame_id} | URL={root_f.url}")

                # 5. Isolated Utility World Script Evaluation
                for _ in range(5):
                    t0 = time.perf_counter()
                    dom_count = await core.get_dom_element_count(in_utility_world=True)
                    latencies["script_eval_ms"].append((time.perf_counter() - t0) * 1000.0)

                self.assertGreater(dom_count, 5)
                print(f"[Phase 3 Real App] Total DOM elements: {dom_count}")

                # 6. Element Geometry Query
                for _ in range(5):
                    t0 = time.perf_counter()
                    geom = await core.query_element_geometry("body", in_utility_world=True)
                    latencies["geometry_query_ms"].append((time.perf_counter() - t0) * 1000.0)

                self.assertIsNotNone(geom)
                self.assertGreater(geom["width"], 0)
                self.assertGreater(geom["height"], 0)
                print(f"[Phase 3 Real App] Body Geometry: width={geom['width']}, height={geom['height']}, dpr={geom['dpr']}")

                # 7. Element Visibility Check
                for _ in range(5):
                    t0 = time.perf_counter()
                    vis = await core.check_element_visibility("body", in_utility_world=True)
                    latencies["visibility_check_ms"].append((time.perf_counter() - t0) * 1000.0)

                self.assertTrue(vis["visible"])
                self.assertTrue(vis["attached"])
                print(f"[Phase 3 Real App] Body Visibility: {vis}")

                # 8. Computed Styles Query
                styles = await core.query_element_styles("body", ["display", "position", "visibility"])
                self.assertIn("display", styles)
                print(f"[Phase 3 Real App] Body Computed Styles: {styles}")

                # 9. Accessibility Inspection & Freeze Validation
                for _ in range(3):
                    t0 = time.perf_counter()
                    ax_snapshot = await core.capture_accessibility_snapshot(auto_recover=True)
                    latencies["ax_snapshot_ms"].append((time.perf_counter() - t0) * 1000.0)

                print(f"[Phase 3 Real App] AX Tree Nodes: {ax_snapshot.node_count} | Freshness: {ax_snapshot.freshness.value}")
                self.assertIn(ax_snapshot.freshness, (AXFreshnessStatus.FRESH, AXFreshnessStatus.UNKNOWN))

                # 10. Coordinate Conversion: CSS -> Physical Screen
                for _ in range(100):
                    t0 = time.perf_counter()
                    css_rect = Rect(x=geom["x"], y=geom["y"], width=geom["width"], height=geom["height"])
                    screen_rect = core.convert_css_rect_to_screen_rect(
                        css_rect=css_rect,
                        client_origin_screen=(100, 100),
                        dpr=geom["dpr"],
                    )
                    latencies["coordinate_transform_us"].append((time.perf_counter() - t0) * 1_000_000.0)

                self.assertGreater(screen_rect.width, 0)
                self.assertGreater(screen_rect.height, 0)
                print(f"[Phase 3 Real App] Converted Screen Rect: {screen_rect.to_dict()}")

                # 11. Clean Disconnect
                await core.disconnect()
                self.assertFalse(core.is_connected)
                print("[Phase 3 Real App] WebviewAutomationCore cleanly disconnected")

                # 12. Save Benchmarks
                def calc_stats(vals):
                    if not vals:
                        return {"min": 0, "median": 0, "p95": 0, "max": 0}
                    sorted_v = sorted(vals)
                    p95_idx = int(0.95 * len(sorted_v))
                    return {
                        "min": round(sorted_v[0], 2),
                        "median": round(sorted_v[len(sorted_v) // 2], 2),
                        "p95": round(sorted_v[min(p95_idx, len(sorted_v) - 1)], 2),
                        "max": round(sorted_v[-1], 2),
                    }

                benchmark_report = {k: calc_stats(v) for k, v in latencies.items()}
                with open("phase3_benchmarks.json", "w", encoding="utf-8") as f:
                    json.dump(benchmark_report, f, indent=2)
                print(f"[Phase 3 Real App] Benchmark Results:\n{json.dumps(benchmark_report, indent=2)}")

            finally:
                ProcessCleanup.safe_cleanup(pid_file="phase3_anki.pid")

        asyncio.run(run_integration())


if __name__ == "__main__":
    unittest.main()
