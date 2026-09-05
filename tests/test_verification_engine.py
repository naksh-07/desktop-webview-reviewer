"""
Tests for VerificationEngine & Tripartite Proof Evaluator (Architecture H).
Validates deterministic claim evaluations, Physical Reality Primacy, contradiction detection,
proof levels, interactive mode decoupling, and action engine integration.
"""

import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from runtime.state import TargetPlane
from runtime.references import ElementRef, ReferenceRegistry, Rect
from runtime.action_models import (
    ActionRequest,
    ActionTarget,
    ActionReceipt,
    ActionOutcome,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
)
from runtime.observation_models import (
    DualPerspectiveSnapshot,
    NativeObservation,
    WebObservation,
    WebElementObservation,
    NativeElementObservation,
    ReconciliationObservation,
    VisibilityObservation,
    InteractionObservation,
)
from runtime.observation_diff import ObservationDiffResult, DiffItem
from runtime.evidence_models import (
    VerificationVerdict,
    ProofLevel,
    EvidenceType,
    ClaimType,
    UnverifiedReason,
    ScreenshotEvidence,
)
from runtime.evidence_store import EvidenceStore
from runtime.verification_engine import VerificationEngine
from runtime.action_engine import ActionExecutionEngine


class TestVerificationEngine(unittest.TestCase):
    """Unit tests for deterministic tripartite proof evaluation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(base_dir=Path(self.temp_dir.name))
        self.verifier = VerificationEngine(evidence_store=self.store, require_visible_gui=True)
        self.session_id = "test_session_v"

        # Baseline Action Request
        self.request = ActionRequest(
            session_id=self.session_id,
            reference="w1e1",
            action_type=ActionType.CLICK,
            observation_epoch=1,
            params={"expect_change": True},
        )

        # Baseline Action Receipt
        self.receipt_dispatched = ActionReceipt(
            action_id=self.request.action_id,
            session_id=self.session_id,
            target_id="target_elem_1",
            epoch=1,
            plane=TargetPlane.WEBVIEW_DOM,
            reference="w1e1",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.CDP_INPUT,
            dispatch_timestamp=time.time(),
            coordinates=(150, 200),
            dispatch_status=DispatchStatus.DISPATCHED,
            duration_ms=12.5,
        )

        # Baseline Native Observation
        self.native_obs_valid = NativeObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            hwnd=0x2001,
            title="Main App Window",
            class_name="QtWebEngineProcess",
            pid=1234,
            bounds=Rect(100, 100, 1024, 768),
            client_bounds=Rect(108, 131, 1008, 729),
            is_visible=True,
            is_minimized=False,
            is_cloaked=False,
            is_responsive=True,
        )

        # Baseline Web Observation
        elem = WebElementObservation(
            session_id=self.session_id,
            observation_epoch=2,
            timestamp=time.time(),
            source_plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_elem_1",
            reference="w1e1",
            role="button",
            normalized_role="button",
            accessible_name="Submit",
            tag_name="button",
            bounds=Rect(120, 180, 80, 40),
            visibility=VisibilityObservation(attached=True, visible=True, in_viewport=True, physically_occluded=False),
            interaction=InteractionObservation(is_enabled=True),
        )
        self.web_obs_valid = WebObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            target_id="target_elem_1",
            target_title="Main Page",
            target_url="https://app.local/main",
            root_frame_id="frame_1",
            elements=(elem,),
        )

        # Baseline Snapshots
        self.pre_snapshot = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=time.time() - 0.5,
            native_observation=self.native_obs_valid,
            web_observation=self.web_obs_valid,
            text_representation="",
        )

        self.post_snapshot = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            native_observation=self.native_obs_valid,
            web_observation=self.web_obs_valid,
            text_representation="",
        )

        # Baseline Diff
        self.diff_mutated = ObservationDiffResult(
            from_epoch=1,
            to_epoch=2,
            modified=(DiffItem(kind="MODIFIED", reference="w1e1", role="button", name="Submit", changes=("text changed",)),),
        )

        # Baseline Action Outcome
        self.outcome_changed = ActionOutcome(
            action_id=self.request.action_id,
            session_id=self.session_id,
            receipt=self.receipt_dispatched,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=1,
            post_epoch=2,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
            duration_ms=45.0,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Full Transaction Verification: PASS Scenario
    # -------------------------------------------------------------------------

    def test_verified_transaction_produces_pass(self):
        """Proves that a completely satisfied transaction loop evaluates to PASS."""
        verdict, manifest, ev_items = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
            target_process_info={"pid": 1234, "is_running": True},
            execution_mode="automated",
        )

        self.assertEqual(verdict, VerificationVerdict.PASS)
        self.assertEqual(manifest.verdict, VerificationVerdict.PASS)
        self.assertIsNone(manifest.unverified_reason)
        self.assertTrue(manifest.manifest_hash)
        self.assertGreater(len(ev_items), 0)

        # Check that evidence store stored manifest and it passes integrity check
        is_valid, violations = self.store.verify_manifest_integrity(manifest)
        self.assertTrue(is_valid, f"Integrity failed: {violations}")

    # -------------------------------------------------------------------------
    # 2. Dispatch Failure: FAIL Scenario
    # -------------------------------------------------------------------------

    def test_rejected_dispatch_produces_fail(self):
        """Proves that a rejected dispatch produces explicit FAIL verdict."""
        receipt_rejected = ActionReceipt(
            action_id=self.request.action_id,
            session_id=self.session_id,
            target_id="target_elem_1",
            epoch=1,
            plane=TargetPlane.WEBVIEW_DOM,
            reference="w1e1",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.CDP_INPUT,
            dispatch_timestamp=time.time(),
            dispatch_status=DispatchStatus.REJECTED,
            error="Target element occluded",
        )
        outcome_rejected = ActionOutcome(
            action_id=self.request.action_id,
            session_id=self.session_id,
            receipt=receipt_rejected,
            outcome_status=ActionOutcomeStatus.REJECTED,
            state_change=StateChangeClassification.NO_EFFECT,
            pre_epoch=1,
            post_epoch=1,
        )

        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=receipt_rejected,
            action_outcome=outcome_rejected,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=None,
            observation_diff=None,
        )

        self.assertEqual(verdict, VerificationVerdict.FAIL)
        self.assertEqual(manifest.verdict, VerificationVerdict.FAIL)
        self.assertIn("Verification failed", manifest.verdict_rationale)

    # -------------------------------------------------------------------------
    # 3. Physical Reality Primacy: UNVERIFIED Scenarios
    # -------------------------------------------------------------------------

    def test_minimized_window_produces_unverified(self):
        """Proves that dispatching to a minimized window yields UNVERIFIED."""
        native_minimized = NativeObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            hwnd=0x2001,
            title="Main App Window",
            class_name="QtWebEngineProcess",
            pid=1234,
            bounds=Rect(0, 0, 100, 100),
            client_bounds=Rect(0, 0, 100, 100),
            is_visible=True,
            is_minimized=True,  # Minimized!
            is_cloaked=False,
            is_responsive=True,
        )
        post_snap_min = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            native_observation=native_minimized,
            web_observation=self.web_obs_valid,
            text_representation="",
        )

        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=post_snap_min,
            observation_diff=self.diff_mutated,
        )

        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertIn(manifest.unverified_reason, (UnverifiedReason.WINDOW_CLOAKED_OR_MINIMIZED, UnverifiedReason.CONTRADICTORY_EVIDENCE))

    def test_cloaked_window_produces_unverified(self):
        """Proves that dispatching to a DWM cloaked window yields UNVERIFIED."""
        native_cloaked = NativeObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            hwnd=0x2001,
            title="Main App Window",
            class_name="QtWebEngineProcess",
            pid=1234,
            bounds=Rect(100, 100, 800, 600),
            client_bounds=Rect(108, 131, 784, 561),
            is_visible=True,
            is_minimized=False,
            is_cloaked=True,  # Cloaked by DWM!
            is_responsive=True,
        )
        post_snap_cloaked = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            native_observation=native_cloaked,
            web_observation=self.web_obs_valid,
            text_representation="",
        )

        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=post_snap_cloaked,
            observation_diff=self.diff_mutated,
        )

        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertIn(manifest.unverified_reason, (UnverifiedReason.WINDOW_CLOAKED_OR_MINIMIZED, UnverifiedReason.CONTRADICTORY_EVIDENCE))

    def test_pid_mismatch_produces_unverified(self):
        """Proves that a PID mismatch yields UNVERIFIED."""
        proc_info_foreign = {"pid": 9999, "process_tree": [9999], "is_running": True}

        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
            target_process_info=proc_info_foreign, # Mismatch with native_obs PID 1234
        )

        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.PID_MISMATCH)

    # -------------------------------------------------------------------------
    # 4. Contradiction Detection
    # -------------------------------------------------------------------------

    def test_contradiction_native_modal_blocks_window(self):
        """Proves that an unhandled native modal dialog is detected as a contradiction."""
        modal = {"hwnd": 0x9999, "title": "Error Dialog", "class_name": "#32770", "is_dialog": True}
        native_modal_obs = NativeObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            hwnd=0x2001,
            title="Main App Window",
            class_name="QtWebEngineProcess",
            pid=1234,
            bounds=Rect(100, 100, 800, 600),
            client_bounds=Rect(108, 131, 784, 561),
            is_visible=True,
            is_minimized=False,
            is_cloaked=False,
            is_responsive=True,
            modal_dialogs=(modal,),
        )
        post_snap_modal = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            native_observation=native_modal_obs,
            web_observation=self.web_obs_valid,
            text_representation="",
        )

        verdict, manifest, ev_items = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=post_snap_modal,
            observation_diff=self.diff_mutated,
        )

        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.CONTRADICTORY_EVIDENCE)
        has_contra_ev = any(e.evidence_type == EvidenceType.CONTRADICTION for e in ev_items)
        self.assertTrue(has_contra_ev)

    # -------------------------------------------------------------------------
    # 5. Proof Level & Interactive Mode
    # -------------------------------------------------------------------------

    def test_proof_level_4_requires_dual_screenshots(self):
        """Proves that LEVEL_4_FORENSIC_COMPLETE requires both native and webview screenshots."""
        # Without screenshots:
        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
            required_proof_level=ProofLevel.LEVEL_4_FORENSIC_COMPLETE,
        )
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.SCREENSHOT_UNAVAILABLE)

        # With dual screenshots:
        shot_nat = ScreenshotEvidence(
            screenshot_id="s_nat",
            screenshot_type="NATIVE_WINDOW",
            coordinate_space="WINDOW_EXTENDED_FRAME",
            dimensions=(1024, 768),
            sha256="a" * 64,
            relative_path="screenshots/native.png",
        )
        shot_web = ScreenshotEvidence(
            screenshot_id="s_web",
            screenshot_type="WEBVIEW_VIEWPORT",
            coordinate_space="VIEWPORT_LOGICAL",
            dimensions=(1024, 768),
            sha256="b" * 64,
            relative_path="screenshots/webview.png",
        )
        verdict4, manifest4, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
            native_screenshot=shot_nat,
            webview_screenshot=shot_web,
            required_proof_level=ProofLevel.LEVEL_4_FORENSIC_COMPLETE,
        )
        self.assertEqual(verdict4, VerificationVerdict.PASS)

    def test_interactive_mode_requires_user_confirmation(self):
        """Proves that interactive mode holds verdict at UNVERIFIED until user confirmation is supplied."""
        # Interactive mode without confirmation -> UNVERIFIED
        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
            execution_mode="interactive",
            user_confirmed=False,
        )
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.USER_CONFIRMATION_PENDING)

        # Interactive mode with confirmation -> PASS
        verdict_ok, manifest_ok, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=self.outcome_changed,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.post_snapshot,
            observation_diff=self.diff_mutated,
            execution_mode="interactive",
            user_confirmed=True,
        )
        self.assertEqual(verdict_ok, VerificationVerdict.PASS)

    # -------------------------------------------------------------------------
    # 6. ActionExecutionEngine Integration
    # -------------------------------------------------------------------------

    def test_action_engine_integration_verifies_and_attaches_manifest(self):
        """Proves that ActionExecutionEngine automatically verifies outcomes and records manifests."""
        engine = ActionExecutionEngine(
            session_id="session_engine_v",
            evidence_store=self.store,
            verification_engine=self.verifier,
        )

        async def run_test():
            ref = ElementRef(
                epoch_id=engine.reference_registry.current_epoch,
                ref_id="n1e1",
                plane=TargetPlane.NATIVE_SHELL,
                role="Button",
                name="Submit",
                bounds=Rect(100, 100, 200, 50),
                target_id="target_native_1",
            )
            engine.reference_registry.add_explicit_ref(ref)

            req = ActionRequest(
                session_id="session_engine_v",
                reference="n1e1",
                action_type=ActionType.CLICK,
                observation_epoch=engine.reference_registry.current_epoch,
            )
            outcome = await engine.execute(req, verify=True, execution_mode="automated")
            self.assertIsNotNone(outcome.manifest)
            self.assertIsNotNone(outcome.verdict)
            self.assertIn("manifest", outcome.details)
            self.assertEqual(len(engine.manifest_history), 1)

        asyncio.run(run_test())

    # -------------------------------------------------------------------------
    # 7. Post-Fix Release Certification: has_mutations tests
    # -------------------------------------------------------------------------

    def test_has_mutations_evaluates_true_on_functional_mutation(self):
        """Proves that a diff with additions/modifications triggers has_mutations = True (PASS)."""
        diff_with_mutations = ObservationDiffResult(
            from_epoch=1,
            to_epoch=2,
            added=(DiffItem(kind="ADDED", reference="w1e2", role="link", name="New Link", changes=("element appeared",)),),
        )
        
        # When expect_change is True, the outcome state_change could be NO_EFFECT, 
        # but if diff has mutations, it should PASS anyway.
        outcome_no_effect_but_mutated = ActionOutcome(
            action_id=self.request.action_id,
            session_id=self.session_id,
            receipt=self.receipt_dispatched,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.NO_EFFECT,
            pre_epoch=1,
            post_epoch=1, # same epoch to isolate has_mutations
            post_snapshot=self.pre_snapshot, # same epoch to prevent has_epoch_advance
            observation_diff=diff_with_mutations,
            duration_ms=45.0,
        )
        
        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=outcome_no_effect_but_mutated,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.pre_snapshot, # same epoch to prevent has_epoch_advance
            observation_diff=diff_with_mutations,
        )
        
        self.assertEqual(verdict, VerificationVerdict.PASS)
        # Verify the claim reason contains the diff_summary
        state_claim = next((c for c in manifest.claims if c.claim_type == ClaimType.ExpectedStateOccurred), None)
        self.assertIsNotNone(state_claim)
        self.assertEqual(state_claim.status, VerificationVerdict.PASS)
        self.assertIn("1 added", state_claim.reason)

    def test_has_mutations_evaluates_false_on_no_mutation(self):
        """Proves that a diff with no additions, removals, or modifications triggers has_mutations = False (FAIL expected change)."""
        diff_no_mutations = ObservationDiffResult(
            from_epoch=1,
            to_epoch=2,
        )
        
        # When expect_change is True, and outcome state_change is NO_EFFECT, 
        # and diff has NO mutations, and epoch didn't advance, it should FAIL.
        outcome_no_effect = ActionOutcome(
            action_id=self.request.action_id,
            session_id=self.session_id,
            receipt=self.receipt_dispatched,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.NO_EFFECT,
            pre_epoch=1,
            post_epoch=1,
            post_snapshot=self.pre_snapshot,
            observation_diff=diff_no_mutations,
            duration_ms=45.0,
        )
        
        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt_dispatched,
            action_outcome=outcome_no_effect,
            pre_snapshot=self.pre_snapshot,
            post_snapshot=self.pre_snapshot, # same epoch to prevent has_epoch_advance
            observation_diff=diff_no_mutations,
        )
        
        self.assertEqual(verdict, VerificationVerdict.FAIL)
        
        state_claim = next((c for c in manifest.claims if c.claim_type == ClaimType.ExpectedStateOccurred), None)
        self.assertIsNotNone(state_claim)
        self.assertEqual(state_claim.status, VerificationVerdict.FAIL)


if __name__ == "__main__":
    unittest.main()
