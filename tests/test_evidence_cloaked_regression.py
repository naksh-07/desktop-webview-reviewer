"""
Regression test for desktop_collect_evidence cloaked-state handling.

Validates that desktop_collect_evidence_impl does NOT call the nonexistent
supervisor.is_window_cloaked() method, and instead reads the authoritative
cloaked state from session.target_window.is_cloaked (WindowIdentity).

Bug: runtime/mcp/tools/evidence.py line 141 called
     supervisor.is_window_cloaked(target_hwnd)
     but NativeOSSupervisor has no such method -> AttributeError crash.

Fix: Use session.target_window.is_cloaked (already populated by inspect_window).
"""

from __future__ import annotations
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane
from runtime.session_manager import SessionState, SessionManager, SessionConfig
from runtime.daemon import DesktopDaemon
from runtime.evidence_store import EvidenceStore
from runtime.target_manager import WindowIdentity, HealthState
from runtime.mcp.runtime_bridge import RuntimeBridge
from runtime.action_models import (
    ActionOutcome,
    ActionReceipt,
    ActionRequest,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
)
from runtime.evidence_models import VerificationVerdict, ProofLevel, EvidenceManifest
from runtime.mcp.tools.evidence import desktop_collect_evidence_impl


def _make_window_identity(is_cloaked=False):
    return WindowIdentity(
        hwnd=0x12345,
        pid=1234,
        title="Test Window",
        class_name="TestClass",
        bounds=Rect(100, 100, 800, 600),
        is_visible=True,
        is_cloaked=is_cloaked,
        is_minimized=False,
        is_hung=False,
    )


def _make_receipt(session_id):
    return ActionReceipt(
        action_id="act_evidence_test",
        session_id=session_id,
        target_id="tgt_evidence",
        epoch=1,
        plane=TargetPlane.WEBVIEW_DOM,
        reference="w1e1",
        action_type=ActionType.CLICK,
        dispatch_method=DispatchMethod.CDP_INPUT,
        dispatch_timestamp=time.time(),
        dispatch_status=DispatchStatus.DISPATCHED,
    )


def _make_outcome(session_id, receipt):
    return ActionOutcome(
        action_id=receipt.action_id,
        session_id=session_id,
        receipt=receipt,
        outcome_status=ActionOutcomeStatus.DISPATCHED,
        state_change=StateChangeClassification.STATE_CHANGED,
        pre_epoch=1,
        post_epoch=2,
        duration_ms=50.0,
    )


