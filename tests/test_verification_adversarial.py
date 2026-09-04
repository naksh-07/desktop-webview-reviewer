"""
Adversarial Verification & Evidence Tamper-Resistance Test Suite (Phase 6).
Tests edge cases, negative scenarios, security sandboxing, and cryptographic tamper detection
under Architecture H invariants (Physical Reality Primacy, Tripartite Verdict Model).
"""

import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from runtime.state import TargetPlane
from runtime.references import Rect
from runtime.action_models import (
    ActionRequest,
    ActionReceipt,
    ActionOutcome,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
)
from runtime.observation_models import (
    DualPerspectiveSnapshot,
    NativeObservation,
    WebObservation,
    WebElementObservation,
    VisibilityObservation,
    InteractionObservation,
    Certainty,
)
from runtime.observation_diff import ObservationDiffResult, DiffItem
from runtime.evidence_models import (
    VerificationVerdict,
    ProofLevel,
    EvidenceType,
    ClaimType,
    UnverifiedReason,
    EvidenceArtifact,
    ScreenshotEvidence,
    EvidenceManifest,
)
from runtime.evidence_store import (
    EvidenceStore,
    EvidenceSecurityException,
    EvidenceTamperException,
)
from runtime.verification_engine import VerificationEngine


class TestVerificationAdversarialAndTamper(unittest.TestCase):
    """Adversarial and tamper verification tests enforcing zero false-PASS guarantees."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(base_dir=Path(self.temp_dir.name))
        self.verifier = VerificationEngine(evidence_store=self.store, require_visible_gui=True)
        self.session_id = "adv_session"
        self.now = time.time()

        # Reusable base action request
        self.request = ActionRequest(
            session_id=self.session_id,
            reference="w1e1",
            action_type=ActionType.CLICK,
            observation_epoch=1,
            params={"expect_change": True},
        )

        # Baseline successful dispatch receipt
        self.receipt_dispatched = ActionReceipt(
            action_id=self.request.action_id,
            session_id=self.session_id,
            target_id="target_elem_1",
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

        # Valid Native observation
        self.native_obs_valid = NativeObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=self.now,
            hwnd=0x2001,
            title="Adversarial Test App",
            class_name="QtWebEngineProcess",
            pid=1234,
            bounds=Rect(100, 100, 1024, 768),
            client_bounds=Rect(108, 131, 1008, 729),
            is_visible=True,
            is_minimized=False,
            is_cloaked=False,
            is_responsive=True,
        )

        # Valid Web observation
        elem = WebElementObservation(
            session_id=self.session_id,
            observation_epoch=2,
            timestamp=self.now,
            source_plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_elem_1",
            reference="w1e1",
            role="button",
            normalized_role="button",
            accessible_name="Submit",
            tag_name="button",
            bounds=Rect(120, 180, 80, 40),
            visibility=VisibilityObservation(attached=True, visible=True, in_viewport=True, physically_occluded=False),
            interaction=InteractionObservation(is_enabled=True),
        )
        self.web_obs_valid = WebObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=self.now,
            target_id="target_elem_1",
            target_title="Main Page",
            target_url="https://app.local/main",
            root_frame_id="frame_1",
            elements=(elem,),
        )

        self.pre_snapshot = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=self.now - 0.5,
            native_observation=self.native_obs_valid,
            web_observation=self.web_obs_valid,
            text_representation="",
        )

        self.post_snapshot = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=2,
            timestamp=self.now,
            native_observation=self.native_obs_valid,
            web_observation=self.web_obs_valid,
            text_representation="",
        )

        self.diff_mutated = ObservationDiffResult(
            from_epoch=1,
            to_epoch=2,
            modified=(DiffItem(kind="MODIFIED", reference="w1e1", role="button", name="Submit", changes=("text changed",)),),
        )

        self.outcome_changed = ActionOutcome(
            action_id=self.request.action_id,
            session_id=self.session_id,
            receipt=self.receipt_dispatched,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=1,
            post_epoch=2,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Adversarial Scenario Tests
    # -------------------------------------------------------------------------

    def test_adversarial_dispatch_succeeds_but_process_exits(self):
        """Action dispatched, but target process terminates before post-state observation."""
        proc_info_dead = {
            "pid": 1234,
            "process_tree": [1234],
            "is_running": False, # Process terminated!
            "exit_code": -1,
        }

        verdict, manifest, ev_items = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
            target_process_info=proc_info_dead,
        )

        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.CONTRADICTORY_EVIDENCE)
        self.assertTrue(any("terminated prematurely" in e.metadata.get("description", "") for e in ev_items if e.evidence_type == EvidenceType.CONTRADICTION))

    def test_adversarial_dom_changes_but_window_is_minimized(self):
        """DOM mutates, but Native OS window is minimized (contradiction)."""
        native_min = NativeObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=self.now,
            hwnd=0x2001,
            title="Adversarial Test App",
            class_name="QtWebEngineProcess",
            pid=1234,
            bounds=Rect(0, 0, 100, 100),
            client_bounds=Rect(0, 0, 100, 100),
            is_visible=True,
            is_minimized=True, # Minimized
            is_cloaked=False,
            is_responsive=True,
        )
        post_snap_min = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=2,
            timestamp=self.now,
            native_observation=native_min,
            web_observation=self.web_obs_valid,
            text_representation="",
        )

        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=post_snap_min,
            observation_diff=self.diff_mutated,
        )

        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertIn(manifest.unverified_reason, (UnverifiedReason.WINDOW_CLOAKED_OR_MINIMIZED, UnverifiedReason.CONTRADICTORY_EVIDENCE))

    def test_adversarial_pre_state_exists_post_state_missing(self):
        """A mutating action has pre-observation, but post-observation is missing."""
        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=None, # Missing!
            observation_diff=None,
        )

        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.POST_STATE_MISSING)

    def test_adversarial_navigation_claimed_but_url_unchanged(self):
        """Action claimed navigation, but URL remained identical (Explicit FAIL)."""
        nav_request = ActionRequest(
            session_id=self.session_id,
            reference="w1e1",
            action_type=ActionType.CLICK,
            observation_epoch=1,
            params={
                "expected_claim": ClaimType.NavigationOccurred,
                "expected_url": "https://app.local/dashboard",
            },
        )

        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=nav_request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.post_snapshot, # url still https://app.local/main
            observation_diff=self.diff_mutated,
        )

        self.assertEqual(verdict, VerificationVerdict.FAIL)
        nav_claims = [c for c in manifest.claims if c.claim_type == ClaimType.NavigationOccurred]
        self.assertEqual(len(nav_claims), 1)
        self.assertEqual(nav_claims[0].status, VerificationVerdict.FAIL)

    def test_adversarial_missing_screenshot_under_level_4(self):
        """Under Level 4 Forensic Complete, missing screenshot must fail closed to UNVERIFIED."""
        shot_nat_only = ScreenshotEvidence(
            screenshot_id="s_nat",
            screenshot_type="NATIVE_WINDOW",
            coordinate_space="WINDOW_EXTENDED_FRAME",
            dimensions=(1024, 768),
            sha256="a" * 64,
            relative_path="screenshots/native.png",
        )

        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
            native_screenshot=shot_nat_only,
            webview_screenshot=None, # Missing webview screenshot!
            required_proof_level=ProofLevel.LEVEL_4_FORENSIC_COMPLETE,
        )

        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.SCREENSHOT_UNAVAILABLE)

    # -------------------------------------------------------------------------
    # 2. Cryptographic Evidence Tamper Tests
    # -------------------------------------------------------------------------

    def test_tamper_artifact_byte_modification_detected(self):
        """Modifying a single byte of a persisted artifact triggers hash mismatch."""
        action_id = self.request.action_id
        original_bytes = b"Original forensically sound evidence artifact content."
        art = self.store.store_bytes(
            session_id=self.session_id,
            action_id=action_id,
            relative_path="web/snapshot.json",
            data=original_bytes,
        )

        manifest = EvidenceManifest(
            manifest_id="man_tamper_1",
            session_id=self.session_id,
            action_id=action_id,
            artifacts=(art,),
            verdict=VerificationVerdict.PASS,
            proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
        )
        self.store.store_manifest(manifest)

        # Baseline verification passes
        is_valid, violations = self.store.verify_manifest_integrity(manifest)
        self.assertTrue(is_valid)
        self.assertEqual(violations, [])

        # Tamper: flip bytes on disk
        art_path = self.store.get_action_dir(self.session_id, action_id) / "web" / "snapshot.json"
        with open(art_path, "wb") as f:
            f.write(b"Tampered and corrupted malicious payload inserted here.")

        # Re-verify: must fail closed!
        is_valid_after, violations_after = self.store.verify_manifest_integrity(manifest)
        self.assertFalse(is_valid_after)
        self.assertTrue(any("Hash mismatch" in v or "size mismatch" in v for v in violations_after))

        with self.assertRaises(EvidenceTamperException):
            self.store.assert_manifest_integrity(manifest)

    def test_tamper_missing_artifact_referenced_in_manifest(self):
        """Manifest referencing a deleted or non-existent artifact triggers tamper violation."""
        action_id = "act_missing_art"
        ghost_art = EvidenceArtifact(
            artifact_id="art_ghost",
            filename="ghost.json",
            mime_type="application/json",
            sha256="c" * 64,
            size_bytes=100,
            created_at=time.time(),
            relative_path="native/ghost.json",
        )
        manifest = EvidenceManifest(
            manifest_id="man_ghost",
            session_id=self.session_id,
            action_id=action_id,
            artifacts=(ghost_art,),
            verdict=VerificationVerdict.PASS,
        )
        self.store.store_manifest(manifest)

        is_valid, violations = self.store.verify_manifest_integrity(manifest)
        self.assertFalse(is_valid)
        self.assertTrue(any("Missing artifact" in v for v in violations))

        with self.assertRaises(EvidenceTamperException):
            self.store.assert_manifest_integrity(manifest)

    def test_tamper_corrupted_manifest_json(self):
        """Corrupted manifest.json file triggers detection on directory verification."""
        action_id = "act_corrupt_manifest"
        action_dir = self.store.get_action_dir(self.session_id, action_id)
        manifest_file = action_dir / "manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            f.write("{corrupt_json_payload: not_valid_json!")

        is_valid, violations = self.store.verify_manifest_integrity(manifest_file)
        self.assertFalse(is_valid)
        self.assertTrue(any("Corrupted manifest JSON" in v for v in violations))

    def test_tamper_duplicate_artifact_id_rejected(self):
        """Manifest with duplicate artifact IDs triggers integrity violation."""
        action_id = "act_dup_id"
        art1 = EvidenceArtifact(
            artifact_id="art_duplicate",
            filename="file1.json",
            mime_type="application/json",
            sha256="d" * 64,
            size_bytes=10,
            created_at=time.time(),
            relative_path="file1.json",
        )
        art2 = EvidenceArtifact(
            artifact_id="art_duplicate", # Duplicate ID!
            filename="file2.json",
            mime_type="application/json",
            sha256="e" * 64,
            size_bytes=10,
            created_at=time.time(),
            relative_path="file2.json",
        )
        manifest = EvidenceManifest(
            manifest_id="man_dup",
            session_id=self.session_id,
            action_id=action_id,
            artifacts=(art1, art2),
            verdict=VerificationVerdict.PASS,
        )

        is_valid, violations = self.store.verify_manifest_integrity(manifest)
        self.assertFalse(is_valid)
        self.assertTrue(any("Duplicate artifact ID detected" in v for v in violations))

    # -------------------------------------------------------------------------
    # 3. Security & Sandboxing Tests
    # -------------------------------------------------------------------------

    def test_security_path_traversal_attempts_prevented(self):
        """Attempts to access or write files outside action sandboxes are blocked."""
        with self.assertRaises(EvidenceSecurityException):
            self.store.store_bytes(
                session_id=self.session_id,
                action_id="act_sec",
                relative_path="../../evil.exe",
                data=b"malware",
            )

        with self.assertRaises(EvidenceSecurityException):
            self.store.store_bytes(
                session_id=self.session_id,
                action_id="act_sec",
                relative_path="/etc/passwd",
                data=b"malware",
            )

        with self.assertRaises(EvidenceSecurityException):
            self.store.store_bytes(
                session_id=self.session_id,
                action_id="act_sec",
                relative_path="C:\\Windows\\System32\\bad.dll",
                data=b"malware",
            )


if __name__ == "__main__":
    unittest.main()
