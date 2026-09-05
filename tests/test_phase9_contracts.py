"""
Unit and Contract Test Suite for Desktop WebView Reviewer 2.0 (Phase 9).
Verifies the Agent Sovereignty Boundary, 2.0 Capability Negotiation, Reality Model
Truth Hierarchy, Action Contract 5-Stage Segregation, Desktop Trace Model,
Reviewer Test Harness Security Boundary, and the Harness Golden Rule.
"""

import unittest
import time

from runtime.capability import (
    CapabilityMatrix,
    CapabilityId,
    CapabilityStatus,
    CapabilityCategory,
    CapabilityNegotiationProfile,
)
from runtime.reality_models import (
    RealityTarget,
    TargetIdentity,
    NativeTargetProps,
    WebTargetProps,
    CompositorTargetProps,
    VisualTargetProps,
    ActionabilityAssessment,
    TruthHierarchyLevel,
    RealityReconciliationSnapshot,
)
from runtime.action_models import (
    ActionLifecycleStage,
    ActionOutcomeStatus,
    DispatchStatus,
    ActionReceipt,
    ActionType,
    DispatchMethod,
)
from runtime.trace_models import (
    DesktopTraceEventType,
    DesktopTraceEvent,
    TraceCorrelation,
    TraceTimeline,
)
from runtime.harness_contracts import (
    BuildMode,
    HarnessLifecycleSignal,
    HarnessDiagnosticData,
    HarnessSecurityValidator,
    HarnessSecurityViolationException,
    HarnessGoldenRuleEnforcer,
)
from runtime.evidence_models import VerificationVerdict
from runtime.specialist_contracts import (
    SpecialistRole,
    SpecialistRegistry,
)
from runtime.state import TargetPlane
from runtime.references import Rect


