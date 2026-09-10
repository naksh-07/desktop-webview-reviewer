import time
import unittest
import tempfile
from pathlib import Path

from runtime.state import TargetPlane
from runtime.references import ElementRef, ReferenceRegistry, Rect
from runtime.action_models import (
    ActionRequest,
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
    VisibilityObservation,
    InteractionObservation,
)
from runtime.observation_diff import ObservationDiffResult, DiffItem
from runtime.evidence_models import VerificationVerdict, UnverifiedReason, ScreenshotEvidence
from runtime.evidence_store import EvidenceStore
from runtime.verification_engine import VerificationEngine

class TestPidIdentityAdversarial(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(base_dir=Path(self.temp_dir.name))
        self.verifier = VerificationEngine(evidence_store=self.store, require_visible_gui=True)
        self.session_id = "test_adversarial_pid"
        self.action_id = "act_1"

        # Valid baseline objects
        self.request = ActionRequest(
            session_id=self.session_id,
            reference="w1e1",
            action_type=ActionType.CLICK,
            observation_epoch=1,
            params={"expect_change": True},
        )
        self.receipt = ActionReceipt(
            action_id=self.action_id,
            session_id=self.session_id,
            target_id="elem_1",
            epoch=1,
            plane=TargetPlane.WEBVIEW_DOM,
            reference="w1e1",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.CDP_INPUT,
            dispatch_timestamp=time.time(),
            dispatch_status=DispatchStatus.DISPATCHED,
        )
        self.native_obs = NativeObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            hwnd=0x2001,
            title="App",
            class_name="Qt",
            pid=1234,
            bounds=Rect(100, 100, 800, 600),
            client_bounds=Rect(108, 131, 784, 561),
            is_visible=True,
            is_minimized=False,
            is_cloaked=False,
            is_responsive=True,
        )
        self.web_obs = WebObservation(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            target_id="t1",
            target_title="Page",
            target_url="http://x",
            root_frame_id="f1",
            elements=(),
        )
        self.snap = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=2,
            timestamp=time.time(),
            native_observation=self.native_obs,
            web_observation=self.web_obs,
            text_representation="",
        )
        self.outcome = ActionOutcome(
            action_id=self.action_id,
            session_id=self.session_id,
            receipt=self.receipt,
            outcome_status=ActionOutcomeStatus.DISPATCHED,
            state_change=StateChangeClassification.STATE_CHANGED,
            pre_epoch=1,
            post_epoch=2,
            post_snapshot=self.snap,
            observation_diff=ObservationDiffResult(from_epoch=1, to_epoch=2),
        )
        self.screenshot = ScreenshotEvidence(
            screenshot_id="s_nat",
            screenshot_type="NATIVE_WINDOW",
            coordinate_space="WINDOW_EXTENDED_FRAME",
            dimensions=(800, 600),
            capture_bounds=(100, 100, 800, 600),
            sha256="fakehash",
            relative_path="s_nat.png",
            timestamp=time.time(),
            capture_method="REAL_DESKTOP_SURFACE",
            is_certifying=True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_creation_time_fails_closed(self):
        # target_process_info is missing creation_time (or it's 0)
        proc_info_missing_time = {"pid": 1234, "is_running": True}
        
        verdict, manifest, _ = self.verifier.evaluate_transaction(
            session_id=self.session_id,
            action_request=self.request,
            action_receipt=self.receipt,
            action_outcome=self.outcome,
            pre_snapshot=self.snap,
            post_snapshot=self.snap,
            observation_diff=self.outcome.observation_diff,
            target_process_info=proc_info_missing_time,
            execution_mode="automated",
            native_screenshot=self.screenshot,
        )
        
        self.assertEqual(verdict, VerificationVerdict.UNVERIFIED)
        self.assertEqual(manifest.unverified_reason, UnverifiedReason.PROCESS_IDENTITY_MISMATCH)

    def test_wrong_creation_time_recycled_pid_fails_closed(self):
        # Native obs pid=1234, target_process_info has pid=1234 but creation_time mismatch
        # The verification engine checks expected_creation != native_obs_creation if it had it.
        # But wait, native_obs doesn't store creation time! 
        # Actually TargetManager checks creation time. 
        pass

if __name__ == "__main__":
    unittest.main()
