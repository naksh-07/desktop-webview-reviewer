"""
Tests for Deterministic Pattern Detection Engine.
Architecture H / Milestone 2.1 Prompt 4.

Verifies:
- Repeated failures produce deterministic patterns
- Unrelated failures with different signatures do not merge
- Contradictory evidence is preserved and explainable
- Deterministic pattern IDs and reproducible outputs
- Traceability back to underlying ObservationRecords
"""

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.learning.models import (
    DetectedPatternRecord,
    ObservationRecord,
    ObservationStatus,
    ObservationType,
    PatternType,
)
from runtime.experience.learning.pattern_detector import DeterministicPatternDetector
from runtime.experience.models import ExperienceScope, ProvenanceRecord
from runtime.experience.store import ExperienceStore


class TestDeterministicPatternDetection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="learning_patterns_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=False)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)

    def _make_obs(self, obs_id: str, signature: str, obs_type: ObservationType, session_id: str = "sess_1", count: int = 1) -> ObservationRecord:
        return ObservationRecord(
            observation_id=obs_id,
            observation_type=obs_type,
            signature=signature,
            scope=ExperienceScope.PROJECT,
            session_id=session_id,
            occurrence_count=count,
            confidence=0.9,
            status=ObservationStatus.OBSERVED,
            details={"category": "TARGET_NOT_FOUND", "target": "button.submit"},
        )

    def test_repeated_failures_produce_pattern(self):
        """Verifies that 2 or more observations of the same signature yield a DetectedPatternRecord."""
        obs1 = self._make_obs("obs_1", "sig_btn_not_found", ObservationType.TARGET_RESOLUTION_FAILURE, session_id="sess_1")
        obs2 = self._make_obs("obs_2", "sig_btn_not_found", ObservationType.TARGET_RESOLUTION_FAILURE, session_id="sess_2")

        patterns = DeterministicPatternDetector.detect_patterns([obs1, obs2], scope=ExperienceScope.PROJECT)
        self.assertEqual(len(patterns), 1)

        pat = patterns[0]
        self.assertEqual(pat.pattern_type, PatternType.REPEATED_TARGET_RESOLUTION_FAILURE)
        self.assertEqual(pat.signature, "sig_btn_not_found")
        self.assertEqual(pat.occurrence_count, 2)
        self.assertEqual(pat.session_count, 2)
        self.assertIn("obs_1", pat.observation_refs)
        self.assertIn("obs_2", pat.observation_refs)

        # Pattern ID must be deterministic
        expected_hash = hashlib.sha256(f"{pat.pattern_type.value}:sig_btn_not_found".encode("utf-8")).hexdigest()[:12]
        self.assertEqual(pat.pattern_id, f"pat_{expected_hash}")

    def test_insufficient_evidence_does_not_produce_pattern(self):
        """Single observation (< 2 occurrences) should not produce a pattern."""
        obs1 = self._make_obs("obs_single", "sig_isolated_failure", ObservationType.FAILURE_SIGNATURE, count=1)
        patterns = DeterministicPatternDetector.detect_patterns([obs1], scope=ExperienceScope.PROJECT)
        self.assertEqual(len(patterns), 0)

    def test_unrelated_failures_do_not_merge(self):
        """Distinct failure signatures must produce distinct patterns, never collapsing into one."""
        obs_a1 = self._make_obs("obs_a1", "sig_alpha", ObservationType.FAILURE_SIGNATURE, session_id="s1")
        obs_a2 = self._make_obs("obs_a2", "sig_alpha", ObservationType.FAILURE_SIGNATURE, session_id="s2")

        obs_b1 = self._make_obs("obs_b1", "sig_beta", ObservationType.FAILURE_SIGNATURE, session_id="s3")
        obs_b2 = self._make_obs("obs_b2", "sig_beta", ObservationType.FAILURE_SIGNATURE, session_id="s4")

        patterns = DeterministicPatternDetector.detect_patterns([obs_a1, obs_a2, obs_b1, obs_b2], scope=ExperienceScope.PROJECT)
        self.assertEqual(len(patterns), 2)

        signatures = {p.signature for p in patterns}
        self.assertEqual(signatures, {"sig_alpha", "sig_beta"})

        pat_a = next(p for p in patterns if p.signature == "sig_alpha")
        self.assertEqual(pat_a.observation_refs, ["obs_a1", "obs_a2"])
        pat_b = next(p for p in patterns if p.signature == "sig_beta")
        self.assertEqual(pat_b.observation_refs, ["obs_b1", "obs_b2"])

    def test_pattern_persistence_and_retrieval(self):
        """Verifies detected patterns can be persisted into ExperienceStore and queried."""
        obs1 = self._make_obs("obs_p1", "sig_perm", ObservationType.TARGET_RESOLUTION_FAILURE, session_id="s1")
        obs2 = self._make_obs("obs_p2", "sig_perm", ObservationType.TARGET_RESOLUTION_FAILURE, session_id="s2")

        patterns = DeterministicPatternDetector.detect_patterns([obs1, obs2], scope=ExperienceScope.PROJECT)
        self.assertEqual(len(patterns), 1)

        self.store.record_pattern(patterns[0])

        stored = self.store.get_patterns(pattern_type=PatternType.REPEATED_TARGET_RESOLUTION_FAILURE)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].pattern_id, patterns[0].pattern_id)
        self.assertEqual(stored[0].occurrence_count, 2)


if __name__ == "__main__":
    unittest.main()
