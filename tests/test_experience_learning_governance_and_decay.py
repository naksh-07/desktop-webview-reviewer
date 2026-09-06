"""
Tests for Human Governance Lifecycle, Knowledge Decay, and Revalidation.
Architecture H / Milestone 2.1 Prompt 4.

Verifies:
- Candidate validation against empirical evidence gates
- Explicit human approval requirement for durable promotion
- Rejection of candidate with explicit rationale
- Knowledge decay evaluation:
  - DURABLE -> REVIEW_DUE when review date passes
  - REVIEW_DUE -> STALE after grace period expires
  - Excessive contradictions trigger STALE transition
- Explicit human revalidation restores DURABLE and increments version
- Supersession links old knowledge to replacement knowledge
- Historical evidence records preserved during all lifecycle transitions
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.learning.decay import KnowledgeDecayEngine
from runtime.experience.learning.governance import GovernanceEngine
from runtime.experience.learning.models import (
    CandidateCategory,
    CandidateStatus,
    DurableKnowledgeRecord,
    GateStatus,
    GovernanceDecision,
    ImprovementCandidateRecord,
    KnowledgeStatus,
)
from runtime.experience.models import ExperienceScope
from runtime.experience.store import ExperienceStore


class TestGovernanceAndDecayLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="learning_gov_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=False)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)
        self.gov_engine = GovernanceEngine(self.store)
        self.decay_engine = KnowledgeDecayEngine(self.store)

    def _create_validatable_candidate(self, candidate_id: str = "cand_gov_1") -> ImprovementCandidateRecord:
        candidate = ImprovementCandidateRecord(
            candidate_id=candidate_id,
            scope=ExperienceScope.PROJECT,
            project_id="test_project",
            category=CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS,
            affected_subsystem="runtime.target_resolver",
            pattern_id="pat_101",
            evidence_count=8,
            session_count=4,
            confidence=0.95,
            status=CandidateStatus.VALIDATION_REQUIRED,
            rationale_summary="Target #main-nav fails in 8 instances across 4 sessions",
        )
        self.store.record_improvement_candidate(candidate)
        return candidate

    def test_candidate_validation_passes_with_sufficient_evidence(self):
        """Verifies candidate validation transitions state to VALIDATED."""
        candidate = self._create_validatable_candidate("cand_val_pass")
        success, validated, gates = self.gov_engine.validate_candidate(candidate)

        self.assertTrue(success)
        self.assertEqual(validated.status, CandidateStatus.VALIDATED)
        self.assertEqual(gates["occurrence_gate"].status, GateStatus.PASS)
        self.assertEqual(gates["session_gate"].status, GateStatus.PASS)

        # Check DB state
        db_cand = self.store.get_improvement_candidate("cand_val_pass")
        self.assertIsNotNone(db_cand)
        self.assertEqual(db_cand.status, CandidateStatus.VALIDATED)

    def test_candidate_validation_fails_with_insufficient_evidence(self):
        """Candidate with insufficient evidence fails validation and remains in previous state."""
        weak_cand = ImprovementCandidateRecord(
            candidate_id="cand_val_weak",
            category=CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS,
            affected_subsystem="runtime.target_resolver",
            pattern_id="pat_weak",
            evidence_count=2,
            session_count=1,
            confidence=0.6,
            status=CandidateStatus.CANDIDATE,
            rationale_summary="Insufficient observations",
        )
        self.store.record_improvement_candidate(weak_cand)

        success, validated, gates = self.gov_engine.validate_candidate(weak_cand)
        self.assertFalse(success)
        self.assertEqual(validated.status, CandidateStatus.CANDIDATE)
        self.assertEqual(gates["occurrence_gate"].status, GateStatus.FAIL)

    def test_human_approval_creates_durable_knowledge_and_governance_record(self):
        """Human approval gate transitions candidate to DURABLE and creates immutable audit records."""
        candidate = self._create_validatable_candidate("cand_approve")
        self.gov_engine.validate_candidate(candidate)

        durable, gov_rec = self.gov_engine.approve_candidate(
            candidate=candidate,
            reviewer_id="human_qa_engineer",
            reviewer_notes="Approved for project after manual desktop test pass",
            ttl_days=45,
        )

        self.assertEqual(durable.status, KnowledgeStatus.DURABLE)
        self.assertEqual(gov_rec.decision, GovernanceDecision.APPROVE)
        self.assertEqual(gov_rec.reviewer_id, "human_qa_engineer")
        self.assertIn("target_resolver", durable.normalized_statement)

        # Verify candidate state updated
        cand_db = self.store.get_improvement_candidate("cand_approve")
        self.assertEqual(cand_db.status, CandidateStatus.DURABLE)

        # Verify durable knowledge persisted in store
        durable_db = self.store.get_durable_knowledge_item(durable.knowledge_id)
        self.assertIsNotNone(durable_db)
        self.assertEqual(durable_db.version, 1)

    def test_human_rejection_marks_candidate_rejected(self):
        """Human rejection updates candidate status to REJECTED and records rationale."""
        candidate = self._create_validatable_candidate("cand_reject")

        rejected_cand, gov_rec = self.gov_engine.reject_candidate(
            candidate=candidate,
            reviewer_id="human_reviewer_2",
            rejection_reason="Expected behavior during offline network mode",
        )

        self.assertEqual(rejected_cand.status, CandidateStatus.REJECTED)
        self.assertEqual(gov_rec.decision, GovernanceDecision.REJECT)

        # Verify DB reflects rejection
        db_cand = self.store.get_improvement_candidate("cand_reject")
        self.assertEqual(db_cand.status, CandidateStatus.REJECTED)

    # -------------------------------------------------------------------------
    # Knowledge Decay & Staleness Tests
    # -------------------------------------------------------------------------

    def test_knowledge_decay_review_due_transition(self):
        """Knowledge past review_due_at transitions to REVIEW_DUE."""
        now = datetime.now(timezone.utc)
        past_review = (now - timedelta(days=5)).isoformat()

        durable = DurableKnowledgeRecord(
            knowledge_id="kn_due_test",
            normalized_statement="For button#save, retry after 50ms",
            status=KnowledgeStatus.DURABLE,
            review_due_at=past_review,
        )
        self.store.record_durable_knowledge(durable)

        state_changed, updated = KnowledgeDecayEngine.evaluate_knowledge(durable, reference_time=now)
        self.assertTrue(state_changed)
        self.assertEqual(updated.status, KnowledgeStatus.REVIEW_DUE)

    def test_knowledge_decay_stale_transition_after_grace_period(self):
        """Knowledge past review_due_at plus 30-day grace period transitions to STALE."""
        now = datetime.now(timezone.utc)
        long_past = (now - timedelta(days=40)).isoformat()

        durable = DurableKnowledgeRecord(
            knowledge_id="kn_stale_test",
            normalized_statement="Old observation rule",
            status=KnowledgeStatus.DURABLE,
            review_due_at=long_past,
        )
        self.store.record_durable_knowledge(durable)

        state_changed, updated = KnowledgeDecayEngine.evaluate_knowledge(durable, reference_time=now)
        self.assertTrue(state_changed)
        self.assertEqual(updated.status, KnowledgeStatus.STALE)

    def test_excessive_contradictions_triggers_stale(self):
        """More than 3 contradictions transitions durable knowledge to STALE."""
        durable = DurableKnowledgeRecord(
            knowledge_id="kn_contra_test",
            normalized_statement="Fragile rule",
            status=KnowledgeStatus.DURABLE,
            contradiction_count=0,
        )

        # 4 new contradictions
        state_changed, updated = KnowledgeDecayEngine.evaluate_knowledge(durable, new_contradictions=4)
        self.assertTrue(state_changed)
        self.assertEqual(updated.status, KnowledgeStatus.STALE)

    def test_revalidation_restores_durable_status_and_increments_version(self):
        """Explicit revalidation of STALE knowledge increments version and resets review due date."""
        stale_item = DurableKnowledgeRecord(
            knowledge_id="kn_reval_test",
            normalized_statement="Revalidatable pattern",
            version=1,
            status=KnowledgeStatus.STALE,
            contradiction_count=4,
        )

        revalidated = KnowledgeDecayEngine.revalidate_knowledge(
            knowledge=stale_item,
            reviewer="lead_engineer",
            rationale="Re-verified on Windows 11 host with WebView2 runtime 132",
            ttl_days=60,
        )

        self.assertEqual(revalidated.status, KnowledgeStatus.DURABLE)
        self.assertEqual(revalidated.version, 2)
        self.assertEqual(revalidated.contradiction_count, 0)
        self.assertIsNotNone(revalidated.review_due_at)

    def test_supersession_links_old_and_new_knowledge(self):
        """Superseding old knowledge marks it SUPERSEDED without deleting historical record."""
        old_item = DurableKnowledgeRecord(
            knowledge_id="kn_v1",
            normalized_statement="Old strategy v1",
            status=KnowledgeStatus.DURABLE,
        )

        superseded = KnowledgeDecayEngine.supersede_knowledge(
            old_knowledge=old_item,
            superseded_by_id="kn_v2",
        )

        self.assertEqual(superseded.status, KnowledgeStatus.SUPERSEDED)
        self.assertEqual(superseded.superseded_by, "kn_v2")


if __name__ == "__main__":
    unittest.main()
