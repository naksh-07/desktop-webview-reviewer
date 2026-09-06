"""
Tests for Production Lifecycle Hardening, Reality Verification & Governance Invariants.
Architecture H / Milestone 2.1 Prompt 5 - Sections 6, 8, 15, 17.

Verifies:
- Verification Truthfulness: PASS, FAIL, UNVERIFIED are strictly distinguished; uncertainty is never PASS.
- Recovery Reality: Retry budgets and bounded recovery; failure preserved across attempts.
- Governance Bypass Prevention: Direct write of DURABLE status without human approval metadata is rejected.
- Governance Record Immutability: Silent mutation of historical governance decisions is rejected.
- Scope Promotion Enforcement: GLOBAL scope promotion is blocked.
- Adversarial Privacy Re-Audit: Prohibited keys (CoT, passwords, api_keys, tokens, transcripts) are blocked.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.errors import GovernanceBypassException
from runtime.experience.config import ExperienceConfig
from runtime.experience.learning.governance import GovernanceEngine
from runtime.experience.learning.models import (
    CandidateCategory,
    CandidateStatus,
    DurableKnowledgeRecord,
    GovernanceDecision,
    GovernanceRecord,
    ImprovementCandidateRecord,
    KnowledgeStatus,
    RiskLevel,
)
from runtime.experience.learning.safety_gate import (
    LearningSafetyException,
    LearningSafetyGate,
)
from runtime.experience.models import (
    ExperienceScope,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    ScopeValidationException,
    validate_scope_promotion,
)
from runtime.experience.store import ExperienceStore


class TestProductionLifecycleHardening(unittest.TestCase):
    """Forensic verification of verification truthfulness, governance invariants, and privacy boundaries."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = ExperienceConfig(
            base_dir=Path(self.temp_dir.name),
            database_name="hardening_test.db",
            enable_wal_mode=True,
            fail_safe_mode=False,
        )
        self.store = ExperienceStore(config=self.config)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_direct_durable_write_without_approval_rejected(self) -> None:
        """Attempting to directly write status=DURABLE without human approval metadata raises GovernanceBypassException."""
        record_unauthorized = DurableKnowledgeRecord(
            knowledge_id="know_unauthorized",
            normalized_statement="Speculative auto-promoted knowledge statement.",
            version=1,
            scope=ExperienceScope.PROJECT,
            candidate_id="cand_123",
            supporting_evidence_refs=[],
            validation_metadata={},
            approval_metadata={},  # Empty approval metadata!
            confidence=1.0,
            status=KnowledgeStatus.DURABLE,
            provenance=ProvenanceRecord(
                source="MaliciousScript",
                source_type=RecordSourceType.RUNTIME,
                session_id="global",
            ),
        )

        with self.assertRaises(GovernanceBypassException) as ctx:
            self.store.record_durable_knowledge(record_unauthorized)
        self.assertIn("legitimate governance approval metadata", str(ctx.exception))

    def test_direct_durable_write_with_empty_reviewer_rejected(self) -> None:
        """Attempting to write DURABLE knowledge with an empty reviewer raises GovernanceBypassException."""
        record_empty_reviewer = DurableKnowledgeRecord(
            knowledge_id="know_unauthorized_2",
            normalized_statement="Knowledge statement with blank reviewer.",
            version=1,
            scope=ExperienceScope.PROJECT,
            candidate_id="cand_123",
            supporting_evidence_refs=[],
            validation_metadata={},
            approval_metadata={"reviewer": "   "},  # Blank reviewer!
            confidence=1.0,
            status=KnowledgeStatus.DURABLE,
            provenance=ProvenanceRecord(
                source="MaliciousScript",
                source_type=RecordSourceType.RUNTIME,
                session_id="global",
            ),
        )

        with self.assertRaises(GovernanceBypassException) as ctx:
            self.store.record_durable_knowledge(record_empty_reviewer)
        self.assertIn("valid non-empty reviewer", str(ctx.exception))

    def test_governance_record_silent_rewrite_rejected(self) -> None:
        """Attempting to silently rewrite an existing governance record raises GovernanceBypassException."""
        cand = ImprovementCandidateRecord(
            candidate_id="cand_101",
            category=CandidateCategory.ENVIRONMENT_ADAPTATION,
            affected_subsystem="runtime",
            rationale_summary="Test candidate for governance immutability.",
            scope=ExperienceScope.PROJECT,
            evidence_count=3,
            session_count=2,
            confidence=1.0,
            risk_level=RiskLevel.MEDIUM,
            status=CandidateStatus.VALIDATED,
            provenance=ProvenanceRecord(
                source="test",
                source_type=RecordSourceType.RUNTIME,
                session_id="global",
            ),
        )
        self.store.record_improvement_candidate(cand)

        gov_rec = GovernanceRecord(
            governance_id="gov_immutable_1",
            candidate_id="cand_101",
            decision=GovernanceDecision.REJECT,
            decision_scope=ExperienceScope.PROJECT,
            reviewer="alice_reviewer",
            decision_timestamp=1700000000.0,
            iso_timestamp="2026-09-06T00:00:00Z",
            rationale="Initial rejection due to high risk.",
        )
        self.store.record_governance_decision(gov_rec)

        # Attempt to forge/rewrite the decision to APPROVE
        gov_forged = GovernanceRecord(
            governance_id="gov_immutable_1",
            candidate_id="cand_101",
            decision=GovernanceDecision.APPROVE,
            decision_scope=ExperienceScope.PROJECT,
            reviewer="mallory_attacker",
            decision_timestamp=1700000010.0,
            iso_timestamp="2026-09-06T00:00:10Z",
            rationale="Forged approval.",
        )
        with self.assertRaises(GovernanceBypassException) as ctx:
            self.store.record_governance_decision(gov_forged)
        self.assertIn("cannot be silently rewritten", str(ctx.exception))

    def test_global_scope_promotion_blocked(self) -> None:
        """Verifies that scope assignment to GLOBAL is rejected."""
        with self.assertRaises(ScopeValidationException) as ctx:
            validate_scope_promotion(ExperienceScope.GLOBAL)
        self.assertIn("Global promotion semantics are not authorized", str(ctx.exception))

    def test_adversarial_privacy_injection_blocked(self) -> None:
        """Adversarial re-audit: forbidden keys are blocked by LearningSafetyGate."""
        forbidden_keys = [
            "password", "api_key", "bearer_token", "auth_token", "cookie",
            "jwt", "private_key", "chain_of_thought", "raw_prompt",
            "hidden_reasoning", "transcript",
        ]

        for key in forbidden_keys:
            payload = {key: "forbidden_sensitive_material_value"}
            with self.assertRaises(LearningSafetyException) as ctx:
                LearningSafetyGate.validate_learning_payload(payload, context="adversarial_test")
            self.assertIn("violation", str(ctx.exception))

        # Nested forbidden payload check
        nested_payload = {"outer": {"sub": {"jwt": "eyJhbGciOi..."}}}
        with self.assertRaises(LearningSafetyException):
            LearningSafetyGate.validate_learning_payload(nested_payload, context="adversarial_nested")

    def test_recovery_circuit_breaker_trip_and_cooldown(self) -> None:
        """Verifies that CircuitBreaker trips to OPEN on repeated failures and enters HALF_OPEN after cooldown."""
        from runtime.recovery_engine import CircuitBreaker, CircuitState

        cb = CircuitBreaker(max_consecutive_failures=3, cooldown_period_sec=5.0)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertFalse(cb.is_blocked(now=100.0))

        # Record 2 failures -> still CLOSED
        cb.record_failure("failure 1", now=101.0)
        cb.record_failure("failure 2", now=102.0)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertFalse(cb.is_blocked(now=103.0))

        # 3rd failure -> trips to OPEN
        cb.record_failure("failure 3", now=104.0)
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertTrue(cb.is_blocked(now=105.0))

        # Cooldown not yet elapsed -> remains blocked
        self.assertTrue(cb.is_blocked(now=108.0))

        # Cooldown elapsed (104.0 + 5.0 = 109.0) -> transitions to HALF_OPEN
        self.assertFalse(cb.is_blocked(now=110.0))
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Successful recovery resets to CLOSED
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.failure_count, 0)
        self.assertEqual(cb.recovery_count, 1)

    def test_verification_truthfulness_unverified_never_converted_to_pass(self) -> None:
        """Forensic audit of verification truthfulness: UNVERIFIED must never be treated as PASS."""
        from runtime.experience.models import OutcomeRecord, SessionExperienceRecord

        self.store.record_session(SessionExperienceRecord(
            session_id="sess_verify_test",
            status="ACTIVE",
            scope=ExperienceScope.SESSION,
        ))

        outcome_unverified = OutcomeRecord(
            outcome_id="out_unverified_1",
            session_id="sess_verify_test",
            verdict="UNVERIFIED",
            confidence=0.5,
            error_category="TARGET_FORENSICS_MISSING",
            source="verification_engine",
            source_type=RecordSourceType.RUNTIME,
            timestamp=1700000000.0,
            iso_timestamp="2026-09-06T00:00:00Z",
            details={"reason": "Native window was not physically visible on compositor surface."},
        )
        self.store.record_outcome(outcome_unverified)

        retrieved = self.store.get_outcomes(session_id="sess_verify_test")
        self.assertEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].verdict, "UNVERIFIED")
        self.assertNotEqual(retrieved[0].verdict, "PASS")
        self.assertEqual(retrieved[0].error_category, "TARGET_FORENSICS_MISSING")


if __name__ == "__main__":
    unittest.main()
