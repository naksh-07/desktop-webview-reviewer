"""
Unit tests for Composite Actionability Engine (Phase 4).
Verifies the 5 independent precondition gates:
Attachment, Computed Visibility, Motion Stability, Enabledness, and Hit-Testing/Physical Occlusion.
"""

import unittest
from unittest.mock import MagicMock, AsyncMock
from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane, HealthState
from runtime.native_supervisor import NativeSupervisor, WindowForensicReport, OcclusionState
from runtime.webview_core import WebviewAutomationCore
from runtime.actionability import (
    ActionabilityEngine,
    GateStatus,
    OverallActionabilityStatus,
)


def _make_forensic_report(
    hwnd=0x7000,
    pid=3000,
    title="App Window",
    class_name="QtWindow",
    bounds=Rect(100, 100, 800, 600),
    client_rect=Rect(100, 130, 800, 570),
    is_visible=True,
    is_iconic=False,
    is_cloaked=False,
    is_hung=False,
    health_state=HealthState.HEALTHY,
    dpi_scaling=1.0,
):
    return WindowForensicReport(
        hwnd=hwnd,
        pid=pid,
        title=title,
        class_name=class_name,
        bounds=bounds,
        raw_window_rect=bounds,
        client_rect=client_rect,
        client_origin_screen=(client_rect.x, client_rect.y),
        is_valid_window=True,
        is_visible=is_visible,
        is_iconic=is_iconic,
        is_cloaked=is_cloaked,
        is_hung=is_hung,
        health_state=health_state,
        dpi_scaling=dpi_scaling,
        shadow_margins={"left": 0, "top": 0, "right": 0, "bottom": 0},
    )


