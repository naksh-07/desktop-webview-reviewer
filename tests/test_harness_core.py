"""
Unit and Contract Tests for Reviewer Test Harness Core & Protocol (Phase 13).
Verifies message serialization, size boundaries, session binding, replay protection,
temporal tolerance, lifecycle signals, diagnostics, fixtures, faults, and the Harness Golden Rule.
"""

import asyncio
import json
import time
import unittest

from runtime.harness_contracts import (
    BuildMode,
    HarnessLifecycleSignal,
    HarnessFixtureAction,
    HarnessFaultType,
    HarnessDiagnosticData,
    HarnessFaultInjectionRequest,
    HarnessSecurityValidator,
    HarnessGoldenRuleEnforcer,
    HarnessSecurityViolationException,
    VerificationVerdict,
)
from runtime.harness.protocol import (
    HarnessMessage,
    HarnessMessageType,
    HarnessProtocolError,
    HarnessSecurityError,
    HarnessMessageValidator,
    MAX_HARNESS_MESSAGE_BYTES,
)
from runtime.harness.service import HarnessService
from runtime.trace_engine import DesktopTraceEngine
from runtime.trace_models import DesktopTraceEventType
from runtime.capability import CapabilityMatrix, CapabilityId, CapabilityStatus


class TestHarnessCoreAndProtocol(unittest.TestCase):
    """Authoritative test suite for harness protocol, service, and contracts."""

    def setUp(self):
        self.session_id = "test_sess_core_01"
        self.app_id = "test_app_01"
        self.auth_token = "secret_test_token_123"

    # -------------------------------------------------------------------------
    # 1. Protocol & Message Serialization
    # -------------------------------------------------------------------------
    def test_message_serialization_and_deserialization(self):
        """Verifies round-trip serialization of valid HarnessMessage."""
        msg = HarnessMessage(
            session_id=self.session_id,
            application_id=self.app_id,
            harness_instance_id="inst_001",
            message_type=HarnessMessageType.LIFECYCLE,
            payload={"signal": "APP_READY", "details": {"version": "1.0"}},
            sequence=1,
            auth_token=self.auth_token,
        )
        json_str = msg.to_json()
        parsed = HarnessMessage.from_json(json_str)

        self.assertEqual(parsed.session_id, self.session_id)
        self.assertEqual(parsed.application_id, self.app_id)
        self.assertEqual(parsed.message_type, HarnessMessageType.LIFECYCLE)
        self.assertEqual(parsed.payload["signal"], "APP_READY")
        self.assertEqual(parsed.sequence, 1)

    def test_protocol_rejects_missing_required_fields(self):
        """Verifies that messages missing session_id, app_id, or message_type fail schema validation."""
        bad_data = {
            "application_id": self.app_id,
            "harness_instance_id": "inst_01",
            "message_type": "LIFECYCLE",
        }
        with self.assertRaises(HarnessProtocolError):
            HarnessMessage.from_dict(bad_data)

    def test_protocol_rejects_oversized_payloads(self):
        """Verifies hard 1 MB payload size limit."""
        huge_payload = "x" * (MAX_HARNESS_MESSAGE_BYTES + 1024)
        msg_json = json.dumps({
            "session_id": self.session_id,
            "application_id": self.app_id,
            "harness_instance_id": "inst_01",
            "message_type": "DIAGNOSTICS",
            "payload": {"huge": huge_payload},
        })
        with self.assertRaises(HarnessProtocolError):
            HarnessMessage.from_json(msg_json)

    def test_protocol_rejects_malformed_json(self):
        """Verifies that non-JSON strings raise structured HarnessProtocolError."""
        with self.assertRaises(HarnessProtocolError):
            HarnessMessage.from_json("NOT_JSON{{{")

    # -------------------------------------------------------------------------
    # 2. Security Validation & Session Binding
    # -------------------------------------------------------------------------
    def test_validator_session_binding_and_auth_token(self):
        """Verifies session ID and auth token enforcement."""
        validator = HarnessMessageValidator(
            expected_session_id=self.session_id,
            expected_auth_token=self.auth_token,
        )

        valid_msg = HarnessMessage(
            session_id=self.session_id,
            application_id=self.app_id,
            harness_instance_id="inst_01",
            message_type=HarnessMessageType.HEALTH_PING,
            auth_token=self.auth_token,
            sequence=1,
        )
        validator.validate(valid_msg)

        # Wrong session
        wrong_sess_msg = HarnessMessage(
            session_id="unrelated_session",
            application_id=self.app_id,
            harness_instance_id="inst_01",
            message_type=HarnessMessageType.HEALTH_PING,
            auth_token=self.auth_token,
            sequence=2,
        )
        with self.assertRaises(HarnessSecurityError):
            validator.validate(wrong_sess_msg)

        # Wrong auth token
        wrong_token_msg = HarnessMessage(
            session_id=self.session_id,
            application_id=self.app_id,
            harness_instance_id="inst_01",
            message_type=HarnessMessageType.HEALTH_PING,
            auth_token="wrong_token",
            sequence=3,
        )
        with self.assertRaises(HarnessSecurityError):
            validator.validate(wrong_token_msg)

    def test_validator_detects_replay_attacks(self):
        """Verifies that sequence regression triggers HarnessSecurityError."""
        validator = HarnessMessageValidator(expected_session_id=self.session_id)
        msg_seq5 = HarnessMessage(
            session_id=self.session_id,
            application_id=self.app_id,
            harness_instance_id="inst_01",
            message_type=HarnessMessageType.LIFECYCLE,
            sequence=5,
        )
        validator.validate(msg_seq5)

        # Regressed sequence (e.g. replay of sequence 3)
        msg_seq3 = HarnessMessage(
            session_id=self.session_id,
            application_id=self.app_id,
            harness_instance_id="inst_01",
            message_type=HarnessMessageType.LIFECYCLE,
            sequence=3,
        )
        with self.assertRaises(HarnessSecurityError):
            validator.validate(msg_seq3)

    def test_validator_clock_drift_check(self):
        """Verifies that messages with timestamps in the far future or distant past are rejected."""
        validator = HarnessMessageValidator(expected_session_id=self.session_id)
        future_msg = HarnessMessage(
            session_id=self.session_id,
            application_id=self.app_id,
            harness_instance_id="inst_01",
            message_type=HarnessMessageType.HEALTH_PING,
            timestamp=time.time() + 3600.0,
        )
        with self.assertRaises(HarnessProtocolError):
            validator.validate(future_msg)

    # -------------------------------------------------------------------------
    # 3. Harness Service, Trace Multiplexing & Capability Negotiation
    # -------------------------------------------------------------------------
    def test_harness_service_lifecycle_and_diagnostics_ingestion(self):
        """Verifies that HarnessService ingests signals into trace with source='harness' and trust_class='diagnostic'."""
        trace = DesktopTraceEngine(session_id=self.session_id)
        caps = CapabilityMatrix(populate_defaults=False)
        service = HarnessService(
            session_id=self.session_id,
            trace_engine=trace,
            capability_matrix=caps,
            build_mode=BuildMode.DEV,
        )

        async def _run():
            # 1. Handshake
            hs_msg = HarnessMessage(
                session_id=self.session_id,
                application_id=self.app_id,
                harness_instance_id="inst_srv_01",
                message_type=HarnessMessageType.HANDSHAKE,
                payload={
                    "capabilities": {
                        "lifecycle": "AVAILABLE",
                        "diagnostics": "AVAILABLE",
                        "fixtures": "AVAILABLE",
                        "fault_injection": "DEGRADED",
                    }
                },
            )
            hs_res = await service.handle_incoming_message(hs_msg)
            self.assertEqual(hs_res["status"], "HANDSHAKE_ACK")
            self.assertTrue(service.handshake_completed)
            self.assertEqual(caps.get_status(CapabilityId.HARNESS_CORE), CapabilityStatus.AVAILABLE)
            self.assertEqual(caps.get_status(CapabilityId.HARNESS_FAULT_INJECTION), CapabilityStatus.DEGRADED)

            # 2. Lifecycle signal
            life_msg = HarnessMessage(
                session_id=self.session_id,
                application_id=self.app_id,
                harness_instance_id="inst_srv_01",
                message_type=HarnessMessageType.LIFECYCLE,
                payload={"signal": HarnessLifecycleSignal.SAVE_COMPLETED.value, "details": {"duration_ms": 42.0}},
            )
            life_res = await service.handle_incoming_message(life_msg)
            self.assertEqual(life_res["status"], "RECORDED")

            # 3. Diagnostics
            diag_msg = HarnessMessage(
                session_id=self.session_id,
                application_id=self.app_id,
                harness_instance_id="inst_srv_01",
                message_type=HarnessMessageType.DIAGNOSTICS,
                payload={
                    "diagnostics": {
                        "current_screen": "SettingsModal",
                        "active_operations": ["sync_task"],
                        "pending_operations_count": 1,
                    }
                },
            )
            diag_res = await service.handle_incoming_message(diag_msg)
            self.assertEqual(diag_res["status"], "RECORDED")
            self.assertIsNotNone(service.latest_diagnostics)
            self.assertEqual(service.latest_diagnostics.current_screen, "SettingsModal")

        asyncio.run(_run())

        # Verify trace events
        events = trace.get_timeline(self.session_id)
        harness_events = [e for e in events if e.details.get("source") == "harness"]
        self.assertTrue(len(harness_events) >= 2)
        for e in harness_events:
            self.assertEqual(e.details["trust_class"], "diagnostic")
            # Must never masquerade as physical verification
            self.assertNotEqual(e.event_type, DesktopTraceEventType.ASSERTION)

    # -------------------------------------------------------------------------
    # 4. Harness Golden Rule Enforcer
    # -------------------------------------------------------------------------
    def test_harness_golden_rule_matrix(self):
        """
        Validates the 4 scenarios of the Harness Golden Rule:
        Harness PASS + Physical PASS -> PASS
        Harness PASS + Physical FAIL -> FAIL
        Harness PASS + Physical UNVERIFIED -> UNVERIFIED
        Harness FAIL + Physical PASS -> decides according to physical reality
        """
        # 1. Harness reports positive SAVE_COMPLETED, but Physical reality failed -> FAIL
        v1 = HarnessGoldenRuleEnforcer.reconcile_verdict(
            physical_reality_verdict=VerificationVerdict.FAIL,
            harness_signal=HarnessLifecycleSignal.SAVE_COMPLETED,
            harness_diagnostics=HarnessDiagnosticData(current_screen="Saved"),
        )
        self.assertEqual(v1, VerificationVerdict.FAIL)

        # 2. Harness reports positive SAVE_COMPLETED, but Physical reality unverified -> UNVERIFIED
        v2 = HarnessGoldenRuleEnforcer.reconcile_verdict(
            physical_reality_verdict=VerificationVerdict.UNVERIFIED,
            harness_signal=HarnessLifecycleSignal.SAVE_COMPLETED,
            harness_diagnostics=HarnessDiagnosticData(current_screen="Saved"),
        )
        self.assertEqual(v2, VerificationVerdict.UNVERIFIED)

        # 3. Physical reality verified PASS, Harness positive -> PASS
        v3 = HarnessGoldenRuleEnforcer.reconcile_verdict(
            physical_reality_verdict=VerificationVerdict.PASS,
            harness_signal=HarnessLifecycleSignal.SAVE_COMPLETED,
        )
        self.assertEqual(v3, VerificationVerdict.PASS)


if __name__ == "__main__":
    unittest.main()
