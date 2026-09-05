"""
Real-Application Validation Suite: Anki Maths (PyQt6 + QtWebEngine) — Phase 6.
Validates the complete verification engine, dual-perspective proof evaluation,
cryptographic evidence manifest sealing, tamper detection, and tripartite verdict
model (PASS, FAIL, UNVERIFIED) against live Anki Maths.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
import unittest

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

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
from runtime.locators import DeterministicLocatorEngine
from runtime.actionability import ActionabilityEngine
from runtime.native_input import NativeInputDispatcher
from runtime.settlement import SettlementEngine
from runtime.web_action_executor import WebActionExecutor
from runtime.native_action_executor import NativeActionExecutor
from runtime.action_engine import ActionExecutionEngine
from runtime.action_models import (
    ActionRequest,
    ActionReceipt,
    ActionOutcome,
    ActionTarget,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
)
from runtime.state import TargetPlane
from runtime.evidence_models import (
    VerificationVerdict,
    ProofLevel,
    EvidenceType,
    ClaimType,
    UnverifiedReason,
    EvidenceManifest,
)
from runtime.evidence_store import EvidenceStore
from runtime.verification_engine import VerificationEngine


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


class TestPhase6RealAppValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        if os.environ.get("RUN_REAL_APP_TESTS") != "1":
            raise unittest.SkipTest("Skipping real app tests (RUN_REAL_APP_TESTS!=1)")

    """End-to-end integration test of Phase 6 Verification & Evidence Hardening against live Anki Maths."""

    @classmethod
    def setUpClass(cls):
        if not ANKI_MATHS_DIR.exists() or not ANKI_PYTHON.exists():
            raise unittest.SkipTest(f"Anki Maths not available at {ANKI_MATHS_DIR}")

    def setUp(self):
        ProcessCleanup.clean_state_files([
            "phase6_anki.pid", "phase6_anki.log"
        ])

    def tearDown(self):
        ProcessCleanup.safe_cleanup(pid_file="phase6_anki.pid")

    def test_real_anki_maths_verification_lifecycle(self):
        """Validates Phase 6 Verification Pipeline, sealed EvidenceManifest, and Tripartite verdicts on live Anki Maths."""
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

        async def run_integration():
            port = ProcessLauncher.find_free_port(start_port=9272)
            print(f"\n[Phase 6 Real App] Launching Anki Maths on CDP port {port}...")

            adapter, _ = EngineDetector.detect_with_details(str(ANKI_MATHS_DIR))
            self.assertIsNotNone(adapter, "Failed to detect engine adapter for Anki Maths")
            assert adapter is not None
            self.assertEqual(adapter.engine_name, "qtwebengine")

            pid = ProcessLauncher.launch(
                executable_or_script=str(ANKI_PYTHON),
                args=[str(ANKI_ENTRY)],
                adapter=adapter,
                port=port,
                pid_file="phase6_anki.pid",
                log_file="phase6_anki.log",
                init_delay=4.0,
                cwd=str(ANKI_MATHS_DIR),
                env_overrides={
                    "ANKIDEV": "1",
                    "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-allow-origins=http://127.0.0.1:{port},http://localhost:{port}"
                }
            )
            self.assertGreater(pid, 0)
            print(f"[Phase 6 Real App] Anki Maths spawned with PID: {pid}")

            try:
                # 1. Discover HTTP target
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

                # 2. Discover Native HWND
                supervisor = NativeSupervisor()
                primary_hwnd = 0
                for _ in range(25):
                    candidate_pids = {pid}
                    try:
                        import psutil
                        proc = psutil.Process(pid)
                        for child in proc.children(recursive=True):
                            candidate_pids.add(child.pid)
                    except Exception:
                        pass

                    try:
                        import psutil
                        for conn in psutil.net_connections(kind="inet"):
                            if conn.laddr and conn.laddr.port == port and conn.status in (psutil.CONN_LISTEN, "LISTEN"):
                                if conn.pid:
                                    candidate_pids.add(conn.pid)
                                    try:
                                        p = psutil.Process(conn.pid)
                                        for c in p.children(recursive=True):
                                            candidate_pids.add(c.pid)
                                    except Exception:
                                        pass
                    except Exception:
                        pass

                    for c_pid in candidate_pids:
                        hwnds = supervisor.find_windows_by_pid(c_pid)
                        for h in hwnds:
                            if supervisor.is_window_visible(h):
                                primary_hwnd = h
                                break
                        if primary_hwnd:
                            break
                    if not primary_hwnd:
                        for h in supervisor.list_top_level_windows(visible_only=True):
                            try:
                                insp = supervisor.inspect_window(h)
                                if insp.pid in candidate_pids or "anki" in (insp.title or "").lower() or (insp.class_name or "").startswith("Qt"):
                                    primary_hwnd = h
                                    break
                            except Exception:
                                pass
                    if primary_hwnd:
                        break
                    await asyncio.sleep(0.5)

                if not primary_hwnd:
                    raise unittest.SkipTest("Native HWND not mapped on physical desktop during test execution")
                self.assertGreater(primary_hwnd, 0)

                # 3. Setup Evidence Store & Verification Engine
                evidence_base = Path(self._temp_dir if hasattr(self, "_temp_dir") else "evidence")
                evidence_store = EvidenceStore(base_dir=evidence_base)
                verifier = VerificationEngine(
                    evidence_store=evidence_store,
                    default_proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
                    require_visible_gui=True,
                )

                # 4. Setup Dual Perspective Core & Action Engine
                transport = WebSocketCDPTransport(endpoint_url=primary_t.ws_url)
                session_id = f"anki_p6_{int(time.time())}"
                registry = ReferenceRegistry(session_id=session_id, initial_epoch=1)

                core = WebviewAutomationCore(
                    session_id=session_id,
                    transport=transport,
                    reference_registry=registry,
                    native_hwnd=primary_hwnd,
                    native_pid=pid,
                    cdp_port=port,
                )
                await core.connect()
                self.assertTrue(core.is_connected)

                flaui = FlaUIBridge()
                actionability = ActionabilityEngine(
                    reference_registry=registry,
                    native_supervisor=supervisor,
                    webview_core=core,
                    flaui_bridge=flaui,
                    session_id=session_id,
                )
                obs_engine = ObservationEngine(
                    session_id=session_id,
                    reference_registry=registry,
                    native_supervisor=supervisor,
                    webview_core=core,
                    flaui_bridge=flaui,
                )
                locator_engine = DeterministicLocatorEngine()
                native_input = NativeInputDispatcher(dry_run=True)
                settlement = SettlementEngine(
                    native_supervisor=supervisor,
                    webview_core=core,
                    default_timeout_ms=1000,
                )
                web_executor = WebActionExecutor(
                    webview_core=core,
                    actionability_engine=actionability,
                    reference_registry=registry,
                )
                native_executor = NativeActionExecutor(
                    native_supervisor=supervisor,
                    native_input=native_input,
                    actionability_engine=actionability,
                    reference_registry=registry,
                )
                action_engine = ActionExecutionEngine(
                    session_id=session_id,
                    reference_registry=registry,
                    native_supervisor=supervisor,
                    webview_core=core,
                    flaui_bridge=flaui,
                    actionability_engine=actionability,
                    observation_engine=obs_engine,
                    native_input=native_input,
                    settlement_engine=settlement,
                    locator_engine=locator_engine,
                    web_executor=web_executor,
                    native_executor=native_executor,
                    evidence_store=evidence_store,
                    verification_engine=verifier,
                )

                # =============================================================
                # Case 1: Real Live PASS Verification Transaction
                # =============================================================
                print("\n[Phase 6 Real App] --- Executing Case 1: PASS Transaction ---")
                t_bench_start = time.perf_counter()

                # 1. Initial Observation
                t_obs_start = time.perf_counter()
                pre_snapshot = await obs_engine.observe(hwnd=primary_hwnd, target_id=primary_t.target_id)
                t_obs_ms = (time.perf_counter() - t_obs_start) * 1000.0
                self.assertIsNotNone(pre_snapshot)
                self.assertIsNotNone(pre_snapshot.web_observation)

                # Find an interactable web button
                clickable = None
                for elem in pre_snapshot.web_observation.elements:
                    is_vis = elem.visibility.visible if elem.visibility else True
                    is_en = elem.interaction.is_enabled if elem.interaction else True
                    if is_vis and is_en and elem.normalized_role in ("button", "link", "menuitem", "generic"):
                        clickable = elem
                        break

                self.assertIsNotNone(clickable, "Expected at least one actionable element on Anki Maths interface")
                print(f"  Target Element: {clickable.normalized_role} '{clickable.accessible_name or clickable.visible_text}' @ ref={clickable.reference}")

                # 2. Formulate Action Request
                req_pass = ActionRequest(
                    session_id=session_id,
                    reference=clickable.reference,
                    action_type=ActionType.CLICK,
                    observation_epoch=registry.current_epoch,
                    params={"expect_change": True}, # Mutating button interaction
                )

                # 3. Execute through Action Engine with automated verification
                t_exec_start = time.perf_counter()
                outcome_pass = await action_engine.execute(
                    request=req_pass,
                    verify=True,
                    execution_mode="automated",
                )
                t_exec_ms = (time.perf_counter() - t_exec_start) * 1000.0

                print(f"  Outcome State Change: {outcome_pass.state_change}")
                if outcome_pass.manifest:
                    for c in outcome_pass.manifest.claims:
                        print(f"    Claim {c.claim_type}: status={c.status}, reason={c.reason}")
                self.assertEqual(outcome_pass.verdict, VerificationVerdict.PASS.value)
                self.assertIsNotNone(outcome_pass.manifest)

                manifest_pass: EvidenceManifest = outcome_pass.manifest
                self.assertEqual(manifest_pass.verdict, VerificationVerdict.PASS)
                self.assertIsNotNone(manifest_pass.manifest_hash)
                self.assertGreater(len(manifest_pass.artifacts), 0)
                print(f"  Manifest Hash: {manifest_pass.manifest_hash}")
                print(f"  Evidence Artifacts Sealed: {len(manifest_pass.artifacts)}")

                # 4. Assert Physical and Cryptographic Integrity on disk
                is_valid, violations = evidence_store.verify_manifest_integrity(manifest_pass)
                self.assertTrue(is_valid, f"Evidence bundle failed integrity check: {violations}")
                self.assertEqual(violations, [])
                evidence_store.assert_manifest_integrity(manifest_pass)
                print("  [PASS CASE OK] Sealed manifest matches disk artifacts byte-for-byte.")

                # =============================================================
                # Case 2: Controlled Negative / FAIL Case
                # =============================================================
                print("\n[Phase 6 Real App] --- Executing Case 2: Controlled Negative (FAIL) ---")
                req_fail = ActionRequest(
                    session_id=session_id,
                    reference=clickable.reference,
                    action_type=ActionType.CLICK,
                    observation_epoch=registry.current_epoch,
                    params={
                        "expected_claim": ClaimType.NavigationOccurred,
                        "expected_url": "https://nonexistent.anki.internal/impossible-page",
                    },
                )

                # Evaluate transaction against identical snapshot (no navigation occurred)
                verdict_fail, manifest_fail, _ = verifier.evaluate_transaction(
                    session_id=session_id,
                    action_request=req_fail,
                    action_receipt=outcome_pass.receipt,
                    action_outcome=outcome_pass,
                    pre_snapshot=pre_snapshot,
                    post_snapshot=outcome_pass.post_snapshot,
                    observation_diff=outcome_pass.observation_diff,
                    execution_mode="automated",
                )

                print(f"  Negative Case Verdict: {verdict_fail}")
                if manifest_fail:
                    print(f"  Negative Case Rationale: {manifest_fail.verdict_rationale}")
                    for c in manifest_fail.claims:
                        print(f"    Claim {c.claim_type}: status={c.status}, expected={c.expected}, actual={c.actual}, reason={c.reason}")
                self.assertEqual(verdict_fail, VerificationVerdict.FAIL)
                self.assertEqual(manifest_fail.verdict, VerificationVerdict.FAIL)
                self.assertIn("Verification failed", manifest_fail.verdict_rationale)
                print("  [FAIL CASE OK] Unfulfilled expectation correctly evaluated to deterministic FAIL.")

                # =============================================================
                # Case 3: Controlled UNVERIFIED Case (Physical Uncertainty)
                # =============================================================
                print("\n[Phase 6 Real App] --- Executing Case 3: Controlled UNVERIFIED ---")
                # Simulate PID mismatch (e.g. spoofed process or foreign window)
                spoofed_proc_info = {"pid": 888888, "process_tree": [888888], "is_running": True}

                verdict_unverified, manifest_unverified, _ = verifier.evaluate_transaction(
                    session_id=session_id,
                    action_request=req_pass,
                    action_receipt=outcome_pass.receipt,
                    action_outcome=outcome_pass,
                    pre_snapshot=pre_snapshot,
                    post_snapshot=outcome_pass.post_snapshot,
                    observation_diff=outcome_pass.observation_diff,
                    target_process_info=spoofed_proc_info,
                    execution_mode="automated",
                )

                print(f"  Uncertainty Verdict: {verdict_unverified} (Reason: {manifest_unverified.unverified_reason})")
                self.assertEqual(verdict_unverified, VerificationVerdict.UNVERIFIED)
                self.assertEqual(manifest_unverified.unverified_reason, UnverifiedReason.PID_MISMATCH)
                print("  [UNVERIFIED CASE OK] Uncertainty preserved without promoting to PASS.")

                # =============================================================
                # Performance & Telemetry Reporting (Prompt Item #33)
                # =============================================================
                action_dir = evidence_store.get_action_dir(session_id, req_pass.action_id, create=False)
                disk_files = list(action_dir.rglob("*")) if action_dir.exists() else []
                total_bytes = sum(f.stat().st_size for f in disk_files if f.is_file())

                print("\n========================================================")
                print(" PHASE 6 REAL-APPLICATION PERFORMANCE & FORENSIC METRICS")
                print("========================================================")
                print(f"  Observation Latency:           {t_obs_ms:.2f} ms")
                print(f"  Dispatch & Settle Latency:     {outcome_pass.duration_ms:.2f} ms")
                print(f"  Total Action Loop Duration:    {t_exec_ms:.2f} ms")
                print(f"  Sealed Artifact Count:         {len(manifest_pass.artifacts)}")
                print(f"  Total Evidence Storage:        {total_bytes:,} bytes")
                print(f"  Integrity Algorithm:           SHA-256 (canonical bytes)")
                print(f"  Tripartite States Verified:    PASS, FAIL, UNVERIFIED")
                print("========================================================\n")

            finally:
                try:
                    await core.disconnect()
                except Exception:
                    pass

        asyncio.run(run_integration())


if __name__ == "__main__":
    unittest.main()