class TestActionability(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_id = "test_act_sess"
        self.registry = ReferenceRegistry(self.session_id, initial_epoch=1)
        self.supervisor = MagicMock(spec=NativeSupervisor)
        self.core = MagicMock(spec=WebviewAutomationCore)
        self.core.is_connected = True
        self.core.native_hwnd = 0x7000

        # Frame manager mock
        self.core.frame_manager = MagicMock()
        self.core.frame_manager.root_frame_id = "frame_root"
        self.core.frame_manager.frames = {"frame_root": MagicMock()}

        # Supervisor inspect mock
        self.supervisor.inspect_window.return_value = _make_forensic_report()
        self.supervisor.check_window_occlusion.return_value = OcclusionState.NOT_OCCLUDED

        self.engine = ActionabilityEngine(
            reference_registry=self.registry,
            native_supervisor=self.supervisor,
            webview_core=self.core,
        )

    async def test_all_five_gates_pass_ready(self):
        """When an element meets all 5 preconditions, status is READY and affordance point is valid."""
        # Register ref
        ref = self.registry.register_ref(
            role="button",
            plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            frame_id="frame_root",
            bounds=Rect(50, 50, 100, 40),
            locator_recipe={"role": "button", "name": "Continue"},
        )

        # Utility world query mock
        # Return state with same rect for sample 1 & sample 2 (stable)
        self.core.utility_world = MagicMock()
        self.core.utility_world.evaluate = AsyncMock(side_effect=[
            # Sample 1: geometry
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": False, "x": 50, "y": 50, "width": 100, "height": 40},
            # Sample 2: geometry after delay (dx=0, dy=0)
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": False, "x": 50, "y": 50, "width": 100, "height": 40},
            # Hit-test at affordance center (100, 70)
            {"hit": True, "tag": "button", "id": "btn_cont"},
        ])

        result = await self.engine.evaluate_actionability(ref.ref_id, sample_interval_ms=10)
        self.assertEqual(result.overall_status, OverallActionabilityStatus.READY)
        self.assertTrue(result.is_actionable)
        self.assertEqual(result.attachment.status, GateStatus.PASSED)
        self.assertEqual(result.visibility.status, GateStatus.PASSED)
        self.assertEqual(result.motion.status, GateStatus.PASSED)
        self.assertEqual(result.enabledness.status, GateStatus.PASSED)
        self.assertEqual(result.hit_test.status, GateStatus.PASSED)
        self.assertEqual(result.affordance_point, (100, 70))
        self.assertEqual(result.affordance_point_type, "VIEWPORT_LOGICAL")

    async def test_motion_instability_fails_gate(self):
        """When an element moves > 1px between samples, motion stability gate fails."""
        ref = self.registry.register_ref(
            role="button",
            plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            frame_id="frame_root",
            bounds=Rect(50, 50, 100, 40),
            locator_recipe={"role": "button", "name": "SlidingButton"},
        )

        self.core.utility_world = MagicMock()
        self.core.utility_world.evaluate = AsyncMock(side_effect=[
            # Sample 1: at x=50
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": False, "x": 50, "y": 50, "width": 100, "height": 40},
            # Sample 2: at x=75 (moved by 25px > 1px!)
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": False, "x": 75, "y": 50, "width": 100, "height": 40},
            # Hit-test
            {"hit": True, "tag": "button"},
        ])

        result = await self.engine.evaluate_actionability(ref.ref_id, sample_interval_ms=10)
        self.assertEqual(result.overall_status, OverallActionabilityStatus.NOT_READY)
        self.assertFalse(result.is_actionable)
        self.assertEqual(result.motion.status, GateStatus.FAILED)
        self.assertTrue(any("animating or moving" in r for r in result.reasons))

    async def test_disabledness_fails_gate(self):
        """When element is disabled, enabledness gate fails."""
        ref = self.registry.register_ref(
            role="button",
            plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            frame_id="frame_root",
            bounds=Rect(50, 50, 100, 40),
            locator_recipe={"role": "button", "name": "DisabledBtn"},
        )

        self.core.utility_world = MagicMock()
        self.core.utility_world.evaluate = AsyncMock(side_effect=[
            # Sample 1: disabled
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": True, "x": 50, "y": 50, "width": 100, "height": 40},
            # Sample 2: disabled
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": True, "x": 50, "y": 50, "width": 100, "height": 40},
            # Hit-test
            {"hit": True, "tag": "button"},
        ])

        result = await self.engine.evaluate_actionability(ref.ref_id, sample_interval_ms=10)
        self.assertEqual(result.overall_status, OverallActionabilityStatus.NOT_READY)
        self.assertFalse(result.is_actionable)
        self.assertEqual(result.enabledness.status, GateStatus.FAILED)

    async def test_stale_reference_returns_stale_status(self):
        """When reference belongs to older epoch, evaluation returns STALE immediately."""
        ref = self.registry.register_ref(
            role="button",
            plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            frame_id="frame_root",
            bounds=Rect(50, 50, 100, 40),
        )

        # Advance epoch
        self.registry.advance_epoch()

        result = await self.engine.evaluate_actionability(ref.ref_id)
        self.assertEqual(result.overall_status, OverallActionabilityStatus.STALE)
        self.assertFalse(result.is_actionable)
        self.assertEqual(result.attachment.status, GateStatus.STALE)

    async def test_physical_minimized_window_blocks_web_actionability(self):
        """Physical Reality Primacy: Even if DOM says visible, native minimized window blocks actionability."""
        ref = self.registry.register_ref(
            role="button",
            plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            frame_id="frame_root",
            bounds=Rect(50, 50, 100, 40),
            locator_recipe={"role": "button", "name": "Btn"},
        )

        # Native window is minimized!
        self.supervisor.inspect_window.return_value = _make_forensic_report(
            is_iconic=True,
            is_visible=False,
            bounds=Rect(0, 0, 0, 0),
            client_rect=Rect(0, 0, 0, 0),
        )

        self.core.utility_world = MagicMock()
        self.core.utility_world.evaluate = AsyncMock(side_effect=[
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": False, "x": 50, "y": 50, "width": 100, "height": 40},
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": False, "x": 50, "y": 50, "width": 100, "height": 40},
            {"hit": True, "tag": "button"},
        ])

        result = await self.engine.evaluate_actionability(ref.ref_id, sample_interval_ms=10)
        self.assertEqual(result.overall_status, OverallActionabilityStatus.NOT_READY)
        self.assertFalse(result.is_actionable)
        self.assertEqual(result.visibility.status, GateStatus.FAILED)
        self.assertEqual(result.physical_visibility, "MINIMIZED")


if __name__ == "__main__":
    unittest.main()
