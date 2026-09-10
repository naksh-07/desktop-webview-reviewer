import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from runtime.state import TargetPlane
from runtime.evidence_models import (
    VerificationVerdict,
    ProofLevel,
    EvidenceType,
    ClaimType,
    UnverifiedReason,
    EvidenceArtifact,
    ScreenshotEvidence,
    EvidenceManifest,
    PhysicalDesktopEvidence
)
from runtime.evidence_store import (
    EvidenceStore,
    EvidenceSecurityException,
    EvidenceTamperException,
)
from runtime.verification_engine import VerificationEngine
from runtime.action_models import ActionRequest, ActionReceipt, ActionOutcome, ActionType, DispatchMethod, DispatchStatus
from runtime.observation_models import NativeObservation, Rect

class TestEvidenceTamperingAdversarial(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(base_dir=Path(self.temp_dir.name))
        self.verifier = VerificationEngine(evidence_store=self.store, require_visible_gui=True)
        self.session_id = "adv_session"
        self.now = time.time()
        self.action_id = "act_123"

        self.request = ActionRequest(
            session_id=self.session_id,
            reference="w1e1",
            action_type=ActionType.CLICK,
            observation_epoch=1,
            params={"expect_change": True},
        )

        self.receipt = ActionReceipt(
            action_id=self.action_id,
            session_id=self.session_id,
            target_id="t1",
            epoch=1,
            plane=TargetPlane.WEBVIEW_DOM,
            reference="w1e1",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.CDP_INPUT,
            dispatch_timestamp=self.now,
            coordinates=(150, 200),
            dispatch_status=DispatchStatus.DISPATCHED,
            duration_ms=10.0,
        )

        from runtime.action_models import ActionOutcomeStatus, StateChangeClassification
        self.outcome = ActionOutcome(
            action_id=self.action_id,
            session_id=self.session_id,
            pre_epoch=1,
            post_epoch=2,
            timestamp=self.now + 1.0,
            receipt=self.receipt,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_forged_physical_desktop_evidence_bypasses_verifier(self):
        # 1. Physical Evidence Trust Boundary: Construct forged PhysicalDesktopEvidence
        native_obs = NativeObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=self.now,
            hwnd=0x2001,
            title="App",
            class_name="Qt",
            pid=1234,
            bounds=Rect(0, 0, 1024, 768),
            client_bounds=Rect(0, 0, 1024, 768),
            is_visible=True,
            is_responsive=True,
            is_minimized=False,
            is_cloaked=False
        )

        from runtime.observation_models import DualPerspectiveSnapshot
        snapshot = DualPerspectiveSnapshot(session_id=self.session_id, timestamp=self.now, epoch=2, native_observation=native_obs, web_observation=None)

        # Forgery
        forged_evidence = PhysicalDesktopEvidence(
            evidence_id="fake_ev",
            session_id=self.session_id,
            target_hwnd=0x2001,
            target_pid=1234,
            foreground_hwnd=0x2001,
            is_exact_foreground=True,
            dimensions=(1024, 768),
            capture_timestamp=self.now,
            pixel_sha256="fake_sha256",
            artifact_path="fake.png",
            process_creation_time=0.0,
            physical_bounds=(0, 0, 1024, 768),
            capture_method="REAL_DESKTOP_SURFACE", # caller supplied
            is_authoritative=True, # caller supplied
            post_capture_validated=True
        )

        verdict, manifest, items = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt,
            action_outcome=self.outcome,
            post_snapshot=snapshot,
            physical_desktop_evidence=forged_evidence
        )

        # The application code correctly defends against the forgery
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        for claim in manifest.claims:
            if claim.claim_type == ClaimType.TargetWasPhysicallyVisible:
                self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)

    def test_artifact_tampering_overwrite_and_verify(self):
        # 2. Artifact Tampering
        data = b"original bytes"
        art = self.store.store_bytes(self.session_id, self.action_id, "test.png", data)
        manifest = EvidenceManifest(
            manifest_id="m1",
            session_id=self.session_id,
            action_id=self.action_id,
            artifacts=(art,)
        )
        man_path, man_hash = self.store.store_manifest(manifest)

        # Modify bytes
        art_path = self.store.get_action_dir(self.session_id, self.action_id) / "test.png"
        with open(art_path, "wb") as f:
            f.write(b"tampered bytes")

        is_valid, violations = self.store.verify_manifest_integrity(manifest)
        self.assertFalse(is_valid)

        # Overwrite original artifact using store_bytes (should be rejected)
        with self.assertRaises(EvidenceSecurityException):
            self.store.store_bytes(self.session_id, self.action_id, "test.png", b"new bytes")

        # Delete artifact -> verify
        os.remove(art_path)
        is_valid, violations = self.store.verify_manifest_integrity(manifest)
        self.assertFalse(is_valid)

    def test_storage_isolation(self):
        # 4. Storage Isolation
        # Attempt to store outside base_dir using path traversal
        with self.assertRaises(EvidenceSecurityException):
            self.store.store_bytes(self.session_id, self.action_id, "../../../outside.png", b"hack")
        with self.assertRaises(EvidenceSecurityException):
            self.store.get_action_dir(self.session_id, "../action1")

if __name__ == "__main__":
    unittest.main()
