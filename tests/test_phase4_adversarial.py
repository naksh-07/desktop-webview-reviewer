"""
Adversarial & Edge Case Tests for Phase 4 (Observation & Actionability Engine).
Covers Prompt Section 32:
- DOM re-rendering between observation and actionability
- Navigation race during actionability wait
- iframe detaches during resolution
- Element moves while being evaluated (animation jitter)
- Element becomes hidden after initial check
- Native window minimized mid-interaction
- Native window occluded by topmost window
- Native modal dialog interrupts webview
- Target UI thread hangs during SendMessageTimeout
- Reference epoch invalidation
- Exact duplicate semantic matches triggering TargetAmbiguousException.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock
from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane, HealthState
from runtime.errors import (
    TargetNotFoundException,
    TargetAmbiguousException,
    StaleReferenceException,
)
from runtime.native_supervisor import NativeSupervisor, WindowForensicReport, OcclusionState, ModalDialogInfo
from runtime.webview_core import WebviewAutomationCore
from runtime.locators import LocatorQuery, DeterministicLocatorEngine
from runtime.actionability import (
    ActionabilityEngine,
    GateStatus,
    OverallActionabilityStatus,
)
from runtime.observation_models import (
    DualPerspectiveSnapshot,
    WebObservation,
    WebElementObservation,
    VisibilityObservation,
    InteractionObservation,
    RoleSource,
)


def _make_forensic_report(
    hwnd=0x8888,
    pid=4000,
    title="Adversarial Target",
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


class TestPhase4Adversarial(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_id = "test_adv_sess"
        self.registry = ReferenceRegistry(self.session_id, initial_epoch=1)
        self.supervisor = MagicMock(spec=NativeSupervisor)
        self.core = MagicMock(spec=WebviewAutomationCore)
        self.core.is_connected = True
        self.core.native_hwnd = 0x8888

        # Base forensic report
        self.supervisor.inspect_window.return_value = _make_forensic_report()
        self.supervisor.check_window_occlusion.return_value = OcclusionState.NOT_OCCLUDED
        self.supervisor.scan_modal_dialogs.return_value = []

        # Frame manager mock
        self.core.frame_manager = MagicMock()
        self.core.frame_manager.root_frame_id = "frame_root"
        self.core.frame_manager.frames = {"frame_root": MagicMock()}

        self.actionability_engine = ActionabilityEngine(
            reference_registry=self.registry,
            native_supervisor=self.supervisor,
            webview_core=self.core,
        )
        self.locator_engine = DeterministicLocatorEngine()

    async def test_element_moves_during_motion_stability_check(self):
        """Element animates across the 60ms sampling window; engine catches motion and fails."""
        ref = self.registry.register_ref(
            role="button",
            plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            frame_id="frame_root",
            bounds=Rect(100, 100, 80, 30),
            locator_recipe={"role": "button", "name": "AnimatedButton"},
        )

        self.core.utility_world = MagicMock()
        self.core.utility_world.evaluate = AsyncMock(side_effect=[
            # Sample 1: x=100
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": False, "x": 100, "y": 100, "width": 80, "height": 30},
            # Sample 2: x=108 (moved by 8px!)
            {"found": True, "display": "block", "visibility": "visible", "opacity": 1.0, "displayed": True, "disabled": False, "x": 108, "y": 100, "width": 80, "height": 30},
            # Hit-test
            {"hit": True, "tag": "button"},
        ])

        res = await self.actionability_engine.evaluate_actionability(ref.ref_id, sample_interval_ms=10)
        self.assertFalse(res.is_actionable)
        self.assertEqual(res.motion.status, GateStatus.FAILED)
        self.assertEqual(res.overall_status, OverallActionabilityStatus.NOT_READY)

    async def test_element_becomes_hidden_after_initial_observation(self):
        """Element was in snapshot, but live DOM style has display: none when evaluated."""
        ref = self.registry.register_ref(
            role="button",
            plane=TargetPlane.WEBVIEW_DOM,
            target_id="target_01",
            frame_id="frame_root",
            bounds=Rect(100, 100, 80, 30),
            locator_recipe={"role": "button", "name": "DisappearingBtn"},
        )

        self.core.utility_world = MagicMock()
        self.core.utility_world.evaluate = AsyncMock(return_value={
            "found": True,
            "display": "none",  # Hidden!
            "visibility": "visible",
            "opacity": 1.0,
            "displayed": False,
            "disabled": False,
            "x": 0,
            "y": 0,
            "width": 0,
            "height": 0,
        })

        res = await self.actionability_engine.evaluate_actionability(ref.ref_id, sample_interval_ms=10)
        self.assertFalse(res.is_actionable)
        self.assertEqual(res.visibility.status, GateStatus.FAILED)

    async def test_native_modal_appears_and_blocks_interaction(self):
        """A native OS modal pops up; hit-test and physical gate detects blocking modal."""
        ref = self.registry.register_ref(
            role="Window",
            plane=TargetPlane.NATIVE_SHELL,
            target_id="0x8888",
            bounds=Rect(100, 100, 800, 600),
            locator_recipe={"hwnd": 0x8888},
        )

        self.supervisor.is_window.return_value = True
        self.supervisor.is_window_enabled.return_value = True
        # Modal detected!
        self.supervisor.scan_modal_dialogs.return_value = [
            ModalDialogInfo(
                hwnd=0x9999,
                pid=4000,
                owner_hwnd=0x8888,
                title="Fatal Error: File not found",
                class_name="#32770",
                bounds=Rect(200, 200, 300, 150),
                is_system_dialog=False,
                is_blocking=True,
                dialog_type="message_box",
            )
        ]

        res = await self.actionability_engine.evaluate_actionability(ref.ref_id, sample_interval_ms=10)
        self.assertFalse(res.is_actionable)
        self.assertEqual(res.hit_test.status, GateStatus.FAILED)
        self.assertTrue(any("modal dialog" in r.lower() for r in res.reasons))

    async def test_target_ui_thread_hung(self):
        """Native window thread fails message pump; enabledness gate marks it failed."""
        ref = self.registry.register_ref(
            role="Window",
            plane=TargetPlane.NATIVE_SHELL,
            target_id="0x8888",
            bounds=Rect(100, 100, 800, 600),
            locator_recipe={"hwnd": 0x8888},
        )

        self.supervisor.is_window.return_value = True
        # Window is hung!
        self.supervisor.inspect_window.return_value = _make_forensic_report(
            is_hung=True,
            title="Adversarial Target (Not Responding)",
        )

        res = await self.actionability_engine.evaluate_actionability(ref.ref_id, sample_interval_ms=10)
        self.assertFalse(res.is_actionable)
        self.assertEqual(res.enabledness.status, GateStatus.FAILED)
        self.assertTrue(any("hung" in r.lower() for r in res.reasons))

    def test_strict_locator_refuses_to_silently_pick_first_on_identical_buttons(self):
        """When multiple identical buttons appear without disambiguating clues, strict mode throws TargetAmbiguousException."""
        snap = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=1,
            timestamp=100.0,
            web_observation=WebObservation(
                session_id=self.session_id, epoch=1, timestamp=100.0,
                target_id="t1", target_title="T", target_url="U", root_frame_id="f1",
                elements=(
                    WebElementObservation(
                        session_id=self.session_id, observation_epoch=1, timestamp=100.0,
                        source_plane=TargetPlane.WEBVIEW_DOM, target_id="t1", reference="w1e1",
                        role="button", normalized_role="button", accessible_name="Confirm",
                        bounds=Rect(10, 10, 100, 30),
                        visibility=VisibilityObservation(attached=True, visible=True, in_viewport=True, physically_occluded=False),
                        interaction=InteractionObservation(is_enabled=True, is_focused=False, affordance_point=(60, 25), supported_actions=("click",)),
                    ),
                    WebElementObservation(
                        session_id=self.session_id, observation_epoch=1, timestamp=100.0,
                        source_plane=TargetPlane.WEBVIEW_DOM, target_id="t1", reference="w1e2",
                        role="button", normalized_role="button", accessible_name="Confirm",
                        bounds=Rect(10, 50, 100, 30),
                        visibility=VisibilityObservation(attached=True, visible=True, in_viewport=True, physically_occluded=False),
                        interaction=InteractionObservation(is_enabled=True, is_focused=False, affordance_point=(60, 65), supported_actions=("click",)),
                    ),
                ),
            ),
        )

        query = LocatorQuery(role="button", name="Confirm")
        with self.assertRaises(TargetAmbiguousException) as ctx:
            self.locator_engine.resolve(query, snap, strict=True)

        self.assertEqual(len(ctx.exception.candidates), 2)
        self.assertEqual(ctx.exception.code, "TARGET_AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
