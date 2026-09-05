"""
Phase 12: Human-Equivalent Hands, Interaction Hierarchy, and Action Lifecycle Tests.
Verifies:
- Expanded action dispatching (KEYBOARD_SHORTCUT, DRAG_AND_DROP, SELECT, DIALOG_INTERACTION)
- Native and Web Action Executors
- The strict 5-stage Action Lifecycle Milestones:
  ACTION_RECEIVED -> ACTION_DISPATCHED -> ACTION_COMPLETED -> STATE_CHANGED -> EXPECTED_STATE_VERIFIED
- Independence of dispatch from verification (input delivered != application changed != pass)
- Visual evidence integration (before/after/failure screenshots tied to trace)
"""

from __future__ import annotations
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import time

from runtime.references import Rect, ElementRef, ReferenceRegistry
from runtime.state import TargetPlane
from runtime.action_models import (
    ActionRequest,
    ActionTarget,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
    ActionLifecycleStage,
)
from runtime.actionability import ActionabilityResult
from runtime.trace_models import DesktopTraceEventType
from runtime.trace_engine import DesktopTraceEngine
from runtime.native_action_executor import NativeActionExecutor
from runtime.web_action_executor import WebActionExecutor
from runtime.action_engine import ActionExecutionEngine
from runtime.settlement import SettlementResult, SettlementType
from runtime.observation_models import DualPerspectiveSnapshot, NativeObservation, WebObservation
from runtime.observation_diff import ObservationDiffResult, DiffItem
from runtime.native_input import DispatchedInputRecord
from runtime.evidence_store import EvidenceStore