class TestEvidenceCloakedStateRegression(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.session_id = "test_evidence_cloaked"
        self.daemon = DesktopDaemon()
        self.session_manager = self.daemon.session_manager
        self.session = await self.session_manager.create_session(
            SessionConfig(session_id=self.session_id)
        )
        self.session.reference_registry = ReferenceRegistry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.session.evidence_store = EvidenceStore(base_dir=Path(self.temp_dir.name))
        self.bridge = RuntimeBridge(daemon=self.daemon)

    async def asyncTearDown(self):
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    async def test_collect_evidence_does_not_call_is_window_cloaked(self):
        """Regression: must NOT call supervisor.is_window_cloaked()."""
        self.session.target_window = _make_window_identity(is_cloaked=False)
        receipt = _make_receipt(self.session_id)
        outcome = _make_outcome(self.session_id, receipt)
        self.session.last_outcome = outcome

        mock_supervisor = MagicMock(spec_set=["is_window_visible", "find_windows_by_pid", "inspect_window"])
        mock_supervisor.is_window_visible = MagicMock(return_value=True)
        self.session.native_supervisor = mock_supervisor

        mock_manifest = MagicMock(spec=EvidenceManifest)
        mock_manifest.evidence_id = "ev_test_123"
        mock_manifest.verdict_rationale = "Test pass"
        mock_verifier = MagicMock()
        mock_verifier.evaluate_transaction = MagicMock(
            return_value=(VerificationVerdict.PASS, mock_manifest, [])
        )
        self.session.verification_engine = mock_verifier

        mock_obs = MagicMock()
        mock_obs.last_snapshot = None
        mock_obs._snapshots = {}
        self.session.observation_engine = mock_obs

        mock_proc = MagicMock()
        mock_proc.pid = 1234
        self.session.target_process = mock_proc
        self.session.target_endpoint = None
        self.session.evidence_store = MagicMock()

        result = await desktop_collect_evidence_impl(
            bridge=self.bridge,
            session_id=self.session_id,
            test_name="regression_cloaked_test",
            expected_outcome_summary="Verify no crash on cloaked state access",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["verdict"], "PASS")
        self.assertFalse(hasattr(mock_supervisor, "is_window_cloaked"))
        self.assertTrue(result["proof_metrics"]["native_window_visible"])

    async def test_collect_evidence_cloaked_window_proof_metrics(self):
        """Cloaked window -> native_window_visible must be False."""
        self.session.target_window = _make_window_identity(is_cloaked=True)
        receipt = _make_receipt(self.session_id)
        outcome = _make_outcome(self.session_id, receipt)
        self.session.last_outcome = outcome

        mock_supervisor = MagicMock(spec_set=["is_window_visible", "find_windows_by_pid", "inspect_window"])
        mock_supervisor.is_window_visible = MagicMock(return_value=True)
        self.session.native_supervisor = mock_supervisor

        mock_manifest = MagicMock(spec=EvidenceManifest)
        mock_manifest.evidence_id = "ev_test_cloaked"
        mock_manifest.verdict_rationale = "Cloaked window"
        mock_verifier = MagicMock()
        mock_verifier.evaluate_transaction = MagicMock(
            return_value=(VerificationVerdict.UNVERIFIED, mock_manifest, [])
        )
        self.session.verification_engine = mock_verifier

        mock_obs = MagicMock()
        mock_obs.last_snapshot = None
        mock_obs._snapshots = {}
        self.session.observation_engine = mock_obs

        mock_proc = MagicMock()
        mock_proc.pid = 1234
        self.session.target_process = mock_proc
        self.session.target_endpoint = None
        self.session.evidence_store = MagicMock()

        result = await desktop_collect_evidence_impl(
            bridge=self.bridge,
            session_id=self.session_id,
            test_name="regression_cloaked_visible_test",
        )

        self.assertIsNotNone(result)
        self.assertFalse(result["proof_metrics"]["native_window_visible"])

    async def test_collect_evidence_no_target_window(self):
        """No target_window -> is_cloaked defaults to False, no crash."""
        self.session.target_window = None
        receipt = _make_receipt(self.session_id)
        outcome = _make_outcome(self.session_id, receipt)
        self.session.last_outcome = outcome

        mock_supervisor = MagicMock(spec_set=["is_window_visible", "find_windows_by_pid", "inspect_window"])
        mock_supervisor.is_window_visible = MagicMock(return_value=False)
        mock_supervisor.find_windows_by_pid = MagicMock(return_value=[])
        self.session.native_supervisor = mock_supervisor

        mock_manifest = MagicMock(spec=EvidenceManifest)
        mock_manifest.evidence_id = "ev_test_no_window"
        mock_manifest.verdict_rationale = "No window"
        mock_verifier = MagicMock()
        mock_verifier.evaluate_transaction = MagicMock(
            return_value=(VerificationVerdict.UNVERIFIED, mock_manifest, [])
        )
        self.session.verification_engine = mock_verifier

        mock_obs = MagicMock()
        mock_obs.last_snapshot = None
        mock_obs._snapshots = {}
        self.session.observation_engine = mock_obs

        mock_proc = MagicMock()
        mock_proc.pid = 9999
        self.session.target_process = mock_proc
        self.session.target_endpoint = None
        self.session.evidence_store = MagicMock()

        result = await desktop_collect_evidence_impl(
            bridge=self.bridge,
            session_id=self.session_id,
            test_name="regression_no_window_test",
        )

        self.assertIsNotNone(result)
        self.assertFalse(result["proof_metrics"]["native_window_visible"])


if __name__ == "__main__":
    unittest.main()
