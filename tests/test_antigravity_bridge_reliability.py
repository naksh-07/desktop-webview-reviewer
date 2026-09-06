"""
Tests for Standalone Operation, Graceful Degradation, and Failure Independence.

Enforces Section 19 and 22 of Milestone 2.1 Prompt 3:
- Antigravity absent -> DWR functions normally
- Antigravity bridge disabled -> DWR functions normally
- Malformed events rejected safely without impacting runtime
- Experience Store unavailable -> Antigravity bridge degrades gracefully without crashing
"""

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from runtime.experience.config import ExperienceConfig
from runtime.experience.models import SessionExperienceRecord
from runtime.experience.store import ExperienceStore
from runtime.experience.antigravity.bridge import AntigravityCorrelationBridge
from runtime.experience.antigravity.contracts import (
    AgentEventEnvelope,
    AgentEventType,
)
from runtime.experience.antigravity.hook_adapter import AntigravityHookAdapter


class TestAntigravityBridgeReliability(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="agy_rel_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.config = ExperienceConfig(base_dir=Path(self.temp_dir), fail_safe_mode=True)
        self.store = ExperienceStore(config=self.config)
        self.addCleanup(self.store.close)

    def test_disabled_bridge_returns_none_without_side_effects(self):
        """Verifies that when disabled, bridge immediately returns None and incurs zero overhead."""
        disabled_bridge = AntigravityCorrelationBridge(store=self.store, enabled=False)
        self.assertFalse(disabled_bridge.enabled)

        env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            tool_name="desktop_click",
        )
        res = disabled_bridge.ingest_event(env)
        self.assertIsNone(res)

        status = disabled_bridge.get_status()
        self.assertFalse(status.enabled)
        self.assertEqual(status.events_accepted, 0)

    def test_malformed_event_payload_gracefully_rejected(self):
        """Verifies malformed or corrupt payloads are rejected without throwing exceptions."""
        bridge = AntigravityCorrelationBridge(store=self.store, enabled=True)

        # 1. Raw hook with invalid data
        res = bridge.ingest_raw_hook("UnknownHookEvent", {"invalid_structure": 123})
        # Handled gracefully, returns either fallback or None
        self.assertTrue(res is None or hasattr(res, "confidence"))

        # 2. Privacy violation payload
        malicious_env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            safe_summary={"chain_of_thought": "secret internal thoughts"},
        )
        res2 = bridge.ingest_event(malicious_env)
        self.assertIsNone(res2)
        self.assertEqual(bridge.sanitizer.privacy_violations_blocked, 1)

    def test_store_unavailable_graceful_degradation(self):
        """Verifies bridge handles unavailable or closed Experience Store without crashing."""
        # Create a store and close it immediately to simulate database outage
        closed_store = ExperienceStore(
            config=ExperienceConfig(
                base_dir=Path(self.temp_dir) / "closed_store",
                fail_safe_mode=True,
            )
        )
        closed_store.close()

        bridge = AntigravityCorrelationBridge(store=closed_store, enabled=True)

        env = AgentEventEnvelope(
            event_type=AgentEventType.AGENT_TOOL_COMPLETED,
            conversation_id="conv_robust",
            tool_name="desktop_click",
        )
        # Ingestion must not crash even if the underlying database is closed
        result = bridge.ingest_event(env)
        # Should gracefully return None or correlation without throwing
        self.assertTrue(result is None or hasattr(result, "confidence"))

    def test_hook_adapter_cli_resilience_on_broken_stdin(self):
        """Verifies execute_cli_hook never exits with non-zero on corrupt stdin."""
        adapter = AntigravityHookAdapter()
        bridge = AntigravityCorrelationBridge(store=self.store, enabled=True)

        broken_stdin = io.StringIO("{ malformed json string !!!")
        stdout_capture = io.StringIO()

        exit_code = adapter.execute_cli_hook(
            "PreToolUse",
            in_stream=broken_stdin,
            out_stream=stdout_capture,
            bridge=bridge,
        )
        self.assertEqual(exit_code, 0)
        output = stdout_capture.getvalue()
        self.assertTrue(len(output) > 0)
        parsed = json.loads(output)
        self.assertEqual(parsed.get("decision"), "allow")


if __name__ == "__main__":
    unittest.main()