class TestPhase12HandsAndInteraction(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_id = "test_hands_session"
        self.ref_registry = ReferenceRegistry(session_id=self.session_id)
        self.trace_engine = DesktopTraceEngine(session_id=self.session_id)

    async def test_native_executor_keyboard_shortcut(self):
        """NativeActionExecutor handles KEYBOARD_SHORTCUT via NativeInputDispatcher."""
        mock_supervisor = MagicMock()
        mock_supervisor.is_window.return_value = True
        mock_supervisor.get_foreground_window.return_value = 0x1234
        mock_input = MagicMock()
        mock_input.press_key = AsyncMock(return_value=[MagicMock(to_dict=lambda: {})])
        mock_actionability = MagicMock()

        executor = NativeActionExecutor(
            native_supervisor=mock_supervisor,
            native_input=mock_input,
            actionability_engine=mock_actionability,
            reference_registry=self.ref_registry,
        )

        req = ActionRequest(
            session_id=self.session_id,
            action_id="act_ctrl_s",
            reference="n1e1",
            action_type=ActionType.KEYBOARD_SHORTCUT,
            observation_epoch=1,
            params={"modifiers": ["Control"], "key": "s"},
        )
        target = ActionTarget(
            session_id=self.session_id,
            reference="n1e1",
            target_id="btn1",
            plane=TargetPlane.NATIVE,
            epoch=1,
            role="Edit",
            name="Text Editor",
            native_hwnd=0x1234,
            affordance_point=(200, 200),
        )
        precond = ActionabilityResult(is_actionable=True, reasons=("Ready",))

        receipt = await executor.execute_action(req, target, precond)

        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.KEYBOARD_SHORTCUT)
        mock_input.press_key.assert_called_once_with("s", ["Control"])

    async def test_native_executor_drag_and_drop(self):
        """NativeActionExecutor handles DRAG_AND_DROP with linear interpolation coordinates."""
        mock_supervisor = MagicMock()
        mock_supervisor.is_window.return_value = True
        mock_input = MagicMock()
        mock_input.drag_and_drop = AsyncMock(return_value=[MagicMock(to_dict=lambda: {})])
        mock_actionability = MagicMock()

        executor = NativeActionExecutor(
            native_supervisor=mock_supervisor,
            native_input=mock_input,
            actionability_engine=mock_actionability,
            reference_registry=self.ref_registry,
        )

        req = ActionRequest(
            session_id=self.session_id,
            action_id="act_drag_drop",
            reference="n1e1",
            action_type=ActionType.DRAG_AND_DROP,
            observation_epoch=1,
            params={"from_x": 100, "from_y": 100, "to_x": 300, "to_y": 400},
        )
        target = ActionTarget(
            session_id=self.session_id,
            reference="n1e1",
            target_id="canvas",
            plane=TargetPlane.NATIVE,
            epoch=1,
            role="Pane",
            name="Drawing Area",
            native_hwnd=0x1234,
            affordance_point=(100, 100),
        )
        precond = ActionabilityResult(is_actionable=True, reasons=("Ready",))

        receipt = await executor.execute_action(req, target, precond)

        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        mock_input.drag_and_drop.assert_called_once_with(100, 100, 300, 400, steps=10)

    async def test_web_executor_keyboard_shortcut(self):
        """WebActionExecutor dispatches keyboard shortcuts via CDP or JS fallback."""
        mock_webview = MagicMock()
        mock_webview.transport.send_command = AsyncMock()
        mock_actionability = MagicMock()

        executor = WebActionExecutor(
            webview_core=mock_webview,
            actionability_engine=mock_actionability,
            reference_registry=self.ref_registry,
        )

        req = ActionRequest(
            session_id=self.session_id,
            action_id="act_web_shortcut",
            reference="w1e1",
            action_type=ActionType.KEYBOARD_SHORTCUT,
            observation_epoch=1,
            params={"modifiers": ["Control"], "key": "a"},
        )
        target = ActionTarget(
            session_id=self.session_id,
            reference="w1e1",
            target_id="input_field",
            plane=TargetPlane.WEBVIEW,
            epoch=1,
            role="textbox",
            name="Search",
            affordance_point=(150, 150),
        )
        precond = ActionabilityResult(is_actionable=True, reasons=("Ready",))

        receipt = await executor.execute_action(req, target, precond)
        self.assertEqual(receipt.dispatch_status, DispatchStatus.DISPATCHED)
        self.assertEqual(receipt.action_type, ActionType.KEYBOARD_SHORTCUT)

    async def test_action_transaction_five_milestones_and_trace(self):
        """
        ActionExecutionEngine enforces the 5 distinct milestones:
        ACTION_RECEIVED -> ACTION_DISPATCHED -> ACTION_COMPLETED -> STATE_CHANGED -> EXPECTED_STATE_VERIFIED
        and records them in the DesktopTraceEngine.
        """
        # Set up a target reference in registry
        ref = self.ref_registry.register_ref(
            plane=TargetPlane.NATIVE,
            role="Button",
            name="Save Button",
            target_id=hex(0x5678),
            locator_recipe={"hwnd": 0x5678},
            bounds=Rect(100, 100, 80, 30),
        )

        mock_supervisor = MagicMock()
        mock_supervisor.is_window.return_value = True
        mock_supervisor.capture_window_screenshot.return_value = b"\x89PNG\r\n\x1a\nfake_image"
        mock_supervisor.inspect_window.return_value = MagicMock(pid=9999, bounds=Rect(0, 0, 800, 600))

        mock_input = MagicMock()
        mock_input.click = AsyncMock(
            return_value=[DispatchedInputRecord(input_type="MOUSE_CLICK", coordinates=(140, 115))]
        )
        mock_actionability = MagicMock()
        mock_actionability.evaluate_actionability = AsyncMock(
            return_value=ActionabilityResult(is_actionable=True, reasons=("Ready for input",))
        )

        mock_settlement = MagicMock()
        mock_settlement.settle = AsyncMock(
            return_value=SettlementResult(
                settled=True,
                settlement_type=SettlementType.STABLE,
                elapsed_ms=25.0,
                iterations=1,
            )
        )

        mock_observation = MagicMock()
        mock_observation.last_snapshot = None
        mock_observation.observe = AsyncMock(
            return_value=DualPerspectiveSnapshot(
                session_id=self.session_id,
                epoch=2,
                timestamp=time.time(),
                native_observation=NativeObservation(
                    session_id=self.session_id,
                    epoch=2,
                    timestamp=time.time(),
                    hwnd=0x5678,
                    pid=9999,
                    title="Main Window",
                    class_name="MainClass",
                    bounds=Rect(0, 0, 800, 600),
                    client_bounds=Rect(0, 0, 800, 600),
                    is_visible=True,
                    is_minimized=False,
                    is_cloaked=False,
                    is_responsive=True,
                ),
            )
        )
        mock_observation.compute_diff.return_value = ObservationDiffResult(
            from_epoch=1,
            to_epoch=2,
            modified=(
                DiffItem(
                    kind="MODIFIED",
                    reference=ref.ref_id,
                    role="Button",
                    name="Save Button",
                    changes=("clicked",),
                ),
            ),
        )

        evidence_store = EvidenceStore()

        engine = ActionExecutionEngine(
            session_id=self.session_id,
            reference_registry=self.ref_registry,
            native_supervisor=mock_supervisor,
            native_input=mock_input,
            actionability_engine=mock_actionability,
            settlement_engine=mock_settlement,
            observation_engine=mock_observation,
            evidence_store=evidence_store,
            trace_engine=self.trace_engine,
        )

        request = ActionRequest(
            session_id=self.session_id,
            action_id="act_save_tx",
            reference=ref.ref_id,
            action_type=ActionType.CLICK,
            observation_epoch=1,
        )

        outcome = await engine.execute(request, verify=True)

        # 1. Verification of distinct outcome and state change
        self.assertEqual(
            outcome.outcome_status,
            ActionOutcomeStatus.DISPATCHED,
            msg=f"Outcome status: {outcome.outcome_status}, error: {outcome.receipt.error if outcome.receipt else 'No receipt'}, details: {outcome.details}",
        )
        self.assertEqual(outcome.state_change, StateChangeClassification.STATE_CHANGED)
        self.assertIsNotNone(outcome.verdict)

        # 2. Check visual evidence screenshots captured
        self.assertIn("before_action", outcome.details["screenshots"])
        self.assertIn("after_action", outcome.details["screenshots"])

        # 3. Check DesktopTraceEngine events emitted
        events = self.trace_engine.timeline.events
        event_types = [e.event_type for e in events]

        # Milestone 1: ACTION_REQUESTED (ACTION_RECEIVED)
        self.assertIn(DesktopTraceEventType.ACTION_REQUESTED, event_types)
        # Target Resolution
        self.assertIn(DesktopTraceEventType.TARGET_RESOLVED, event_types)
        # Before screenshot
        self.assertIn(DesktopTraceEventType.SCREENSHOT, event_types)
        # Milestone 2: ACTION_DISPATCHED
        self.assertIn(DesktopTraceEventType.ACTION_DISPATCHED, event_types)
        # Milestone 3: ACTION_SETTLED (ACTION_COMPLETED)
        self.assertIn(DesktopTraceEventType.ACTION_SETTLED, event_types)
        # Milestone 4: OBSERVATION (STATE_CHANGED)
        self.assertIn(DesktopTraceEventType.OBSERVATION, event_types)
        # Milestone 5: ASSERTION (EXPECTED_STATE_VERIFIED)
        self.assertIn(DesktopTraceEventType.ASSERTION, event_types)

        # Verify causal correlation
        for ev in events:
            self.assertEqual(ev.correlation.session_id, self.session_id)
            if ev.correlation.action_id:
                self.assertEqual(ev.correlation.action_id, "act_save_tx")


if __name__ == "__main__":
    unittest.main()
