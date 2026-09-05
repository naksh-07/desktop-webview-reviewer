"""
Unit tests for Specialist Contracts, Delegation Envelopes, and Domain Models (Phase 15).
Verifies formal boundary validation, timeout budgets, tool permissions, and result serialization.
"""

import json
import time
import unittest

from runtime.specialist_contracts import SpecialistRole, SpecialistRegistry
from runtime.specialist_models import (
    SpecialistLifecycleState,
    SpecialistResultStatus,
    DelegationScope,
    SpecialistDelegation,
    ToolAuditRecord,
    SpecialistResult,
)


class TestSpecialistContractsAndModels(unittest.TestCase):
    """Tests specialist contract validation and delegation models."""

    def test_specialist_registry_canonical_roles(self):
        """Verifies that all 5 canonical roles are present with strict contracts."""
        roles = [
            SpecialistRole.EXPLORER,
            SpecialistRole.TESTER,
            SpecialistRole.REALITY_INSPECTOR,
            SpecialistRole.DEBUGGER,
            SpecialistRole.EVIDENCE_SPECIALIST,
        ]
        for role in roles:
            contract = SpecialistRegistry.get_contract(role)
            self.assertEqual(contract.role, role)
            self.assertTrue(len(contract.permitted_tools) > 0)
            self.assertTrue(len(contract.forbidden_operations) > 0)

        # Explorer, Reality Inspector, and Evidence Specialist are read-only
        self.assertTrue(SpecialistRegistry.get_explorer_contract().is_read_only)
        self.assertTrue(SpecialistRegistry.get_reality_inspector_contract().is_read_only)
        self.assertTrue(SpecialistRegistry.get_evidence_specialist_contract().is_read_only)

        # Tester is state-mutating
        self.assertFalse(SpecialistRegistry.get_tester_contract().is_read_only)

    def test_delegation_scope_validation_success(self):
        """Verifies a valid delegation passes validation."""
        scope = DelegationScope(
            session_id="sess_abc123",
            target_epoch=5,
            expected_pid=1234,
        )
        delegation = SpecialistDelegation(
            role=SpecialistRole.EXPLORER,
            task="Enumerate active windows",
            scope=scope,
            permitted_tools={"desktop_inspect", "desktop_screenshot"},
            timeout_sec=10.0,
        )

        rejections = delegation.validate(
            current_session_id="sess_abc123",
            current_epoch=5,
            current_pid=1234,
        )
        self.assertEqual(len(rejections), 0)
        self.assertFalse(delegation.is_expired())
        self.assertGreater(delegation.get_remaining_timeout(), 0.0)

    def test_delegation_rejection_on_session_mismatch(self):
        """Verifies delegation targeting another session is rejected."""
        scope = DelegationScope(session_id="sess_one")
        delegation = SpecialistDelegation(
            role=SpecialistRole.EXPLORER,
            task="Inspect session",
            scope=scope,
            permitted_tools={"desktop_inspect"},
        )
        rejections = delegation.validate(current_session_id="sess_two")
        self.assertTrue(any("Session mismatch" in r for r in rejections))

    def test_delegation_rejection_on_stale_epoch(self):
        """Verifies delegation targeting an older observation epoch is rejected."""
        scope = DelegationScope(session_id="sess_1", target_epoch=2)
        delegation = SpecialistDelegation(
            role=SpecialistRole.EXPLORER,
            task="Inspect stale epoch",
            scope=scope,
            permitted_tools={"desktop_inspect"},
        )
        rejections = delegation.validate(current_session_id="sess_1", current_epoch=3)
        self.assertTrue(any("Stale observation epoch" in r for r in rejections))

    def test_delegation_rejection_on_pid_mismatch(self):
        """Verifies delegation targeting a recycled PID is rejected."""
        scope = DelegationScope(session_id="sess_1", expected_pid=1111)
        delegation = SpecialistDelegation(
            role=SpecialistRole.TESTER,
            task="Test click",
            scope=scope,
            permitted_tools={"desktop_click"},
            allow_state_mutation=True,
        )
        rejections = delegation.validate(current_session_id="sess_1", current_pid=9999)
        self.assertTrue(any("Target process PID mismatch" in r for r in rejections))

    def test_delegation_rejection_on_forbidden_tool(self):
        """Verifies delegation requesting tools forbidden by role contract is rejected."""
        scope = DelegationScope(session_id="sess_1")
        delegation = SpecialistDelegation(
            role=SpecialistRole.EXPLORER,
            task="Try clicking as explorer",
            scope=scope,
            permitted_tools={"desktop_click"},  # Explorer cannot click!
        )
        rejections = delegation.validate(current_session_id="sess_1")
        self.assertTrue(any("Forbidden tool for role EXPLORER" in r for r in rejections))

    def test_delegation_rejection_on_readonly_mutation(self):
        """Verifies read-only specialist cannot be granted allow_state_mutation=True."""
        scope = DelegationScope(session_id="sess_1")
        delegation = SpecialistDelegation(
            role=SpecialistRole.REALITY_INSPECTOR,
            task="Inspect reality",
            scope=scope,
            permitted_tools={"desktop_screenshot"},
            allow_state_mutation=True,  # Illegal for read-only role!
        )
        rejections = delegation.validate(current_session_id="sess_1")
        self.assertTrue(any("role REALITY_INSPECTOR is read-only" in r for r in rejections))

    def test_delegation_expiration_check(self):
        """Verifies is_expired() correctly catches expired deadlines."""
        scope = DelegationScope(session_id="sess_1")
        delegation = SpecialistDelegation(
            role=SpecialistRole.EXPLORER,
            task="Old task",
            scope=scope,
            permitted_tools={"desktop_inspect"},
            timeout_sec=0.1,
            created_at=time.time() - 5.0,  # Created 5 seconds ago
        )
        self.assertTrue(delegation.is_expired())
        self.assertEqual(delegation.get_remaining_timeout(), 0.0)

        rejections = delegation.validate(current_session_id="sess_1")
        self.assertTrue(any("Delegation expired" in r for r in rejections))

    def test_tool_audit_record_and_result_envelope(self):
        """Verifies audit records and specialist result serialization."""
        audit = ToolAuditRecord(
            specialist_id="spec_test_1",
            role=SpecialistRole.TESTER,
            delegation_id="delg_1",
            tool="desktop_click",
            timestamp=time.time(),
            duration_ms=45.2,
            arguments_digest="abcd1234",
            authorization_result="AUTHORIZED",
            result_status="SUCCESS",
        )
        audit_dict = audit.to_dict()
        self.assertEqual(audit_dict["tool"], "desktop_click")
        self.assertEqual(audit_dict["authorization_result"], "AUTHORIZED")

        res = SpecialistResult(
            specialist_id="spec_test_1",
            role=SpecialistRole.TESTER,
            delegation_id="delg_1",
            session_id="sess_1",
            status=SpecialistResultStatus.SUCCESS,
            answer="Workflow executed successfully",
            observations={"steps": 2},
            confidence=0.95,
        )
        json_str = res.to_json()
        parsed = SpecialistResult.from_dict(json.loads(json_str))
        self.assertEqual(parsed.status, SpecialistResultStatus.SUCCESS)
        self.assertEqual(parsed.role, SpecialistRole.TESTER)
        self.assertEqual(parsed.confidence, 0.95)


if __name__ == "__main__":
    unittest.main()
