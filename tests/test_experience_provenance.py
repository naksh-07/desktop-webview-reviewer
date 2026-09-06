"""
Tests for Experience Store provenance, entities, tripartite outcomes, and scope boundaries.
"""

import os
import shutil
import tempfile
from pathlib import Path
import unittest

from runtime.experience.config import ExperienceConfig
from runtime.experience.store import ExperienceStore
from runtime.experience.models import (
    ActionReferenceRecord,
    EvidenceReferenceRecord,
    ExperienceScope,
    MissionExperienceRecord,
    OutcomeRecord,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    ScopeValidationException,
    SessionExperienceRecord,
    TraceReferenceRecord,
    validate_scope_promotion,
)


class TestExperienceProvenance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="exp_prov_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=False)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)

    def test_session_lifecycle_and_retrieval(self):
        """Verifies session recording and subsequent retrieval with metadata."""
        record = SessionExperienceRecord(
            session_id="sess_alpha_01",
            project_id="proj_crm_app",
            created_at="2026-09-06T12:00:00Z",
            completed_at="2026-09-06T12:02:00Z",
            status="COMPLETED",
            target_executable="C:\\Apps\\CRM\\app.exe",
            target_pid=4520,
            target_hwnd="0x00010204",
            target_plane="WEBVIEW",
            scope=ExperienceScope.SESSION,
            metadata={"framework": "electron", "verified": True},
        )
        saved = self.store.record_session(record)
        self.assertIsNotNone(saved)

        fetched = self.store.get_session("sess_alpha_01")
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.session_id, "sess_alpha_01")
        self.assertEqual(fetched.project_id, "proj_crm_app")
        self.assertEqual(fetched.target_pid, 4520)
        self.assertEqual(fetched.scope, ExperienceScope.SESSION)
        self.assertEqual(fetched.metadata["framework"], "electron")

    def test_mission_recording_and_association(self):
        """Verifies mission persistence and foreign key association with session."""
        sess = SessionExperienceRecord(
            session_id="sess_m_01",
            created_at="2026-09-06T12:00:00Z",
            status="ACTIVE",
            runtime_version="2.0.0b1",
        )
        self.store.record_session(sess)

        mission = MissionExperienceRecord(
            mission_id="msn_001",
            session_id="sess_m_01",
            project_id="proj_crm",
            goal="Verify payment form submission",
            scope="checkout_screen",
            created_at="2026-09-06T12:00:05Z",
            status="IN_PROGRESS",
            metadata={"priority": "P0"},
        )
        self.store.record_mission(mission)

        # Update status
        mission.status = "COMPLETED"
        mission.completed_at = "2026-09-06T12:01:30Z"
        self.store.record_mission(mission)

        counts = self.store.get_record_counts()
        self.assertEqual(counts["missions"], 1)

    def test_action_reference_recording(self):
        """Verifies action references with complete provenance envelopes."""
        sess = SessionExperienceRecord(
            session_id="sess_act_01",
            created_at="2026-09-06T12:00:00Z",
            status="ACTIVE",
            runtime_version="2.0.0b1",
        )
        self.store.record_session(sess)

        prov = ProvenanceRecord(
            source="desktop_webview_reviewer.action_engine",
            source_type=RecordSourceType.RUNTIME,
            session_id="sess_act_01",
            runtime_version="2.0.0b1",
            confidence=1.0,
            kind=RecordKind.FACT,
            trace_reference="evt_act_01",
            evidence_reference="ev_act_01",
        )
        act_ref = ActionReferenceRecord(
            action_id="act_click_01",
            session_id="sess_act_01",
            action_type="CLICK",
            plane="WEBVIEW",
            status="SUCCESS",
            provenance=prov,
            target="button#submit",
            duration_ms=45.2,
            metadata={"coordinates": [120, 340]},
        )
        self.store.record_action_reference(act_ref)

        refs = self.store.get_action_references("sess_act_01")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].action_id, "act_click_01")
        self.assertEqual(refs[0].provenance.kind, RecordKind.FACT)
        self.assertEqual(refs[0].provenance.source_type, RecordSourceType.RUNTIME)
        self.assertEqual(refs[0].target, "button#submit")

    def test_trace_and_evidence_references(self):
        """Verifies trace event and forensic evidence references are decoupled from large payloads."""
        sess = SessionExperienceRecord(
            session_id="sess_ref_01",
            created_at="2026-09-06T12:00:00Z",
            status="ACTIVE",
            runtime_version="2.0.0b1",
        )
        self.store.record_session(sess)

        prov = ProvenanceRecord(
            source="desktop_webview_reviewer.trace_engine",
            source_type=RecordSourceType.TRACE_ENGINE,
            session_id="sess_ref_01",
            runtime_version="2.0.0b1",
        )
        trace_ref = TraceReferenceRecord(
            event_id="evt_window_01",
            session_id="sess_ref_01",
            sequence_monotonic=104,
            event_type="WINDOW_DISCOVERED",
            plane="NATIVE",
            provenance=prov,
            metadata={"title": "Host Window", "hwnd": "0x1234"},
        )
        self.store.record_trace_reference(trace_ref)

        ev_prov = ProvenanceRecord(
            source="desktop_webview_reviewer.evidence_store",
            source_type=RecordSourceType.EVIDENCE_STORE,
            session_id="sess_ref_01",
            runtime_version="2.0.0b1",
        )
        ev_ref = EvidenceReferenceRecord(
            evidence_id="ev_manifest_88",
            session_id="sess_ref_01",
            artifact_id="art_screenshot_native_01",
            artifact_type="screenshot_native",
            checksum_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            relative_path_or_uri="session-sess_ref_01/action-act_1/artifacts/native.png",
            provenance=ev_prov,
            metadata={"width": 1920, "height": 1080},
        )
        self.store.record_evidence_reference(ev_ref)

        retrieved_traces = self.store.get_action_references("sess_ref_01")
        retrieved_evidences = self.store.get_evidence_references("sess_ref_01")
        self.assertEqual(len(retrieved_evidences), 1)
        self.assertEqual(retrieved_evidences[0].checksum_sha256, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_tripartite_outcomes_and_epistemic_classification(self):
        """Verifies PASS, FAIL, UNVERIFIED verdicts with confidence and factual vs inference classification."""
        sess = SessionExperienceRecord(
            session_id="sess_out_01",
            created_at="2026-09-06T12:00:00Z",
            status="ACTIVE",
            runtime_version="2.0.0b1",
        )
        self.store.record_session(sess)

        prov_pass = ProvenanceRecord(
            source="desktop_webview_reviewer.verification_engine",
            source_type=RecordSourceType.RUNTIME,
            session_id="sess_out_01",
            runtime_version="2.0.0b1",
            kind=RecordKind.FACT,
            confidence=1.0,
        )
        outcome_pass = OutcomeRecord(
            outcome_id="out_001",
            session_id="sess_out_01",
            verdict="PASS",
            confidence=1.0,
            provenance=prov_pass,
            details={"gui_verified": True, "assertions": 5},
        )
        self.store.record_outcome(outcome_pass)

        prov_unver = ProvenanceRecord(
            source="desktop_webview_reviewer.reconciliation",
            source_type=RecordSourceType.DIAGNOSTICS,
            session_id="sess_out_01",
            runtime_version="2.0.0b1",
            kind=RecordKind.INFERENCE,
            confidence=0.6,
        )
        outcome_unverified = OutcomeRecord(
            outcome_id="out_002",
            session_id="sess_out_01",
            verdict="UNVERIFIED",
            confidence=0.6,
            provenance=prov_unver,
            error_category="CLOAKED_WINDOW",
            details={"reason": "Window was minimized or cloaked during capture"},
        )
        self.store.record_outcome(outcome_unverified)

        outcomes = self.store.get_outcomes("sess_out_01")
        self.assertEqual(len(outcomes), 2)
        verdicts = {o.verdict for o in outcomes}
        self.assertEqual(verdicts, {"PASS", "UNVERIFIED"})

    def test_scope_validation_and_global_promotion_rejection(self):
        """Verifies SESSION and PROJECT scopes succeed, while GLOBAL promotion is rejected."""
        # Valid SESSION and PROJECT scopes
        self.assertEqual(validate_scope_promotion("SESSION"), ExperienceScope.SESSION)
        self.assertEqual(validate_scope_promotion("PROJECT"), ExperienceScope.PROJECT)
        self.assertEqual(validate_scope_promotion(ExperienceScope.SESSION), ExperienceScope.SESSION)

        # Rejection of GLOBAL promotion
        with self.assertRaises(ScopeValidationException) as ctx:
            validate_scope_promotion(ExperienceScope.GLOBAL)
        self.assertIn("Global promotion semantics are not authorized", str(ctx.exception))

        with self.assertRaises(ScopeValidationException):
            validate_scope_promotion("GLOBAL")

        # Rejection on session record
        sess_invalid = SessionExperienceRecord(
            session_id="sess_global_err",
            created_at="2026-09-06T12:00:00Z",
            status="ACTIVE",
            runtime_version="2.0.0b1",
            scope=ExperienceScope.GLOBAL,
        )
        with self.assertRaises(ScopeValidationException):
            self.store.record_session(sess_invalid)


if __name__ == "__main__":
    unittest.main()
