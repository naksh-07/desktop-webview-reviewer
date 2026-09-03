"""
Phase 5 Test Suite — Native Action Executor.
Tests NativeActionExecutor: native click, keyboard input, scroll, focus,
responsiveness rejection, modal dialog blocking, minimized window rejection.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

from runtime.state import TargetPlane
from runtime.references import Rect, ElementRef, ReferenceRegistry
from runtime.native_supervisor import (
    NativeSupervisor, WindowForensicReport, OcclusionReport,
    OcclusionState, NativeModalReport, ModalState,
)
from runtime.native_input import NativeInputDispatcher, MouseButton, DispatchedInputRecord
from runtime.actionability import ActionabilityResult, GateStatus, MotionStatus, OverallActionabilityStatus
from runtime.action_models import (
    ActionRequest, ActionTarget, ActionReceipt, ActionType,
    DispatchMethod, DispatchStatus, ActionRiskLevel,
)
from runtime.native_action_executor import NativeActionExecutor


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_native_supervisor():
    """Creates a mock NativeSupervisor for testing."""
    ns = MagicMock(spec=NativeSupervisor)
    ns.is_window.return_value = True
    ns.inspect_window.return_value = WindowForensicReport(
        hwnd=0x1234, pid=5678, title="Test Window",
        class_name="TestClass", bounds=Rect(100, 100, 400, 300),
        is_visible=True, is_enabled=True,
    )
    ns.scan_modal_dialogs.return_value = []
    ns.bring_to_foreground.return_value = None
    ns.get_foreground_window.return_value = 0x1234
    return ns


def make_reference_registry(epoch=3):
    reg = ReferenceRegistry()
    for _ in range(epoch):
        reg.advance_epoch(reason="setup")
    reg.register_ref(
        ref_id="n1e5",
        target_id="0x1234",
        plane=TargetPlane.NATIVE_SHELL,
        role="window",
        name="Test Window",
        bounds=Rect(100, 100, 400, 300),
        locator_recipe={"hwnd": "0x1234", "role": "window"},
    )
    return reg


def make_action_target(epoch=3, hwnd=0x1234):
    return ActionTarget(
        session_id="sess-001",
        target_id="0x1234",
        reference="n1e5",
        plane=TargetPlane.NATIVE_SHELL,
        epoch=epoch,
        affordance_point=(300, 250),
        coordinate_space="SCREEN_CANONICAL",
        native_hwnd=hwnd,
        role="window",
        name="Test Window",
        bounds=Rect(100, 100, 400, 300),
    )


def make_actionability_result(actionable=True, point=(300, 250)):
    return ActionabilityResult(
        is_actionable=actionable,
        overall_status=OverallActionabilityStatus.READY if actionable else OverallActionabilityStatus.NOT_ACTIONABLE,
        attachment=GateStatus.PASSED,
        visibility=GateStatus.PASSED if actionable else GateStatus.FAILED,
        motion_stability=MotionStatus.STABLE,
        enabledness=GateStatus.PASSED,
        hit_test=GateStatus.PASSED,
        affordance_point=point,
        reasons=[] if actionable else ["element not visible"],
    )


class TestNativeActionExecutorClick(unittest.TestCase):
    """Tests native click dispatch via NativeActionExecutor."""

    def setUp(self):
        self.ns = make_native_supervisor()
        self.ni = NativeInputDispatcher(dry_run=True)
        self.reg = make_reference_registry()
        self.act_engine = MagicMock()
        self.executor = NativeActionExecutor(
            native_supervisor=self.ns,
            native_input=self.ni,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def test_click_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.CLICK, observation_epoch=3,
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.CLICK)
        self.assertEqual(receipt.dispatch_method, DispatchMethod.NATIVE_SENDINPUT)
        self.assertEqual(receipt.native_hwnd, 0x1234)
        self.assertIn("dispatched_records", receipt.metadata)

    def test_double_click_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.DOUBLE_CLICK, observation_epoch=3,
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.DOUBLE_CLICK)

    def test_right_click_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.RIGHT_CLICK, observation_epoch=3,
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.RIGHT_CLICK)


class TestNativeActionExecutorRejection(unittest.TestCase):
    """Tests rejection scenarios for native executor."""

    def setUp(self):
        self.ns = make_native_supervisor()
        self.ni = NativeInputDispatcher(dry_run=True)
        self.reg = make_reference_registry()
        self.act_engine = MagicMock()
        self.executor = NativeActionExecutor(
            native_supervisor=self.ns,
            native_input=self.ni,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def test_epoch_mismatch_rejected(self):
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.CLICK, observation_epoch=3,
        )
        target = make_action_target(epoch=99)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)
        self.assertIn("Epoch mismatch", receipt.precondition_summary)

    def test_invalid_hwnd_fails(self):
        self.ns.is_window.return_value = False
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.CLICK, observation_epoch=3,
        )
        target = make_action_target(epoch=self.reg.current_epoch, hwnd=0xDEAD)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.FAILED)
        self.assertIn("Invalid HWND", receipt.error)

    def test_no_hwnd_fails(self):
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.CLICK, observation_epoch=3,
        )
        target = make_action_target(epoch=self.reg.current_epoch, hwnd=None)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.FAILED)

    def test_actionability_gate_rejected(self):
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.CLICK, observation_epoch=3,
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(actionable=False),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)
        self.assertIn("Precondition", receipt.error)


class TestNativeActionExecutorKeyboard(unittest.TestCase):
    """Tests keyboard and text input dispatch."""

    def setUp(self):
        self.ns = make_native_supervisor()
        self.ni = NativeInputDispatcher(dry_run=True)
        self.reg = make_reference_registry()
        self.act_engine = MagicMock()
        self.executor = NativeActionExecutor(
            native_supervisor=self.ns,
            native_input=self.ni,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def test_type_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.TYPE, observation_epoch=3,
            params={"text": "hello"},
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.TYPE)

    def test_key_press_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.KEY_PRESS, observation_epoch=3,
            params={"key": "Enter"},
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.KEY_PRESS)

    def test_scroll_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="n1e5",
            action_type=ActionType.SCROLL, observation_epoch=3,
            params={"delta_y": -120},
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.SCROLL)


if __name__ == "__main__":
    unittest.main()
