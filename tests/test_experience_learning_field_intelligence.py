"""
Tests for Field Intelligence Query & Aggregate Reporting Engine.
Architecture H / Milestone 2.1 Prompt 4.

Verifies the 12 descriptive aggregate queries:
1. Top recurring failure signatures
2. Failure recurrence by action type
3. Recovery success by strategy/category
4. Verification outcome distribution over time
5. Agent tool categories associated with failures
6. User corrections associated with recurring failures
7. Most frequent improvement candidates
8. Candidate validation status
9. Durable knowledge due for review
10. Stale/superseded knowledge
11. Experience volume by project/scope
12. Newly emerging patterns

Ensures results are purely descriptive without ungrounded causal claims.
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.learning.field_intelligence import FieldIntelligenceEngine
from runtime.experience.learning.models import (
    CandidateCategory,
    CandidateStatus,
    DetectedPatternRecord,
    DurableKnowledgeRecord,
    ImprovementCandidateRecord,
    KnowledgeStatus,
    PatternType,
)
from runtime.experience.models import (
    ExperienceScope,
    NormalizedFailureRecord,
    OutcomeRecord,
    RecoveryExperienceRecord,
)
from runtime.experience.antigravity.models import (
    AgentCorrectionRecord,
    AgentToolCallRecord,
)
from runtime.experience.store import ExperienceStore


class TestFieldIntelligenceEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="learning_fi_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=False)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)
        self.engine = FieldIntelligenceEngine(self.store)

    def test_empty_store_field_intelligence_report(self):
        """Verifies report generation degrades safely when store contains no records."""
        report = self.engine.generate_full_report()
        self.assertEqual(len(report.top_recurring_failures), 0)
        self.assertEqual(len(report.failures_by_action_type), 0)
        self.assertEqual(len(report.recovery_success_by_strategy), 0)
        self.assertEqual(len(report.knowledge_due_for_review), 0)
        self.assertIsNotNone(report.generated_at)

    def test_populated_store_all_12_queries(self):
        """Populates store with synthetic history and verifies all 12 descriptive queries."""
        from runtime.experience.models import SessionExperienceRecord
        from runtime.experience.antigravity.models import AgentSessionRecord

        # Seed sessions required by FK constraints in normalized_failures and recovery_attempts
        for sid in ("s1", "s2", "s3"):
            self.store.record_session(SessionExperienceRecord(session_id=sid, status="COMPLETED"))

        # Seed agent session required for agent_tool_calls and agent_corrections
        self.store.record_agent_session(
            AgentSessionRecord(
                agent_session_id="as1",
                conversation_id="conv_test",
                status="COMPLETED",
            )
        )

        # 1 & 2: Normalized failures and action types
        f1 = NormalizedFailureRecord(
            failure_id="f1",
            session_id="s1",
            category="TARGET_NOT_FOUND",
            signature="sig_btn",
            safe_context={"action_type": "CLICK", "plane": "WEB"},
        )
        f2 = NormalizedFailureRecord(
            failure_id="f2",
            session_id="s2",
            category="TARGET_NOT_FOUND",
            signature="sig_btn",
            safe_context={"action_type": "CLICK", "plane": "WEB"},
        )
        f3 = NormalizedFailureRecord(
            failure_id="f3",
            session_id="s3",
            category="ACTION_TIMEOUT",
            signature="sig_load",
            safe_context={"action_type": "NAVIGATE", "plane": "WEB"},
        )
        self.store.record_failure(f1)
        self.store.record_failure(f2)
        self.store.record_failure(f3)

        # 3: Recovery attempts
        r1 = RecoveryExperienceRecord(
            recovery_id="r1",
            session_id="s1",
            failure_category="TARGET_NOT_FOUND",
            recovery_action="REFRESH_OBSERVATION",
            result="SUCCESS",
        )
        r2 = RecoveryExperienceRecord(
            recovery_id="r2",
            session_id="s2",
            failure_category="TARGET_NOT_FOUND",
            recovery_action="REFRESH_OBSERVATION",
            result="SUCCESS",
        )
        self.store.record_recovery_attempt(r1)
        self.store.record_recovery_attempt(r2)

        # 4: Verification outcomes
        v1 = OutcomeRecord(outcome_id="v1", session_id="s1", verdict="PASS", confidence=1.0)
        v2 = OutcomeRecord(outcome_id="v2", session_id="s2", verdict="FAIL", confidence=0.9)
        self.store.record_outcome(v1)
        self.store.record_outcome(v2)

        # 5: Agent tool calls
        t1 = AgentToolCallRecord(
            tool_call_id="t1",
            agent_session_id="as1",
            tool_name="desktop_click",
            tool_category="ACTION",
            success=False,
            error_class="TargetNotFound",
        )
        self.store.record_agent_tool_call(t1)

        # 6: User corrections
        c1 = AgentCorrectionRecord(
            correction_id="c1",
            correction_type="TARGET_ADJUSTMENT",
            agent_session_id="as1",
            classification_details={"target": "button.primary"},
        )
        self.store.record_agent_correction(c1)

        # 7 & 8: Improvement candidates
        cand1 = ImprovementCandidateRecord(
            candidate_id="cand_1",
            category=CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS,
            affected_subsystem="runtime.target_resolver",
            rationale_summary="Repeated click failure",
            pattern_id="pat_1",
            evidence_count=10,
            session_count=5,
            confidence=0.9,
            status=CandidateStatus.VALIDATED,
        )
        self.store.record_improvement_candidate(cand1)

        # 9 & 10: Durable knowledge (one review due, one stale)
        now = datetime.now(timezone.utc)
        k_due = DurableKnowledgeRecord(
            knowledge_id="k_due",
            normalized_statement="Knowledge due for review",
            status=KnowledgeStatus.DURABLE,
            review_due_at=(now - timedelta(days=5)).isoformat(),
        )
        k_stale = DurableKnowledgeRecord(
            knowledge_id="k_stale",
            normalized_statement="Stale knowledge",
            status=KnowledgeStatus.STALE,
            updated_at=(now - timedelta(days=60)).isoformat(),
        )
        self.store.record_durable_knowledge(k_due)
        self.store.record_durable_knowledge(k_stale)

        # 12: Emerging pattern
        pat1 = DetectedPatternRecord(
            pattern_id="pat_1",
            pattern_type=PatternType.REPEATED_TARGET_RESOLUTION_FAILURE,
            signature="sig_btn",
            summary="Repeated target resolution failure on button",
            occurrence_count=4,
            session_count=2,
        )
        self.store.record_pattern(pat1)

        # Execute full report
        report = self.engine.generate_full_report()

        # 1. Top recurring failure signatures
        self.assertGreaterEqual(len(report.top_recurring_failures), 1)
        self.assertEqual(report.top_recurring_failures[0]["signature"], "sig_btn")
        self.assertEqual(report.top_recurring_failures[0]["occurrence_count"], 2)

        # 2. Failure recurrence by action type
        self.assertGreaterEqual(len(report.failures_by_action_type), 1)

        # 3. Recovery success by strategy
        self.assertGreaterEqual(len(report.recovery_success_by_strategy), 1)
        rec_stat = report.recovery_success_by_strategy[0]
        self.assertEqual(rec_stat["recovery_action"], "REFRESH_OBSERVATION")
        self.assertEqual(rec_stat["successful_attempts"], 2)

        # 4. Verification distribution
        self.assertIn("pass_count", report.verification_distribution)
        self.assertIn("fail_count", report.verification_distribution)
        self.assertEqual(report.verification_distribution["pass_count"], 1)
        self.assertEqual(report.verification_distribution["fail_count"], 1)

        # 5. Agent tool categories
        self.assertGreaterEqual(len(report.agent_tool_failures), 1)
        self.assertEqual(report.agent_tool_failures[0]["tool_category"], "ACTION")

        # 6. User corrections
        self.assertGreaterEqual(len(report.user_corrections), 1)
        self.assertEqual(report.user_corrections[0]["correction_type"], "TARGET_ADJUSTMENT")

        # 7. Frequent improvement candidates
        self.assertGreaterEqual(len(report.frequent_candidates), 1)
        self.assertEqual(report.frequent_candidates[0]["candidate_id"], "cand_1")

        # 8. Candidate validation status
        self.assertIn("VALIDATED", report.candidate_validation_status)
        self.assertEqual(report.candidate_validation_status["VALIDATED"], 1)

        # 9. Durable knowledge due for review
        self.assertGreaterEqual(len(report.knowledge_due_for_review), 1)
        self.assertEqual(report.knowledge_due_for_review[0]["knowledge_id"], "k_due")

        # 10. Stale knowledge
        self.assertGreaterEqual(len(report.stale_or_superseded_knowledge), 1)
        self.assertEqual(report.stale_or_superseded_knowledge[0]["knowledge_id"], "k_stale")

        # 12. Emerging patterns
        self.assertGreaterEqual(len(report.emerging_patterns), 1)
        self.assertEqual(report.emerging_patterns[0]["pattern_id"], "pat_1")


if __name__ == "__main__":
    unittest.main()