class TestPhase9Contracts(unittest.TestCase):
    """Authoritative contract validation for Phase 9 specifications."""

    # -------------------------------------------------------------------------
    # 1. Agent Sovereignty & Specialist Boundaries
    # -------------------------------------------------------------------------
    def test_specialist_contracts_enforce_boundaries(self):
        """Verifies that all 5 specialist roles have strict operational non-scopes."""
        explorer = SpecialistRegistry.get_explorer_contract()
        self.assertEqual(explorer.role, SpecialistRole.EXPLORER)
        self.assertTrue(explorer.is_read_only)
        self.assertTrue(explorer.validate_tool_access("desktop_inspect"))
        self.assertFalse(explorer.validate_tool_access("desktop_click"))
        self.assertIn("autonomous_mission_expansion", explorer.forbidden_operations)

        tester = SpecialistRegistry.get_tester_contract()
        self.assertEqual(tester.role, SpecialistRole.TESTER)
        self.assertFalse(tester.is_read_only)
        self.assertTrue(tester.validate_tool_access("desktop_click"))
        self.assertIn("inventing_new_business_workflows", tester.forbidden_operations)

        inspector = SpecialistRegistry.get_reality_inspector_contract()
        self.assertEqual(inspector.role, SpecialistRole.REALITY_INSPECTOR)
        self.assertTrue(inspector.is_read_only)
        self.assertTrue(inspector.validate_tool_access("desktop_screenshot"))
        self.assertIn("relying_solely_on_dom_visibility", inspector.forbidden_operations)

        debugger = SpecialistRegistry.get_debugger_contract()
        self.assertEqual(debugger.role, SpecialistRole.DEBUGGER)
        self.assertTrue(debugger.validate_tool_access("desktop_get_trace"))
        self.assertIn("blind_retries_without_diagnosis", debugger.forbidden_operations)

        evidence = SpecialistRegistry.get_evidence_specialist_contract()
        self.assertEqual(evidence.role, SpecialistRole.EVIDENCE_SPECIALIST)
        self.assertTrue(evidence.is_read_only)
        self.assertTrue(evidence.validate_tool_access("desktop_get_evidence"))
        self.assertIn("faking_hashes", evidence.forbidden_operations)

    # -------------------------------------------------------------------------
    # 2. 2.0 Capability Model & Negotiation
    # -------------------------------------------------------------------------
    def test_capability_statuses_and_negotiation_profile(self):
        """Validates 2.0 capability statuses and startup negotiation profile."""
        matrix = CapabilityMatrix(populate_defaults=False)
        matrix.set_capability(CapabilityId.NATIVE_WIN32, CapabilityStatus.AVAILABLE, reason="Native Win32 active")
        matrix.set_capability(CapabilityId.WEBVIEW_CDP, CapabilityStatus.SUPPORTED, reason="CDP supported")
        matrix.set_capability(CapabilityId.NATIVE_UIA3, CapabilityStatus.DEGRADED, reason="COM walkers pending")
        matrix.set_capability(CapabilityId.CDP_INPUT_EVENTS, CapabilityStatus.UNAVAILABLE, reason="Sandbox restricted")

        self.assertTrue(matrix.is_supported(CapabilityId.NATIVE_WIN32))
        self.assertTrue(matrix.is_supported(CapabilityId.WEBVIEW_CDP))
        self.assertFalse(matrix.is_supported(CapabilityId.NATIVE_UIA3))
        self.assertFalse(matrix.is_supported(CapabilityId.CDP_INPUT_EVENTS))

        # Build negotiation profile
        profile = matrix.build_negotiation_profile(
            session_id="test_sess_01",
            target_id="target_main",
            engine_info={"engine": "QtWebEngine", "version": "6.7"},
        )
        self.assertIsInstance(profile, CapabilityNegotiationProfile)
        self.assertEqual(profile.session_id, "test_sess_01")
        self.assertEqual(profile.engine_info["engine"], "QtWebEngine")
        self.assertTrue(any("COM walkers pending" in lim for lim in profile.limitations))
        self.assertTrue(any("Sandbox restricted" in lim for lim in profile.limitations))

        d = profile.to_dict()
        self.assertEqual(d["session_id"], "test_sess_01")
        self.assertIn("native", d["capabilities"])

    # -------------------------------------------------------------------------
    # 3. Reality Model & Physical Reality Primacy
    # -------------------------------------------------------------------------
    def test_reality_model_physical_primacy_overrides_dom(self):
        """Verifies that DWM cloaking, minimization, and occlusion override DOM claims."""
        identity = TargetIdentity(session_id="s1", target_id="t1", reference="w1e1", role="button", name="Submit")
        native_visible = NativeTargetProps(hwnd=0x1234, visible=True, focused=True, bounds=Rect(100, 100, 200, 150))
        web_exists = WebTargetProps(exists=True, enabled=True, tag_name="BUTTON", css_bounds=Rect(10, 10, 100, 40))
        visual_rendered = VisualTargetProps(is_physically_rendered=True)
        actionable = ActionabilityAssessment(is_actionable=True)

        # Case A: Window is uncloaked, visible, not minimized -> Physically Visible
        target_valid = RealityTarget(
            identity=identity,
            source_plane=TargetPlane.WEBVIEW,
            native=native_visible,
            web=web_exists,
            compositor=CompositorTargetProps(is_cloaked=False, is_minimized=False, is_occluded=False),
            visual=visual_rendered,
            actionability=actionable,
            observation_epoch=1,
            truth_rank=TruthHierarchyLevel.PHYSICAL_DESKTOP,
        )
        self.assertTrue(target_valid.is_physically_visible)

        # Case B: Window is CLOAKED by DWM -> Not Physically Visible despite DOM claims
        target_cloaked = RealityTarget(
            identity=identity,
            source_plane=TargetPlane.WEBVIEW,
            native=native_visible,
            web=web_exists,
            compositor=CompositorTargetProps(is_cloaked=True, is_minimized=False, is_occluded=False),
            visual=visual_rendered,
            actionability=actionable,
            observation_epoch=1,
        )
        self.assertFalse(target_cloaked.is_physically_visible)

        # Case C: Window is MINIMIZED -> Not Physically Visible
        target_minimized = RealityTarget(
            identity=identity,
            source_plane=TargetPlane.WEBVIEW,
            native=native_visible,
            web=web_exists,
            compositor=CompositorTargetProps(is_cloaked=False, is_minimized=True, is_occluded=False),
            visual=visual_rendered,
            actionability=actionable,
            observation_epoch=1,
        )
        self.assertFalse(target_minimized.is_physically_visible)

        # Case D: Native window IsWindowVisible=False -> Not Physically Visible
        target_hidden_native = RealityTarget(
            identity=identity,
            source_plane=TargetPlane.WEBVIEW,
            native=NativeTargetProps(hwnd=0x1234, visible=False, focused=False, bounds=Rect(100, 100, 200, 150)),
            web=web_exists,
            compositor=CompositorTargetProps(is_cloaked=False, is_minimized=False, is_occluded=False),
            visual=visual_rendered,
            actionability=actionable,
            observation_epoch=1,
        )
        self.assertFalse(target_hidden_native.is_physically_visible)

        # Case E: Completely occluded (100%) -> Not Physically Visible
        target_occluded = RealityTarget(
            identity=identity,
            source_plane=TargetPlane.WEBVIEW,
            native=native_visible,
            web=web_exists,
            compositor=CompositorTargetProps(is_cloaked=False, is_minimized=False, is_occluded=True, occlusion_percentage=1.0),
            visual=visual_rendered,
            actionability=actionable,
            observation_epoch=1,
        )
        self.assertFalse(target_occluded.is_physically_visible)

    def test_reality_reconciliation_snapshot(self):
        """Verifies snapshot aggregation and reference lookup."""
        snap = RealityReconciliationSnapshot(session_id="snap_sess", observation_epoch=2)
        target = RealityTarget(
            identity=TargetIdentity("snap_sess", "t1", "w1e9", "link", "Home"),
            source_plane=TargetPlane.WEBVIEW,
            native=NativeTargetProps(hwnd=0x999, visible=True),
            web=WebTargetProps(exists=True, enabled=True),
            compositor=CompositorTargetProps(is_cloaked=False, is_minimized=False),
            visual=VisualTargetProps(is_physically_rendered=True),
            actionability=ActionabilityAssessment(is_actionable=True),
            observation_epoch=2,
        )
        snap.add_target(target)
        found = snap.find_by_reference("w1e9")
        self.assertIsNotNone(found)
        self.assertEqual(found.identity.target_id, "t1")
        self.assertIsNone(snap.find_by_reference("w1e999"))

    # -------------------------------------------------------------------------
    # 4. Action Contract: 5-Stage Distinction
    # -------------------------------------------------------------------------
    def test_action_lifecycle_milestone_segregation(self):
        """Validates that action stages are distinct and cannot be conflated."""
        stages = [
            ActionLifecycleStage.ACTION_RECEIVED,
            ActionLifecycleStage.ACTION_DISPATCHED,
            ActionLifecycleStage.ACTION_COMPLETED,
            ActionLifecycleStage.STATE_CHANGED,
            ActionLifecycleStage.EXPECTED_STATE_VERIFIED,
        ]
        # Assert all 5 stages exist and are unique
        self.assertEqual(len(set(stages)), 5)
        self.assertNotEqual(ActionLifecycleStage.ACTION_DISPATCHED, ActionLifecycleStage.EXPECTED_STATE_VERIFIED)

        # Receipt with status DISPATCHED cannot be claimed as PASS
        receipt = ActionReceipt(
            action_id="act_01",
            session_id="s1",
            target_id="t1",
            epoch=1,
            plane=TargetPlane.WEBVIEW,
            reference="w1e1",
            action_type=ActionType.CLICK,
            dispatch_method=DispatchMethod.PHYSICAL_INPUT,
            dispatch_timestamp=time.time(),
            dispatch_status=DispatchStatus.DISPATCHED,
        )
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        # ActionOutcomeStatus DISPATCHED != VerificationVerdict PASS
        self.assertNotEqual(ActionOutcomeStatus.DISPATCHED.value, VerificationVerdict.PASS.value)

    # -------------------------------------------------------------------------
    # 5. Desktop Trace & Event Correlation
    # -------------------------------------------------------------------------
    def test_desktop_trace_event_correlation(self):
        """Verifies monotonic trace timeline and multi-key correlation."""
        timeline = TraceTimeline()
        corr = TraceCorrelation(session_id="trace_s1", epoch_id=1, action_id="act_click_01", request_id="req_99")

        e1 = DesktopTraceEvent(
            event_type=DesktopTraceEventType.APP_LAUNCH,
            correlation=corr,
            process_id=5001,
            status="SUCCESS",
        )
        e2 = DesktopTraceEvent(
            event_type=DesktopTraceEventType.ACTION_REQUESTED,
            correlation=corr,
            target_reference="w1e1",
        )
        e3 = DesktopTraceEvent(
            event_type=DesktopTraceEventType.ACTION_DISPATCHED,
            correlation=corr,
            target_reference="w1e1",
        )
        e4 = DesktopTraceEvent(
            event_type=DesktopTraceEventType.ASSERTION,
            correlation=corr,
            details={"verdict": "PASS", "claim": "ButtonStateChanged"},
        )

        timeline.record(e1)
        timeline.record(e2)
        timeline.record(e3)
        timeline.record(e4)

        events = timeline.get_events()
        self.assertEqual(len(events), 4)
        # Monotonic sequence ordering
        self.assertTrue(events[0].sequence_monotonic < events[1].sequence_monotonic < events[2].sequence_monotonic)

        # Multi-key filtering
        session_events = timeline.filter_by_session("trace_s1")
        self.assertEqual(len(session_events), 4)

        action_events = timeline.filter_by_action("act_click_01")
        self.assertEqual(len(action_events), 4)

        assertions = timeline.filter_by_type(DesktopTraceEventType.ASSERTION)
        self.assertEqual(len(assertions), 1)
        self.assertEqual(assertions[0].details["verdict"], "PASS")

    # -------------------------------------------------------------------------
    # 6. Reviewer Test Harness Security Boundary & Golden Rule
    # -------------------------------------------------------------------------
    def test_harness_security_rejection_in_release_build(self):
        """Verifies that release builds strictly reject harness access."""
        # Development build allowed
        self.assertTrue(HarnessSecurityValidator.validate_harness_access(BuildMode.DEV_OR_REVIEW))

        # Release build raises HarnessSecurityViolationException
        with self.assertRaises(HarnessSecurityViolationException):
            HarnessSecurityValidator.validate_harness_access(BuildMode.RELEASE_PRODUCTION)

    def test_harness_golden_rule_cannot_override_physical_reality(self):
        """Verifies that harness signals cannot override physical verification failure or uncertainty."""
        # Scenario 1: Physical reality FAIL, but harness claims SAVE_COMPLETED -> Result MUST be FAIL
        verdict_1 = HarnessGoldenRuleEnforcer.reconcile_verdict(
            physical_reality_verdict=VerificationVerdict.FAIL,
            harness_signal=HarnessLifecycleSignal.SAVE_COMPLETED,
            harness_diagnostics=HarnessDiagnosticData(current_screen="Settings"),
        )
        self.assertEqual(verdict_1, VerificationVerdict.FAIL)

        # Scenario 2: Physical reality UNVERIFIED (e.g. window cloaked), but harness claims SAVE_COMPLETED -> Result MUST be UNVERIFIED
        verdict_2 = HarnessGoldenRuleEnforcer.reconcile_verdict(
            physical_reality_verdict=VerificationVerdict.UNVERIFIED,
            harness_signal=HarnessLifecycleSignal.SAVE_COMPLETED,
            harness_diagnostics=HarnessDiagnosticData(current_screen="Settings"),
        )
        self.assertEqual(verdict_2, VerificationVerdict.UNVERIFIED)

        # Scenario 3: Physical reality PASS, harness confirms SAVE_COMPLETED -> Result is PASS
        verdict_3 = HarnessGoldenRuleEnforcer.reconcile_verdict(
            physical_reality_verdict=VerificationVerdict.PASS,
            harness_signal=HarnessLifecycleSignal.SAVE_COMPLETED,
        )
        self.assertEqual(verdict_3, VerificationVerdict.PASS)


if __name__ == "__main__":
    unittest.main()
