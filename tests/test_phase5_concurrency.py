"""
Phase 5 Test Suite — Session Concurrency Isolation.
Tests that independent concurrent sessions executing actions simultaneously
do not cross-talk, share state, or cause target confusion.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock

from runtime.state import TargetPlane
from runtime.references import Rect, ReferenceRegistry
from runtime.action_models import (
    ActionRequest, ActionReceipt, ActionType, DispatchStatus,
)
from runtime.web_action_executor import WebActionExecutor
from runtime.native_action_executor import NativeActionExecutor
from runtime.native_input import NativeInputDispatcher
from runtime.native_supervisor import NativeSupervisor, WindowForensicReport
from runtime.cdp_transport import MockCDPTransport
from runtime.actionability import (
    ActionabilityResult, GateStatus, MotionStatus, OverallActionabilityStatus,
)
from runtime.action_models import ActionTarget


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_web_session(session_id, epoch=5):
    """Creates independent web session components."""
    reg = ReferenceRegistry()
    for _ in range(epoch):
        reg.advance_epoch(reason="setup")
    reg.register_ref(
        ref_id=f"w1e{epoch}", target_id=f"btn-{session_id}",
        plane=TargetPlane.WEBVIEW_DOM, role="button",
        name=f"Btn_{session_id}", bounds=Rect(100, 100, 50, 30),
        frame_id="FRAME_ROOT", locator_recipe={"role": "button", "name": f"Btn_{session_id}"},
    )

    wc = MagicMock()
    wc.is_connected = True
    transport = MockCDPTransport()
    run_async(transport.connect())
    wc.transport = transport
    wc.frame_manager = MagicMock()
    wc.frame_manager.root_frame = MagicMock(url="http://test")
    wc.frame_manager.root_frame_id = "FRAME_ROOT"
    wc.target_manager = MagicMock(active_target_id="target-main")
    wc.utility_world = MagicMock()
    wc.utility_world.evaluate = AsyncMock(return_value={"focused": True})
    wc.native_hwnd = 0x100 + hash(session_id) % 0xFFF
    wc.native_pid = 1000

    act_engine = MagicMock()
    executor = WebActionExecutor(
        webview_core=wc, actionability_engine=act_engine,
        reference_registry=reg,
    )

    target = ActionTarget(
        session_id=session_id, target_id=f"btn-{session_id}",
        reference=f"w1e{epoch}", plane=TargetPlane.WEBVIEW_DOM,
        epoch=reg.current_epoch, affordance_point=(125, 115),
        native_hwnd=wc.native_hwnd, cdp_target_id="target-main",
        frame_id="FRAME_ROOT", bounds=Rect(100, 100, 50, 30),
    )

    precondition = ActionabilityResult(
        is_actionable=True, overall_status=OverallActionabilityStatus.READY,
        attachment=GateStatus.PASSED, visibility=GateStatus.PASSED,
        motion_stability=MotionStatus.STABLE, enabledness=GateStatus.PASSED,
        hit_test=GateStatus.PASSED, affordance_point=(125, 115), reasons=[],
    )

    return executor, reg, target, precondition


class TestConcurrentSessionIsolation(unittest.TestCase):
    """Tests that multiple sessions can execute actions independently."""

    def test_two_sessions_do_not_crosstalk(self):
        exec_a, reg_a, target_a, precon_a = make_web_session("session-alpha")
        exec_b, reg_b, target_b, precon_b = make_web_session("session-beta")

        req_a = ActionRequest(
            session_id="session-alpha", reference=target_a.reference,
            action_type=ActionType.CLICK, observation_epoch=5,
        )
        req_b = ActionRequest(
            session_id="session-beta", reference=target_b.reference,
            action_type=ActionType.TYPE, observation_epoch=5,
            params={"text": "hello"},
        )

        receipt_a = run_async(exec_a.execute_action(
            request=req_a, target=target_a, precondition_result=precon_a,
        ))
        receipt_b = run_async(exec_b.execute_action(
            request=req_b, target=target_b, precondition_result=precon_b,
        ))

        # Both should dispatch independently
        self.assertEqual(receipt_a.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt_b.dispatch_status, DispatchStatus.DISPATCHED)

        # Session IDs must not cross
        self.assertEqual(receipt_a.session_id, "session-alpha")
        self.assertEqual(receipt_b.session_id, "session-beta")

        # Target IDs must not cross
        self.assertEqual(receipt_a.target_id, "btn-session-alpha")
        self.assertEqual(receipt_b.target_id, "btn-session-beta")

        # Action types distinct
        self.assertEqual(receipt_a.action_type, ActionType.CLICK)
        self.assertEqual(receipt_b.action_type, ActionType.TYPE)

    def test_epoch_independence(self):
        """Tests that epoch advances in one session don't affect another."""
        _, reg_a, _, _ = make_web_session("session-1")
        _, reg_b, _, _ = make_web_session("session-2")

        epoch_a_before = reg_a.current_epoch
        epoch_b_before = reg_b.current_epoch

        # Advance epoch only in session A
        reg_a.advance_epoch(reason="session-a-action")

        # Session B should be unaffected
        self.assertEqual(reg_a.current_epoch, epoch_a_before + 1)
        self.assertEqual(reg_b.current_epoch, epoch_b_before)


