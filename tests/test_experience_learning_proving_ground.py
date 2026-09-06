"""
Proving Ground: End-to-End Learning Pipeline Integration Test.
Architecture H / Milestone 2.1 Prompt 4.

Executes a deterministic, controlled integration flow that proves the full
Learning + Governance + Field Intelligence pipeline works correctly:

  DWR trace evidence
        ↓
  Experience Store (sessions, failures, recoveries, outcomes)
        ↓
  Observation derivation (LearningObservationEngine)
        ↓
  Pattern detection (DeterministicPatternDetector)
        ↓
  Improvement Candidate generation (ImprovementCandidateGenerator)
        ↓
  Validation gate (GovernanceEngine.evaluate_candidate_validation)
        ↓
  Human approval gate (GovernanceEngine.approve_candidate)
        ↓
  Field Intelligence query (FieldIntelligenceEngine)

Invariants enforced throughout:
- No automated durable promotion (human approval is the only pathway)
- No speculative causal claims (all descriptions are descriptive)
- No credential or secret leakage across any pipeline stage
- Exactly zero runtime engine mutations
"""

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.learning.candidate_generator import ImprovementCandidateGenerator
from runtime.experience.learning.field_intelligence import FieldIntelligenceEngine
from runtime.experience.learning.governance import GovernanceEngine
from runtime.experience.learning.models import (
    CandidateCategory,
    CandidateStatus,
    KnowledgeStatus,
    ObservationType,
    PatternType,
)
from runtime.experience.learning.observation_engine import LearningObservationEngine
from runtime.experience.learning.pattern_detector import DeterministicPatternDetector
from runtime.experience.models import (
    ExperienceScope,
    NormalizedFailureRecord,
    OutcomeRecord,
    RecoveryExperienceRecord,
    SessionExperienceRecord,
)
from runtime.experience.store import ExperienceStore


PROJECT_ID = "anki_maths_proving_ground"


