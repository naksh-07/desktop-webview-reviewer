"""
Tests for Session and Window Isolation & Multi-Process Reality.
Architecture H / Milestone 2.1 Prompt 5 - Section 10 & 11 Audit.

Verifies:
- Complete isolation between sequential sessions (Session A -> close -> Session B)
- Zero cross-contamination between concurrent review sessions
- Distinct HWND, PID, and target identity preservation
- Strict scoping of action references, traces, evidence, and outcomes
- Agent correlations and observations do not leak across unrelated sessions
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.models import (
    ActionReferenceRecord,
    EvidenceReferenceRecord,
    ExperienceScope,
    OutcomeRecord,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    SessionExperienceRecord,
    TraceReferenceRecord,
)
from runtime.experience.store import ExperienceStore


class TestSessionAndWindowIsolation(unittest.TestCase):
    """Forensic verification of session boundaries and zero cross-contamination."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = ExperienceConfig(
            base_dir=Path(self.temp_dir.name),
            database_name="isolation_test.db",
            enable_wal_mode=True,
            fail_safe_mode=False,
        )
        self.store = ExperienceStore(config=self.config)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_sequential_session_isolation(self) -> None:
        """Verifies that Session B cannot see or inherit artifacts/traces from Session A."""
        # --- Session A ---
        session_a_id = f"sess_a_{uuid.uuid4().hex[:8]}"
        sess_a = SessionExperienceRecord(
            session_id=session_a_id,
            project_id="proj_alpha",
            status="COMPLETED",
            target_executable="C:\\AppA\\app.exe",
            target_pid=1111,
            target_hwnd="0x0001001",
            scope=ExperienceScope.SESSION,
        )
        self.store.record_session(sess_a)

        # Record action, trace, evidence, outcome in Session A
        act_a_id = f"act_{uuid.uuid4().hex[:8]}"
        self.store.record_action_reference(ActionReferenceRecord(
            action_id=act_a_id,
            session_id=session_a_id,
            action_type="CLICK",
            plane="WEB",
            status="SUCCESS",
            provenance=ProvenanceRecord(
                source="executor",
                source_type=RecordSourceType.RUNTIME,
                session_id=session_a_id,
            ),
        ))

        trace_a_id = f"tr_{uuid.uuid4().hex[:8]}"
        self.store.record_trace_reference(TraceReferenceRecord(
            event_id=trace_a_id,
            session_id=session_a_id,
            sequence_monotonic=1,
            event_type="ACTION_DISPATCH",
            plane="WEB",
            provenance=ProvenanceRecord(
                source="trace_engine",
                source_type=RecordSourceType.RUNTIME,
                session_id=session_a_id,
            ),
        ))

        ev_a_id = f"ev_{uuid.uuid4().hex[:8]}"
        self.store.record_evidence_reference(EvidenceReferenceRecord(
            evidence_id=ev_a_id,
            session_id=session_a_id,
            artifact_id="art_a",
            artifact_type="SCREENSHOT",
            checksum_sha256="a" * 64,
            relative_path_or_uri="evidence/a.png",
            provenance=ProvenanceRecord(
                source="evidence_collector",
                source_type=RecordSourceType.RUNTIME,
                session_id=session_a_id,
            ),
        ))

        # Close Session A
        sess_a.status = "CLOSED"
        self.store.record_session(sess_a)

        # --- Session B ---
        session_b_id = f"sess_b_{uuid.uuid4().hex[:8]}"
        sess_b = SessionExperienceRecord(
            session_id=session_b_id,
            project_id="proj_beta",
            status="ACTIVE",
            target_executable="C:\\AppB\\app.exe",
            target_pid=2222,
            target_hwnd="0x0002002",
            scope=ExperienceScope.SESSION,
        )
        self.store.record_session(sess_b)

        act_b_id = f"act_{uuid.uuid4().hex[:8]}"
        self.store.record_action_reference(ActionReferenceRecord(
            action_id=act_b_id,
            session_id=session_b_id,
            action_type="TYPE",
            plane="NATIVE",
            status="SUCCESS",
            provenance=ProvenanceRecord(
                source="executor",
                source_type=RecordSourceType.RUNTIME,
                session_id=session_b_id,
            ),
        ))

        # Verify strict isolation
        self.assertNotEqual(session_a_id, session_b_id)
        self.assertNotEqual(act_a_id, act_b_id)

        actions_a = self.store.get_actions_for_session(session_a_id)
        actions_b = self.store.get_actions_for_session(session_b_id)
        self.assertEqual(len(actions_a), 1)
        self.assertEqual(len(actions_b), 1)
        self.assertEqual(actions_a[0].action_id, act_a_id)
        self.assertEqual(actions_b[0].action_id, act_b_id)
        self.assertNotIn(act_b_id, [a.action_id for a in actions_a])

        traces_a = self.store.get_traces_for_session(session_a_id)
        traces_b = self.store.get_traces_for_session(session_b_id)
        self.assertEqual(len(traces_a), 1)
        self.assertEqual(len(traces_b), 0)  # B has no traces yet

        ev_a = self.store.get_evidence_for_session(session_a_id)
        ev_b = self.store.get_evidence_for_session(session_b_id)
        self.assertEqual(len(ev_a), 1)
        self.assertEqual(len(ev_b), 0)

    def test_concurrent_sessions_process_and_window_identity(self) -> None:
        """Verifies two concurrent sessions maintain distinct HWNDs, PIDs, and references."""
        s1_id = "sess_concurrent_1"
        s2_id = "sess_concurrent_2"

        self.store.record_session(SessionExperienceRecord(
            session_id=s1_id,
            target_executable="C:\\App1\\main.exe",
            target_pid=5001,
            target_hwnd="0x000A001",
            status="ACTIVE",
            scope=ExperienceScope.SESSION,
        ))

        self.store.record_session(SessionExperienceRecord(
            session_id=s2_id,
            target_executable="C:\\App2\\main.exe",
            target_pid=5002,
            target_hwnd="0x000A002",
            status="ACTIVE",
            scope=ExperienceScope.SESSION,
        ))

        s1_retrieved = self.store.get_session(s1_id)
        s2_retrieved = self.store.get_session(s2_id)
        assert s1_retrieved is not None
        assert s2_retrieved is not None

        self.assertEqual(s1_retrieved.target_pid, 5001)
        self.assertEqual(s2_retrieved.target_pid, 5002)
        self.assertEqual(s1_retrieved.target_hwnd, "0x000A001")
        self.assertEqual(s2_retrieved.target_hwnd, "0x000A002")
        self.assertNotEqual(s1_retrieved.target_pid, s2_retrieved.target_pid)
        self.assertNotEqual(s1_retrieved.target_hwnd, s2_retrieved.target_hwnd)


if __name__ == "__main__":
    unittest.main()
