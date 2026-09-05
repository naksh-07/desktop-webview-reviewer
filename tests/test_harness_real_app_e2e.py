"""
End-to-End Real Framework Integration Test (Phase 13–14).
Demonstrates the complete developer and review workflow:
    Application Project -> harness init -> review build -> launch -> handshake ->
    lifecycle event -> diagnostic event -> Reviewer interaction -> Desktop Trace correlation ->
    physical observation -> verification -> harness remove.
"""

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from runtime.harness.detector import ProjectDetector
from runtime.harness.injector import HarnessInjector
from runtime.harness.service import HarnessService
from runtime.harness.transport import HarnessClient
from runtime.harness.manifest import IntegrationManifest
from runtime.harness_contracts import (
    BuildMode,
    HarnessLifecycleSignal,
    VerificationVerdict,
)
from runtime.trace_engine import DesktopTraceEngine
from runtime.settlement import SettlementEngine, SettlementType
from runtime.capability import CapabilityMatrix, CapabilityId, CapabilityStatus


class TestHarnessRealAppE2E(unittest.TestCase):
    """Authoritative end-to-end test of the complete harness development workflow."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="reviewer_e2e_app_"))
        self.session_id = "sess_e2e_real_01"
        self.app_id = "real_framework_app"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_complete_real_app_lifecycle_and_trace_correlation(self):
        """
        Executes the complete 10-step developer and reviewer lifecycle:
        1. Initialize project fixture
        2. harness init
        3. Start Reviewer Runtime HarnessService
        4. Application connects & completes handshake
        5. Ingest lifecycle signals
        6. Ingest diagnostic telemetry
        7. Deterministic settlement wait
        8. Desktop Trace correlation check
        9. Physical reality reconciliation
        10. Clean harness remove
        """
        # Step 1: Create application project fixture
        pkg = {
            "name": "e2e-electron-app",
            "version": "1.0.0",
            "main": "main.js",
            "dependencies": {"electron": "^28.0.0"},
        }
        (self.temp_dir / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
        orig_entry = (
            "const { app, BrowserWindow } = require('electron');\n"
            "app.on('ready', () => {\n"
            "  const win = new BrowserWindow({ width: 800, height: 600 });\n"
            "  win.loadURL('https://app.local');\n"
            "});\n"
        )
        (self.temp_dir / "main.js").write_text(orig_entry, encoding="utf-8")

        # Step 2: Run harness init
        detection = ProjectDetector.detect(self.temp_dir)
        self.assertTrue(detection.is_supported)
        self.assertEqual(detection.framework, "electron")

        plan = HarnessInjector.plan(self.temp_dir)
        manifest, report = HarnessInjector.apply(plan, dry_run=False)
        self.assertEqual(report["status"], "READY")
        self.assertTrue((self.temp_dir / "reviewer_harness.dev.js").exists())
        self.assertTrue((self.temp_dir / ".reviewer_harness.json").exists())

        # Step 3: Start Reviewer Runtime HarnessService
        trace_engine = DesktopTraceEngine(session_id=self.session_id)
        capability_matrix = CapabilityMatrix(populate_defaults=False)
        harness_service = HarnessService(
            session_id=self.session_id,
            trace_engine=trace_engine,
            capability_matrix=capability_matrix,
            build_mode=BuildMode.REVIEW,
        )

        settlement_engine = SettlementEngine()

        async def _run_flow():
            host, port = await harness_service.start()
            self.assertGreater(port, 0)

            # Step 4: Application Harness Client connects & performs handshake
            client = HarnessClient(
                endpoint_url=harness_service.endpoint_url,
                session_id=self.session_id,
                application_id=self.app_id,
                auth_token=harness_service.auth_token,
            )

            hs_resp = await client.send_message(
                "HANDSHAKE",  # type: ignore
                {
                    "capabilities": {
                        "lifecycle": "AVAILABLE",
                        "diagnostics": "AVAILABLE",
                        "fixtures": "AVAILABLE",
                        "fault_injection": "AVAILABLE",
                    }
                },
            )
            self.assertEqual(hs_resp["status"], "HANDSHAKE_ACK")
            self.assertTrue(harness_service.handshake_completed)
            self.assertEqual(capability_matrix.get_status(CapabilityId.HARNESS_CORE), CapabilityStatus.AVAILABLE)

            # Step 5: Emit lifecycle signals
            await client.emit_lifecycle("APP_STARTING", {"pid": 12345})
            await client.emit_lifecycle("APP_READY", {"platform": "win32"})
            await client.emit_lifecycle("NAVIGATION_STARTED", {"route": "/dashboard"})
            await client.emit_lifecycle("SCREEN_READY", {"screen": "Dashboard"})

            # Step 6: Emit diagnostic telemetry
            await client.emit_diagnostics({
                "current_screen": "DashboardScreen",
                "current_route": "/dashboard",
                "active_operations": [],
                "pending_operations_count": 0,
            })

            # Step 7: Deterministic settlement synchronization via Harness signal
            settle_res = await settlement_engine.wait_for_harness_signal(
                signal_predicate=lambda s: s == "SCREEN_READY",
                harness_service=harness_service,
                timeout_ms=2000,
            )
            self.assertTrue(settle_res.settled)
            self.assertEqual(settle_res.settlement_type, SettlementType.HARNESS_SIGNAL)
            self.assertEqual(settle_res.details["signal"], "SCREEN_READY")

            await harness_service.stop()

        asyncio.run(_run_flow())

        # Step 8: Desktop Trace correlation check
        events = trace_engine.get_timeline(self.session_id)
        harness_trace = [e for e in events if e.details.get("source") == "harness"]
        self.assertTrue(len(harness_trace) >= 4)
        signals_seen = [e.details.get("signal") for e in harness_trace if "signal" in e.details]
        self.assertIn("APP_READY", signals_seen)
        self.assertIn("SCREEN_READY", signals_seen)

        # Step 9: Physical Reality Reconciliation & Golden Rule
        # Case A: Physical reality is FAIL -> Final verdict remains FAIL despite SCREEN_READY
        verdict_fail = harness_service.reconcile_with_physical_reality(
            physical_reality_verdict=VerificationVerdict.FAIL,
            harness_signal=HarnessLifecycleSignal.SCREEN_READY,
        )
        self.assertEqual(verdict_fail, VerificationVerdict.FAIL)

        # Case B: Physical reality is PASS -> Final verdict is PASS
        verdict_pass = harness_service.reconcile_with_physical_reality(
            physical_reality_verdict=VerificationVerdict.PASS,
            harness_signal=HarnessLifecycleSignal.SCREEN_READY,
        )
        self.assertEqual(verdict_pass, VerificationVerdict.PASS)

        # Step 10: Clean harness removal
        rem_res = HarnessInjector.remove(self.temp_dir)
        self.assertEqual(rem_res["status"], "REMOVED")
        self.assertFalse((self.temp_dir / "reviewer_harness.dev.js").exists())
        self.assertFalse((self.temp_dir / ".reviewer_harness.json").exists())
        restored = (self.temp_dir / "main.js").read_text(encoding="utf-8").strip()
        self.assertEqual(restored, orig_entry.strip())


if __name__ == "__main__":
    unittest.main()
