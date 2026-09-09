import unittest
import time
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
            session_id="test",
            epoch=1,
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

    def _build_physical_evidence(self, hwnd=123, bounds=None, capture_time=None, process_creation_time=100.0):
        return PhysicalDesktopEvidence(
            evidence_id="ev_1",
            session_id="test",
            target_hwnd=hwnd,
            target_pid=456,
            foreground_hwnd=hwnd,
            is_exact_foreground=True,
            dimensions=(800, 600),
            capture_timestamp=capture_time or time.time(),
            pixel_sha256="hash",
            artifact_path="/tmp/test.png",
            action_epoch=1,
            process_creation_time=process_creation_time,
            occlusion_state="NOT_OCCLUDED",
            occlusion_ratio=0.0,
            physical_bounds=bounds or (0, 0, 800, 600),
            capture_method="REAL_DESKTOP_SURFACE",
            is_authoritative=True,
            post_capture_validated=True
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
        
    def test_fail_print_window_only(self):
        obs = self._build_native_obs()
        snat = ScreenshotEvidence(
            screenshot_id="1",
            screenshot_type="native",
            coordinate_space="screen",
            dimensions=(800, 600),
            pixel_format="rgba",
            capture_bounds=(0,0,800,600),
            dpi_context=1.0,
            sha256="hash",
            relative_path="path",
            is_thumbnail=False,
            timestamp=time.time(),
            capture_method="PRINT_WINDOW_DIAGNOSTIC",
            is_certifying=False
        )
        claim = self.engine._evaluate_claim_physical_visibility(
            self.session_id, self.action_id, self.epoch, obs, None, [], snat, None
        )
        self.assertEqual(claim.status, VerificationVerdict.UNVERIFIED)
        self.assertEqual(claim.unverified_reason, UnverifiedReason.NON_AUTHORITATIVE_CAPTURE)

if __name__ == "__main__":
    unittest.main()
