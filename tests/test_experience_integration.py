"""
Tests for Runtime Experience Integration Adapter (Prompt 2).
Verifies:
- Session lifecycle persistence (create -> activate -> close)
- Mission lifecycle persistence (admit -> complete)
- Action lifecycle preservation (REQUESTED -> DISPATCHED -> SETTLED)
- Trace reference persistence and filtering of significant events
- Evidence reference persistence (artifact_id, sha256, relative path) with NO binary blobs
- Verification tripartite preservation (PASS, FAIL, UNVERIFIED)
- Recovery attempt auditing
- Graceful degradation: database failures never break live reviewer execution
"""

import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from runtime.experience.config import ExperienceConfig
from runtime.experience.store import ExperienceStore
from runtime.experience.adapter import ExperienceIntegrationAdapter
from runtime.experience.models import (
    SessionExperienceRecord,
    MissionExperienceRecord,
    ActionReferenceRecord,
    TraceReferenceRecord,
    EvidenceReferenceRecord,
    OutcomeRecord,
    NormalizedFailureRecord,
    RecoveryExperienceRecord,
    ExperienceScope,
)
from runtime.recovery_engine import RecoveryAttemptRecord, RecoveryAction
from runtime.diagnostics import FailureCategory
from runtime.state import TargetPlane


