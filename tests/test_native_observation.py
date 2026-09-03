"""
Unit tests for Native Semantic Observation Extractor (Phase 4).
Verifies extraction of native window forensics, modal scanning, reference registration,
and integration with the UIA bridge.
"""

import unittest
from unittest.mock import MagicMock, AsyncMock
from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane, HealthState
from runtime.native_supervisor import NativeSupervisor, WindowForensicReport, PhysicalVisibilityReport
from runtime.flaui_bridge import FlaUIBridge, UIAElementDTO
from runtime.native_observation import NativeObservationExtractor


def _make_forensic_report(
    hwnd=0x5678,
    pid=1234,
    title="StudyLab Deck Viewer",
    class_name="Qt650QWindowIcon",
    bounds=Rect(50, 50, 1000, 700),
    client_rect=Rect(50, 80, 1000, 670),
    is_visible=True,
    is_iconic=False,
    is_cloaked=False,
    is_hung=False,
    health_state=HealthState.HEALTHY,
    dpi_scaling=1.5,
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


class TestNativeObservation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_id = "test_sess_native"
        self.registry = ReferenceRegistry(self.session_id, initial_epoch=1)
        self.supervisor = MagicMock(spec=NativeSupervisor)
        self.flaui = MagicMock(spec=FlaUIBridge)

    async def test_native_observation_with_window_forensics(self):
        """Native window is accurately converted to NativeObservation with root ref."""
        hwnd = 0x5678
        forensic_report = _make_forensic_report(hwnd=hwnd)
        self.supervisor.inspect_window.return_value = forensic_report
        self.supervisor.scan_modal_dialogs.return_value = []
        self.flaui.is_connected = False

        extractor = NativeObservationExtractor(
            native_supervisor=self.supervisor,
            reference_registry=self.registry,
            flaui_bridge=self.flaui,
        )

        obs = await extractor.observe_native_window(self.session_id, hwnd)
        self.assertEqual(obs.hwnd, hwnd)
        self.assertEqual(obs.title, "StudyLab Deck Viewer")
        self.assertTrue(obs.is_visible)
        self.assertFalse(obs.is_minimized)
        self.assertEqual(len(obs.elements), 1)

        root_elem = obs.elements[0]
        self.assertEqual(root_elem.control_type, "Window")
        self.assertEqual(root_elem.reference, "n1e1")
        self.assertEqual(root_elem.geometry.dpr, 1.5)

        # Verified in registry
        ref = self.registry.resolve_ref("n1e1")
        self.assertEqual(ref.role, "Window")
        self.assertEqual(ref.plane, TargetPlane.NATIVE_SHELL)

    async def test_native_observation_with_child_controls(self):
        """Child controls from FlaUI are enriched with sequential n{epoch}e{n} refs."""
        hwnd = 0x5678
        forensic_report = _make_forensic_report(
            hwnd=hwnd,
            title="Main Application",
            class_name="MainWindow",
            bounds=Rect(0, 0, 800, 600),
            client_rect=Rect(0, 30, 800, 570),
            dpi_scaling=1.0,
        )
        self.supervisor.inspect_window.return_value = forensic_report
        self.supervisor.scan_modal_dialogs.return_value = []

        self.flaui.is_connected = True
        self.flaui.find_children = AsyncMock(return_value=[
            UIAElementDTO(
                automation_id="menu_file",
                name="File",
                class_name="MenuItem",
                control_type="MenuItem",
                bounds=Rect(10, 35, 40, 20),
                is_enabled=True,
                is_offscreen=False,
                supported_patterns=("Invoke",),
                depth=1,
            ),
            UIAElementDTO(
                automation_id="btn_ok",
                name="OK",
                class_name="Button",
                control_type="Button",
                bounds=Rect(100, 200, 80, 30),
                is_enabled=True,
                is_offscreen=False,
                supported_patterns=("Invoke",),
                depth=1,
            ),
        ])

        extractor = NativeObservationExtractor(
            native_supervisor=self.supervisor,
            reference_registry=self.registry,
            flaui_bridge=self.flaui,
        )

        obs = await extractor.observe_native_window(self.session_id, hwnd)
        self.assertEqual(len(obs.elements), 3)  # root + 2 children

        elem_refs = [e.reference for e in obs.elements]
        self.assertEqual(elem_refs, ["n1e1", "n1e2", "n1e3"])

        btn_elem = obs.elements[2]
        self.assertEqual(btn_elem.name, "OK")
        self.assertEqual(btn_elem.control_type, "Button")
        self.assertIn("click", btn_elem.interaction.supported_actions)


if __name__ == "__main__":
    unittest.main()
