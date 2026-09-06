"""
Proving-Ground Integration Test for Antigravity Correlation Bridge.

Enforces Sections 24 and 25 of Milestone 2.1 Prompt 3:
- End-to-end controlled workflow:
  Agent lifecycle -> DWR session/action -> Verification outcome -> Relational correlation -> Historical query
- Proves historical intelligence questions:
  1. Which agent session caused this DWR review?
  2. Which tool call was associated with this DWR action?
  3. What was the final DWR verification result?
  4. Was recovery required?
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.models import OutcomeRecord, SessionExperienceRecord
from runtime.experience.store import ExperienceStore
from runtime.experience.adapter import ExperienceIntegrationAdapter
from runtime.experience.antigravity.bridge import AntigravityCorrelationBridge
from runtime.experience.antigravity.contracts import CorrelationConfidence


class TestAntigravityProvingGround(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="agy_proving_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=False)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)

        self.bridge = AntigravityCorrelationBridge(store=self.store, enabled=True)
        self.adapter = ExperienceIntegrationAdapter(store=self.store, bridge=self.bridge)

    def test_end_to_end_controlled_proving_ground(self):
        """
        Executes a controlled micro-workflow demonstrating agent ↔ DWR reality correlation.
        """
        conv_id = "conv_proving_ground_01"
        turn_id = "turn_1"
        action_id = "act_inspect_main_window"
        session_id = "sess_dwr_pg_01"

        # Step 1: Agent PreInvocation hook fires (AGENT_TURN_STARTED)
        self.bridge.ingest_raw_hook(
            "PreInvocation",
            {
                "conversationId": conv_id,
                "invocationNum": 1,
            },
        )

        # Step 2: DWR session initializes
        self.adapter.on_session_created(
            session_id=session_id,
            project_id="desktop_review_target",
            metadata={"conversation_id": conv_id},
        )

        # Step 3: Agent PreToolUse hook fires before desktop_inspect
        self.bridge.ingest_raw_hook(
            "PreToolUse",
            {
                "conversationId": conv_id,
                "stepIdx": 1,
                "toolCall": {
                    "name": "desktop_inspect",
                    "args": {"session_id": session_id, "plane": "NATIVE"},
                },
            },
        )

        # Step 4: DWR executes action and settles
        class DummyRequest:
            action_id = "act_inspect_main_window"
            action_type = "INSPECT"
            target = "Window"

        class DummyReceipt:
            plane = "NATIVE"
            target = "Window"

        class DummyOutcome:
            duration_ms = 85.0
            verdict = "PASS"

        self.adapter.on_action_settled(
            session_id=session_id,
            action_request=DummyRequest(),
            receipt=DummyReceipt(),
            outcome=DummyOutcome(),
        )

        # Step 5: Agent PostToolUse hook fires
        self.bridge.ingest_raw_hook(
            "PostToolUse",
            {
                "conversationId": conv_id,
                "stepIdx": 1,
                "toolCall": {
                    "name": "desktop_inspect",
                    "args": {"session_id": session_id},
                },
                "durationMs": 85.0,
            },
        )

        # Step 6: Final DWR verification outcome recorded
        self.store.record_outcome(
            OutcomeRecord(
                outcome_id="out_pg_01",
                session_id=session_id,
                verdict="PASS",
                confidence=1.0,
            )
        )

        # ---------------------------------------------------------------------
        # Verification of Historical Intelligence Questions
        # ---------------------------------------------------------------------

        # Question 1: Which agent session caused this DWR review?
        correlations = self.store.get_agent_dwr_correlations(dwr_session_id=session_id)
        self.assertTrue(len(correlations) >= 1)
        corr = correlations[0]
        self.assertEqual(corr.conversation_id, conv_id)
        self.assertIn(corr.confidence, [CorrelationConfidence.EXACT, CorrelationConfidence.HIGH])

        # Question 2: Which tool call was associated with this DWR action?
        action_tools = self.store.get_agent_activity_for_dwr_action(action_id)
        self.assertTrue(len(action_tools) >= 1)
        self.assertEqual(action_tools[0].tool_name, "desktop_inspect")
        self.assertTrue(action_tools[0].success)

        # Question 3: What was the final DWR verification result?
        tool_outcomes = self.store.get_agent_tool_calls_by_outcome("PASS")
        self.assertTrue(len(tool_outcomes) >= 1)
        self.assertEqual(tool_outcomes[0]["review_verdict"], "PASS")

        # Question 4: Was recovery required?
        recoveries = self.store.get_recovery_attempts(session_id=session_id)
        self.assertEqual(len(recoveries), 0, "No recovery should have been required for smooth inspection.")


if __name__ == "__main__":
    unittest.main()
