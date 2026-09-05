"""
Phase 10: Unified Desktop Trace & Observability Unit and Contract Tests.
Verifies:
- Monotonic BoundedTraceTimeline retention and capacity enforcement
- Universal correlation envelope (session, epoch, action, plane)
- Trace causal reconstruction across the 5 action lifecycle milestones
- Sensitive credential and token redaction
- Log line and console event ingestion into canonical trace events
"""

from __future__ import annotations
import unittest
import time

from runtime.trace_models import (
    DesktopTraceEvent,
    DesktopTraceEventType,
    TraceCorrelation,
    TraceTimeline,
)
from runtime.trace_engine import (
    DesktopTraceEngine,
    BoundedTraceTimeline,
    redact_sensitive_text,
)
from runtime.state import TargetPlane
from runtime.action_models import ActionLifecycleStage


class TestPhase10TraceAndObservability(unittest.TestCase):
    def setUp(self):
        self.session_id = "test_sess_p10"
        self.engine = DesktopTraceEngine(session_id=self.session_id, max_events_per_session=100)

    def test_bounded_timeline_capacity(self):
        """Timeline must not grow unboundedly beyond max_events."""
        timeline = BoundedTraceTimeline(max_events=10)
        corr = TraceCorrelation(session_id=self.session_id, epoch_id=1, action_id="act_1")
        for i in range(25):
            evt = DesktopTraceEvent(
                event_type=DesktopTraceEventType.OBSERVATION,
                correlation=corr,
                status=f"EVT_{i}",
            )
            timeline.record(evt)

        events = timeline.get_events()
        self.assertEqual(len(events), 10)
        self.assertEqual(events[-1].status, "EVT_24")
        self.assertEqual(events[0].status, "EVT_15")

    def test_sensitive_token_redaction(self):
        """API keys, Bearer tokens, and secrets must be replaced with [REDACTED]."""
        raw_log = "Connected with Bearer sk-ant-1234567890abcdef1234567890 to backend"
        redacted = redact_sensitive_text(raw_log)
        self.assertNotIn("sk-ant-1234567890abcdef1234567890", redacted)
        self.assertIn("[REDACTED]", redacted)

        pwd_log = "password=SuperSecretPassword123! token=ghp_abc1234567890def"
        redacted_pwd = redact_sensitive_text(pwd_log)
        self.assertNotIn("SuperSecretPassword123!", redacted_pwd)
        self.assertNotIn("ghp_abc1234567890def", redacted_pwd)

    def test_trace_event_correlation_and_lifecycle_milestones(self):
        """Events must support multi-key filtering and preserve exact action lifecycle sequence."""
        action_id = "act_lifecycle_test"
        corr = TraceCorrelation(session_id=self.session_id, epoch_id=1, action_id=action_id)

        # 1. ACTION_RECEIVED
        self.engine.record_event(DesktopTraceEvent(
            event_type=DesktopTraceEventType.ACTION_REQUESTED,
            correlation=corr,
            plane=TargetPlane.NATIVE,
            target_reference="w1e1",
            status="RECEIVED",
            details={"stage": ActionLifecycleStage.ACTION_RECEIVED.value},
        ))

        # 2. TARGET_RESOLVED
        self.engine.record_event(DesktopTraceEvent(
            event_type=DesktopTraceEventType.TARGET_RESOLVED,
            correlation=corr,
            plane=TargetPlane.NATIVE,
            target_reference="w1e1",
            status="RESOLVED",
        ))

        # 3. ACTION_DISPATCHED
        self.engine.record_event(DesktopTraceEvent(
            event_type=DesktopTraceEventType.ACTION_DISPATCHED,
            correlation=corr,
            plane=TargetPlane.NATIVE,
            target_reference="w1e1",
            status="DISPATCHED",
            details={"stage": ActionLifecycleStage.ACTION_DISPATCHED.value},
        ))

        # 4. ACTION_SETTLED (ACTION_COMPLETED)
        self.engine.record_event(DesktopTraceEvent(
            event_type=DesktopTraceEventType.ACTION_SETTLED,
            correlation=corr,
            plane=TargetPlane.NATIVE,
            status="SETTLED",
            details={"stage": ActionLifecycleStage.ACTION_COMPLETED.value},
        ))

        # 5. OBSERVATION (STATE_CHANGED)
        post_corr = TraceCorrelation(session_id=self.session_id, epoch_id=2, action_id=action_id)
        self.engine.record_event(DesktopTraceEvent(
            event_type=DesktopTraceEventType.OBSERVATION,
            correlation=post_corr,
            plane=TargetPlane.NATIVE,
            status="STATE_CHANGED",
            details={"stage": ActionLifecycleStage.STATE_CHANGED.value},
        ))

        # 6. ASSERTION (EXPECTED_STATE_VERIFIED)
        self.engine.record_event(DesktopTraceEvent(
            event_type=DesktopTraceEventType.ASSERTION,
            correlation=post_corr,
            plane=TargetPlane.NATIVE,
            status="PASS",
            details={"stage": ActionLifecycleStage.EXPECTED_STATE_VERIFIED.value},
        ))

        # Reconstruct action lifecycle
        lifecycle = self.engine.get_action_lifecycle(action_id, self.session_id)
        self.assertEqual(len(lifecycle), 6)
        event_types = [e.event_type for e in lifecycle]
        self.assertEqual(event_types, [
            DesktopTraceEventType.ACTION_REQUESTED,
            DesktopTraceEventType.TARGET_RESOLVED,
            DesktopTraceEventType.ACTION_DISPATCHED,
            DesktopTraceEventType.ACTION_SETTLED,
            DesktopTraceEventType.OBSERVATION,
            DesktopTraceEventType.ASSERTION,
        ])

    def test_log_and_console_stream_ingestion(self):
        """Stdout/stderr lines and CDP console messages must be converted to correlated trace events."""
        # Ingest stdout log line
        evt_log = self.engine.ingest_log_line(
            stream="stdout",
            line="Application initialization completed successfully with token=sec1234567890",
            process_id=4321,
            session_id=self.session_id,
        )
        self.assertEqual(evt_log.event_type, DesktopTraceEventType.LOG_EVENT)
        self.assertNotIn("sec1234567890", evt_log.details["message"])
        self.assertIn("[REDACTED]", evt_log.details["message"])
        self.assertEqual(evt_log.process_id, 4321)

        # Ingest console event
        evt_console = self.engine.ingest_console_message(
            level="error",
            message="Uncaught TypeError: Cannot read properties of undefined",
            source="console",
            cdp_target_id="target_cdp_99",
            session_id=self.session_id,
        )
        self.assertEqual(evt_console.event_type, DesktopTraceEventType.CONSOLE_EVENT)
        self.assertEqual(evt_console.details["level"], "error")
        self.assertEqual(evt_console.cdp_target_id, "target_cdp_99")

        # Query events from timeline
        events = self.engine.query(session_id=self.session_id)
        self.assertGreaterEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