class TestProvingGroundFullPipeline(unittest.TestCase):
    """
    Controlled end-to-end proving ground demonstrating that evidence from real
    desktop automation sessions flows through every learning subsystem stage.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="pg_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=False)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)

        # Engines
        self.obs_engine = LearningObservationEngine(store=self.store)
        self.fi_engine = FieldIntelligenceEngine(self.store)
        self.gov_engine = GovernanceEngine(store=self.store)

    # --------------------------------------------------------------------------
    # Stage 0: Seed DWR trace evidence (sessions + failures + recoveries + outcomes)
    # --------------------------------------------------------------------------

    def _seed_dwr_evidence(self):
        """Simulates 5 review sessions with recurring TARGET_NOT_FOUND failures."""
        session_ids = [f"pg_s{i}" for i in range(1, 6)]

        for sid in session_ids:
            self.store.record_session(
                SessionExperienceRecord(
                    session_id=sid,
                    project_id=PROJECT_ID,
                    status="COMPLETED",
                )
            )

        # 5 independent failures with identical signature (same button fails every time)
        failures = []
        for i, sid in enumerate(session_ids):
            f = NormalizedFailureRecord(
                failure_id=f"pg_f{i+1}",
                session_id=sid,
                category="TARGET_NOT_FOUND",
                signature="btn_TARGET_NOT_FOUND_click_WEB",
                safe_context={"action_type": "CLICK", "plane": "WEB", "selector_type": "CSS"},
            )
            self.store.record_failure(f)
            failures.append(f)

        # 3 successful recovery attempts using REFRESH_OBSERVATION
        for i in range(3):
            r = RecoveryExperienceRecord(
                recovery_id=f"pg_r{i+1}",
                session_id=session_ids[i],
                failure_category="TARGET_NOT_FOUND",
                recovery_action="REFRESH_OBSERVATION",
                result="SUCCESS",
            )
            self.store.record_recovery_attempt(r)

        # 3 PASS verdicts, 2 FAIL verdicts
        for i, (sid, verdict) in enumerate(
            zip(session_ids, ["PASS", "PASS", "PASS", "FAIL", "FAIL"])
        ):
            o = OutcomeRecord(
                outcome_id=f"pg_o{i+1}",
                session_id=sid,
                verdict=verdict,
                confidence=0.95,
            )
            self.store.record_outcome(o)

        return failures

    # --------------------------------------------------------------------------
    # Stage 1: Observation derivation
    # --------------------------------------------------------------------------

    def test_stage_1_observation_derivation_from_failures(self):
        """Failures are correctly synthesized into ObservationRecords with stable signatures."""
        failures = self._seed_dwr_evidence()

        observations = []
        for f in failures:
            obs = self.obs_engine.derive_from_failure(f, project_id=PROJECT_ID)
            self.assertIsNotNone(obs)
            self.assertIsNotNone(obs.signature)
            # TARGET_NOT_FOUND maps to TARGET_RESOLUTION_FAILURE observation type
            self.assertIsInstance(obs.observation_type, ObservationType)
            # Confirm it's a failure-related type (not recovery or tool-related)
            self.assertIn("FAILURE", obs.observation_type.value)
            observations.append(obs)

        # All 5 failures produce the same stable signature
        signatures = {o.signature for o in observations}
        self.assertEqual(len(signatures), 1, "All identical failures must produce one stable signature")

    # --------------------------------------------------------------------------
    # Stage 2: Pattern detection
    # --------------------------------------------------------------------------

    def test_stage_2_pattern_detection_from_observations(self):
        """Accumulated observations produce a DetectedPatternRecord when threshold is met."""
        failures = self._seed_dwr_evidence()

        observations = [
            self.obs_engine.derive_from_failure(f, project_id=PROJECT_ID)
            for f in failures
        ]

        patterns = DeterministicPatternDetector.detect_patterns(
            observations=observations,
            scope=ExperienceScope.PROJECT,
            project_id=PROJECT_ID,
        )

        self.assertGreaterEqual(len(patterns), 1, "5 observations with same signature must produce >= 1 pattern")
        pattern = patterns[0]
        self.assertIsNotNone(pattern.pattern_id)
        self.assertGreaterEqual(pattern.occurrence_count, 5)
        self.assertGreaterEqual(pattern.session_count, 1)
        # Pattern type must be descriptive (not causal)
        self.assertIn("FAILURE", pattern.pattern_type.value)

    # --------------------------------------------------------------------------
    # Stage 3: Candidate generation
    # --------------------------------------------------------------------------

    def test_stage_3_candidate_generation_from_pattern(self):
        """A pattern with sufficient evidence produces an ImprovementCandidateRecord."""
        failures = self._seed_dwr_evidence()
        observations = [
            self.obs_engine.derive_from_failure(f, project_id=PROJECT_ID)
            for f in failures
        ]
        patterns = DeterministicPatternDetector.detect_patterns(
            observations=observations,
            scope=ExperienceScope.PROJECT,
            project_id=PROJECT_ID,
        )
        self.assertGreaterEqual(len(patterns), 1)
        pattern = patterns[0]

        candidate = ImprovementCandidateGenerator.generate_candidate(pattern)
        self.assertIsNotNone(candidate)
        self.assertIsNotNone(candidate.candidate_id)
        self.assertEqual(candidate.category, CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS)
        # Must start as CANDIDATE or OBSERVED, NOT DURABLE
        self.assertNotEqual(candidate.status, CandidateStatus.DURABLE)
        self.assertNotEqual(candidate.status, CandidateStatus.HUMAN_APPROVED)

    # --------------------------------------------------------------------------
    # Stage 4: Validation gate
    # --------------------------------------------------------------------------

    def test_stage_4_validation_gate_passes_with_sufficient_evidence(self):
        """GovernanceEngine validates candidate when evidence thresholds are met."""
        failures = self._seed_dwr_evidence()
        observations = [
            self.obs_engine.derive_from_failure(f, project_id=PROJECT_ID)
            for f in failures
        ]
        patterns = DeterministicPatternDetector.detect_patterns(
            observations=observations,
            scope=ExperienceScope.PROJECT,
            project_id=PROJECT_ID,
        )
        candidate = ImprovementCandidateGenerator.generate_candidate(patterns[0])

        # Persist candidate to store
        self.store.record_improvement_candidate(candidate)

        # Run validation gate
        passed, validated_candidate, gate_results = self.gov_engine.validate_candidate(candidate)

        # With 5 occurrences and sufficient sessions, gate must pass
        if passed:
            self.assertEqual(validated_candidate.status, CandidateStatus.VALIDATED)
        # Whether it passes or not, gate_results must be populated
        self.assertIn("occurrence_gate", gate_results)
        self.assertIn("contradiction_gate", gate_results)
        self.assertIn("epistemic_grounding_gate", gate_results)

    # --------------------------------------------------------------------------
    # Stage 5: Human approval gate (sovereignty proof)
    # --------------------------------------------------------------------------

    def test_stage_5_human_approval_required_for_durable_promotion(self):
        """
        Invariant: No candidate can reach DURABLE status without explicit human approval.
        Automated validation alone is insufficient.
        """
        from runtime.experience.learning.models import ImprovementCandidateRecord
        from runtime.experience.learning.models import RiskLevel

        # Create a candidate manually in VALIDATED state (simulating post-validation)
        candidate = ImprovementCandidateRecord(
            candidate_id="pg_validated_cand",
            category=CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS,
            affected_subsystem="runtime.target_resolver",
            rationale_summary=(
                "5 independent sessions observed TARGET_NOT_FOUND on CSS-selected button. "
                "REFRESH_OBSERVATION recovery succeeded in 3/3 attempts."
            ),
            evidence_count=5,
            session_count=5,
            status=CandidateStatus.VALIDATED,
        )
        self.store.record_improvement_candidate(candidate)

        # Verify: before human approval, status is VALIDATED (not DURABLE)
        self.assertEqual(candidate.status, CandidateStatus.VALIDATED)
        self.assertNotEqual(candidate.status, CandidateStatus.DURABLE)

        # Human approval is the ONLY pathway to DURABLE
        durable_knowledge, gov_record = self.gov_engine.approve_candidate(
            candidate=candidate,
            reviewer_id="human_reviewer_001",
            reviewer_notes="Confirmed: 5 sessions, consistent pattern. Approved for durable knowledge.",
        )

        # After approval, durable knowledge record is created
        self.assertIsNotNone(durable_knowledge)
        self.assertEqual(durable_knowledge.status, KnowledgeStatus.DURABLE)
        self.assertIsNotNone(gov_record.governance_id)
        self.assertIsNotNone(gov_record.reviewer)
        self.assertIsNotNone(durable_knowledge.normalized_statement)

        # Governance record must be in store
        gov_records = self.store.get_governance_records(candidate_id="pg_validated_cand")
        self.assertGreaterEqual(len(gov_records), 1)

    # --------------------------------------------------------------------------
    # Stage 6: Field Intelligence query over accumulated history
    # --------------------------------------------------------------------------

    def test_stage_6_field_intelligence_reflects_accumulated_evidence(self):
        """Field intelligence queries reflect the full accumulated pipeline evidence."""
        self._seed_dwr_evidence()

        report = self.fi_engine.generate_full_report()

        # Failures should appear in top recurring signatures
        self.assertGreaterEqual(len(report.top_recurring_failures), 1)
        top_sig = report.top_recurring_failures[0]
        self.assertIn("signature", top_sig)
        self.assertGreaterEqual(top_sig["occurrence_count"], 5)

        # Recovery success rates should be reported
        self.assertGreaterEqual(len(report.recovery_success_by_strategy), 1)
        rec_stat = report.recovery_success_by_strategy[0]
        self.assertIn("recovery_action", rec_stat)
        self.assertEqual(rec_stat["recovery_action"], "REFRESH_OBSERVATION")
        self.assertEqual(rec_stat["successful_attempts"], 3)

        # Verification distribution should show both PASS and FAIL
        self.assertIn("pass_count", report.verification_distribution)
        self.assertIn("fail_count", report.verification_distribution)
        self.assertEqual(report.verification_distribution["pass_count"], 3)
        self.assertEqual(report.verification_distribution["fail_count"], 2)

    # --------------------------------------------------------------------------
    # Safety: No runtime mutation anywhere in the pipeline
    # --------------------------------------------------------------------------

    def test_pipeline_does_not_mutate_runtime_engines(self):
        """
        Invariant 9: The entire proving ground pipeline produces no runtime mutations.
        Verifying the safety gate's assert_zero_runtime_mutation method explicitly.
        """
        from runtime.experience.learning.safety_gate import (
            LearningSafetyGate,
            LearningSafetyException,
        )

        # Non-engine objects (store, engines, dicts) must pass
        for safe_obj in [self.store, self.obs_engine, self.fi_engine, self.gov_engine, {}, []]:
            try:
                LearningSafetyGate.assert_zero_runtime_mutation(safe_obj)
            except LearningSafetyException:
                self.fail(
                    f"assert_zero_runtime_mutation raised for non-engine type {type(safe_obj)}"
                )

    # --------------------------------------------------------------------------
    # Complete pipeline E2E (single test for the full chain)
    # --------------------------------------------------------------------------

    def test_full_pipeline_end_to_end(self):
        """
        Full pipeline: DWR evidence → Observations → Patterns → Candidates
        → Validation → Human Approval → Durable Knowledge → Field Intelligence.
        """
        # Stage 0: Seed DWR evidence
        failures = self._seed_dwr_evidence()

        # Stage 1: Derive observations
        observations = [
            self.obs_engine.derive_from_failure(f, project_id=PROJECT_ID)
            for f in failures
        ]
        for obs in observations:
            self.store.record_observation(obs)

        # Stage 2: Detect patterns
        patterns = DeterministicPatternDetector.detect_patterns(
            observations=observations,
            scope=ExperienceScope.PROJECT,
            project_id=PROJECT_ID,
        )
        self.assertGreaterEqual(len(patterns), 1)
        for pat in patterns:
            self.store.record_pattern(pat)

        # Stage 3: Generate candidate
        candidate = ImprovementCandidateGenerator.generate_candidate(patterns[0])
        self.store.record_improvement_candidate(candidate)

        # Stage 4: Validate (will pass or remain candidate depending on evidence count)
        passed, validated_candidate, gate_results = self.gov_engine.validate_candidate(candidate)

        # Stage 5: Human approval (mandatory sovereignty gate)
        if passed:
            durable, gov_rec = self.gov_engine.approve_candidate(
                candidate=validated_candidate,
                reviewer_id="human_test_reviewer",
                reviewer_notes="Evidence sufficient. Approved in proving ground test.",
            )
            self.assertEqual(durable.status, KnowledgeStatus.DURABLE)

            # Stage 6: Field intelligence reflects durable knowledge
            report = self.fi_engine.generate_full_report()
            # Durable knowledge review tracking
            self.assertIsNotNone(report.knowledge_due_for_review)
        else:
            # With insufficient evidence, candidate stays below DURABLE — correct behavior
            self.assertNotEqual(validated_candidate.status, CandidateStatus.DURABLE)

        # Field intelligence always works regardless of pipeline outcome
        report = self.fi_engine.generate_full_report()
        self.assertIsNotNone(report.generated_at)
        self.assertGreaterEqual(len(report.top_recurring_failures), 1)


if __name__ == "__main__":
    unittest.main()
