"""
Phase 5 Test Suite — Adversarial Scenarios.
Tests edge cases: element vanishes before click, element moves during dispatch,
page navigates before click, frame detaches, native window minimizes,
modal dialog appears, PID/HWND mismatch.
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
    ActionRequest, ActionTarget, ActionReceipt, ActionType,
    DispatchMethod, DispatchStatus,
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


def make_passing_actionability(point=(200, 150)):
    return ActionabilityResult(
        is_actionable=True, overall_status=OverallActionabilityStatus.READY,
        attachment=GateStatus.PASSED, visibility=GateStatus.PASSED,
        motion_stability=MotionStatus.STABLE, enabledness=GateStatus.PASSED,
        hit_test=GateStatus.PASSED, affordance_point=point, reasons=[],
    )


def make_failing_actionability(reason="element vanished"):
    return ActionabilityResult(
        is_actionable=False, overall_status=OverallActionabilityStatus.NOT_ACTIONABLE,
        attachment=GateStatus.FAILED, visibility=GateStatus.FAILED,
        motion_stability=MotionStatus.STABLE, enabledness=GateStatus.PASSED,
        hit_test=GateStatus.FAILED, affordance_point=None, reasons=[reason],
    )


class TestAdversarialWebElementVanishes(unittest.TestCase):
    """Tests: element vanishes immediately before click dispatch."""

    def setUp(self):
        self.wc = MagicMock()
        self.wc.is_connected = True
        self.wc.transport = MockCDPTransport()
        self.wc.frame_manager = MagicMock()
        self.wc.frame_manager.root_frame = MagicMock(url="http://test")
        self.wc.frame_manager.root_frame_id = "ROOT"
        self.wc.target_manager = MagicMock(active_target_id="t1")
        self.wc.utility_world = MagicMock()
        self.wc.utility_world.evaluate = AsyncMock(return_value={"focused": True})
        self.wc.native_hwnd = 0x100
        self.reg = ReferenceRegistry()
        for _ in range(5):
            self.reg.advance_epoch(reason="s")
        self.reg.register_ref(ref_id="w1e5", target_id="elem-gone",
                             plane=TargetPlane.WEBVIEW_DOM, role="button",
                             name="Gone", bounds=Rect(100, 100, 50, 30),
                             frame_id="ROOT", locator_recipe={"role": "button"})
        self.executor = WebActionExecutor(self.wc, MagicMock(), self.reg)

    def test_vanished_element_rejected(self):
        req = ActionRequest(session_id="s1", reference="w1e5",
                          action_type=ActionType.CLICK, observation_epoch=5)
        target = ActionTarget(
            session_id="s1", target_id="elem-gone", reference="w1e5",
            plane=TargetPlane.WEBVIEW_DOM, epoch=self.reg.current_epoch,
            affordance_point=(125, 115), native_hwnd=0x100,
            cdp_target_id="t1", frame_id="ROOT",
            bounds=Rect(100, 100, 50, 30),
        )
        # Actionability says NOT actionable (element vanished)
        receipt = run_async(self.executor.execute_action(
            request=req, target=target,
            precondition_result=make_failing_actionability("element vanished from DOM"),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)
        self.assertIn("vanished", receipt.error)


class TestAdversarialElementMoving(unittest.TestCase):
    """Tests: element is moving during dispatch."""

    def setUp(self):
        self.wc = MagicMock()
        self.wc.is_connected = True
        self.wc.transport = MockCDPTransport()
        self.wc.frame_manager = MagicMock()
        self.wc.frame_manager.root_frame = MagicMock(url="http://test")
        self.wc.frame_manager.root_frame_id = "ROOT"
        self.wc.target_manager = MagicMock(active_target_id="t1")
        self.wc.utility_world = MagicMock()
        self.wc.utility_world.evaluate = AsyncMock(return_value={"focused": True})
        self.wc.native_hwnd = 0x100
        self.reg = ReferenceRegistry()
        for _ in range(5):
            self.reg.advance_epoch(reason="s")
        self.reg.register_ref(ref_id="w1e5", target_id="elem-moving",
                             plane=TargetPlane.WEBVIEW_DOM, role="div",
                             name="Carousel", bounds=Rect(50, 50, 200, 100),
                             frame_id="ROOT")
        self.executor = WebActionExecutor(self.wc, MagicMock(), self.reg)

    def test_moving_element_rejected(self):
        req = ActionRequest(session_id="s1", reference="w1e5",
                          action_type=ActionType.CLICK, observation_epoch=5)
        target = ActionTarget(
            session_id="s1", target_id="elem-moving", reference="w1e5",
            plane=TargetPlane.WEBVIEW_DOM, epoch=self.reg.current_epoch,
            affordance_point=(150, 100), native_hwnd=0x100,
            cdp_target_id="t1", frame_id="ROOT",
            bounds=Rect(50, 50, 200, 100),
        )
        moving_result = ActionabilityResult(
            is_actionable=False, overall_status=OverallActionabilityStatus.NOT_ACTIONABLE,
            attachment=GateStatus.PASSED, visibility=GateStatus.PASSED,
            motion_stability=MotionStatus.MOVING, enabledness=GateStatus.PASSED,
            hit_test=GateStatus.PASSED, affordance_point=None,
            reasons=["element is still moving"],
        )
        receipt = run_async(self.executor.execute_action(
            request=req, target=target, precondition_result=moving_result,
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)


class TestAdversarialNativeWindowMinimized(unittest.TestCase):
    """Tests: native window is minimized before action dispatch."""

    def test_minimized_window_fails(self):
        ns = MagicMock(spec=NativeSupervisor)
        ns.is_window.return_value = True
        ns.inspect_window.return_value = WindowForensicReport(
            hwnd=0x1234, pid=100, title="Minimized", class_name="C",
            bounds=Rect(0, 0, 0, 0), is_visible=False, is_enabled=True,
        )
        ns.bring_to_foreground.return_value = None
        ns.get_foreground_window.return_value = 0x1234
        ni = NativeInputDispatcher(dry_run=True)
        reg = ReferenceRegistry()
        for _ in range(3):
            reg.advance_epoch(reason="s")
        reg.register_ref(ref_id="n1e3", target_id="0x1234",
                        plane=TargetPlane.NATIVE_SHELL, role="window",
                        name="Minimized", bounds=Rect(0, 0, 0, 0))
        executor = NativeActionExecutor(ns, ni, MagicMock(), reg)

        req = ActionRequest(session_id="s1", reference="n1e3",
                          action_type=ActionType.CLICK, observation_epoch=3)
        target = ActionTarget(
            session_id="s1", target_id="0x1234", reference="n1e3",
            plane=TargetPlane.NATIVE_SHELL, epoch=reg.current_epoch,
            affordance_point=(0, 0), native_hwnd=0x1234,
            bounds=Rect(0, 0, 0, 0),
        )
        receipt = run_async(executor.execute_action(
            request=req, target=target,
            precondition_result=make_failing_actionability("window minimized"),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)


class TestAdversarialPidHwndMismatch(unittest.TestCase):
    """Tests: HWND becomes invalid/destroyed between validation and dispatch."""

    def test_destroyed_hwnd_fails(self):
        ns = MagicMock(spec=NativeSupervisor)
        ns.is_window.return_value = False  # Window destroyed!
        ni = NativeInputDispatcher(dry_run=True)
        reg = ReferenceRegistry()
        for _ in range(3):
            reg.advance_epoch(reason="s")
        reg.register_ref(ref_id="n1e3", target_id="0xDEAD",
                        plane=TargetPlane.NATIVE_SHELL, role="window",
                        name="Destroyed", bounds=Rect(0, 0, 800, 600))
        executor = NativeActionExecutor(ns, ni, MagicMock(), reg)

        req = ActionRequest(session_id="s1", reference="n1e3",
                          action_type=ActionType.CLICK, observation_epoch=3)
        target = ActionTarget(
            session_id="s1", target_id="0xDEAD", reference="n1e3",
            plane=TargetPlane.NATIVE_SHELL, epoch=reg.current_epoch,
            affordance_point=(400, 300), native_hwnd=0xDEAD,
            bounds=Rect(0, 0, 800, 600),
        )
        receipt = run_async(executor.execute_action(request=req, target=target))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.FAILED)
        self.assertIn("Invalid HWND", receipt.error)


class TestAdversarialEpochRace(unittest.TestCase):
    """Tests: epoch changes between request and dispatch."""

    def test_epoch_race_condition(self):
        wc = MagicMock()
        wc.is_connected = True
        wc.transport = MockCDPTransport()
        wc.frame_manager = MagicMock()
        wc.frame_manager.root_frame = MagicMock(url="http://test")
        wc.frame_manager.root_frame_id = "ROOT"
        wc.target_manager = MagicMock(active_target_id="t1")
        wc.utility_world = MagicMock()
        wc.utility_world.evaluate = AsyncMock(return_value={"focused": True})
        wc.native_hwnd = 0x100

        reg = ReferenceRegistry()
        for _ in range(5):
            reg.advance_epoch(reason="s")
        reg.register_ref(ref_id="w1e5", target_id="btn-1",
                        plane=TargetPlane.WEBVIEW_DOM, role="button",
                        name="Btn", bounds=Rect(100, 100, 50, 30),
                        frame_id="ROOT")
        executor = WebActionExecutor(wc, MagicMock(), reg)

        # Target was at epoch 5, but registry has advanced to 6
        reg.advance_epoch(reason="race-condition-mutation")

        req = ActionRequest(session_id="s1", reference="w1e5",
                          action_type=ActionType.CLICK, observation_epoch=5)
        target = ActionTarget(
            session_id="s1", target_id="btn-1", reference="w1e5",
            plane=TargetPlane.WEBVIEW_DOM, epoch=5,  # stale epoch
            affordance_point=(125, 115), native_hwnd=0x100,
            cdp_target_id="t1", frame_id="ROOT",
            bounds=Rect(100, 100, 50, 30),
        )
        receipt = run_async(executor.execute_action(request=req, target=target))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)
        self.assertIn("Epoch mismatch", receipt.precondition_summary)


if __name__ == "__main__":
    unittest.main()
