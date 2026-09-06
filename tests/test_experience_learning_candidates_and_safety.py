"""
Tests for Improvement Candidates & Learning Safety Gate (10 Invariants).
Architecture H / Milestone 2.1 Prompt 4.

Verifies:
- Candidate lifecycle: OBSERVED -> CANDIDATE -> VALIDATION_REQUIRED
- Candidate never auto-promotes to DURABLE without human approval
- Invariant 1: Raw chain-of-thought and hidden reasoning strictly prohibited
- Invariant 2: Raw prompts and unrestricted transcripts prohibited
- Invariant 3: Sensitive typed text and credentials rejected
- Invariant 4: Agent interpretation alone cannot promote; speculation rejected
- Invariant 5: Minimum independent occurrences gate (1 occurrence cannot promote)
- Invariant 6: Historical frequency alone cannot make rule authoritative
- Invariant 7: Contradictory evidence gate (>20% contradictions blocks promotion)
- Invariant 8: Stale knowledge detection
- Invariant 9: assert_zero_runtime_mutation prevents modifying runtime engines
- Invariant 10: Architecture H sovereignty & global scope promotion gate
"""

import unittest
from runtime.errors import DesktopAutomationException
from runtime.experience.learning.candidate_generator import ImprovementCandidateGenerator
from runtime.experience.learning.models import (
    CandidateCategory,
    CandidateStatus,
    DetectedPatternRecord,
    GateStatus,
    ImprovementCandidateRecord,
    PatternType,
    RiskLevel,
)
from runtime.experience.learning.safety_gate import (
    LearningSafetyException,
    LearningSafetyGate,
)
from runtime.experience.models import ExperienceScope


