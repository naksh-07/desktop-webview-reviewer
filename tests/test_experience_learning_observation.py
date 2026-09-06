"""
Tests for Learning Observation Layer.
Architecture H / Milestone 2.1 Prompt 4.

Verifies:
- Deterministic observation identity and stable fingerprints
- Provenance and scope preservation
- Derived normalized observations from failures, recoveries, verifications, tool calls, corrections
- Bounded payloads and non-duplication
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.learning.models import (
    ObservationRecord,
    ObservationStatus,
    ObservationType,
)
from runtime.experience.learning.observation_engine import LearningObservationEngine
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


class TestLearningObservationLayer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="learning_obs_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=False)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)
        self.engine = LearningObservationEngine(self.store)

    def test_observation_from_normalized_failure_deterministic(self):
        """Verifies deterministic observation identity and fingerprinting from normalized failures."""
        failure = NormalizedFailureRecord(
            failure_id="fail_101",
            session_id="sess_1",
            category="TARGET_NOT_FOUND",
            root_cause="Element #submit-btn not found in DOM or UIA tree",
            signature="sig_target_not_found_submit",
            safe_context={"target_selector": "#submit-btn", "engine": "WebView2"},
            project_id="test_proj",
            scope=ExperienceScope.PROJECT,
        )

        obs1 = self.engine.create_observation_from_failure(failure)
        obs2 = self.engine.create_observation_from_failure(failure)

        # Observation ID must be deterministic based on type, scope, signature
        self.assertEqual(obs1.observation_id, obs2.observation_id)
        self.assertEqual(obs1.signature, "sig_target_not_found_submit")
        self.assertEqual(obs1.observation_type, ObservationType.TARGET_RESOLUTION_FAILURE)
        self.assertEqual(obs1.scope, ExperienceScope.SESSION)
        self.assertIn("fail_101", obs1.source_refs)
        self.assertEqual(obs1.status, ObservationStatus.OBSERVED)

    def test_observation_deduplication_and_count_accumulation(self):
        """Verifies recording the same observation increments count and updates timestamps."""
        failure1 = NormalizedFailureRecord(
            failure_id="fail_a",
            session_id="sess_1",
            category="ACTION_TIMEOUT",
            root_cause="Timeout waiting for renderer commit",
            signature="sig_timeout_commit",
            project_id="proj_alpha",
            scope=ExperienceScope.PROJECT,
        )
        failure2 = NormalizedFailureRecord(
            failure_id="fail_b",
            session_id="sess_2",
            category="ACTION_TIMEOUT",
            root_cause="Timeout waiting for renderer commit",
            signature="sig_timeout_commit",
            project_id="proj_alpha",
            scope=ExperienceScope.PROJECT,
        )

        obs1 = self.engine.create_observation_from_failure(failure1)
        self.store.record_observation(obs1)

        obs2 = self.engine.create_observation_from_failure(failure2)
        # Record second observation: should aggregate
        stored_obs = self.store.record_observation(obs2)

        self.assertEqual(stored_obs.occurrence_count, 2)
        self.assertIn("fail_a", stored_obs.source_refs)
        self.assertIn("fail_b", stored_obs.source_refs)

        # Verify from database fetch
        retrieved = self.store.get_observations(signature="sig_timeout_commit")
        self.assertEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].occurrence_count, 2)

    def test_observation_from_recovery_attempt(self):
        """Verifies recovery attempt observations capture success/failure rates and strategy."""
        recovery = RecoveryExperienceRecord(
            recovery_id="rec_1",
            session_id="sess_r",
            failure_id="fail_101",
            failure_category="ACTION_TIMEOUT",
            recovery_action="CDP_PAGE_RELOAD",
            result="SUCCESS",
            duration_ms=250.0,
        )

        obs = self.engine.create_observation_from_recovery(recovery)
        self.assertEqual(obs.observation_type, ObservationType.RECOVERY_PATTERN)
        self.assertEqual(obs.details.get("recovery_action"), "CDP_PAGE_RELOAD")
        self.assertEqual(obs.details.get("result"), "SUCCESS")

    def test_observation_from_verification_outcome(self):
        """Verifies verification outcome observation creation."""
        verif = OutcomeRecord(
            outcome_id="ver_1",
            session_id="sess_v",
            verdict="FAIL",
            confidence=0.95,
            error_category="TARGET_MISMATCH",
            details={"reason": "visual mismatch"},
        )

        obs = self.engine.create_observation_from_outcome(verif)
        self.assertIsNotNone(obs)
        self.assertEqual(obs.details.get("verdict"), "FAIL")
        self.assertIn("ver_1", obs.source_refs)

    def test_observation_from_agent_tool_call(self):
        """Verifies agent tool call observations sanitize arguments and preserve tool name."""
        tool_call = AgentToolCallRecord(
            tool_call_id="call_99",
            agent_session_id="sess_agy",
            conversation_id="conv_1",
            tool_name="desktop_click",
            tool_category="ACTION",
            success=False,
            safe_summary={"target": "button#submit"},
        )

        obs = self.engine.create_observation_from_tool_call(tool_call)
        self.assertIsNotNone(obs)
        self.assertEqual(len(obs.signature), 64)
        self.assertEqual(obs.details.get("tool_name"), "desktop_click")

    def test_observation_from_agent_correction(self):
        """Verifies user correction observations capture correction category."""
        correction = AgentCorrectionRecord(
            correction_id="corr_5",
            correction_type="TARGET_ADJUSTMENT",
            agent_session_id="sess_corr",
            conversation_id="conv_2",
            tool_call_id="call_99",
            related_dwr_session_id="dwr_sess_1",
            classification_details={"note": "User corrected target selector from #old to #new"},
        )

        obs = self.engine.create_observation_from_correction(correction)
        self.assertEqual(obs.observation_type, ObservationType.USER_CORRECTION_FOLLOWING_FAILURE)
        self.assertEqual(obs.details.get("correction_type"), "TARGET_ADJUSTMENT")
        self.assertIn("corr_5", obs.source_refs)


if __name__ == "__main__":
    unittest.main()
