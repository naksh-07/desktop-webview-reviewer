"""
Unit tests for EvidenceSpecialist (Phase 15 - Prompt P4).
"""
import asyncio
import unittest
from unittest.mock import MagicMock
from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import SpecialistDelegation, DelegationScope, SpecialistResultStatus
from runtime.specialists.evidence import EvidenceSpecialist
from runtime.evidence_models import EvidenceManifest, VerificationVerdict, EvidenceArtifact


class TestEvidenceSpecialist(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.session_id = "test-session-ev"
        self.mock_session.current_epoch = 1

        self.mock_store = MagicMock()
        self.mock_session.evidence_store = self.mock_store

    def test_evidence_specialist_verifies_valid_manifest(self):
        """Evidence Specialist validates unaltered artifacts and returns SUCCESS with proof."""
        mock_manifest = MagicMock(spec=EvidenceManifest)
        mock_manifest.manifest_id = "mnf-12345"
        mock_manifest.verdict = VerificationVerdict.PASS
        mock_art = MagicMock(spec=EvidenceArtifact)
        mock_art.artifact_id = "art-1"
        mock_art.relative_path = "screenshot.png"
        mock_manifest.artifacts = [mock_art]

        self.mock_store.load_manifest.return_value = mock_manifest
        self.mock_store.verify_manifest_integrity.return_value = (True, [])

        delegation = SpecialistDelegation(
            role=SpecialistRole.EVIDENCE_SPECIALIST,
            task="Verify cryptographic integrity of action act-1 evidence",
            scope=DelegationScope(session_id="test-session-ev"),
            permitted_tools={"desktop_verify_manifest", "desktop_get_evidence"},
            parameters={"manifest_path": "fake/path/manifest.json", "action_id": "act-1"},
            timeout_sec=5.0
        )

        # Mock Path.exists to return True
        from unittest.mock import patch
        with patch("pathlib.Path.exists", return_value=True):
            specialist = EvidenceSpecialist(delegation=delegation, session_state=self.mock_session)
            result = asyncio.run(specialist.run())

        self.assertEqual(result.status, SpecialistResultStatus.SUCCESS)
        self.assertEqual(result.observations["cryptographic_proof"], "VERIFIED")
        self.assertEqual(result.observations["verified_artifacts"], 1)
        self.assertIn("mnf-12345", result.evidence_refs)

    def test_evidence_specialist_detects_tampering(self):
        """Evidence Specialist flags SHA-256 hash mismatches and marks audit as FAILED."""
        mock_manifest = MagicMock(spec=EvidenceManifest)
        mock_manifest.manifest_id = "mnf-tampered"
        mock_manifest.verdict = VerificationVerdict.PASS
        mock_manifest.artifacts = [MagicMock(artifact_id="art-1", relative_path="screenshot.png")]

        self.mock_store.load_manifest.return_value = mock_manifest
        self.mock_store.verify_manifest_integrity.return_value = (
            False,
            ["Hash mismatch tampering detected for screenshot.png: expected abc, got def"]
        )

        delegation = SpecialistDelegation(
            role=SpecialistRole.EVIDENCE_SPECIALIST,
            task="Audit evidence for tampering",
            scope=DelegationScope(session_id="test-session-ev"),
            permitted_tools={"desktop_verify_manifest"},
            parameters={"manifest_path": "fake/path/manifest.json"},
            timeout_sec=5.0
        )

        from unittest.mock import patch
        with patch("pathlib.Path.exists", return_value=True):
            specialist = EvidenceSpecialist(delegation=delegation, session_state=self.mock_session)
            result = asyncio.run(specialist.run())

        self.assertEqual(result.status, SpecialistResultStatus.FAILED)
        self.assertEqual(result.observations["cryptographic_proof"], "TAMPERED")
        self.assertEqual(len(result.observations["tampered_artifacts"]), 1)

    def test_evidence_specialist_missing_manifest_is_unverified(self):
        """When manifest cannot be found, evidence audit must return UNVERIFIED, not fabricate success."""
        mock_dir = MagicMock()
        mock_file = MagicMock()
        mock_file.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_file
        self.mock_store.get_action_dir.return_value = mock_dir

        delegation = SpecialistDelegation(
            role=SpecialistRole.EVIDENCE_SPECIALIST,
            task="Audit missing evidence",
            scope=DelegationScope(session_id="test-session-ev"),
            permitted_tools={"desktop_verify_manifest"},
            parameters={"action_id": "nonexistent-action"},
            timeout_sec=5.0
        )

        from unittest.mock import patch
        with patch("pathlib.Path.exists", return_value=False):
            specialist = EvidenceSpecialist(delegation=delegation, session_state=self.mock_session)
            result = asyncio.run(specialist.run())

        self.assertEqual(result.status, SpecialistResultStatus.UNVERIFIED)
        self.assertFalse(result.observations["manifest_found"])


if __name__ == "__main__":
    unittest.main()