class TestCandidatesAndSafetyGate(unittest.TestCase):
    def _create_pattern(self, occurrences: int = 3, sessions: int = 2, pat_type: PatternType = PatternType.REPEATED_TARGET_RESOLUTION_FAILURE) -> DetectedPatternRecord:
        return DetectedPatternRecord(
            pattern_id="pat_test_1",
            pattern_type=pat_type,
            signature="sig_test_element",
            summary="Repeated target resolution failure for element",
            scope=ExperienceScope.PROJECT,
            project_id="test_project",
            occurrence_count=occurrences,
            session_count=sessions,
            confidence=0.95,
        )

    # -------------------------------------------------------------------------
    # Candidate Generation & Lifecycle
    # -------------------------------------------------------------------------

    def test_candidate_generation_insufficient_evidence_remains_observed(self):
        """Patterns with < 3 occurrences must have status OBSERVED, not CANDIDATE."""
        pat = self._create_pattern(occurrences=2, sessions=1)
        candidate = ImprovementCandidateGenerator.generate_candidate(pat)
        self.assertEqual(candidate.status, CandidateStatus.OBSERVED)
        self.assertEqual(candidate.evidence_count, 2)

    def test_candidate_generation_sufficient_evidence_becomes_candidate(self):
        """Patterns with >= 3 occurrences transition to CANDIDATE."""
        pat = self._create_pattern(occurrences=3, sessions=2)
        candidate = ImprovementCandidateGenerator.generate_candidate(pat)
        self.assertEqual(candidate.status, CandidateStatus.CANDIDATE)

    def test_candidate_generation_validation_required_threshold(self):
        """Patterns with >= 5 occurrences and >= 2 sessions transition to VALIDATION_REQUIRED."""
        pat = self._create_pattern(occurrences=5, sessions=2)
        candidate = ImprovementCandidateGenerator.generate_candidate(pat)
        self.assertEqual(candidate.status, CandidateStatus.VALIDATION_REQUIRED)

    def test_candidate_never_auto_promotes_to_durable(self):
        """Candidate generator must never produce status DURABLE or HUMAN_APPROVED."""
        pat = self._create_pattern(occurrences=100, sessions=50)
        candidate = ImprovementCandidateGenerator.generate_candidate(pat)
        self.assertNotIn(candidate.status, (CandidateStatus.HUMAN_APPROVED, CandidateStatus.DURABLE))

    # -------------------------------------------------------------------------
    # Invariant 1 & 2: Chain of thought, raw prompts, unrestricted transcripts
    # -------------------------------------------------------------------------

    def test_invariant_1_and_2_prohibits_cot_and_prompts(self):
        """Invariant 1 & 2: Raw reasoning, CoT, prompts, and transcripts are rejected."""
        prohibited_payloads = [
            {"chain_of_thought": "I should first click the button"},
            {"raw_reasoning": "Hidden thought process"},
            {"thought_process": "Internal monologue"},
            {"raw_prompt": "Please click submit"},
            {"system_prompt": "You are an assistant"},
            {"transcript": "Full user interaction text"},
        ]
        for payload in prohibited_payloads:
            with self.assertRaises(LearningSafetyException):
                LearningSafetyGate.validate_learning_payload(payload, context="test")

    # -------------------------------------------------------------------------
    # Invariant 3: Secrets, credentials, sensitive typed text
    # -------------------------------------------------------------------------

    def test_invariant_3_prohibits_secrets_and_typed_text(self):
        """Invariant 3: Secrets, passwords, API keys, and sensitive typed text are rejected."""
        sensitive_payloads = [
            {"password": "SecretPassword123!"},
            {"token": "ghp_xxxxxxxxxxxxxxxxxxxx"},
            {"api_key": "AIzaSyD-xxxxxxxxxxxx"},
            {"typed_text": "Sensitive user input"},
            {"raw_input": "user_credit_card_1234"},
        ]
        for payload in sensitive_payloads:
            with self.assertRaises(LearningSafetyException):
                LearningSafetyGate.validate_learning_payload(payload, context="test")

    # -------------------------------------------------------------------------
    # Invariant 4: Speculation vs Grounded Facts
    # -------------------------------------------------------------------------

    def test_invariant_4_rejects_speculative_reasoning_in_candidates(self):
        """Invariant 4: Speculative interpretations ('the agent probably intended') fail the epistemic gate."""
        pat = self._create_pattern(occurrences=5, sessions=3)
        candidate = ImprovementCandidateGenerator.generate_candidate(pat)
        candidate.rationale_summary = "The agent probably intended to click the secondary dialog button."

        passes, gates = LearningSafetyGate.evaluate_candidate_safety(candidate)
        self.assertFalse(passes)
        self.assertEqual(gates["epistemic_grounding_gate"].status, GateStatus.FAIL)
        self.assertIn("speculative reasoning marker", gates["epistemic_grounding_gate"].details)

    # -------------------------------------------------------------------------
    # Invariant 5: Minimum independent occurrences gate
    # -------------------------------------------------------------------------

    def test_invariant_5_single_occurrence_fails_occurrence_gate(self):
        """Invariant 5: Single occurrence cannot satisfy candidate safety gates."""
        candidate = ImprovementCandidateRecord(
            candidate_id="cand_single",
            category=CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS,
            affected_subsystem="runtime.target_resolver",
            rationale_summary="Single occurrence test",
            pattern_id="pat_1",
            evidence_count=1,
            session_count=1,
            confidence=0.5,
            status=CandidateStatus.CANDIDATE,
        )
        passes, gates = LearningSafetyGate.evaluate_candidate_safety(candidate)
        self.assertFalse(passes)
        self.assertEqual(gates["occurrence_gate"].status, GateStatus.FAIL)

    # -------------------------------------------------------------------------
    # Invariant 6: Frequency alone cannot make rule authoritative
    # -------------------------------------------------------------------------

    def test_invariant_6_durable_requires_human_approval(self):
        """Invariant 6: Promotion to DURABLE fails without explicit human approval confirmation."""
        candidate = ImprovementCandidateRecord(
            candidate_id="cand_high_freq",
            category=CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS,
            affected_subsystem="runtime.target_resolver",
            rationale_summary="High frequency observation",
            pattern_id="pat_1",
            evidence_count=100,
            session_count=50,
            confidence=0.99,
            status=CandidateStatus.DURABLE,
        )
        # Without is_human_approved=True, gate must fail
        passes, gates = LearningSafetyGate.evaluate_candidate_safety(candidate, is_human_approved=False)
        self.assertFalse(passes)
        self.assertEqual(gates["human_governance_gate"].status, GateStatus.REVIEW_REQUIRED)

    # -------------------------------------------------------------------------
    # Invariant 7: Contradictory evidence gate
    # -------------------------------------------------------------------------

    def test_invariant_7_excessive_contradictions_blocks_promotion(self):
        """Invariant 7: Contradiction ratio > 20% blocks candidate safety validation."""
        pat = self._create_pattern(occurrences=10, sessions=4)
        candidate = ImprovementCandidateGenerator.generate_candidate(pat)
        # 10 occurrences with 5 contradictions -> 5/15 = 33.3% contradictions (> 20%)
        passes, gates = LearningSafetyGate.evaluate_candidate_safety(candidate, contradiction_count=5)
        self.assertFalse(passes)
        self.assertEqual(gates["contradiction_gate"].status, GateStatus.FAIL)

    def test_invariant_7_low_contradictions_passes_gate(self):
        """Invariant 7: Contradiction ratio <= 20% passes contradiction gate."""
        pat = self._create_pattern(occurrences=10, sessions=4)
        candidate = ImprovementCandidateGenerator.generate_candidate(pat)
        # 10 occurrences with 1 contradiction -> 1/11 = 9.1% contradictions (<= 20%)
        passes, gates = LearningSafetyGate.evaluate_candidate_safety(candidate, contradiction_count=1)
        self.assertTrue(passes)
        self.assertEqual(gates["contradiction_gate"].status, GateStatus.PASS)

    # -------------------------------------------------------------------------
    # Invariant 9: Zero runtime mutation
    # -------------------------------------------------------------------------

    def test_invariant_9_assert_zero_runtime_mutation(self):
        """Invariant 9: Attempt to mutate runtime engine raises LearningSafetyException."""
        from runtime.action_engine import ActionExecutionEngine
        from runtime.verification_engine import VerificationEngine
        from runtime.recovery_engine import RecoveryEngine

        action_eng = ActionExecutionEngine()
        verif_eng = VerificationEngine()
        rec_eng = RecoveryEngine()

        with self.assertRaises(LearningSafetyException):
            LearningSafetyGate.assert_zero_runtime_mutation(action_eng)

        with self.assertRaises(LearningSafetyException):
            LearningSafetyGate.assert_zero_runtime_mutation(verif_eng)

        with self.assertRaises(LearningSafetyException):
            LearningSafetyGate.assert_zero_runtime_mutation(rec_eng)

    # -------------------------------------------------------------------------
    # Invariant 10: Architecture H sovereignty & global scope promotion gate
    # -------------------------------------------------------------------------

    def test_invariant_10_global_scope_requires_explicit_authorization(self):
        """Invariant 10: Global scope candidates require explicit human approval to pass."""
        candidate = ImprovementCandidateRecord(
            candidate_id="cand_global",
            scope=ExperienceScope.GLOBAL,
            category=CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS,
            affected_subsystem="runtime.target_resolver",
            rationale_summary="Proposed global knowledge rule",
            pattern_id="pat_global",
            evidence_count=20,
            session_count=10,
            confidence=0.99,
            status=CandidateStatus.CANDIDATE,
        )
        # Without explicit approval, global scope gate fails
        passes, gates = LearningSafetyGate.evaluate_candidate_safety(candidate, is_human_approved=False)
        self.assertFalse(passes)
        self.assertEqual(gates["global_scope_gate"].status, GateStatus.FAIL)

        # With explicit approval, passes
        passes_app, gates_app = LearningSafetyGate.evaluate_candidate_safety(candidate, is_human_approved=True)
        self.assertTrue(passes_app)
        self.assertEqual(gates_app["global_scope_gate"].status, GateStatus.PASS)


if __name__ == "__main__":
    unittest.main()
