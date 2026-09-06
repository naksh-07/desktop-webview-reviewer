"""
Tests for Experience Store Privacy Boundaries and Secret Sanitization (Section 10).
"""

import unittest
from runtime.experience.privacy import (
    PrivacyEnforcer,
    PrivacyViolationException,
    MAX_METADATA_STRING_LENGTH,
)
from runtime.experience.config import ExperienceConfig
from runtime.experience.store import ExperienceStore
from runtime.experience.models import (
    OutcomeRecord,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    SessionExperienceRecord,
)


class TestExperiencePrivacy(unittest.TestCase):
    def test_prohibited_keys_rejected(self):
        """Verifies explicit rejection of chain-of-thought, reasoning, credentials, and cookies."""
        prohibited_keys = [
            "chain_of_thought",
            "cot",
            "hidden_thoughts",
            "reasoning_trace",
            "raw_reasoning",
            "model_transcript",
            "unfiltered_prompt",
            "password",
            "passwd",
            "api_key",
            "apikey",
            "bearer_token",
            "auth_token",
            "private_key",
            "cookie",
            "cookies",
        ]

        for key in prohibited_keys:
            bad_data = {key: "confidential reasoning or secret"}
            with self.subTest(key=key):
                with self.assertRaises(PrivacyViolationException) as ctx:
                    PrivacyEnforcer.check_and_sanitize(bad_data)
                self.assertIn("Privacy violation", str(ctx.exception))
                self.assertIn(key, str(ctx.exception))

    def test_nested_prohibited_keys_rejected(self):
        """Verifies rejection of prohibited keys inside nested dictionaries."""
        nested_bad_data = {
            "execution": {
                "metadata": {
                    "hidden_thoughts": "intermediate unverified thoughts",
                }
            }
        }
        with self.assertRaises(PrivacyViolationException):
            PrivacyEnforcer.check_and_sanitize(nested_bad_data)

    def test_credential_sanitization_in_string_values(self):
        """Verifies sensitive credential strings are redacted rather than saved in plain text."""
        raw_data = {
            "request_header": "Authorization: Bearer mySecretToken1234567890",
            "connection_url": "https://service.internal?api_key=sk-1234567890abcdef",
            "env_info": "password: superSecretPassword!123",
        }
        sanitized = PrivacyEnforcer.check_and_sanitize(raw_data)
        self.assertNotIn("mySecretToken1234567890", sanitized["request_header"])
        self.assertNotIn("superSecretPassword!123", sanitized["env_info"])
        self.assertIn("[REDACTED", sanitized["request_header"])
        self.assertIn("[REDACTED", sanitized["env_info"])

    def test_oversized_payload_dump_rejected(self):
        """Verifies rejection of unrestricted filesystem dumps exceeding size bounds."""
        giant_string = "A" * (MAX_METADATA_STRING_LENGTH + 10)
        with self.assertRaises(PrivacyViolationException) as ctx:
            PrivacyEnforcer.check_and_sanitize({"dump": giant_string})
        self.assertIn("Payload size violation", str(ctx.exception))

    def test_store_enforces_privacy_on_public_api(self):
        """Verifies that ExperienceStore rejects prohibited fields during record operations."""
        import tempfile
        import shutil
        from pathlib import Path

        temp_dir = tempfile.mkdtemp(prefix="exp_priv_store_")
        self.addCleanup(shutil.rmtree, temp_dir, ignore_errors=True)

        config = ExperienceConfig(base_dir=Path(temp_dir), fail_safe_mode=False)
        store = ExperienceStore(config=config)
        self.addCleanup(store.close)

        # Attempt to record session with chain-of-thought in metadata
        bad_session = SessionExperienceRecord(
            session_id="sess_bad_cot",
            created_at="2026-09-06T12:00:00Z",
            status="ACTIVE",
            runtime_version="2.0.0b1",
            metadata={"chain_of_thought": "Step 1: I will think about this..."},
        )
        with self.assertRaises(PrivacyViolationException):
            store.record_session(bad_session)

        # Attempt to record outcome with bearer token in details
        prov = ProvenanceRecord(
            source="test",
            source_type=RecordSourceType.RUNTIME,
            session_id="sess_bad_cot",
            runtime_version="2.0.0b1",
        )
        bad_outcome = OutcomeRecord(
            outcome_id="out_bad",
            session_id="sess_bad_cot",
            verdict="FAIL",
            confidence=1.0,
            provenance=prov,
            details={"bearer_token": "secret_token"},
        )
        with self.assertRaises(PrivacyViolationException):
            store.record_outcome(bad_outcome)


if __name__ == "__main__":
    unittest.main()
