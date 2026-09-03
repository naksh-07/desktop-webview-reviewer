"""
Phase 5 Test Suite — Web Action Executor.
Tests WebActionExecutor: click, double click, type, key press, scroll, focus,
hover, CDP input events, receipt generation, and fallback recording.
Uses MockCDPTransport for deterministic testing without a real browser.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from runtime.state import TargetPlane
from runtime.references import Rect, ElementRef, ReferenceRegistry
from runtime.cdp_transport import MockCDPTransport
from runtime.actionability import ActionabilityResult, GateStatus, MotionStatus, OverallActionabilityStatus
from runtime.action_models import (
    ActionRequest,
    ActionTarget,
    ActionReceipt,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionRiskLevel,
)
from runtime.web_action_executor import WebActionExecutor


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_mock_webview_core(is_connected=True):
    """Creates a minimal mock WebviewAutomationCore for unit testing."""
    wc = MagicMock()
    wc.is_connected = is_connected
    transport = MockCDPTransport()
    if is_connected:
        run_async(transport.connect())
    wc.transport = transport
    wc.native_hwnd = 0x123456

    # Frame manager
    fm = MagicMock()
    root_frame = MagicMock()
    root_frame.url = "http://localhost/test"
    fm.root_frame = root_frame
    fm.root_frame_id = "FRAME_ROOT"
    wc.frame_manager = fm

    # Target manager
    tm = MagicMock()
    tm.active_target_id = "target-main"
    wc.target_manager = tm

    # Utility world
    uw = MagicMock()
    uw.evaluate = AsyncMock(return_value={"focused": True, "tag": "INPUT"})
    wc.utility_world = uw

    # Native PID
    wc.native_pid = 1234

    return wc


def make_actionability_result(actionable=True, point=(200, 150)):
    """Creates a minimal ActionabilityResult for test use."""
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


def make_reference_registry(epoch=5):
    """Creates a ReferenceRegistry with a pre-registered web element."""
    reg = ReferenceRegistry()
    for _ in range(epoch):
        reg.advance_epoch(reason="setup")
    reg.register_ref(
        ref_id="w1e5",
        target_id="btn-submit",
        plane=TargetPlane.WEBVIEW_DOM,
        role="button",
        name="Submit",
        bounds=Rect(180, 130, 40, 40),
        frame_id="FRAME_ROOT",
        locator_recipe={"role": "button", "name": "Submit"},
    )
    return reg


def make_action_target(epoch=5):
    return ActionTarget(
        session_id="sess-001",
        target_id="btn-submit",
        reference="w1e5",
        plane=TargetPlane.WEBVIEW_DOM,
        epoch=epoch,
        affordance_point=(200, 150),
        coordinate_space="VIEWPORT_LOGICAL",
        native_hwnd=0x123456,
        cdp_target_id="target-main",
        frame_id="FRAME_ROOT",
        role="button",
        name="Submit",
        bounds=Rect(180, 130, 40, 40),
    )


class TestWebActionExecutorClick(unittest.TestCase):
    """Tests click, double click, right click dispatches."""

    def setUp(self):
        self.wc = make_mock_webview_core()
        self.reg = make_reference_registry()
        self.act_engine = MagicMock()
        self.act_engine.evaluate_actionability = AsyncMock(
            return_value=make_actionability_result()
        )
        self.executor = WebActionExecutor(
            webview_core=self.wc,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def test_click_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.CLICK, observation_epoch=5,
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertIsInstance(receipt, ActionReceipt)
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.CLICK)
        self.assertEqual(receipt.dispatch_method, DispatchMethod.CDP_INPUT)
        self.assertEqual(receipt.coordinates, (200, 150))

    def test_double_click_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.DOUBLE_CLICK, observation_epoch=5,
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
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.RIGHT_CLICK, observation_epoch=5,
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.RIGHT_CLICK)


class TestWebActionExecutorType(unittest.TestCase):
    """Tests text entry dispatch."""

    def setUp(self):
        self.wc = make_mock_webview_core()
        self.reg = make_reference_registry()
        self.act_engine = MagicMock()
        self.executor = WebActionExecutor(
            webview_core=self.wc,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def test_type_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.TYPE, observation_epoch=5,
            params={"text": "Hi", "clear_first": False},
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.TYPE)


class TestWebActionExecutorKeyPress(unittest.TestCase):
    """Tests key press dispatch."""

    def setUp(self):
        self.wc = make_mock_webview_core()
        self.reg = make_reference_registry()
        self.act_engine = MagicMock()
        self.executor = WebActionExecutor(
            webview_core=self.wc,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def test_key_press_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.KEY_PRESS, observation_epoch=5,
            params={"key": "Enter", "modifiers": []},
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.KEY_PRESS)

    def test_key_press_with_modifiers(self):
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.KEY_PRESS, observation_epoch=5,
            params={"key": "a", "modifiers": ["ctrl", "shift"]},
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)


class TestWebActionExecutorScroll(unittest.TestCase):
    """Tests scroll dispatch."""

    def setUp(self):
        self.wc = make_mock_webview_core()
        self.reg = make_reference_registry()
        self.act_engine = MagicMock()
        self.executor = WebActionExecutor(
            webview_core=self.wc,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def test_scroll_dispatched(self):
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.SCROLL, observation_epoch=5,
            params={"delta_x": 0, "delta_y": -120},
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.SCROLL)


class TestWebActionExecutorRejection(unittest.TestCase):
    """Tests dispatch rejection scenarios."""

    def setUp(self):
        self.wc = make_mock_webview_core()
        self.reg = make_reference_registry()
        self.act_engine = MagicMock()
        self.executor = WebActionExecutor(
            webview_core=self.wc,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def test_epoch_mismatch_rejected(self):
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.CLICK, observation_epoch=5,
        )
        # Wrong epoch in target
        target = make_action_target(epoch=99)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)
        self.assertIn("Epoch mismatch", receipt.precondition_summary)

    def test_disconnected_webview_fails(self):
        self.wc.is_connected = False
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.CLICK, observation_epoch=5,
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.FAILED)
        self.assertIn("disconnected", receipt.error)

    def test_actionability_gate_rejected(self):
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.CLICK, observation_epoch=5,
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(actionable=False),
        ))
        self.assertEqual(receipt.dispatch_status, DispatchStatus.REJECTED)
        self.assertIn("Precondition", receipt.error)


class TestWebActionExecutorReceipt(unittest.TestCase):
    """Tests receipt metadata and serialization."""

    def setUp(self):
        self.wc = make_mock_webview_core()
        self.reg = make_reference_registry()
        self.act_engine = MagicMock()
        self.executor = WebActionExecutor(
            webview_core=self.wc,
            actionability_engine=self.act_engine,
            reference_registry=self.reg,
        )

    def test_receipt_contains_session_info(self):
        request = ActionRequest(
            session_id="sess-001", reference="w1e5",
            action_type=ActionType.HOVER, observation_epoch=5,
        )
        target = make_action_target(epoch=self.reg.current_epoch)
        receipt = run_async(self.executor.execute_action(
            request=request, target=target,
            precondition_result=make_actionability_result(),
        ))
        self.assertEqual(receipt.session_id, "sess-001")
        self.assertEqual(receipt.reference, "w1e5")
        self.assertEqual(receipt.plane, TargetPlane.WEBVIEW_DOM)
        self.assertGreater(receipt.dispatch_timestamp, 0)
        self.assertGreater(receipt.duration_ms, 0)


if __name__ == "__main__":
    unittest.main()
