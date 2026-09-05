"""
Real-Application Validation Suite: Anki Maths (PyQt6 + QtWebEngine + Svelte 5).
Performs end-to-end testing against the genuine Anki Maths desktop application
in both Launch Mode (reviewer-owned) and Attach Mode (externally-owned).
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
import unittest

try:
    from .env_config import CORE_SKILL_DIR, get_python_exe
except ImportError:
    from env_config import CORE_SKILL_DIR, get_python_exe

if CORE_SKILL_DIR not in sys.path:
    sys.path.insert(0, CORE_SKILL_DIR)

from adapters import get_adapter
from core.actions import WebviewActions
from core.assertions import WebviewAssertions
from core.capabilities import CapabilityRegistry
from core.cleanup import ProcessCleanup
from core.discovery import TargetDiscovery
from core.evidence import EvidenceCollector
from core.models import ProcessOwnership, Target, TargetCriteria, VerificationLevel
from detectors.engine_detector import EngineDetector
from launchers.process_launcher import ProcessLauncher


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



class TestAnkiMathsRealAppValidation(unittest.TestCase):
    """End-to-end real application verification suite on Anki Maths."""

    @classmethod
    def setUpClass(cls):
        if os.environ.get("RUN_REAL_APP_TESTS") != "1":
            raise unittest.SkipTest("Skipping real app tests (RUN_REAL_APP_TESTS!=1)")
        if not ANKI_MATHS_DIR.exists() or not ANKI_PYTHON.exists():
            raise unittest.SkipTest(f"Anki Maths not available at {ANKI_MATHS_DIR}")

    def setUp(self):
        ProcessCleanup.clean_state_files([
            "desktop_app.pid", "desktop_ws_url.txt", "desktop_ownership.json",
            "anki_screenshot.png", "anki_evidence.json", "qt_app.pid", "qt_ws_url.txt"
        ])

    def tearDown(self):
        ProcessCleanup.safe_cleanup(
            pid_file="desktop_app.pid",
            ownership_file="desktop_ownership.json"
        )

    def test_real_anki_maths_launch_mode_lifecycle(self):
        """
        Tests complete Launch Mode lifecycle against real Anki Maths:
        Launch -> Detect -> Discover -> Rank -> Attach -> Inspect DOM -> Interact -> Screenshot -> Evidence -> Cleanup.
        """
        async def run_test():
            port = ProcessLauncher.find_free_port(start_port=9230)
            print(f"\n[Real App Test] Launching Anki Maths on port {port}...")

            # 1. Framework & Engine Detection on repository
            adapter, engine_info = EngineDetector.detect_with_details(str(ANKI_MATHS_DIR))
            self.assertEqual(adapter.engine_name, "qtwebengine")
            print(f"[Real App Test] Detected Engine: {adapter.engine_name} (Confidence: {engine_info.confidence.value})")

            # 2. Launch real application
            pid = ProcessLauncher.launch(
                executable_or_script=str(ANKI_PYTHON),
                args=[str(ANKI_ENTRY)],
                adapter=adapter,
                port=port,
                pid_file="desktop_app.pid",
                log_file="desktop_app.log",
                init_delay=4.0,
                cwd=str(ANKI_MATHS_DIR),
                env_overrides={
                    "ANKIDEV": "1",
                    "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-allow-origins=http://127.0.0.1:{port},http://localhost:{port}"
                }
            )
            self.assertGreater(pid, 0)
            print(f"[Real App Test] Anki Maths spawned with PID: {pid}")

            # 3. Target Discovery & Ranking
            targets = adapter.discover_targets(host="127.0.0.1", port=port, timeout=15.0)
            self.assertTrue(len(targets) > 0, "Expected at least one webview target from Anki Maths")
            print(f"[Real App Test] Discovered {len(targets)} active webview target(s):")
            for t in targets:
                print(f"   Target: ID={t.id[:8]}... | Title='{t.title}' | URL={t.url}")

            # Select primary main webview / toolbar target
            criteria = TargetCriteria(target_type="page", title_pattern="webview")
            selected_target = adapter.select_target(targets, criteria)
            self.assertIsNotNone(selected_target)
            self.assertTrue(selected_target.websocket_endpoint.startswith("ws://127.0.0.1:"))
            print(f"[Real App Test] Selected Primary Target: '{selected_target.title}' -> {selected_target.websocket_endpoint}")

            # 4. Direct CDP Attachment
            session = await adapter.attach(selected_target)
            self.assertTrue(session.is_connected)
            print("[Real App Test] Successfully attached to Anki Maths webview via CDP WebSocket")

            actions = adapter.create_actions(session)
            assertions = adapter.create_assertions(session)
            collector = adapter.create_evidence_collector(session)

            try:
                # 5. Inspect DOM and Runtime
                doc_title = await session.evaluate_js("document.title")
                doc_url = await session.evaluate_js("window.location.href")
                print(f"[Real App Test] Live Page Title: '{doc_title}' | URL: '{doc_url}'")
                self.assertIn("127.0.0.1", str(doc_url))

                # 6. Verify JavaScript Environment
                arith_res = await assertions.assert_js("2 + 3", 5, "Anki Maths Math Engine Arithmetic Evaluation")
                self.assertTrue(arith_res)

                body_res = await assertions.assert_exists("body", "Anki Main Webview Body Presence")
                self.assertTrue(body_res)

                # 7. Non-destructive UI interaction / state inspection
                html_content = await collector.capture_dom_snapshot()
                self.assertGreater(len(html_content), 100, "DOM content should be non-empty")
                print(f"[Real App Test] Captured live DOM ({len(html_content)} bytes)")

                # Execute deterministic UI query on Anki elements
                element_count = await session.evaluate_js("document.querySelectorAll('*').length")
                self.assertGreater(int(element_count or 0), 5)
                print(f"[Real App Test] DOM elements inspected: {element_count} nodes")

                # 8. Capture verified live application screenshot
                screenshot_path = "anki_maths_screenshot.png"
                sha256 = await collector.capture_screenshot_file(screenshot_path)
                self.assertTrue(os.path.exists(screenshot_path))
                self.assertEqual(len(sha256), 64)
                print(f"[Real App Test] Captured live application screenshot: {screenshot_path} (SHA-256: {sha256[:16]}...)")

                # 9. Build forensic evidence report
                ownership = ProcessOwnership(
                    pid=pid,
                    create_time=time.time(),
                    launched_by_reviewer=True,
                    command=[str(ANKI_PYTHON), str(ANKI_ENTRY)],
                    port=port
                )
                report = await collector.build_report(
                    screenshot_path=screenshot_path,
                    assertions=[r.to_dict() for r in assertions.history],
                    actions=actions.history,
                    process_ownership=ownership,
                    diagnostics={
                        "application": "Anki Maths",
                        "repository": "https://github.com/naksh-07/anki-maths",
                        "framework": "PyQt6",
                        "engine": "QtWebEngine",
                        "frontend": "Svelte 5 + Vite + MathJax",
                        "page_title": selected_target.title,
                        "page_url": selected_target.url
                    },
                    verification_level=VerificationLevel.RUNTIME_VERIFIED
                )
                evidence_path = "anki_maths_evidence.json"
                collector.save_report_json(report, evidence_path)
                self.assertTrue(os.path.exists(evidence_path))
                print(f"[Real App Test] Forensic evidence written to {evidence_path}")

            finally:
                await adapter.detach(session)
                print("[Real App Test] Detached CDP session cleanly")

            # 10. Clean up reviewer-owned process
            ProcessCleanup.safe_cleanup(
                pid_file="desktop_app.pid",
                ownership_file="desktop_ownership.json"
            )
            time.sleep(1.0)
            self.assertFalse(ProcessCleanup.is_process_alive(pid), f"PID {pid} should be terminated after safe_cleanup")
            print(f"[Real App Test] Process {pid} cleanly terminated; no orphaned processes left.")

        asyncio.run(run_test())

    def test_real_anki_maths_attach_mode_safety(self):
        """
        Tests Attach Mode against externally running Anki Maths:
        Verifies reviewer attaches, inspects DOM, detaches, and leaves external application ALIVE.
        """
        async def run_test():
            port = ProcessLauncher.find_free_port(start_port=9240)
            print(f"\n[Attach Mode Test] Starting external Anki Maths process on port {port}...")

            adapter = get_adapter("qtwebengine")

            # Start externally owned process
            ext_pid = ProcessLauncher.launch(
                executable_or_script=str(ANKI_PYTHON),
                args=[str(ANKI_ENTRY)],
                adapter=adapter,
                port=port,
                pid_file="external_anki.pid",
                log_file="external_anki.log",
                init_delay=4.0,
                cwd=str(ANKI_MATHS_DIR),
                env_overrides={
                    "ANKIDEV": "1",
                    "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-allow-origins=http://127.0.0.1:{port},http://localhost:{port}"
                }
            )
            self.assertTrue(ProcessCleanup.is_process_alive(ext_pid))
            print(f"[Attach Mode Test] External application running with PID: {ext_pid}")

            # Simulate Attach Mode metadata (launched_by_reviewer = False)
            attach_ownership_file = "attached_ownership.json"
            with open(attach_ownership_file, "w", encoding="utf-8") as f:
                json.dump({
                    "pid": ext_pid,
                    "create_time": time.time(),
                    "launched_by_reviewer": False,
                    "command": "external_start",
                    "port": port
                }, f)

            try:
                # 1. Discover targets from running application
                targets = adapter.discover_targets(host="127.0.0.1", port=port, timeout=12.0)
                self.assertGreater(len(targets), 0)
                target = adapter.select_target(targets, TargetCriteria(target_type="page"))

                # 2. Attach
                session = await adapter.attach(target)
                self.assertTrue(session.is_connected)

                # 3. Inspect DOM
                assertions = adapter.create_assertions(session)
                res = await assertions.assert_js("typeof window", "object", "Window Global Object Exists")
                self.assertTrue(res)

                # 4. Detach session
                await adapter.detach(session)
                print("[Attach Mode Test] Reviewer detached from external session")

                # 5. Execute safe cleanup with attach metadata
                ProcessCleanup.safe_cleanup(
                    pid_file="external_anki.pid",
                    ownership_file=attach_ownership_file
                )

                # 6. Verify externally owned process remains ALIVE!
                self.assertTrue(
                    ProcessCleanup.is_process_alive(ext_pid),
                    f"Attach Mode Safety Violation: External process {ext_pid} was terminated!"
                )
                print(f"[Attach Mode Test] PASS: External process {ext_pid} remained alive after detachment!")

            finally:
                # Clean up the external process now that test is finished
                ProcessCleanup.terminate_process_tree(ext_pid, expected_create_time=None)
                if os.path.exists(attach_ownership_file):
                    os.remove(attach_ownership_file)
                if os.path.exists("external_anki.pid"):
                    os.remove("external_anki.pid")
                print(f"[Attach Mode Test] Teardown complete.")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
