"""
Tests for Antigravity Event Contracts, Envelopes, Models, and Schema v3 Migrations.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.schema import CURRENT_SCHEMA_VERSION, apply_migrations
from runtime.experience.store import ExperienceStore
from runtime.experience.antigravity.contracts import (
    AgentEventEnvelope,
    AgentEventType,
    CorrelationConfidence,
    UserCorrectionType,
)
from runtime.experience.antigravity.models import (
    AgentArtifactRecord,
    AgentCorrectionRecord,
    AgentDwrCorrelationRecord,
    AgentSessionRecord,
    AgentSubagentRecord,
    AgentToolCallRecord,
    AgentTurnRecord,
)


class TestAntigravityContractsAndSchema(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="agy_contracts_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=False)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)

    def test_schema_version_is_v3(self):
        """Verifies current schema version is updated to v3."""
        self.assertEqual(CURRENT_SCHEMA_VERSION, 3)
        health = self.store.get_health_report()
        self.assertEqual(health.schema_version, 3)

    def test_migration_v3_creates_all_tables_and_indices(self):
        """Verifies all 7 Antigravity correlation tables and their indexes exist in SQLite."""
        conn = sqlite3.connect(str(self.config.database_path))
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        required_tables = {
            "agent_sessions",
            "agent_turns",
            "agent_tool_calls",
            "agent_subagents",
            "agent_artifacts",
            "agent_corrections",
            "agent_dwr_correlations",
        }
        for rt in required_tables:
            self.assertIn(rt, tables, f"Expected table '{rt}' missing from SQLite schema.")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
        indices = {row[0] for row in cursor.fetchall()}
        self.assertIn("idx_agent_sess_conv", indices)
        self.assertIn("idx_agent_tools_sess", indices)
        self.assertIn("idx_corr_dwr_sess", indices)
        conn.close()

    def test_event_envelope_serialization_and_optional_fields(self):
        """Verifies AgentEventEnvelope handles optional fields and JSON serialization."""
        envelope = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            conversation_id="conv_123",
            tool_name="desktop_click",
            tool_category="mcp",
            success=True,
            duration_ms=45.2,
            safe_summary={"action_type": "CLICK", "target_role": "button"},
        )
        d = envelope.to_dict()
        self.assertEqual(d["event_type"], "AGENT_TOOL_COMPLETED")
        self.assertEqual(d["conversation_id"], "conv_123")
        self.assertIsNone(d["subagent_id"])

        reconstructed = AgentEventEnvelope.from_dict(d)
        self.assertEqual(reconstructed.event_type, AgentEventType.AGENT_TOOL_COMPLETED)
        self.assertEqual(reconstructed.tool_name, "desktop_click")
        self.assertTrue(reconstructed.success)
        self.assertEqual(reconstructed.safe_summary["target_role"], "button")

    def test_agent_records_persistence_and_retrieval(self):
        """Verifies all agent entities survive persistence and can be queried cleanly."""
        # 1. Agent Session
        sess = AgentSessionRecord(
            agent_session_id="asess_001",
            conversation_id="conv_001",
            agent_id="main_orchestrator",
            workspace_id="workspace_alpha",
            metadata={"framework": "antigravity"},
        )
        self.store.record_agent_session(sess)

        # 2. Agent Turn
        turn = AgentTurnRecord(
            turn_id="aturn_001",
            agent_session_id="asess_001",
            conversation_id="conv_001",
            step_index=1,
            status="COMPLETED",
        )
        self.store.record_agent_turn(turn)

        # 3. Agent Tool Call
        tool_call = AgentToolCallRecord(
            tool_call_id="atool_001",
            turn_id="aturn_001",
            agent_session_id="asess_001",
            conversation_id="conv_001",
            tool_name="desktop_click",
            tool_category="mcp",
            success=True,
            duration_ms=120.5,
            safe_summary={"target_role": "button"},
        )
        self.store.record_agent_tool_call(tool_call)

        # 4. Subagent Delegation
        sub = AgentSubagentRecord(
            subagent_id="sub_001",
            parent_agent_id="main_orchestrator",
            conversation_id="conv_001",
            agent_session_id="asess_001",
            status="COMPLETED",
        )
        self.store.record_agent_subagent(sub)

        # 5. Agent Artifact
        art = AgentArtifactRecord(
            artifact_id="art_001",
            artifact_type="plan",
            safe_reference="implementation_plan.md",
            agent_session_id="asess_001",
            turn_id="aturn_001",
        )
        self.store.record_agent_artifact(art)

        # 6. Agent Correction
        corr = AgentCorrectionRecord(
            correction_id="acorr_001",
            correction_type=UserCorrectionType.USER_CORRECTED_AGENT.value,
            agent_session_id="asess_001",
            conversation_id="conv_001",
            classification_details={"reason": "target_adjusted"},
        )
        self.store.record_agent_correction(corr)

        # 7. DWR Correlation
        dwr_corr = AgentDwrCorrelationRecord(
            correlation_id="dcorr_001",
            confidence=CorrelationConfidence.EXACT,
            agent_session_id="asess_001",
            conversation_id="conv_001",
            tool_call_id="atool_001",
            dwr_session_id=None,  # Optional
            dwr_action_id="act_physical_01",
            correlation_source="test_verification",
        )
        self.store.record_agent_correlation(dwr_corr)

        # Verify counts in health report
        counts = self.store.get_record_counts()
        self.assertEqual(counts["agent_sessions"], 1)
        self.assertEqual(counts["agent_turns"], 1)
        self.assertEqual(counts["agent_tool_calls"], 1)
        self.assertEqual(counts["agent_subagents"], 1)
        self.assertEqual(counts["agent_artifacts"], 1)
        self.assertEqual(counts["agent_corrections"], 1)
        self.assertEqual(counts["agent_dwr_correlations"], 1)


if __name__ == "__main__":
    unittest.main()
