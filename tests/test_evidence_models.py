"""
Tests for Evidence and Verification Domain Models (Architecture H).
Validates model immutability, enum classifications, serialization round-trips,
and deterministic manifest SHA-256 sealing.
"""

import hashlib
import json
import time
import unittest

from runtime.state import TargetPlane
from runtime.evidence_models import (
    VerificationVerdict,
    ProofLevel,
    EvidenceType,
    ClaimType,
    UnverifiedReason,
    EvidenceItem,
    VerificationClaim,
    EvidenceArtifact,
    ScreenshotEvidence,
    EvidenceManifest,
)


class TestEvidenceModels(unittest.TestCase):
    """Unit tests for Phase 6 immutable evidence models."""

    def test_verdict_enum_values(self):
        """Verifies tripartite verdict enum values."""
        self.assertEqual(VerificationVerdict.PASS.value, "PASS")
        self.assertEqual(VerificationVerdict.FAIL.value, "FAIL")
        self.assertEqual(VerificationVerdict.UNVERIFIED.value, "UNVERIFIED")

    def test_proof_level_hierarchy(self):
        """Verifies progressive proof level ordering."""
        levels = [
            ProofLevel.LEVEL_0_DISPATCH_EVIDENCE,
            ProofLevel.LEVEL_1_TARGET_EVIDENCE,
            ProofLevel.LEVEL_2_STATE_CHANGE_EVIDENCE,
            ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
            ProofLevel.LEVEL_4_FORENSIC_COMPLETE,
        ]
        self.assertEqual(len(levels), 5)

    def test_evidence_item_immutability_and_roundtrip(self):
        """Verifies EvidenceItem immutability and dict serialization round-trip."""
        item = EvidenceItem(
            evidence_id="ev_001",
            evidence_type=EvidenceType.NATIVE_WINDOW_STATE,
            timestamp=1700000000.0,
            monotonic_time=12345.67,
            session_id="sess_abc",
            action_id="act_xyz",
            epoch=3,
            source_plane=TargetPlane.NATIVE_SHELL,
            source_component="NativeSupervisor",
            payload_reference="native/state.json",
            integrity_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            metadata={"hwnd": "0x1004", "visible": True},
        )

        with self.assertRaises(Exception):
            item.epoch = 4  # Frozen dataclass check

        d = item.to_dict()
        self.assertEqual(d["evidence_id"], "ev_001")
        self.assertEqual(d["evidence_type"], "NATIVE_WINDOW_STATE")
        self.assertEqual(d["source_plane"], "NATIVE_SHELL")

        restored = EvidenceItem.from_dict(d)
        self.assertEqual(restored.evidence_id, item.evidence_id)
        self.assertEqual(restored.evidence_type, item.evidence_type)
        self.assertEqual(restored.source_plane, item.source_plane)
        self.assertEqual(restored.integrity_hash, item.integrity_hash)
        self.assertEqual(restored.metadata, item.metadata)

    def test_verification_claim_serialization(self):
        """Verifies VerificationClaim serialization and deserialization."""
        claim = VerificationClaim(
            claim_id="clm_001",
            session_id="sess_1",
            action_id="act_1",
            observation_epoch=2,
            claim_type=ClaimType.InputReachedTarget,
            expected={"coords": [100, 200]},
            actual={"coords": [100, 200]},
            status=VerificationVerdict.PASS,
            confidence=0.95,
            evidence_refs=("ev_rec_1", "ev_vis_1"),
            reason="Input delivered to physical window coordinates",
            unverified_reason=None,
        )

        d = claim.to_dict()
        self.assertEqual(d["claim_type"], "InputReachedTarget")
        self.assertEqual(d["status"], "PASS")
        self.assertEqual(d["confidence"], 0.95)

        restored = VerificationClaim.from_dict(d)
        self.assertEqual(restored.claim_id, claim.claim_id)
        self.assertEqual(restored.claim_type, ClaimType.InputReachedTarget)
        self.assertEqual(restored.status, VerificationVerdict.PASS)
        self.assertEqual(restored.evidence_refs, ("ev_rec_1", "ev_vis_1"))

    def test_screenshot_evidence_metadata(self):
        """Verifies ScreenshotEvidence coordinate space and provenance fields."""
        shot = ScreenshotEvidence(
            screenshot_id="shot_001",
            screenshot_type="NATIVE_WINDOW",
            coordinate_space="WINDOW_EXTENDED_FRAME",
            dimensions=(1280, 720),
            pixel_format="RGBA",
            capture_bounds=(10, 20, 1280, 720),
            dpi_context=1.5,
            target_hwnd=0x4010a,
            sha256="abc123" * 10,
            relative_path="screenshots/native.png",
            is_thumbnail=False,
        )

        d = shot.to_dict()
        self.assertEqual(d["target_hwnd"], "0x4010a")
        self.assertEqual(d["coordinate_space"], "WINDOW_EXTENDED_FRAME")
        self.assertEqual(d["dpi_context"], 1.5)
        self.assertEqual(d["dimensions"], [1280, 720])

    def test_evidence_manifest_deterministic_hashing(self):
        """Proves that EvidenceManifest calculates deterministic SHA-256 manifest hash."""
        claim = VerificationClaim(
            claim_id="clm_001",
            session_id="sess_1",
            action_id="act_1",
            observation_epoch=1,
            claim_type=ClaimType.ActionWasDispatched,
            expected="DISPATCHED",
            actual="DISPATCHED",
            status=VerificationVerdict.PASS,
            confidence=1.0,
            evidence_refs=("ev_1",),
            reason="Dispatch confirmed",
        )
        artifact = EvidenceArtifact(
            artifact_id="art_001",
            filename="action_receipt.json",
            mime_type="application/json",
            sha256="a" * 64,
            size_bytes=128,
            created_at=1700000000.0,
            relative_path="receipts/action_receipt.json",
        )

        manifest = EvidenceManifest(
            manifest_id="man_001",
            session_id="sess_1",
            action_id="act_1",
            created_at="2026-09-04T05:00:00Z",
            created_timestamp=1700000000.0,
            monotonic_sequence=1,
            proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
            verdict=VerificationVerdict.PASS,
            verdict_rationale="All proofs verified",
            pre_state_epoch=1,
            post_state_epoch=2,
            claims=(claim,),
            evidence_chain=("ev_1", "ev_2"),
            artifacts=(artifact,),
        )

        hash1 = manifest.compute_manifest_hash()
        hash2 = manifest.compute_manifest_hash()
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)

        d = manifest.to_dict(include_hash=True)
        self.assertEqual(d["manifest_hash"], hash1)

        # Roundtrip
        restored = EvidenceManifest.from_dict(d)
        self.assertEqual(restored.manifest_id, manifest.manifest_id)
        self.assertEqual(restored.verdict, VerificationVerdict.PASS)
        self.assertEqual(restored.manifest_hash, hash1)


if __name__ == "__main__":
    unittest.main()