class TestConcurrentNativeSessionIsolation(unittest.TestCase):
    """Tests native session isolation."""

    def test_native_sessions_isolated(self):
        ns1 = MagicMock(spec=NativeSupervisor)
        ns1.is_window.return_value = True
        ns1.inspect_window.return_value = WindowForensicReport(
            hwnd=0x1111, pid=100, title="Win1", class_name="C1",
            bounds=Rect(0, 0, 800, 600), is_visible=True, is_enabled=True,
        )
        ns1.bring_to_foreground.return_value = None
        ns1.get_foreground_window.return_value = 0x1111

        ns2 = MagicMock(spec=NativeSupervisor)
        ns2.is_window.return_value = True
        ns2.inspect_window.return_value = WindowForensicReport(
            hwnd=0x2222, pid=200, title="Win2", class_name="C2",
            bounds=Rect(0, 0, 800, 600), is_visible=True, is_enabled=True,
        )
        ns2.bring_to_foreground.return_value = None
        ns2.get_foreground_window.return_value = 0x2222

        reg1 = ReferenceRegistry()
        for _ in range(3):
            reg1.advance_epoch(reason="s")
        reg1.register_ref(ref_id="n1e3", target_id="0x1111",
                         plane=TargetPlane.NATIVE_SHELL, role="window",
                         name="Win1", bounds=Rect(0, 0, 800, 600))

        reg2 = ReferenceRegistry()
        for _ in range(3):
            reg2.advance_epoch(reason="s")
        reg2.register_ref(ref_id="n2e3", target_id="0x2222",
                         plane=TargetPlane.NATIVE_SHELL, role="window",
                         name="Win2", bounds=Rect(0, 0, 800, 600))

        ni1 = NativeInputDispatcher(dry_run=True)
        ni2 = NativeInputDispatcher(dry_run=True)

        act1 = MagicMock()
        act2 = MagicMock()

        exec1 = NativeActionExecutor(ns1, ni1, act1, reg1)
        exec2 = NativeActionExecutor(ns2, ni2, act2, reg2)

        precon = ActionabilityResult(
            is_actionable=True, overall_status=OverallActionabilityStatus.READY,
            attachment=GateStatus.PASSED, visibility=GateStatus.PASSED,
            motion_stability=MotionStatus.STABLE, enabledness=GateStatus.PASSED,
            hit_test=GateStatus.PASSED, affordance_point=(400, 300), reasons=[],
        )

        t1 = ActionTarget(
            session_id="s1", target_id="0x1111", reference="n1e3",
            plane=TargetPlane.NATIVE_SHELL, epoch=reg1.current_epoch,
            affordance_point=(400, 300), native_hwnd=0x1111,
            bounds=Rect(0, 0, 800, 600),
        )
        t2 = ActionTarget(
            session_id="s2", target_id="0x2222", reference="n2e3",
            plane=TargetPlane.NATIVE_SHELL, epoch=reg2.current_epoch,
            affordance_point=(400, 300), native_hwnd=0x2222,
            bounds=Rect(0, 0, 800, 600),
        )

        r1 = ActionRequest(session_id="s1", reference="n1e3",
                          action_type=ActionType.CLICK, observation_epoch=3)
        r2 = ActionRequest(session_id="s2", reference="n2e3",
                          action_type=ActionType.CLICK, observation_epoch=3)

        receipt1 = run_async(exec1.execute_action(r1, t1, precon))
        receipt2 = run_async(exec2.execute_action(r2, t2, precon))

        self.assertEqual(receipt1.native_hwnd, 0x1111)
        self.assertEqual(receipt2.native_hwnd, 0x2222)
        self.assertEqual(receipt1.session_id, "s1")
        self.assertEqual(receipt2.session_id, "s2")


if __name__ == "__main__":
    unittest.main()