class TestExperienceIntegrationAdapter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="exp_adapter_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir))
        self.store = ExperienceStore(self.config)
        self.addCleanup(self.store.close)
        self.adapter = ExperienceIntegrationAdapter(self.store)

    def test_session_lifecycle_persistence(self):
        """Verifies session persistence through create, activate, and close lifecycle."""
        session_id = "sess_integration_001"

        # 1. Created
        self.adapter.on_session_created(
            session_id=session_id,
            target_executable="testapp.exe",
            target_pid=1234,
            target_hwnd=0x10050,
            active_plane="NATIVE_SHELL",
            project_id="test_project",
        )
        sess = self.store.get_session(session_id)
        self.assertIsNotNone(sess)
        self.assertEqual(sess.status, "INITIALIZING")
        self.assertEqual(sess.target_executable, "testapp.exe")
        self.assertEqual(sess.target_pid, 1234)
        self.assertEqual(sess.target_hwnd, "0x10050")
        self.assertEqual(sess.project_id, "test_project")

        # 2. Activated
        self.adapter.on_session_activated(session_id=session_id)
        sess = self.store.get_session(session_id)
        self.assertEqual(sess.status, "RUNNING")

        # 3. Closed
        self.adapter.on_session_closed(session_id=session_id, status="CLOSED")
        sess = self.store.get_session(session_id)
        self.assertEqual(sess.status, "CLOSED")
        self.assertIsNotNone(sess.completion_time)

    def test_mission_lifecycle_persistence(self):
        """Verifies admitted missions and their completion are persisted with correlation."""
        session_id = "sess_mission_001"
        mission_id = "mission_audit_001"

        # Create session first
        self.adapter.on_session_created(session_id=session_id)

        # 1. Mission Admitted
        mission_mock = MagicMock()
        mission_mock.mission_id = mission_id
        mission_mock.goal = "Verify login dialog opens"
        mission_mock.scope = "SESSION"
        mission_mock.started_at = time.time()
        mission_mock.project_id = "proj_test"
        mission_mock.safe_metadata = {"target_button": "btn_login"}

        self.adapter.on_mission_admitted(session_id=session_id, mission=mission_mock)

        missions = self.store.get_missions_for_session(session_id)
        self.assertEqual(len(missions), 1)
        self.assertEqual(missions[0].mission_id, mission_id)
        self.assertEqual(missions[0].execution_status, "ADMITTED")
        self.assertEqual(missions[0].goal, "Verify login dialog opens")

        # 2. Mission Completed
        self.adapter.on_mission_completed(
            session_id=session_id,
            mission=mission_mock,
            execution_status="COMPLETED",
            verdict="PASS",
        )
        missions = self.store.get_missions_for_session(session_id)
        self.assertEqual(missions[0].execution_status, "COMPLETED")
        self.assertIsNotNone(missions[0].completion_time)

    def test_action_lifecycle_and_dispatch_fallacy_prevention(self):
        """
        Verifies that ACTION_REQUESTED, ACTION_DISPATCHED, and ACTION_SETTLED
        maintain distinct historical states, preventing the Dispatch Fallacy.
        """
        session_id = "sess_action_001"
        action_id = "act_click_save"

        self.adapter.on_session_created(session_id=session_id)

        # 1. Action Requested
        req_mock = MagicMock()
        req_mock.action_id = action_id
        req_mock.action_type.value = "CLICK"
        req_mock.reference = "ref_button_1"
        req_mock.params = {"button": "left"}
        req_mock.timeout_ms = 3000

        self.adapter.on_action_requested(session_id, req_mock)
        actions = self.store.get_actions_for_session(session_id)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action_id, action_id)
        self.assertEqual(actions[0].status, "REQUESTED")

        # 2. Action Dispatched
        receipt_mock = MagicMock()
        receipt_mock.action_id = action_id
        receipt_mock.plane.value = "NATIVE_SHELL"
        receipt_mock.dispatch_status.value = "DISPATCHED"
        receipt_mock.duration_ms = 45.2
        receipt_mock.trace_id = "trace_001"

        self.adapter.on_action_dispatched(session_id, req_mock, receipt_mock)
        actions = self.store.get_actions_for_session(session_id)
        self.assertEqual(actions[0].status, "DISPATCHED")
        self.assertEqual(actions[0].duration_ms, 45.2)

        # 3. Action Settled (Verified)
        outcome_mock = MagicMock()
        outcome_mock.action_id = action_id
        outcome_mock.duration_ms = 180.5
        outcome_mock.verdict = "PASS"
        outcome_mock.manifest = MagicMock(manifest_id="man_001")
        outcome_mock.details = {"diff": "layout_shifted"}

        self.adapter.on_action_settled(session_id, req_mock, receipt_mock, outcome_mock)
        actions = self.store.get_actions_for_session(session_id)
        self.assertEqual(actions[0].status, "SETTLED")
        self.assertEqual(actions[0].duration_ms, 180.5)
        self.assertEqual(actions[0].provenance.evidence_reference, "man_001")

    def test_trace_persistence_and_filtering(self):
        """Verifies canonical trace events are persisted while non-significant spam is omitted."""
        session_id = "sess_trace_001"
        self.adapter.on_session_created(session_id=session_id)

        # 1. Significant event (ACTION_REQUESTED)
        sig_event = MagicMock()
        sig_event.event_id = "ev_sig_001"
        sig_event.correlation = MagicMock(session_id=session_id, action_id="act_01", mission_id=None)
        sig_event.sequence_monotonic = 1
        sig_event.event_type = MagicMock(value="ACTION_REQUESTED")
        sig_event.plane = MagicMock(value="NATIVE_SHELL")
        sig_event.timestamp = time.time()
        sig_event.status = "SUCCESS"
        sig_event.details = {"sensitive": "password 12345"}
        sig_event.artifact_references = []

        self.adapter.on_trace_event(sig_event)

        traces = self.store.get_traces_for_session(session_id)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].event_id, "ev_sig_001")
        # Ensure password is redacted by privacy enforcer
        self.assertNotIn("12345", traces[0].metadata_json)

        # 2. Non-significant spam event (e.g. HEARTBEAT or INTERNAL_TICK)
        spam_event = MagicMock()
        spam_event.event_id = "ev_spam_002"
        spam_event.correlation = MagicMock(session_id=session_id, action_id=None, mission_id=None)
        spam_event.sequence_monotonic = 2
        spam_event.event_type = MagicMock(value="INTERNAL_TICK")
        spam_event.plane = MagicMock(value="NATIVE")
        spam_event.timestamp = time.time()
        spam_event.status = "SUCCESS"
        spam_event.details = {}
        spam_event.artifact_references = []

        self.adapter.on_trace_event(spam_event)

        # Count should still be 1 because INTERNAL_TICK was filtered
        traces = self.store.get_traces_for_session(session_id)
        self.assertEqual(len(traces), 1)

    def test_evidence_reference_integrity_no_binary_blobs(self):
        """
        Verifies evidence references persist artifact metadata, paths, and SHA-256
        WITHOUT copying or storing raw binary payloads into SQLite.
        """
        session_id = "sess_evidence_001"
        self.adapter.on_session_created(session_id=session_id)

        artifact_mock = MagicMock()
        artifact_mock.artifact_id = "art_screenshot_101"
        artifact_mock.mime_type = "image/png"
        artifact_mock.sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        artifact_mock.relative_path = "artifacts/screenshots/login.png"
        artifact_mock.size_bytes = 45000
        artifact_mock.metadata = {"epoch": 1, "plane": "NATIVE"}

        self.adapter.on_evidence_created(
            session_id=session_id,
            artifact=artifact_mock,
            action_id="act_click",
        )

        evidence_records = self.store.get_evidence_for_session(session_id)
        self.assertEqual(len(evidence_records), 1)
        rec = evidence_records[0]
        self.assertEqual(rec.artifact_id, "art_screenshot_101")
        self.assertEqual(rec.sha256, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertEqual(rec.relative_path, "artifacts/screenshots/login.png")

        # Verify directly in SQLite that no BLOB columns exist in evidence_references table
        db_path = self.config.database_path
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(evidence_references)")
            columns = cursor.fetchall()
            for col in columns:
                col_type = col[2].upper()
                self.assertNotEqual(col_type, "BLOB", f"Column {col[1]} must not be BLOB in evidence_references")

    def test_verification_tripartite_preservation(self):
        """
        Verifies that PASS, FAIL, and UNVERIFIED verdicts are preserved strictly
        without reinterpretation or conversion.
        """
        session_id = "sess_verif_001"
        self.adapter.on_session_created(session_id=session_id)

        for verdict_str in ("PASS", "FAIL", "UNVERIFIED"):
            manifest_mock = MagicMock()
            manifest_mock.manifest_id = f"man_{verdict_str.lower()}"
            manifest_mock.verdict = MagicMock(value=verdict_str)
            manifest_mock.confidence = 0.85
            manifest_mock.primary_failure = "Target obscured" if verdict_str != "PASS" else None
            manifest_mock.timestamp = time.time()
            manifest_mock.to_dict.return_value = {"checks": ["gui_visible"]}

            self.adapter.on_verification_completed(
                session_id=session_id,
                manifest=manifest_mock,
                action_id=f"act_{verdict_str.lower()}",
            )

        outcomes = self.store.get_outcomes_for_session(session_id)
        self.assertEqual(len(outcomes), 3)
        verdicts = {o.verdict for o in outcomes}
        self.assertEqual(verdicts, {"PASS", "FAIL", "UNVERIFIED"})

    def test_recovery_audit_persistence(self):
        """Verifies recovery attempts are audited and linked to sessions."""
        session_id = "sess_recovery_001"
        self.adapter.on_session_created(session_id=session_id)

        rec_mock = RecoveryAttemptRecord(
            recovery_id="rec_001",
            failure_id="fail_001",
            trigger_category=FailureCategory.TARGET_NOT_FOUND,
            action=RecoveryAction.REFRESH_OBSERVATION,
            attempt_number=1,
            max_attempts=2,
            started_at=time.time(),
            duration_ms=250.0,
            result="SUCCESS",
            evidence_refs=["art_after_refresh"],
            error=None,
        )

        self.adapter.on_recovery_completed(
            session_id=session_id,
            recovery_record=rec_mock,
            action_id="act_locate",
        )

        recoveries = self.store.get_recovery_attempts(session_id=session_id)
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0].recovery_id, "rec_001")
        self.assertEqual(recoveries[0].trigger_category, FailureCategory.TARGET_NOT_FOUND.value)
        self.assertEqual(recoveries[0].action, RecoveryAction.REFRESH_OBSERVATION.value)
        self.assertEqual(recoveries[0].result, "SUCCESS")

    def test_graceful_degradation_when_database_fails(self):
        """
        Critical requirement: If SQLite fails, locks, or raises exceptions,
        the adapter must swallow the persistence error, log a warning,
        and never crash or block the caller.
        """
        # Create a mock store that raises RuntimeError on everything
        failing_store = MagicMock()
        failing_store.record_session.side_effect = sqlite3.OperationalError("database is locked")
        failing_store.record_mission.side_effect = sqlite3.DatabaseError("disk I/O error")
        failing_store.record_action_reference.side_effect = RuntimeError("SQLite unavailable")
        failing_store.record_trace_reference.side_effect = Exception("General error")
        failing_store.record_evidence_reference.side_effect = Exception("Write failed")
        failing_store.record_outcome.side_effect = Exception("Store corrupted")
        failing_store.record_failure.side_effect = Exception("Failure write failed")
        failing_store.record_recovery_attempt.side_effect = Exception("Recovery write failed")

        degraded_adapter = ExperienceIntegrationAdapter(failing_store)

        # None of these calls should raise any exception
        degraded_adapter.on_session_created("sess_deg", target_executable="app.exe")
        degraded_adapter.on_session_activated("sess_deg")
        degraded_adapter.on_session_closed("sess_deg")

        mission_mock = MagicMock(mission_id="m_deg", goal="g", scope="SESSION", started_at=0.0)
        degraded_adapter.on_mission_admitted("sess_deg", mission_mock)
        degraded_adapter.on_mission_completed("sess_deg", mission_mock, "COMPLETED", "PASS")

        req_mock = MagicMock(action_id="a_deg", action_type=MagicMock(value="CLICK"), reference="ref1", params={})
        degraded_adapter.on_action_requested("sess_deg", req_mock)

        receipt_mock = MagicMock(action_id="a_deg", plane=MagicMock(value="NATIVE"), dispatch_status=MagicMock(value="DISPATCHED"), duration_ms=1.0)
        degraded_adapter.on_action_dispatched("sess_deg", req_mock, receipt_mock)

        outcome_mock = MagicMock(action_id="a_deg", duration_ms=1.0, verdict="PASS", manifest=None, details={})
        degraded_adapter.on_action_settled("sess_deg", req_mock, receipt_mock, outcome_mock)

        trace_mock = MagicMock(event_id="t_deg", correlation=MagicMock(session_id="s"), sequence_monotonic=1, event_type=MagicMock(value="ACTION_REQUESTED"), plane=MagicMock(value="NATIVE"), timestamp=0.0, status="OK", details={}, artifact_references=[])
        degraded_adapter.on_trace_event(trace_mock)

        art_mock = MagicMock(artifact_id="art_deg", mime_type="text/plain", sha256="abc", relative_path="path", size_bytes=10, metadata={})
        degraded_adapter.on_evidence_created("sess_deg", art_mock)

        manifest_mock = MagicMock(manifest_id="m_deg", verdict=MagicMock(value="PASS"), confidence=1.0, primary_failure=None, timestamp=0.0, to_dict=lambda: {})
        degraded_adapter.on_verification_completed("sess_deg", manifest_mock)

        degraded_adapter.on_failure_diagnosed("sess_deg", error="Simulated timeout")

        rec_mock = RecoveryAttemptRecord(
            recovery_id="r_deg", failure_id="f_deg", trigger_category=FailureCategory.PROCESS_HANG,
            action=RecoveryAction.WAIT_FOR_PROCESS, attempt_number=1, max_attempts=1,
            started_at=0.0, duration_ms=0.0, result="FAILED"
        )
        degraded_adapter.on_recovery_completed("sess_deg", rec_mock)

        # If we reached here without exception, graceful degradation succeeded
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
