"""
Real-Application Validation Suite: Anki Maths (PyQt6 + QtWebEngine) — Phase 4.
Validates Dual-Perspective Observation, Context Reconciliation, Compact YAML,
Deterministic Locators, and Composite 5-Point Actionability Engine against live Anki Maths.
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
from runtime.cdp_target import CDPTargetManager
from runtime.references import ReferenceRegistry
from runtime.native_supervisor import NativeSupervisor
from runtime.webview_core import WebviewAutomationCore
from runtime.flaui_bridge import FlaUIBridge
from runtime.observation_engine import ObservationEngine
from runtime.locators import DeterministicLocatorEngine, LocatorQuery
from runtime.actionability import ActionabilityEngine, OverallActionabilityStatus
from runtime.state import TargetPlane


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


class TestPhase4RealAppValidation(unittest.TestCase):
    """End-to-end integration test of Phase 4 Observation & Actionability against live Anki Maths."""

    @classmethod
    def setUpClass(cls):
        if not ANKI_MATHS_DIR.exists() or not ANKI_PYTHON.exists():
            raise unittest.SkipTest(f"Anki Maths not available at {ANKI_MATHS_DIR}")

    def setUp(self):
        ProcessCleanup.clean_state_files([
            "phase4_anki.pid", "phase4_anki.log", "phase4_benchmarks.json"
        ])

    def tearDown(self):
        ProcessCleanup.safe_cleanup(pid_file="phase4_anki.pid")

    def test_real_anki_maths_observation_and_actionability(self):
        """Validates all Phase 4 subsystems against live PyQt6 + QtWebEngine Anki Maths."""
        async def run_integration():
            port = ProcessLauncher.find_free_port(start_port=9250)
            print(f"\n[Phase 4 Real App] Launching Anki Maths on CDP port {port}...")

            adapter, _ = EngineDetector.detect_with_details(str(ANKI_MATHS_DIR))
            self.assertEqual(adapter.engine_name, "qtwebengine")

            pid = ProcessLauncher.launch(
                executable_or_script=str(ANKI_PYTHON),
                args=[str(ANKI_ENTRY)],
                adapter=adapter,
                port=port,
                pid_file="phase4_anki.pid",
                log_file="phase4_anki.log",
                init_delay=4.0,
                cwd=str(ANKI_MATHS_DIR),
                env_overrides={
                    "ANKIDEV": "1",
                    "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-allow-origins=http://127.0.0.1:{port},http://localhost:{port}"
                }
            )
            self.assertGreater(pid, 0)
            print(f"[Phase 4 Real App] Anki Maths spawned with PID: {pid}")

            latencies = {
                "native_observation_ms": [],
                "web_observation_ms": [],
                "reconciliation_ms": [],
                "yaml_compaction_ms": [],
                "locator_resolution_ms": [],
                "actionability_gate_ms": [],
            }

            try:
                # 1. Correlate Target and Discover Webview
                http_targets = []
                for _ in range(25):
                    try:
                        http_targets = CDPTargetManager.discover_http_targets(port=port)
                        if http_targets:
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

                self.assertGreater(len(http_targets), 0, f"Expected at least one inspectable target on port {port}")
                main_t = next((t for t in http_targets if t.type == "page" and "main" in t.title.lower() and t.ws_url), None)
                if not main_t:
                    main_t = next((t for t in http_targets if t.type == "page" and t.ws_url), http_targets[0])
                primary_t = main_t

                # 2. Find native HWND across parent and child processes
                supervisor = NativeSupervisor()
                candidate_pids = {pid}
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    for child in proc.children(recursive=True):
                        candidate_pids.add(child.pid)
                except Exception:
                    pass

                primary_hwnd = 0
                for _ in range(10):
                    for c_pid in candidate_pids:
                        hwnds = supervisor.find_windows_by_pid(c_pid)
                        for h in hwnds:
                            if supervisor.is_window_visible(h):
                                primary_hwnd = h
                                break
                        if primary_hwnd:
                            break
                    if primary_hwnd:
                        break
                    await asyncio.sleep(0.5)

                print(f"[Phase 4 Real App] Identified Native HWND: {hex(primary_hwnd)}")

                # 3. Setup Transports and WebviewAutomationCore
                transport = WebSocketCDPTransport(endpoint_url=primary_t.ws_url)
                registry = ReferenceRegistry(session_id="anki_phase4_sess", initial_epoch=1)

                core = WebviewAutomationCore(
                    session_id="anki_phase4_sess",
                    transport=transport,
                    reference_registry=registry,
                    native_hwnd=primary_hwnd,
                    native_pid=pid,
                    cdp_port=port,
                )
                await core.connect()
                self.assertTrue(core.is_connected)

                flaui = FlaUIBridge()
                # Attempt to connect flaui if binary available
                if os.path.exists(flaui.sidecar_path):
                    await flaui.connect()

                # 4. Initialize Phase 4 ObservationEngine
                engine = ObservationEngine(
                    session_id="anki_phase4_sess",
                    reference_registry=registry,
                    native_supervisor=supervisor,
                    webview_core=core,
                    flaui_bridge=flaui if flaui.is_connected else None,
                )

                # 5. Full Dual-Perspective Observation
                for _ in range(3):
                    t0 = time.perf_counter()
                    snapshot = await engine.observe(
                        hwnd=primary_hwnd,
                        target_id=primary_t.target_id,
                        actionable_only=False,
                    )
                    latencies["web_observation_ms"].append((time.perf_counter() - t0) * 1000.0)

                self.assertIsNotNone(snapshot)
                self.assertIsNotNone(snapshot.native_observation)
                self.assertIsNotNone(snapshot.web_observation)
                self.assertIsNotNone(snapshot.reconciliation)

                print(f"[Phase 4 Real App] Native Observation: Title='{snapshot.native_observation.title}', Elements={len(snapshot.native_observation.elements)}")
                print(f"[Phase 4 Real App] Web Observation: URL='{snapshot.web_observation.target_url}', Elements={len(snapshot.web_observation.elements)}")
                print(f"[Phase 4 Real App] Reconciliation Relationship: {snapshot.reconciliation.relationship_type.value}, Confidence: {snapshot.reconciliation.confidence.value}")
                print(f"[Phase 4 Real App] Contradictions detected: {len(snapshot.reconciliation.contradictions)}")

                # 6. Verify Physical Reality Primacy
                self.assertTrue(snapshot.native_observation.is_visible)
                self.assertFalse(snapshot.native_observation.is_minimized)
                self.assertEqual(len(snapshot.reconciliation.contradictions), 0)

                # 7. Verify Compact YAML Output
                t0 = time.perf_counter()
                yaml_rep = snapshot.text_representation
                latencies["yaml_compaction_ms"].append((time.perf_counter() - t0) * 1000.0)
                self.assertIn("# Observation Epoch: 1", yaml_rep)
                self.assertIn("@@ native_window:", yaml_rep)
                self.assertIn("@@ webview:", yaml_rep)
                print(f"[Phase 4 Real App] Compact YAML snippet:\n{yaml_rep[:400]}...\n")

                # 8. Deterministic Locator Query
                locator_engine = DeterministicLocatorEngine()
                # Find an element in web elements list
                actionable_elems = [e for e in snapshot.web_observation.elements if e.normalized_role in ("button", "link", "generic")]
                self.assertGreater(len(actionable_elems), 0)
                target_elem = actionable_elems[0]

                t0 = time.perf_counter()
                query = LocatorQuery(
                    role=target_elem.normalized_role,
                    name=target_elem.accessible_name or target_elem.visible_text,
                    exact=False,
                    index=0,  # use index=0 to be explicit
                )
                match = locator_engine.resolve(query, snapshot, strict=False)
                latencies["locator_resolution_ms"].append((time.perf_counter() - t0) * 1000.0)
                print(f"[Phase 4 Real App] Resolved Locator Match: Ref={match.reference}, Strategy={match.match_strategy}, Conf={match.confidence}")

                # 9. 5-Point Composite Actionability Evaluation
                actionability_engine = ActionabilityEngine(
                    reference_registry=registry,
                    native_supervisor=supervisor,
                    webview_core=core,
                )

                t0 = time.perf_counter()
                act_result = await actionability_engine.evaluate_actionability(
                    ref_id=match.reference,
                    sample_interval_ms=50,
                )
                latencies["actionability_gate_ms"].append((time.perf_counter() - t0) * 1000.0)

                print(f"[Phase 4 Real App] Actionability Outcome:")
                print(f"  - Overall: {act_result.overall_status.value}")
                print(f"  - Attachment: {act_result.attachment.status.value}")
                print(f"  - Visibility: {act_result.visibility.status.value}")
                print(f"  - Motion Stability: {act_result.motion.status.value}")
                print(f"  - Enabledness: {act_result.enabledness.status.value}")
                print(f"  - Hit-Test: {act_result.hit_test.status.value}")
                print(f"  - Affordance Point: {act_result.affordance_point} ({act_result.affordance_point_type})")

                # 10. Clean Disconnect
                await core.disconnect()
                if flaui.is_connected:
                    await flaui.disconnect()

                # 11. Write Benchmark Report
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

                benchmarks = {k: calc_stats(v) for k, v in latencies.items()}
                with open("phase4_benchmarks.json", "w", encoding="utf-8") as f:
                    json.dump(benchmarks, f, indent=2)
                print(f"[Phase 4 Real App] Benchmark Summary:\n{json.dumps(benchmarks, indent=2)}")

            finally:
                ProcessCleanup.safe_cleanup(pid_file="phase4_anki.pid")

        asyncio.run(run_integration())


if __name__ == "__main__":
    unittest.main()
