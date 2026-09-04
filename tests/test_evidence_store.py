"""
Tests for EvidenceStore (Architecture H).
Validates filesystem sandboxing, path traversal rejection, atomic writes,
content addressing, and cryptographic tamper detection.
"""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.evidence_models import (
    EvidenceArtifact,
    EvidenceManifest,
    VerificationVerdict,
    ProofLevel,
    VerificationClaim,
    ClaimType,
)
from runtime.evidence_store import (
    EvidenceStore,
    EvidenceSecurityException,
    IntegrityVerificationException,
)


class TestEvidenceStore(unittest.TestCase):
    """Unit tests for sandboxed evidence storage and cryptographic tamper verification."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.store = EvidenceStore(base_dir=self.base_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Security & Sandboxing
    # -------------------------------------------------------------------------

    def test_path_traversal_session_id_rejected(self):
        """Proves that session_id containing path traversal tokens is rejected."""
        with self.assertRaises(EvidenceSecurityException):
            self.store.get_action_dir("../../etc", "act_001")

        with self.assertRaises(EvidenceSecurityException):
            self.store.get_action_dir("session/evil", "act_001")

        with self.assertRaises(EvidenceSecurityException):
            self.store.get_action_dir("session\\evil", "act_001")

    def test_path_traversal_action_id_rejected(self):
        """Proves that action_id containing path traversal tokens is rejected."""
        with self.assertRaises(EvidenceSecurityException):
            self.store.get_action_dir("sess_001", "../escape")

    def test_path_traversal_artifact_relative_path_rejected(self):
        """Proves that relative_path escaping action sandbox is rejected."""
        with self.assertRaises(EvidenceSecurityException):
            self.store.store_bytes("sess_001", "act_001", "../escaped.txt", b"malicious")

        with self.assertRaises(EvidenceSecurityException):
            self.store.store_bytes("sess_001", "act_001", "sub/../../escaped.txt", b"malicious")

    # -------------------------------------------------------------------------
    # 2. Atomic Writing & Content Hashing
    # -------------------------------------------------------------------------

    def test_store_bytes_atomic_and_sha256(self):
        """Proves that store_bytes writes data atomically and returns accurate SHA-256."""
        payload = b"Hello Forensic Verification World!"
        expected_hash = hashlib.sha256(payload).hexdigest()

        artifact = self.store.store_bytes(
            session_id="sess_123",
            action_id="act_456",
            relative_path="raw/message.txt",
            data=payload,
            mime_type="text/plain",
        )

        self.assertEqual(artifact.sha256, expected_hash)
        self.assertEqual(artifact.size_bytes, len(payload))
        self.assertEqual(artifact.relative_path, "raw/message.txt")

        # Verify on disk
        loaded = self.store.load_artifact_bytes("sess_123", "act_456", "raw/message.txt")
        self.assertEqual(loaded, payload)

    def test_store_json_serialization(self):
        """Proves that store_json serializes data as valid JSON and computes sha256."""
        data_obj = {"timestamp": 12345, "action": "CLICK", "target": "w1e3"}
        artifact = self.store.store_json("sess_1", "act_1", "receipts/receipt.json", data_obj)

        self.assertTrue(artifact.sha256)
        loaded_bytes = self.store.load_artifact_bytes("sess_1", "act_1", "receipts/receipt.json")
        loaded_obj = json.loads(loaded_bytes.decode("utf-8"))
        self.assertEqual(loaded_obj, data_obj)

    # -------------------------------------------------------------------------
    # 3. Cryptographic Tamper Detection
    # -------------------------------------------------------------------------

    def test_verify_manifest_integrity_success(self):
        """Proves that an unmodified evidence bundle passes cryptographic verification."""
        session_id = "sess_clean"
        action_id = "act_clean"

        art1 = self.store.store_bytes(session_id, action_id, "receipts/rec.json", b'{"status": "DISPATCHED"}', "application/json")
        art2 = self.store.store_bytes(session_id, action_id, "diffs/diff.json", b'{"mutations": 1}', "application/json")

        claim = VerificationClaim(
            claim_id="clm_1",
            session_id=session_id,
            action_id=action_id,
            observation_epoch=1,
            claim_type=ClaimType.ActionWasDispatched,
            expected="DISPATCHED",
            actual="DISPATCHED",
            status=VerificationVerdict.PASS,
            confidence=1.0,
            evidence_refs=("ev_1",),
            reason="Verified",
        )

        manifest = EvidenceManifest(
            manifest_id="man_clean",
            session_id=session_id,
            action_id=action_id,
            created_at="2026-09-04T05:00:00Z",
            created_timestamp=1700000000.0,
            monotonic_sequence=1,
            proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
            verdict=VerificationVerdict.PASS,
            verdict_rationale="Passed",
            pre_state_epoch=1,
            post_state_epoch=2,
            claims=(claim,),
            evidence_chain=("ev_1",),
            artifacts=(art1, art2),
        )

        manifest_path, manifest_hash = self.store.store_manifest(manifest)

        # Update manifest object with its sealed hash
        sealed_manifest = self.store.load_manifest(manifest_path)
        self.assertEqual(sealed_manifest.manifest_hash, manifest_hash)

        is_valid, violations = self.store.verify_manifest_integrity(sealed_manifest)
        self.assertTrue(is_valid)
        self.assertEqual(len(violations), 0)

        # assert_manifest_integrity should not raise
        self.store.assert_manifest_integrity(manifest_path)

    def test_tamper_detection_modified_artifact(self):
        """Proves that modifying even 1 byte of a stored artifact fails integrity verification."""
        session_id = "sess_tamper"
        action_id = "act_tamper"

        art1 = self.store.store_bytes(session_id, action_id, "data.bin", b"ORIGINAL DATA")

        manifest = EvidenceManifest(
            manifest_id="man_tamper",
            session_id=session_id,
            action_id=action_id,
            created_at="2026-09-04T05:00:00Z",
            created_timestamp=1700000000.0,
            monotonic_sequence=1,
            proof_level=ProofLevel.LEVEL_1_TARGET_EVIDENCE,
            verdict=VerificationVerdict.PASS,
            verdict_rationale="Passed",
            claims=(),
            artifacts=(art1,),
        )
        manifest_path, _ = self.store.store_manifest(manifest)

        # Tamper with data.bin on disk!
        action_dir = self.store.get_action_dir(session_id, action_id)
        target_file = action_dir / "data.bin"
        with open(target_file, "wb") as f:
            f.write(b"TAMPERED DATA!!")

        is_valid, violations = self.store.verify_manifest_integrity(manifest_path)
        self.assertFalse(is_valid)
        self.assertTrue(any("Artifact tampering detected" in v for v in violations))

        with self.assertRaises(IntegrityVerificationException):
            self.store.assert_manifest_integrity(manifest_path)

    def test_tamper_detection_missing_artifact(self):
        """Proves that deleting a referenced artifact fails integrity verification."""
        session_id = "sess_missing"
        action_id = "act_missing"

        art1 = self.store.store_bytes(session_id, action_id, "temp.bin", b"temporary")

        manifest = EvidenceManifest(
            manifest_id="man_missing",
            session_id=session_id,
            action_id=action_id,
            created_at="2026-09-04T05:00:00Z",
            created_timestamp=1700000000.0,
            monotonic_sequence=1,
            proof_level=ProofLevel.LEVEL_1_TARGET_EVIDENCE,
            verdict=VerificationVerdict.PASS,
            verdict_rationale="Passed",
            claims=(),
            artifacts=(art1,),
        )
        manifest_path, _ = self.store.store_manifest(manifest)

        # Delete artifact on disk
        action_dir = self.store.get_action_dir(session_id, action_id)
        (action_dir / "temp.bin").unlink()

        is_valid, violations = self.store.verify_manifest_integrity(manifest_path)
        self.assertFalse(is_valid)
        self.assertTrue(any("Missing artifact file" in v for v in violations))

    def test_tamper_detection_modified_manifest_json(self):
        """Proves that mutating manifest.json without updating manifest_hash is detected."""
        session_id = "sess_m_tamper"
        action_id = "act_m_tamper"

        manifest = EvidenceManifest(
            manifest_id="man_mt",
            session_id=session_id,
            action_id=action_id,
            created_at="2026-09-04T05:00:00Z",
            created_timestamp=1700000000.0,
            monotonic_sequence=1,
            proof_level=ProofLevel.LEVEL_1_TARGET_EVIDENCE,
            verdict=VerificationVerdict.FAIL,
            verdict_rationale="Explicit fail",
            claims=(),
            artifacts=(),
        )
        manifest_path, _ = self.store.store_manifest(manifest)

        # Tamper manifest.json directly on disk: alter verdict FAIL -> PASS
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["verdict"] = "PASS"  # Tampered!
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        is_valid, violations = self.store.verify_manifest_integrity(manifest_path)
        self.assertFalse(is_valid)
        self.assertTrue(any("Manifest tampering detected" in v for v in violations))


if __name__ == "__main__":
    unittest.main()
