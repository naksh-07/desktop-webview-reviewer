import unittest
import time
import os
from unittest.mock import MagicMock
from runtime.evidence_models import (
    CaptureMethod,
    ScreenshotEvidence,
    PhysicalDesktopEvidence,
    UnverifiedReason,
    VerificationVerdict,
    EvidenceItem,
)
from runtime.observation_models import NativeObservation
from runtime.references import Rect
from runtime.verification_engine import VerificationEngine

class TestPhysicalDesktopVerification(unittest.TestCase):
    def setUp(self):
        self.engine = VerificationEngine()
        self.session_id = "test_sess"
        self.action_id = "act_1"
        self.epoch = 1

    def _build_native_obs(self, hwnd=123, pid=456, is_visible=True, is_iconic=False, is_cloaked=False, bounds=None, is_foreground=True, occlusion_ratio=0.0):
        obs = NativeObservation(
            session_id=self.session_id,
            epoch=self.epoch,
            timestamp=time.time(),
            title="Test",
            class_name="TestClass",
            is_minimized=is_iconic,
            hwnd=hwnd,
            pid=pid,
            is_visible=is_visible,
            is_cloaked=is_cloaked,
            is_responsive=True,
            bounds=bounds or Rect(0, 0, 800, 600),
            client_bounds=bounds or Rect(0, 0, 800, 600),
            elements=tuple(),
            modal_dialogs=tuple()
        )
        object.__setattr__(obs, 'is_iconic', is_iconic)
        object.__setattr__(obs, 'is_foreground', is_foreground)
        object.__setattr__(obs, 'occlusion_ratio', occlusion_ratio)
        return obs

    def _build_physical_evidence(
        self,
        hwnd=123,
        bounds=None,
        capture_time=None,
        process_creation_time=100.0,
        session_id=None,
        action_id=None,
        epoch=None,
        pixel_sha256=None,
        artifact_path="",
        capture_method="REAL_DESKTOP_SURFACE",
        is_authoritative=True,
        post_capture_validated=True,
        occlusion_state="NOT_OCCLUDED",
        occlusion_ratio=0.0,
        foreground_hwnd=None,
        is_exact_foreground=True,
        pid=456,
        dimensions=(800, 600),
    ):
        b = bounds or (0, 0, 800, 600)
        return PhysicalDesktopEvidence(
            evidence_id="ev_1",
            session_id=session_id or self.session_id,
            action_id=action_id if action_id is not None else self.action_id,
            target_hwnd=hwnd,
            target_pid=pid,
            foreground_hwnd=foreground_hwnd if foreground_hwnd is not None else hwnd,
            is_exact_foreground=is_exact_foreground,
            dimensions=dimensions,
            capture_timestamp=capture_time or time.time(),
            pixel_sha256=pixel_sha256 or ("a" * 64),
            artifact_path=artifact_path,
            action_epoch=epoch if epoch is not None else self.epoch,
            process_creation_time=process_creation_time,
            occlusion_state=occlusion_state,
            occlusion_ratio=occlusion_ratio,
            physical_bounds=b,
            capture_method=capture_method,
            is_authoritative=is_authoritative,
            post_capture_validated=post_capture_validated,
        )

    def test_pass_valid_capture(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence()
        proc_info = {"pid": 456, "create_time": 100.0}
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, proc_info, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.PASS)

    def test_fail_no_hwnd(self):
        obs = self._build_native_obs(hwnd=0)
        ev = self._build_physical_evidence()
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.PHYSICAL_STATE_UNKNOWN)

    def test_fail_occluded(self):
        obs = self._build_native_obs(occlusion_ratio=0.5)
        ev = self._build_physical_evidence()
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.WINDOW_OCCLUDED)

    def test_fail_cloaked(self):
        obs = self._build_native_obs(is_cloaked=True)
        ev = self._build_physical_evidence()
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.WINDOW_CLOAKED_OR_MINIMIZED)

    def test_fail_minimized(self):
        obs = self._build_native_obs(is_iconic=True)
        ev = self._build_physical_evidence()
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.WINDOW_CLOAKED_OR_MINIMIZED)

    def test_fail_stale(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(capture_time=time.time() - 10.0) # 10s old
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.EVIDENCE_STALE)

    def test_fail_background_foreground_mismatch(self):
        obs = self._build_native_obs(is_foreground=False)
        ev = self._build_physical_evidence()
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.FOREGROUND_MISMATCH)

    def test_fail_bounds_mismatch(self):
        obs = self._build_native_obs(bounds=Rect(0, 0, 800, 600))
        ev = self._build_physical_evidence(bounds=(0, 0, 801, 600))
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.BOUNDS_MISMATCH)

    def test_fail_pid_mismatch(self):
        obs = self._build_native_obs(pid=456)
        ev = self._build_physical_evidence()
        proc_info = {"pid": 999}
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, proc_info, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.PID_MISMATCH)

    def test_fail_creation_time_mismatch(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(process_creation_time=200.0)
        proc_info = {"pid": 456, "create_time": 100.0}
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, proc_info, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.PROCESS_IDENTITY_MISMATCH)

    def test_fail_no_physical_capture_cdp_only(self):
        obs = self._build_native_obs()
        cdp_snat = ScreenshotEvidence(
            screenshot_id="cdp1",
            screenshot_type="cdp",
            coordinate_space="viewport",
            dimensions=(800, 600),
            pixel_format="rgba",
            capture_bounds=(0,0,800,600),
            dpi_context=1.0,
            sha256="hash",
            relative_path="path",
            is_thumbnail=False,
            timestamp=time.time(),
            capture_method="CDP",
            is_certifying=False
        )
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], cdp_snat, None
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.NON_AUTHORITATIVE_CAPTURE)
        
    def test_fail_session_mismatch(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(session_id="wrong_session")
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.SESSION_MISMATCH)

    def test_fail_epoch_mismatch(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(epoch=999)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.EPOCH_MISMATCH)

    def test_fail_action_id_mismatch(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(action_id="different_action")
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.ACTION_MISMATCH)

    def test_fail_hwnd_mismatch(self):
        obs = self._build_native_obs(hwnd=123)
        ev = self._build_physical_evidence(hwnd=456)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.HWND_MISMATCH)

    def test_fail_foreground_hwnd_mismatch(self):
        obs = self._build_native_obs(hwnd=123)
        ev = self._build_physical_evidence(hwnd=123, foreground_hwnd=999)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.FOREGROUND_MISMATCH)

    def test_fail_exact_foreground_false(self):
        obs = self._build_native_obs(hwnd=123)
        ev = self._build_physical_evidence(hwnd=123, is_exact_foreground=False)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.FOREGROUND_MISMATCH)

    def test_fail_process_tree_mismatch(self):
        obs = self._build_native_obs(pid=456)
        ev = self._build_physical_evidence(pid=456)
        proc_info = {"pid": 100, "process_tree": [100, 101, 102]}
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, proc_info, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.PID_MISMATCH)

    def test_fail_missing_creation_time(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(process_creation_time=0.0)
        proc_info = {"pid": 456, "create_time": 100.0}
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, proc_info, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.PROCESS_IDENTITY_MISMATCH)

    def test_fail_evidence_occlusion_ratio(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(occlusion_ratio=0.15)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.WINDOW_OCCLUDED)

    def test_fail_evidence_occlusion_state(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(occlusion_state="PARTIALLY_OCCLUDED")
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.WINDOW_OCCLUDED)

    def test_fail_non_renderable_bounds(self):
        obs = self._build_native_obs(bounds=Rect(0, 0, 0, 0))
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, None
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.WINDOW_NON_RENDERABLE)

    def test_fail_dimensions_mismatch(self):
        obs = self._build_native_obs(bounds=Rect(0, 0, 800, 600))
        ev = self._build_physical_evidence(bounds=(0, 0, 800, 600), dimensions=(1024, 768))
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.DIMENSIONS_MISMATCH)

    def test_fail_malformed_sha256(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(pixel_sha256="not_a_valid_hex_hash")
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.NON_AUTHORITATIVE_CAPTURE)

    def test_fail_artifact_file_missing(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(artifact_path="C:\\nonexistent\\missing_image.png")
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.ARTIFACT_MISSING)

    def test_fail_artifact_file_empty(self):
        import tempfile
        obs = self._build_native_obs()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
            temp_path = f.name
        try:
            ev = self._build_physical_evidence(artifact_path=temp_path)
            claim = self.engine._evaluate_claim_physical_visibility(
                self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
            )
            self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
            self.assertEqual(claim.unverified_reason, UnverifiedReason.ARTIFACT_MISSING)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_fail_artifact_hash_mismatch(self):
        import tempfile, hashlib
        obs = self._build_native_obs()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
            f.write(b"actual_different_bytes")
            temp_path = f.name
        try:
            expected_hash = hashlib.sha256(b"original_bytes").hexdigest()
            ev = self._build_physical_evidence(pixel_sha256=expected_hash, artifact_path=temp_path)
            claim = self.engine._evaluate_claim_physical_visibility(
                self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
            )
            self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
            self.assertEqual(claim.unverified_reason, UnverifiedReason.ARTIFACT_HASH_MISMATCH)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_pass_artifact_file_valid(self):
        import tempfile, hashlib
        obs = self._build_native_obs()
        data = b"\x89PNG\r\n\x1a\nfake_valid_png_data"
        actual_hash = hashlib.sha256(data).hexdigest()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
            f.write(data)
            temp_path = f.name
        try:
            proc_info = {"pid": 456, "create_time": 100.0}
            ev = self._build_physical_evidence(pixel_sha256=actual_hash, artifact_path=temp_path)
            claim = self.engine._evaluate_claim_physical_visibility(
                self.session_id, self.action_id, self.epoch, obs, proc_info, [], None, ev
            )
            self.assertEqual(claim.status, VerificationVerdict.PASS)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_fail_future_timestamp(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(capture_time=time.time() + 10.0)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.EVIDENCE_STALE)

    def test_fail_webview_diagnostic(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(capture_method="WEBVIEW_DIAGNOSTIC")
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.NON_AUTHORITATIVE_CAPTURE)

    def test_fail_non_authoritative_flag(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(is_authoritative=False)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.NON_AUTHORITATIVE_CAPTURE)

    def test_fail_post_capture_validation_failed(self):
        obs = self._build_native_obs()
        ev = self._build_physical_evidence(post_capture_validated=False)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.POST_CAPTURE_VALIDATION_FAILED)

    def test_policy_gate_no_require_visible_gui(self):
        engine = VerificationEngine(require_visible_gui=False)
        obs = self._build_native_obs()
        claim = engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, None
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.PHYSICAL_STATE_UNKNOWN)

    # --- End-to-End Transaction Evaluation Tests ---
    def _build_transaction_context(self):
        from runtime.action_models import (
            ActionRequest, ActionReceipt, ActionOutcome, ActionType,
            TargetPlane, DispatchMethod, DispatchStatus, ActionOutcomeStatus,
            StateChangeClassification,
        )
        from runtime.observation_models import DualPerspectiveSnapshot
        req = ActionRequest(session_id=self.session_id, reference="w1e1", action_type=ActionType.CLICK, observation_epoch=1)
        rec = ActionReceipt(
            action_id=req.action_id, session_id=self.session_id, target_id="target_main",
            epoch=1, plane=TargetPlane.NATIVE, reference="w1e1", action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.NATIVE_SENDINPUT, dispatch_timestamp=time.time(),
            dispatch_status=DispatchStatus.DISPATCHED, duration_ms=15.0
        )
        out = ActionOutcome(
            action_id=req.action_id, session_id=self.session_id, receipt=rec,
            outcome_status=ActionOutcomeStatus.DISPATCHED, state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=1, post_epoch=1, duration_ms=15.0
        )
        obs = self._build_native_obs()
        pre_snap = DualPerspectiveSnapshot(self.session_id, 1, time.time() - 0.5, obs, None, "")
        post_snap = DualPerspectiveSnapshot(self.session_id, 1, time.time(), obs, None, "")
        proc_info = {"pid": 456, "process_tree": [456], "is_running": True, "create_time": 100.0}
        return req, rec, out, pre_snap, post_snap, proc_info

    def test_transaction_pass_authoritative_physical(self):
        from runtime.evidence_models import ProofLevel
        req, rec, out, pre_snap, post_snap, proc_info = self._build_transaction_context()
        ev = self._build_physical_evidence(action_id=req.action_id)
        verdict, manifest, items = self.engine.evaluate_transaction(
            session_id=self.session_id,
            action_request=req,
            action_receipt=rec,
            action_outcome=out,
            pre_snapshot=pre_snap,
            post_snapshot=post_snap,
            target_process_info=proc_info,
            physical_desktop_evidence=ev,
            required_proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
        )
        self.assertEqual(verdict, VerificationVerdict.PASS)

    def test_transaction_unverified_missing_physical(self):
        from runtime.evidence_models import ProofLevel
        req, rec, out, pre_snap, post_snap, proc_info = self._build_transaction_context()
        verdict, manifest, items = self.engine.evaluate_transaction(
            session_id=self.session_id,
            action_request=req,
            action_receipt=rec,
            action_outcome=out,
            pre_snapshot=pre_snap,
            post_snapshot=post_snap,
            target_process_info=proc_info,
            physical_desktop_evidence=None,
            required_proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
        )
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)

    def test_transaction_unverified_occluded(self):
        from runtime.evidence_models import ProofLevel
        req, rec, out, pre_snap, post_snap, proc_info = self._build_transaction_context()
        ev = self._build_physical_evidence(action_id=req.action_id, occlusion_ratio=0.8)
        verdict, manifest, items = self.engine.evaluate_transaction(
            session_id=self.session_id,
            action_request=req,
            action_receipt=rec,
            action_outcome=out,
            pre_snapshot=pre_snap,
            post_snapshot=post_snap,
            target_process_info=proc_info,
            physical_desktop_evidence=ev,
            required_proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
        )
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)

    def test_transaction_unverified_stale(self):
        from runtime.evidence_models import ProofLevel
        req, rec, out, pre_snap, post_snap, proc_info = self._build_transaction_context()
        ev = self._build_physical_evidence(action_id=req.action_id, capture_time=time.time() - 20.0)
        verdict, manifest, items = self.engine.evaluate_transaction(
            session_id=self.session_id,
            action_request=req,
            action_receipt=rec,
            action_outcome=out,
            pre_snapshot=pre_snap,
            post_snapshot=post_snap,
            target_process_info=proc_info,
            physical_desktop_evidence=ev,
            required_proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
        )
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)

    def test_transaction_unverified_pid_recycled(self):
        from runtime.evidence_models import ProofLevel
        req, rec, out, pre_snap, post_snap, proc_info = self._build_transaction_context()
        ev = self._build_physical_evidence(action_id=req.action_id, process_creation_time=999.0)
        verdict, manifest, items = self.engine.evaluate_transaction(
            session_id=self.session_id,
            action_request=req,
            action_receipt=rec,
            action_outcome=out,
            pre_snapshot=pre_snap,
            post_snapshot=post_snap,
            target_process_info=proc_info,
            physical_desktop_evidence=ev,
            required_proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
        )
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)

    # --- Sneaky Agent Attack Tests ---
    def test_sneaky_agent_dom_claim_rejected_when_hidden(self):
        """Sneaky agent attempts to claim PASS using DOM mutations while window is minimized or occluded."""
        from runtime.evidence_models import ProofLevel
        from runtime.observation_models import WebObservation
        req, rec, out, pre_snap, post_snap, proc_info = self._build_transaction_context()
        # Mock minimized native observation
        obs_min = self._build_native_obs(is_iconic=True)
        object.__setattr__(post_snap, "native_observation", obs_min)
        # Agent claims DOM mutation succeeded in web observation
        web_obs = MagicMock()
        web_obs.url = "http://localhost/app"
        web_obs.title = "App"
        web_obs.to_dict.return_value = {"url": "http://localhost/app", "title": "App"}
        object.__setattr__(post_snap, "web_observation", web_obs)

        verdict, manifest, items = self.engine.evaluate_transaction(
            session_id=self.session_id,
            action_request=req,
            action_receipt=rec,
            action_outcome=out,
            pre_snapshot=pre_snap,
            post_snapshot=post_snap,
            target_process_info=proc_info,
            physical_desktop_evidence=None,
            required_proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
        )
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.WINDOW_CLOAKED_OR_MINIMIZED)

    def test_sneaky_agent_cdp_spoofing_rejected(self):
        """Sneaky agent attempts to spoof physical proof using a CDP screenshot."""
        from runtime.evidence_models import ProofLevel
        req, rec, out, pre_snap, post_snap, proc_info = self._build_transaction_context()
        cdp_snat = ScreenshotEvidence(
            screenshot_id="cdp1",
            screenshot_type="cdp",
            coordinate_space="viewport",
            dimensions=(800, 600),
            pixel_format="rgba",
            capture_bounds=(0,0,800,600),
            dpi_context=1.0,
            sha256="a"*64,
            relative_path="path",
            is_thumbnail=False,
            timestamp=time.time(),
            capture_method="CDP",
            is_certifying=False,
        )
        verdict, manifest, items = self.engine.evaluate_transaction(
            session_id=self.session_id,
            action_request=req,
            action_receipt=rec,
            action_outcome=out,
            pre_snapshot=pre_snap,
            post_snapshot=post_snap,
            target_process_info=proc_info,
            physical_desktop_evidence=cdp_snat,
            required_proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
        )
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.NON_AUTHORITATIVE_CAPTURE)

    # --- Target / Control Mismatch Tests ---
    def test_target_control_mismatch_wrong_hwnd(self):
        """Agent controls HWND 123 but physical evidence was taken from HWND 999."""
        obs = self._build_native_obs(hwnd=123)
        ev = self._build_physical_evidence(hwnd=999)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.HWND_MISMATCH)

    def test_target_control_mismatch_wrong_pid(self):
        """Agent controls PID 456 but physical evidence was taken from PID 789."""
        obs = self._build_native_obs(pid=456)
        ev = self._build_physical_evidence(pid=789)
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, {"pid": 456}, [], None, ev
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.PID_MISMATCH)

    # --- Agent Control Subsystem Tests ---
    def test_agent_control_indicator_lifecycle(self):
        from runtime.agent_control import AgentControlStatusIndicator, AgentControlState
        indicator = AgentControlStatusIndicator(
            session_id="test_ctrl",
            target_hwnd=0,
            target_pid=os.getpid(),
            process_creation_time=0.0,
        )
        self.assertEqual(indicator.control_state, AgentControlState.INACTIVE)
        self.assertFalse(indicator.is_active)

        # Activate
        self.assertTrue(indicator.activate())
        self.assertEqual(indicator.control_state, AgentControlState.ACTIVE)
        self.assertTrue(indicator.is_active)
        self.assertTrue(indicator.overlay_visible)

        # Pause
        self.assertTrue(indicator.pause("user_requested"))
        self.assertEqual(indicator.control_state, AgentControlState.PAUSED)
        self.assertFalse(indicator.is_active)
        self.assertFalse(indicator.overlay_visible)

        # Resume
        self.assertTrue(indicator.resume())
        self.assertEqual(indicator.control_state, AgentControlState.ACTIVE)
        self.assertTrue(indicator.is_active)

        # Terminate
        self.assertTrue(indicator.terminate("completed"))
        self.assertEqual(indicator.control_state, AgentControlState.TERMINATED)
        self.assertFalse(indicator.is_active)
        self.assertEqual(indicator.termination_reason, "completed")

    def test_agent_control_indicator_auto_termination_on_invalid_hwnd(self):
        from runtime.agent_control import AgentControlStatusIndicator, AgentControlState
        indicator = AgentControlStatusIndicator(
            session_id="test_invalid_hwnd",
            target_hwnd=0x999999,
            target_pid=os.getpid(),
            process_creation_time=0.0,
        )
        self.assertFalse(indicator.activate())
        self.assertEqual(indicator.control_state, AgentControlState.TERMINATED)
        self.assertEqual(indicator.termination_reason, "target_window_destroyed")

    def test_agent_control_indicator_auto_termination_on_dead_pid(self):
        from runtime.agent_control import AgentControlStatusIndicator, AgentControlState
        # PID 99999999 is guaranteed non-existent
        indicator = AgentControlStatusIndicator(
            session_id="test_dead",
            target_hwnd=0,
            target_pid=99999999,
            process_creation_time=0.0,
        )
        # Activation must fail because target process is dead
        self.assertFalse(indicator.activate())
        self.assertEqual(indicator.control_state, AgentControlState.TERMINATED)
        self.assertEqual(indicator.termination_reason, "target_process_exited")

    def test_agent_control_indicator_auto_termination_on_recycled_pid(self):
        from runtime.agent_control import AgentControlStatusIndicator, AgentControlState
        # Current process exists, but creation time is completely bogus
        indicator = AgentControlStatusIndicator(
            session_id="test_recycled",
            target_hwnd=0,
            target_pid=os.getpid(),
            process_creation_time=123.456,
        )
        self.assertFalse(indicator.activate())
        self.assertEqual(indicator.control_state, AgentControlState.TERMINATED)
        self.assertEqual(indicator.termination_reason, "target_pid_recycled")

    def test_agent_control_session_lifecycle(self):
        from runtime.agent_control import AgentControlledRuntimeSession, AgentControlState
        import psutil
        cur_proc = psutil.Process(os.getpid())
        cur_create_time = cur_proc.create_time()

        session = AgentControlledRuntimeSession(
            session_id="sess_ctrl",
            target_hwnd=0,
            target_pid=os.getpid(),
            process_creation_time=cur_create_time,
        )
        self.assertTrue(session.is_active)
        self.assertEqual(session.current_epoch, 1)

        # Increment epoch
        self.assertEqual(session.increment_epoch(), 2)

        # Heartbeat & liveness
        session.heartbeat()
        self.assertTrue(session.verify_liveness())

        # Serialization
        d = session.to_dict()
        self.assertEqual(d["session_id"], "sess_ctrl")
        self.assertEqual(d["agent_controlled"], True)
        self.assertEqual(d["indicator"]["control_state"], "ACTIVE")

        # Terminate
        session.terminate_control("done")
        self.assertFalse(session.is_active)
        self.assertEqual(session.control_state, AgentControlState.TERMINATED)

    def test_session_state_agent_control_integration(self):
        from runtime.session_manager import SessionState, SessionLifecycleState, ConnectionState, TargetPlane
        from datetime import datetime, timezone
        import psutil
        now = datetime.now(timezone.utc)
        state = SessionState(
            session_id="sess_int",
            lifecycle_state=SessionLifecycleState.CREATED,
            connection_state=ConnectionState.DISCONNECTED,
            active_plane=TargetPlane.NATIVE_SHELL,
            created_at=now,
            updated_at=now,
            last_heartbeat=now,
        )
        self.assertFalse(state.is_agent_controlled)

        cur_create_time = psutil.Process(os.getpid()).create_time()
        agent_sess = state.start_agent_control(
            target_hwnd=0,
            target_pid=os.getpid(),
            process_creation_time=cur_create_time,
        )
        self.assertTrue(state.is_agent_controlled)
        self.assertIsNotNone(state.agent_control_session)

        # Dict includes agent control
        state_dict = state.to_dict()
        self.assertTrue(state_dict["agent_controlled"])
        self.assertIsNotNone(state_dict["agent_control_session"])

        # Pause and resume
        state.pause_agent_control("paused_test")
        self.assertFalse(state.is_agent_controlled)
        state.resume_agent_control()
        self.assertTrue(state.is_agent_controlled)

        # Terminate
        state.terminate_agent_control("finished_test")
        self.assertFalse(state.is_agent_controlled)

    def test_session_manager_close_terminates_agent_control(self):
        import asyncio
        import psutil
        from runtime.session_manager import SessionManager, SessionConfig
        cur_create_time = psutil.Process(os.getpid()).create_time()

        async def _run():
            mgr = SessionManager()
            sess = await mgr.create_session(SessionConfig(session_id="sess_mgr_test"))
            sess.start_agent_control(
                target_hwnd=0,
                target_pid=os.getpid(),
                process_creation_time=cur_create_time,
            )
            self.assertTrue(sess.is_agent_controlled)

            await mgr.close_session("sess_mgr_test", reason="test_close")
            self.assertFalse(sess.is_agent_controlled)
            self.assertEqual(sess.agent_control_session.control_state.value, "TERMINATED")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

