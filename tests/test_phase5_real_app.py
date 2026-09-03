"""
Real-Application Validation Suite: Anki Maths (PyQt6 + QtWebEngine) — Phase 5.
Validates Action Execution Engine, Action-Observation Transaction Loop, NativeInputDispatcher,
Settlement Engine, and ActionReceipt/ActionOutcome against live Anki Maths.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
import unittest

try:
    from tests.env_config import CORE_SKILL_DIR
except ImportError:
    try:
        from .env_config import CORE_SKILL_DIR
    except ImportError:
        try:
            from env_config import CORE_SKILL_DIR
        except ImportError:
            CORE_SKILL_DIR = str(Path(__file__).resolve().parent.parent)

if CORE_SKILL_DIR not in sys.path:
    sys.path.insert(0, CORE_SKILL_DIR)

from adapters import get_adapter
from core.cleanup import ProcessCleanup
from detectors.engine_detector import EngineDetector
from launchers.process_launcher import ProcessLauncher

from runtime.cdp_transport import WebSocketCDPTransport
from runtime.cdp_target import CDPTargetManager
from runtime.references import Rect, ReferenceRegistry
from runtime.native_supervisor import NativeSupervisor
from runtime.webview_core import WebviewAutomationCore
from runtime.flaui_bridge import FlaUIBridge
from runtime.observation_engine import ObservationEngine
from runtime.locators import DeterministicLocatorEngine, LocatorQuery
from runtime.actionability import ActionabilityEngine, OverallActionabilityStatus, ActionabilityResult
from runtime.native_input import NativeInputDispatcher
from runtime.settlement import SettlementEngine, SettlementType
from runtime.web_action_executor import WebActionExecutor
from runtime.native_action_executor import NativeActionExecutor
from runtime.action_engine import ActionExecutionEngine
from runtime.action_models import (
    ActionRequest, ActionReceipt, ActionOutcome, ActionTarget,
    ActionType, DispatchMethod, DispatchStatus,
    ActionOutcomeStatus, StateChangeClassification,
)
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


class TestPhase5RealAppValidation(unittest.TestCase):
    """End-to-end integration test of Phase 5 Action Execution against live Anki Maths."""

    @classmethod
    def setUpClass(cls):
        if not ANKI_MATHS_DIR.exists() or not ANKI_PYTHON.exists():
            raise unittest.SkipTest(f"Anki Maths not available at {ANKI_MATHS_DIR}")

    def setUp(self):
        ProcessCleanup.clean_state_files([
            "phase5_anki.pid", "phase5_anki.log", "phase5_benchmarks.json"
        ])

    def tearDown(self):
        ProcessCleanup.safe_cleanup(pid_file="phase5_anki.pid")

    def test_real_anki_maths_action_execution(self):
        """Validates Phase 5 Action Execution Engine against live PyQt6 + QtWebEngine Anki Maths."""
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

        async def run_integration():
            port = ProcessLauncher.find_free_port(start_port=9260)
            print(f"\n[Phase 5 Real App] Launching Anki Maths on CDP port {port}...")

            adapter, _ = EngineDetector.detect_with_details(str(ANKI_MATHS_DIR))
            self.assertIsNotNone(adapter, "Failed to detect engine adapter for Anki Maths")
            assert adapter is not None
            self.assertEqual(adapter.engine_name, "qtwebengine")

            pid = ProcessLauncher.launch(
                executable_or_script=str(ANKI_PYTHON),
                args=[str(ANKI_ENTRY)],
                adapter=adapter,
                port=port,
                pid_file="phase5_anki.pid",
                log_file="phase5_anki.log",
                init_delay=4.0,
                cwd=str(ANKI_MATHS_DIR),
                env_overrides={
                    "ANKIDEV": "1",
                    "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-allow-origins=http://127.0.0.1:{port},http://localhost:{port}"
                }
            )
            self.assertGreater(pid, 0)
            print(f"[Phase 5 Real App] Anki Maths spawned with PID: {pid}")

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

                print(f"[Phase 5 Real App] Identified Native HWND: {hex(primary_hwnd)}")

                # 3. Setup Transports and WebviewAutomationCore
                transport = WebSocketCDPTransport(endpoint_url=primary_t.ws_url)
                registry = ReferenceRegistry(session_id="anki_phase5_sess", initial_epoch=1)

                core = WebviewAutomationCore(
                    session_id="anki_phase5_sess",
                    transport=transport,
                    reference_registry=registry,
                    native_hwnd=primary_hwnd,
                    native_pid=pid,
                    cdp_port=port,
                )
                await core.connect()
                self.assertTrue(core.is_connected)

                flaui = FlaUIBridge()
                if os.path.exists(flaui.sidecar_path):
                    await flaui.connect()

                # 4. Initialize Phase 4 ObservationEngine & ActionabilityEngine
                obs_engine = ObservationEngine(
                    session_id="anki_phase5_sess",
                    reference_registry=registry,
                    native_supervisor=supervisor,
                    webview_core=core,
                    flaui_bridge=flaui if flaui.is_connected else None,
                )

                locator_engine = DeterministicLocatorEngine()
                action_engine = ActionabilityEngine(
                    session_id="anki_phase5_sess",
                    reference_registry=registry,
                    webview_core=core,
                    native_supervisor=supervisor,
                    flaui_bridge=flaui if flaui.is_connected else None,
                )

                # Phase 5 infrastructure
                native_input = NativeInputDispatcher(dry_run=True)  # dry_run in tests
                settlement_engine = SettlementEngine(
                    native_supervisor=supervisor,
                    webview_core=core,
                    default_timeout_ms=1000,
                    poll_interval_ms=30,
                )
                web_executor = WebActionExecutor(
                    webview_core=core,
                    actionability_engine=action_engine,
                    reference_registry=registry,
                )
                native_executor = NativeActionExecutor(
                    native_supervisor=supervisor,
                    native_input=native_input,
                    actionability_engine=action_engine,
                    reference_registry=registry,
                )
                engine = ActionExecutionEngine(
                    web_executor=web_executor,
                    native_executor=native_executor,
                    settlement_engine=settlement_engine,
                    observation_engine=obs_engine,
                    locator_engine=locator_engine,
                    reference_registry=registry,
                    native_supervisor=supervisor,
                )

                print("[Phase 5 Real App] Infrastructure ready. Running action tests...")

                # 1. Take initial observation
                snapshot = await obs_engine.observe(
                    hwnd=primary_hwnd,
                    target_id=primary_t.target_id,
                    actionable_only=False,
                )
                self.assertIsNotNone(snapshot)
                epoch_before = registry.current_epoch
                print(f"  Epoch: {epoch_before}, Web Elements: {len(snapshot.web_observation.elements) if snapshot.web_observation else 0}")

                # 2. Find a clickable element
                if snapshot.web_observation and snapshot.web_observation.elements:
                    clickable = None
                    for elem in snapshot.web_observation.elements:
                        is_vis = elem.visibility.visible if elem.visibility else True
                        is_en = elem.interaction.is_enabled if elem.interaction else True
                        if is_vis and is_en and elem.normalized_role in ("button", "link", "menuitem", "generic"):
                            clickable = elem
                            break

                    if clickable:
                        print(f"  Target: {clickable.normalized_role} '{clickable.accessible_name or clickable.visible_text}' @ ref={clickable.reference}")

                        # 3. Construct ActionRequest
                        request = ActionRequest(
                            session_id="real-app-test",
                            reference=clickable.reference,
                            action_type=ActionType.CLICK,
                            observation_epoch=epoch_before,
                        )

                        # 4. Look up the ref
                        ref = registry.resolve_ref(clickable.reference)
                        self.assertIsNotNone(ref)

                        # 5. Test receipt generation via web executor directly
                        target = ActionTarget(
                            session_id="real-app-test",
                            target_id=str(ref.target_id or clickable.reference),
                            reference=clickable.reference,
                            plane=TargetPlane.WEBVIEW_DOM,
                            epoch=epoch_before,
                            affordance_point=(
                                int(clickable.geometry.bounds.x + clickable.geometry.bounds.width / 2),
                                int(clickable.geometry.bounds.y + clickable.geometry.bounds.height / 2),
                            ) if clickable.geometry else None,
                            native_hwnd=primary_hwnd,
                            cdp_target_id=primary_t.target_id,
                            frame_id=ref.frame_id,
                            role=clickable.normalized_role,
                            name=clickable.accessible_name,
                            bounds=ref.bounds or Rect(0, 0, 0, 0),
                        )

                        # 6. Check actionability
                        act_result = await action_engine.evaluate_actionability(clickable.reference)
                        print(f"  Actionability: {act_result.overall_status} | Afford Point: {act_result.affordance_point}")

                        if act_result.is_actionable:
                            # 7. Execute action via web executor
                            receipt = await web_executor.execute_action(
                                request=request,
                                target=target,
                                precondition_result=act_result,
                            )
                            print(f"  Receipt: status={receipt.dispatch_status}, method={receipt.dispatch_method}, coords={receipt.coordinates}")

                            self.assertIsInstance(receipt, ActionReceipt)
                            self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
                            self.assertEqual(receipt.dispatch_method, DispatchMethod.CDP_INPUT)
                            self.assertEqual(receipt.session_id, "real-app-test")
                            self.assertIsNotNone(receipt.coordinates)
                            self.assertGreater(receipt.dispatch_timestamp, 0)

                            # 8. Settlement
                            settle_result = await settlement_engine.settle(
                                target_pid=pid,
                                target_hwnd=primary_hwnd,
                                timeout_ms=800,
                            )
                            print(f"  Settlement: type={settle_result.settlement_type}, elapsed={settle_result.elapsed_ms:.1f}ms")
                            self.assertIsNotNone(settle_result)

                            # 9. Post-action observation
                            post_snapshot = await obs_engine.observe(
                                hwnd=primary_hwnd,
                                target_id=primary_t.target_id,
                                actionable_only=False,
                            )
                            self.assertIsNotNone(post_snapshot)
                            epoch_after = registry.current_epoch
                            print(f"  Post-action epoch: {epoch_after}")

                            # 10. Construct outcome
                            outcome = ActionOutcome(
                                action_id=receipt.action_id,
                                session_id="real-app-test",
                                receipt=receipt,
                                outcome_status=ActionOutcomeStatus.DISPATCHED,
                                state_change=(
                                    StateChangeClassification.STATE_CHANGED if epoch_after > epoch_before
                                    else StateChangeClassification.NO_EFFECT
                                ),
                                pre_epoch=epoch_before,
                                post_epoch=epoch_after,
                                duration_ms=settle_result.elapsed_ms,
                            )
                            print(f"  Outcome: status={outcome.outcome_status}, state_change={outcome.state_change}")
                            self.assertIsInstance(outcome, ActionOutcome)

                            # 11. Validate serialization
                            outcome_dict = outcome.to_dict()
                            self.assertIn("receipt", outcome_dict)
                            self.assertIn("state_change", outcome_dict)
                            json.dumps(outcome_dict)  # Must be JSON-serializable
                            print("  [OK] Outcome serialization valid")
                        else:
                            print(f"  Skipping action (not actionable): {act_result.reasons}")
                    else:
                        print("  No clickable elements found in observation")
                else:
                    print("  No web elements in observation")

                # 12. Test native action path
                print("\n  [Phase 5 Real App] Testing native action path...")
                win_bounds = supervisor.inspect_window(primary_hwnd).bounds if supervisor.is_window(primary_hwnd) else Rect(0, 0, 0, 0)
                target_native = ActionTarget(
                    session_id="real-app-native-test",
                    target_id=hex(primary_hwnd),
                    reference="native_window",
                    plane=TargetPlane.NATIVE_SHELL,
                    epoch=registry.current_epoch,
                    affordance_point=(300, 200),
                    native_hwnd=primary_hwnd,
                    bounds=win_bounds,
                )
                native_req = ActionRequest(
                    session_id="real-app-native-test",
                    reference="native_window",
                    action_type=ActionType.CLICK,
                    observation_epoch=registry.current_epoch,
                )

                # Register a native ref for the test
                registry.register_ref(
                    ref_id="native_window",
                    target_id=hex(primary_hwnd),
                    plane=TargetPlane.NATIVE_SHELL,
                    role="window",
                    name="Anki Maths",
                    bounds=target_native.bounds,
                )

                precon_native = ActionabilityResult(
                    ref_id="native_window",
                    plane=TargetPlane.NATIVE_SHELL,
                    is_actionable=True,
                    affordance_point=(300, 200),
                )
                native_receipt = await native_executor.execute_action(
                    request=native_req,
                    target=target_native,
                    precondition_result=precon_native,
                )
                if native_receipt:
                    print(f"  Native Receipt: status={native_receipt.dispatch_status}, method={native_receipt.dispatch_method}")
                    self.assertIsInstance(native_receipt, ActionReceipt)
                else:
                    print("  Native receipt returned None (expected if preconditions unavailable)")

                print("\n  [OK] Phase 5 Real App Validation COMPLETE")

            finally:
                if 'core' in locals() and core.is_connected:
                    await core.disconnect()
                if 'flaui' in locals() and flaui.is_connected:
                    await flaui.disconnect()
                ProcessCleanup.safe_cleanup(pid_file="phase5_anki.pid")

        asyncio.run(run_integration())


if __name__ == "__main__":
    unittest.main()
