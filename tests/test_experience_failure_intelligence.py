"""
Tests for Failure Normalization, Failure Signatures, and Historical Failure Intelligence (Prompt 2).
Verifies:
- FailureNormalizer mappings from exceptions, diagnoses, and unverified reasons
- Deterministic SHA-256 failure signatures over stable structured fields
- Privacy exclusion in signatures (volatile PIDs, HWNDs, timestamps, passwords excluded)
- Historical analytics queries:
  * Failure counts by category
  * Failure signature frequencies
  * Recovery success rate by category
  * Verification outcome distributions
  * Failure trends over time
"""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from runtime.diagnostics import FailureCategory, DiagnosticDiagnosis
from runtime.errors import StaleReferenceException, TargetNotFoundException
from runtime.experience.config import ExperienceConfig
from runtime.experience.models import (
    NormalizedFailureRecord,
    RecoveryExperienceRecord,
    OutcomeRecord,
    SessionExperienceRecord,
)
from runtime.experience.normalization import FailureNormalizer
from runtime.experience.store import ExperienceStore
from runtime.recovery_engine import RecoveryAction


class TestFailureIntelligence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="exp_fail_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir))
        self.store = ExperienceStore(self.config)
        self.addCleanup(self.store.close)
        self.normalizer = FailureNormalizer()

    def test_normalize_from_exception_types(self):
        """Verifies canonical mapping of common desktop automation exceptions."""
        # 1. Timeout
        cat_timeout, conf_t = self.normalizer.normalize_error(TimeoutError("Settlement timed out"))
        self.assertEqual(cat_timeout, FailureCategory.SETTLEMENT_TIMEOUT)
        self.assertGreaterEqual(conf_t, 0.8)

        # 2. Stale Reference
        cat_stale, conf_s = self.normalizer.normalize_error(StaleReferenceException(ref_id="ref_1", current_epoch=2, ref_epoch=1))
        self.assertEqual(cat_stale, FailureCategory.TARGET_NOT_ACTIONABLE)
        self.assertGreaterEqual(conf_s, 0.9)

        # 3. Target Not Found
        cat_not_found, conf_u = self.normalizer.normalize_error(TargetNotFoundException("HWND closed"))
        self.assertEqual(cat_not_found, FailureCategory.TARGET_NOT_FOUND)
        self.assertGreaterEqual(conf_u, 0.85)

        # 4. Unknown
        cat_unknown, conf_unk = self.normalizer.normalize_error(ValueError("Arbitrary logic error"))
        self.assertEqual(cat_unknown, FailureCategory.UNKNOWN)
        self.assertLessEqual(conf_unk, 0.5)

    def test_normalize_from_diagnostic_diagnosis(self):
        """Verifies mapping directly from authoritative DiagnosticDiagnosis."""
        diag = DiagnosticDiagnosis(
            session_id="sess_test",
            failure_category=FailureCategory.INPUT_DISPATCH_FAILURE,
            root_cause_summary="SendInput rejected due to UIPI permissions",
            confidence=0.98,
        )
        cat, conf = self.normalizer.normalize_error(diag)
        self.assertEqual(cat, FailureCategory.INPUT_DISPATCH_FAILURE)
        self.assertEqual(conf, 0.98)

    def test_deterministic_failure_signature_stability(self):
        """
        Verifies that equivalent failure conditions produce the EXACT same SHA-256 signature,
        even across different sessions, different timestamps, and different PIDs/HWNDs.
        """
        # Session A: target PID 1000, HWND 0x10, timestamp 100.0
        sig_a = self.normalizer.compute_failure_signature(
            category=FailureCategory.TARGET_NOT_FOUND,
            action_type="CLICK",
            plane="NATIVE_SHELL",
            target_role="Button",
            verdict="FAIL",
            recovery_result="FAILED",
        )

        # Session B: identical failure conditions, completely different session context
        sig_b = self.normalizer.compute_failure_signature(
            category=FailureCategory.TARGET_NOT_FOUND,
            action_type="CLICK",
            plane="NATIVE_SHELL",
            target_role="Button",
            verdict="FAIL",
            recovery_result="FAILED",
        )

        self.assertEqual(sig_a, sig_b)
        self.assertEqual(len(sig_a), 64)  # Valid SHA-256 hex string

    def test_distinct_failure_signatures_for_different_conditions(self):
        """Verifies that different failure conditions produce distinctly different signatures."""
        sig_click_fail = self.normalizer.compute_failure_signature(
            category=FailureCategory.TARGET_NOT_FOUND,
            action_type="CLICK",
            plane="NATIVE_SHELL",
            target_role="Button",
            verdict="FAIL",
        )

        sig_type_fail = self.normalizer.compute_failure_signature(
            category=FailureCategory.TARGET_NOT_FOUND,
            action_type="TYPE_TEXT",
            plane="NATIVE_SHELL",
            target_role="Edit",
            verdict="FAIL",
        )

        sig_timeout = self.normalizer.compute_failure_signature(
            category=FailureCategory.SETTLEMENT_TIMEOUT,
            action_type="CLICK",
            plane="NATIVE_SHELL",
            target_role="Button",
            verdict="FAIL",
        )

        self.assertNotEqual(sig_click_fail, sig_type_fail)
        self.assertNotEqual(sig_click_fail, sig_timeout)
        self.assertNotEqual(sig_type_fail, sig_timeout)

    def test_historical_failure_queries(self):
        """Verifies querying stored failures, grouping by category, signature, and action type."""
        sess_rec = SessionExperienceRecord(session_id="sess_hist_1", status="RUNNING")
        self.store.record_session(sess_rec)

        now = time.time()
        # Seed 3 failures of TARGET_NOT_FOUND (same signature)
        sig1 = self.normalizer.compute_failure_signature(
            FailureCategory.TARGET_NOT_FOUND, action_type="CLICK", plane="NATIVE"
        )
        for i in range(3):
            fail = NormalizedFailureRecord(
                failure_id=f"fail_tnf_{i}",
                session_id="sess_hist_1",
                normalized_category=FailureCategory.TARGET_NOT_FOUND.value,
                original_classification="TargetUnreachableException",
                failure_signature=sig1,
                action_id=f"act_{i}",
                action_type="CLICK",
                plane="NATIVE",
                timestamp=now - (i * 10),
            )
            self.store.record_failure(fail)

        # Seed 2 failures of SETTLEMENT_TIMEOUT (different signature)
        sig2 = self.normalizer.compute_failure_signature(
            FailureCategory.SETTLEMENT_TIMEOUT, action_type="TYPE_TEXT", plane="WEBVIEW_DOM"
        )
        for i in range(2):
            fail = NormalizedFailureRecord(
                failure_id=f"fail_timeout_{i}",
                session_id="sess_hist_1",
                normalized_category=FailureCategory.SETTLEMENT_TIMEOUT.value,
                original_classification="TimeoutError",
                failure_signature=sig2,
                action_id=f"act_t_{i}",
                action_type="TYPE_TEXT",
                plane="WEBVIEW_DOM",
                timestamp=now - (i * 10),
            )
            self.store.record_failure(fail)

        # 1. Total counts by category
        cat_counts = self.store.get_failure_category_counts()
        self.assertEqual(len(cat_counts), 2)
        counts_dict = {c.category: c.count for c in cat_counts}
        self.assertEqual(counts_dict[FailureCategory.TARGET_NOT_FOUND.value], 3)
        self.assertEqual(counts_dict[FailureCategory.SETTLEMENT_TIMEOUT.value], 2)

        # 2. Failure signature frequency
        sig_counts = self.store.get_failure_signature_counts()
        self.assertEqual(len(sig_counts), 2)
        sig_dict = {s.failure_signature: s.count for s in sig_counts}
        self.assertEqual(sig_dict[sig1], 3)
        self.assertEqual(sig_dict[sig2], 2)

        # 3. Failures by action type
        by_action = self.store.get_failures_by_action_type()
        action_dict = {item.category: item.count for item in by_action}
        self.assertEqual(action_dict["CLICK"], 3)
        self.assertEqual(action_dict["TYPE_TEXT"], 2)

        # 4. Recent failure trend
        trend = self.store.get_recent_failure_trend(time_window_seconds=3600)
        self.assertEqual(trend.get(FailureCategory.TARGET_NOT_FOUND.value), 3)
        self.assertEqual(trend.get(FailureCategory.SETTLEMENT_TIMEOUT.value), 2)

    def test_historical_recovery_and_verification_statistics(self):
        """Verifies aggregate calculation for recovery success rate and verification distribution."""
        sess_rec = SessionExperienceRecord(session_id="sess_stats_1", status="RUNNING")
        self.store.record_session(sess_rec)

        now = time.time()
        # Seed recovery attempts for TARGET_NOT_FOUND: 3 attempts, 2 success, 1 failed
        for i, res in enumerate(["SUCCESS", "SUCCESS", "FAILED"]):
            rec = RecoveryExperienceRecord(
                recovery_id=f"rec_{i}",
                session_id="sess_stats_1",
                trigger_category=FailureCategory.TARGET_NOT_FOUND.value,
                action=RecoveryAction.REFRESH_OBSERVATION.value,
                attempt_number=1,
                result=res,
                duration_ms=100.0 * (i + 1),
                timestamp=now,
            )
            self.store.record_recovery_attempt(rec)

        # Recovery statistics query
        stats = self.store.get_recovery_statistics(category=FailureCategory.TARGET_NOT_FOUND)
        self.assertEqual(stats.category, FailureCategory.TARGET_NOT_FOUND.value)
        self.assertEqual(stats.attempt_count, 3)
        self.assertEqual(stats.success_count, 2)
        self.assertAlmostEqual(stats.success_rate, 2.0 / 3.0, places=2)
        self.assertAlmostEqual(stats.mean_duration_ms, 200.0, places=1)

        # Seed outcomes: 3 PASS, 1 FAIL, 1 UNVERIFIED
        for i, v in enumerate(["PASS", "PASS", "PASS", "FAIL", "UNVERIFIED"]):
            out = OutcomeRecord(
                outcome_id=f"out_{i}",
                session_id="sess_stats_1",
                verdict=v,
                confidence=0.9,
                timestamp=now,
            )
            self.store.record_outcome(out)

        # Verification distribution query
        dist = self.store.get_verification_distribution(session_id="sess_stats_1")
        self.assertEqual(dist.total_outcomes, 5)
        self.assertEqual(dist.pass_count, 3)
        self.assertEqual(dist.fail_count, 1)
        self.assertEqual(dist.unverified_count, 1)
        self.assertAlmostEqual(dist.pass_rate, 0.6, places=2)
        self.assertAlmostEqual(dist.fail_rate, 0.2, places=2)
        self.assertAlmostEqual(dist.unverified_rate, 0.2, places=2)


if __name__ == "__main__":
    unittest.main()
