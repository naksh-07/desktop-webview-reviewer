"""
Phase 5 Test Suite — Immediate Pre-Dispatch Precondition Revalidation.
Tests that WebActionExecutor and NativeActionExecutor reject dispatch when
actionability gate conditions fail immediately before action dispatch.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock

from runtime.state import TargetPlane
from runtime.references import Rect, ReferenceRegistry
from runtime.cdp_transport import MockCDPTransport
from runtime.actionability import (
    ActionabilityResult, GateStatus, MotionStatus, OverallActionabilityStatus,
)
from runtime.action_models import (
    ActionRequest, ActionTarget, ActionType, DispatchStatus, ActionRiskLevel,
)
from runtime.web_action_executor import WebActionExecutor
from runtime.native_action_executor import NativeActionExecutor
from runtime.native_input import NativeInputDispatcher
from runtime.native_supervisor import NativeSupervisor, WindowForensicReport


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_reg(epoch=5):
    reg = ReferenceRegistry()
    for _ in range(epoch):
        reg.advance_epoch(reason="setup")
    reg.register_ref(
        ref_id="w1e5", target_id="elem-1", plane=TargetPlane.WEBVIEW_DOM,
        role="button", name="Go", bounds=Rect(100, 100, 50, 30),
        frame_id="FRAME_ROOT", locator_recipe={"role": "button", "name": "Go"},
    )
    reg.register_ref(
        ref_id="n1e5", target_id="0x1234", plane=TargetPlane.NATIVE_SHELL,
        role="window", name="Test Win", bounds=Rect(0, 0, 800, 600),
        locator_recipe={"hwnd": "0x1234"},
    )
    return reg


def make_failed_actionability(reason):
    return ActionabilityResult(
        is_actionable=False,
        overall_status=OverallActionabilityStatus.NOT_ACTIONABLE,
        attachment=GateStatus.FAILED if "attach" in reason else GateStatus.PASSED,
        visibility=GateStatus.FAILED if "hidden" in reason else GateStatus.PASSED,
        motion_stability=MotionStatus.MOVING if "moving" in reason else MotionStatus.STABLE,
        enabledness=GateStatus.FAILED if "disabled" in reason else GateStatus.PASSED,
        hit_test=GateStatus.FAILED if "occluded" in reason else GateStatus.PASSED,
        affordance_point=None,
        reasons=[reason],
    )


class TestWebPreconditionRecheck(unittest.TestCase):
    """Tests that WebActionExecutor rejects when preconditions fail."""

    def setUp(self):
        self.wc = MagicMock()
        self.wc.is_connected = True
        self.wc.transport = MockCDPTransport()
        self.wc.frame_manager = MagicMock()
        self.wc.frame_manager.root_frame = MagicMock()
        self.wc.frame_manager.root_frame.url = "http://test"
        self.wc.frame_manager.root_frame_id = "FRAME_ROOT"
        self.wc.target_manager = MagicMock()
        self.wc.target_manager.active_target_id = "t1"
        self.wc.utility_world = MagicMock()
        self.wc.utility_world.evaluate = AsyncMock(return_value={"focused": True})
        self.wc.native_hwnd = 0x100
        self.reg = make_reg()
        self.act_engine = MagicMock()
        self.executor = WebActionExecutor(
            webview_core=self.wc,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def _make_target(self):
        return ActionTarget(
            session_id="s1", target_id="elem-1", reference="w1e5",
            plane=TargetPlane.WEBVIEW_DOM, epoch=self.reg.current_epoch,
            affordance_point=(125, 115), native_hwnd=0x100,
            cdp_target_id="t1", frame_id="FRAME_ROOT",
            bounds=Rect(100, 100, 50, 30),
        )

    def test_hidden_element_rejected(self):
        req = ActionRequest(session_id="s1", reference="w1e5",
                          action_type=ActionType.CLICK, observation_epoch=5)
        receipt = run_async(self.executor.execute_action(
            request=req, target=self._make_target(),
            precondition_result=make_failed_actionability("hidden by display:none"),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)

    def test_moving_element_rejected(self):
        req = ActionRequest(session_id="s1", reference="w1e5",
                          action_type=ActionType.CLICK, observation_epoch=5)
        receipt = run_async(self.executor.execute_action(
            request=req, target=self._make_target(),
            precondition_result=make_failed_actionability("element is moving"),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)

    def test_disabled_element_rejected(self):
        req = ActionRequest(session_id="s1", reference="w1e5",
                          action_type=ActionType.CLICK, observation_epoch=5)
        receipt = run_async(self.executor.execute_action(
            request=req, target=self._make_target(),
            precondition_result=make_failed_actionability("element is disabled"),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)

    def test_occluded_element_rejected(self):
        req = ActionRequest(session_id="s1", reference="w1e5",
                          action_type=ActionType.CLICK, observation_epoch=5)
        receipt = run_async(self.executor.execute_action(
            request=req, target=self._make_target(),
            precondition_result=make_failed_actionability("occluded by overlay"),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)


class TestNativePreconditionRecheck(unittest.TestCase):
    """Tests that NativeActionExecutor rejects when preconditions fail."""

    def setUp(self):
        self.ns = MagicMock(spec=NativeSupervisor)
        self.ns.is_window.return_value = True
        self.ns.inspect_window.return_value = WindowForensicReport(
            hwnd=0x1234, pid=1000, title="Win", class_name="Cls",
            bounds=Rect(0, 0, 800, 600), is_visible=True, is_enabled=True,
        )
        self.ns.bring_to_foreground.return_value = None
        self.ns.get_foreground_window.return_value = 0x1234
        self.ni = NativeInputDispatcher(dry_run=True)
        self.reg = make_reg()
        self.act_engine = MagicMock()
        self.executor = NativeActionExecutor(
            native_supervisor=self.ns,
            native_input=self.ni,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def _make_target(self):
        return ActionTarget(
            session_id="s1", target_id="0x1234", reference="n1e5",
            plane=TargetPlane.NATIVE_SHELL, epoch=self.reg.current_epoch,
            affordance_point=(400, 300), native_hwnd=0x1234,
            bounds=Rect(0, 0, 800, 600),
        )

    def test_native_hidden_rejected(self):
        req = ActionRequest(session_id="s1", reference="n1e5",
                          action_type=ActionType.CLICK, observation_epoch=5)
        receipt = run_async(self.executor.execute_action(
            request=req, target=self._make_target(),
            precondition_result=make_failed_actionability("hidden by cloaking"),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)

    def test_native_stale_epoch_rejected(self):
        req = ActionRequest(session_id="s1", reference="n1e5",
                          action_type=ActionType.CLICK, observation_epoch=5)
        target = ActionTarget(
            session_id="s1", target_id="0x1234", reference="n1e5",
            plane=TargetPlane.NATIVE_SHELL, epoch=999,
            affordance_point=(400, 300), native_hwnd=0x1234,
            bounds=Rect(0, 0, 800, 600),
        )
        receipt = run_async(self.executor.execute_action(
            request=req, target=target,
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)


if __name__ == "__main__":
    unittest.main()
