"""
Unit tests for RealityInspectorSpecialist (Phase 15 - Prompt P4).
"""
import asyncio
import unittest
from unittest.mock import MagicMock
from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import SpecialistDelegation, DelegationScope, SpecialistResultStatus
from runtime.specialists.reality_inspector import RealityInspectorSpecialist
from runtime.reality_models import TruthHierarchyLevel


class TestRealityInspectorSpecialist(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.session_id = "test-session-reality"
        self.mock_session.current_epoch = 1
        self.mock_session.trace_recorder = MagicMock()
        self.mock_session.trace_engine = None

        # Mock target window / hwnd
        self.mock_session.target_window = None
        self.mock_session.target_hwnd = 0x12345

        # Mock native supervisor
        self.mock_supervisor = MagicMock()
        self.mock_session.native_supervisor = self.mock_supervisor

        # Mock window inspection
        self.mock_insp = MagicMock()
        self.mock_insp.title = "App Window"
        self.mock_insp.pid = 9999
        self.mock_insp.bounds = MagicMock()
        self.mock_insp.bounds.x = 100
        self.mock_insp.bounds.y = 100
        self.mock_insp.bounds.width = 800
        self.mock_insp.bounds.height = 600
        self.mock_insp.is_visible = True
        self.mock_insp.is_cloaked = False
        self.mock_insp.is_iconic = False
        self.mock_supervisor.inspect_window.return_value = self.mock_insp
        self.mock_supervisor.get_foreground_window.return_value = 0x12345

        # Mock monitor topology
        mock_monitor = MagicMock()
        mock_monitor.to_dict.return_value = {"id": "MONITOR_1", "rect": [0, 0, 1920, 1080]}
        self.mock_supervisor.get_monitor_topology.return_value = [mock_monitor]

        # Mock screenshot
        mock_shot = MagicMock()
        mock_shot.width = 800
        mock_shot.height = 600
        self.mock_supervisor.capture_window_screenshot.return_value = mock_shot

    def test_physical_visibility_success(self):
        """Reality Inspector succeeds when window is visible, non-cloaked, and in foreground."""
        delegation = SpecialistDelegation(
            role=SpecialistRole.REALITY_INSPECTOR,
            task="Verify physical visibility of primary window",
            scope=DelegationScope(session_id="test-session-reality"),
            permitted_tools={"desktop_inspect", "desktop_screenshot"},
            timeout_sec=5.0
        )

        specialist = RealityInspectorSpecialist(delegation=delegation, session_state=self.mock_session)
        result = asyncio.run(specialist.run())

        self.assertEqual(result.status, SpecialistResultStatus.SUCCESS)
        self.assertTrue(result.observations["physical_visibility"])
        self.assertFalse(result.observations["is_cloaked"])
        self.assertFalse(result.observations["is_minimized"])
        self.assertTrue(result.observations["is_foreground"])
        self.assertEqual(result.observations["truth_hierarchy_level"], TruthHierarchyLevel.PHYSICAL_DESKTOP.value)
        self.assertIn("screenshot_0x12345", result.evidence_refs)

    def test_cloaked_window_contradiction_detected(self):
        """Reality Inspector detects DWM cloaking and marks physical visibility as false despite DOM claim."""
        self.mock_insp.is_cloaked = True
        # Mock DOM observation claiming elements exist
        mock_obs = MagicMock()
        mock_node = MagicMock()
        mock_obs.nodes = [mock_node]
        mock_obs_engine = MagicMock()
        mock_obs_engine.last_observation = mock_obs
        self.mock_session.observation_engine = mock_obs_engine

        delegation = SpecialistDelegation(
            role=SpecialistRole.REALITY_INSPECTOR,
            task="Verify physical visibility",
            scope=DelegationScope(session_id="test-session-reality"),
            permitted_tools={"desktop_inspect"},
            timeout_sec=5.0
        )

        specialist = RealityInspectorSpecialist(delegation=delegation, session_state=self.mock_session)
        result = asyncio.run(specialist.run())

        self.assertEqual(result.status, SpecialistResultStatus.DEGRADED)
        self.assertFalse(result.observations["physical_visibility"])
        self.assertTrue(result.observations["is_cloaked"])
        self.assertTrue(any("CLOAKED" in c for c in result.observations["contradictions"]))

    def test_forbidden_mutation_tool_rejected(self):
        """Reality Inspector must reject any synthetic input or state mutation tools during validation."""
        delegation = SpecialistDelegation(
            role=SpecialistRole.REALITY_INSPECTOR,
            task="Attempt to click something while inspecting",
            scope=DelegationScope(session_id="test-session-reality"),
            permitted_tools={"desktop_click"},  # Forbidden by contract!
            timeout_sec=5.0
        )

        specialist = RealityInspectorSpecialist(delegation=delegation, session_state=self.mock_session)
        result = asyncio.run(specialist.run())

        self.assertEqual(result.status, SpecialistResultStatus.REJECTED)
        self.assertTrue(any("Forbidden tool" in err for err in result.errors))


if __name__ == "__main__":
    unittest.main()
