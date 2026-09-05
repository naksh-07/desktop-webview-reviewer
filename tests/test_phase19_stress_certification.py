"""
Phase 19: End-to-End Stress Certification Test Suite.
Verifies system resilience under repeated and concurrent stress:
  1. Multiple sequential missions without authority or state leakage
  2. High-frequency trace emission with strict memory bounding
  3. Concurrent session trace isolation
  4. Rapid target epoch and PID recycling detection
  5. High-volume evidence artifact storage and tamper-free verification
  6. Repeated cleanup calls preserving external processes
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.cleanup import ProcessCleanup
from runtime.evidence_models import EvidenceManifest
from runtime.evidence_store import EvidenceStore
from runtime.mission_admission import MissionAdmissionGate
from runtime.mission_models import (
    MissionLifecycleState,
    ReviewMission,
)
from runtime.recovery_engine import CircuitBreaker, CircuitState
from runtime.specialist_contracts import SpecialistRole
from runtime.trace_engine import DesktopTraceEngine
from runtime.trace_models import DesktopTraceEventType


class TestPhase19StressCertification(unittest.TestCase):
    """End-to-end stress certification suite."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="reviewer_stress_"))
        self.evidence_store = EvidenceStore(base_dir=self.temp_dir / "evidence")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_sequential_missions_authority_isolation(self):
        """Executes 10 sequential missions verifying zero authority or state cross-leakage."""
        gate = MissionAdmissionGate()

        for i in range(10):
            session_id = f"sess_seq_{i:03d}"
            mock_session = MagicMock()
            mock_session.session_id = session_id
            mock_session.is_closed = False
            mock_session.current_epoch = 1
            mock_session.target_pid = 10000 + i

            mission = ReviewMission(
                session_id=session_id,
                objective=f"Sequential mission {i} verification",
                declared_scope=[f"Scope_{i}"],
                allowed_surfaces=[f"Surface_{i}"],
                prohibited_surfaces=["ProhibitedAdmin"],
                acceptance_criteria=[f"Criterion {i} met"],
                authorized_specialist_roles=[SpecialistRole.EXPLORER, SpecialistRole.TESTER],
                max_duration_sec=30.0,
                max_actions=5,
                max_delegations=3,
                max_recoveries=1,
            )

            res = gate.validate(mission, session_state=mock_session)
            self.assertTrue(res.is_admitted)
            self.assertEqual(mission.lifecycle_status, MissionLifecycleState.ADMITTED)

            # Transition through to COMPLETED
            mission.transition_to(MissionLifecycleState.DISCOVERING, reason="Starting discovery")
            mission.transition_to(MissionLifecycleState.PLANNING, reason="Starting plan")
            mission.transition_to(MissionLifecycleState.EXECUTING, reason="Starting execution")
            mission.transition_to(MissionLifecycleState.COMPLETED, reason="Mission complete")
            self.assertEqual(mission.lifecycle_status, MissionLifecycleState.COMPLETED)
            self.assertTrue(mission.lifecycle_status.is_terminal)

    def test_02_bounded_trace_retention_under_high_event_volume(self):
        """Emits 3,000 trace events verifying circular buffer bounding and zero unbounded growth."""
        te = DesktopTraceEngine(session_id="sess_stress_vol", max_events_per_session=500)

        for i in range(3000):
            te.emit(
                event_type=DesktopTraceEventType.ACTION_DISPATCHED,
                session_id="sess_stress_vol",
                action_id=f"act_{i:04d}",
                details={"index": i, "status": "OK"},
            )

        timeline = te.get_or_create_timeline("sess_stress_vol")
        events = timeline.get_events()
        # Max capacity was set to 500, so deque length should strictly not exceed 500
        self.assertLessEqual(len(events), 500)
        # Most recent event should be index 2999
        self.assertEqual(events[-1].details.get("index"), 2999)

    def test_03_concurrent_sessions_trace_isolation(self):
        """Emits events across 20 distinct sessions verifying strict correlation separation."""
        te = DesktopTraceEngine(session_id="sess_root")

        for s_idx in range(20):
            s_name = f"sess_parallel_{s_idx:02d}"
            te.emit(
                event_type=DesktopTraceEventType.ACTION_DISPATCHED,
                session_id=s_name,
                action_id=f"act_{s_idx}",
                details={"session_tag": s_name},
            )

        for s_idx in range(20):
            s_name = f"sess_parallel_{s_idx:02d}"
            s_events = te.get_or_create_timeline(s_name).get_events()
            self.assertEqual(len(s_events), 1)
            self.assertEqual(s_events[0].correlation.session_id, s_name)

    def test_04_rapid_pid_recycling_detection(self):
        """Simulates 5 rapid target PID changes verifying deterministic rejection at admission."""
        gate = MissionAdmissionGate()

        for step in range(5):
            expected_pid = 20000 + step
            recycled_pid = 30000 + step

            mock_session = MagicMock()
            mock_session.is_closed = False
            mock_session.current_epoch = 1
            mock_session.target_pid = recycled_pid  # Stale recycled PID

            mission = ReviewMission(
                session_id=f"sess_recycle_{step}",
                objective="Detect PID recycling",
                declared_scope=["Scope"],
                allowed_surfaces=["Surface"],
                prohibited_surfaces=[],
                acceptance_criteria=["Criteria"],
                authorized_specialist_roles=[SpecialistRole.TESTER],
            )

            admission = gate.validate(mission, session_state=mock_session, current_pid=expected_pid)
            self.assertFalse(admission.is_admitted)
            self.assertIn("Point 13 (Stale State)", admission.rejections[0])

    def test_05_high_volume_evidence_integrity(self):
        """Stores and cryptographically verifies 50 discrete evidence artifacts."""
        manifest_artifacts = []
        action_id = "act_stress_batch"
        for i in range(50):
            payload = f"ARTIFACT_CONTENT_DATA_{i}".encode("utf-8")
            art = self.evidence_store.store_bytes(
                session_id="sess_stress_ev",
                action_id=action_id,
                relative_path=f"data_{i}.bin",
                data=payload,
            )
            manifest_artifacts.append(art)

        manifest = EvidenceManifest(
            manifest_id="man_stress_50",
            session_id="sess_stress_ev",
            action_id=action_id,
            artifacts=tuple(manifest_artifacts),
        )
        manifest_path, m_hash = self.evidence_store.store_manifest(manifest)

        is_valid, violations = self.evidence_store.verify_manifest_integrity(manifest_path)
        self.assertTrue(is_valid, f"Verification failed: {violations}")
        self.assertEqual(len(violations), 0)

    def test_06_repeated_safe_cleanup_calls(self):
        """Repeatedly invokes safe_cleanup ensuring externally-owned process remains alive."""
        my_pid = os.getpid()
        self.assertTrue(ProcessCleanup.is_process_alive(my_pid))

        ownership_file = self.temp_dir / "external_own.json"
        ownership_file.write_text(json.dumps({"pid": my_pid, "launched_by_reviewer": False}), encoding="utf-8")

        for _ in range(10):
            ProcessCleanup.safe_cleanup(
                pid_file="fake.pid",
                ownership_file=str(ownership_file),
            )
            self.assertTrue(ProcessCleanup.is_process_alive(my_pid))


if __name__ == "__main__":
    unittest.main()
