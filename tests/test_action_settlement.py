"""
Phase 5 Test Suite — Bounded Settlement Engine.
Tests for: stable DOM, changing DOM, navigation settle, modal appearance,
settlement timeout, and forensic SettlementResult reporting.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from runtime.references import Rect, ElementRef, ReferenceRegistry
from runtime.state import TargetPlane
from runtime.native_supervisor import (
    NativeSupervisor, WindowForensicReport, ModalDialogInfo,
)
from runtime.settlement import (
    SettlementEngine, SettlementType, SettlementResult,
)


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestSettlementResult(unittest.TestCase):
    """Tests SettlementResult construction and serialization."""

    def test_stable_result(self):
        r = SettlementResult(
            settled=True,
            settlement_type=SettlementType.STABLE,
            elapsed_ms=50.0,
            iterations=3,
            details={"rect": {"x": 100, "y": 100}},
        )
        self.assertTrue(r.settled)
        self.assertEqual(r.settlement_type, SettlementType.STABLE)
        d = r.to_dict()
        self.assertEqual(d["settlement_type"], "STABLE")
        self.assertTrue(d["settled"])

    def test_timeout_result(self):
        r = SettlementResult(
            settled=False,
            settlement_type=SettlementType.TIMEOUT,
            elapsed_ms=1500.0,
            iterations=38,
            details={"timeout_reached": True},
        )
        self.assertFalse(r.settled)
        self.assertEqual(r.settlement_type, SettlementType.TIMEOUT)

    def test_navigation_result(self):
        r = SettlementResult(
            settled=True,
            settlement_type=SettlementType.NAVIGATED,
            elapsed_ms=120.0,
            iterations=3,
            details={"initial_url": "http://a.com", "navigated_url": "http://b.com"},
        )
        self.assertTrue(r.settled)
        self.assertEqual(r.settlement_type, SettlementType.NAVIGATED)


class TestSettlementEngineModalDetection(unittest.TestCase):
    """Tests that SettlementEngine detects native modal dialogs immediately."""

    def test_modal_detected_immediately(self):
        ns = MagicMock(spec=NativeSupervisor)
        modal = MagicMock()
        modal.to_dict.return_value = {
            "class": "#32770", "title": "Save As", "hwnd": 0xAAAA,
        }
        ns.scan_modal_dialogs.return_value = [modal]

        engine = SettlementEngine(
            native_supervisor=ns,
            webview_core=None,
            default_timeout_ms=1000,
            poll_interval_ms=40,
        )

        result = run_async(engine.settle(
            target_pid=1234,
            timeout_ms=500,
        ))

        self.assertTrue(result.settled)
        self.assertEqual(result.settlement_type, SettlementType.MODAL_APPEARED)
        self.assertIn("modal_dialogs", result.details)

    def test_no_modal_no_ref_times_out(self):
        ns = MagicMock(spec=NativeSupervisor)
        ns.scan_modal_dialogs.return_value = []
        ns.is_window.return_value = False

        engine = SettlementEngine(
            native_supervisor=ns,
            webview_core=None,
            default_timeout_ms=100,
            poll_interval_ms=20,
        )

        result = run_async(engine.settle(
            target_pid=1234,
            timeout_ms=100,
        ))

        self.assertEqual(result.settlement_type, SettlementType.TIMEOUT)
        self.assertIn("timeout_reached", result.details)


class TestSettlementEngineNativeStability(unittest.TestCase):
    """Tests native window settlement via bounds stability check."""

    def test_native_stable_window(self):
        ns = MagicMock(spec=NativeSupervisor)
        ns.scan_modal_dialogs.return_value = []
        ns.is_window.return_value = True

        # Window bounds don't change — should settle as STABLE
        static_report = WindowForensicReport(
            hwnd=0x1234, pid=1000, title="Test", class_name="Cls",
            bounds=Rect(100, 100, 400, 300), is_visible=True, is_enabled=True,
        )
        ns.inspect_window.return_value = static_report

        engine = SettlementEngine(
            native_supervisor=ns,
            webview_core=None,
            default_timeout_ms=500,
            poll_interval_ms=10,
        )

        result = run_async(engine.settle(
            target_pid=1000,
            target_hwnd=0x1234,
            timeout_ms=500,
        ))

        self.assertTrue(result.settled)
        self.assertEqual(result.settlement_type, SettlementType.STABLE)


class TestSettlementTypeEnum(unittest.TestCase):
    """Tests SettlementType enum values."""

    def test_all_types_present(self):
        expected = {"STABLE", "NAVIGATED", "MODAL_APPEARED",
                     "TARGET_DISAPPEARED", "DOM_MUTATED", "FOCUS_ACQUIRED", "TIMEOUT"}
        actual = {e.value for e in SettlementType}
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
