"""
Tests for WebviewActions before/after verification and synthetic event fallbacks.
"""

import asyncio
import unittest
import sys
from unittest.mock import AsyncMock, MagicMock

try:
    from .env_config import CORE_SKILL_DIR
except ImportError:
    from env_config import CORE_SKILL_DIR

from core.actions import WebviewActions
from core.models import NodeGeometry, ActionReceipt


class TestActionSemantics(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.evaluate_js = AsyncMock()
        self.mock_session.get_bounding_rect = AsyncMock()
        self.mock_session.dispatch_mouse_click = AsyncMock()
        self.mock_session.send_command = AsyncMock()

    def test_click_records_before_and_after_receipt(self):
        async def run():
            # Setup mock returns
            self.mock_session.get_bounding_rect.return_value = NodeGeometry(x=10, y=20, width=100, height=40)
            self.mock_session.evaluate_js.side_effect = [
                # _capture_element_state before
                {"tagName": "BUTTON", "textContent": "Clicks: 0", "value": None, "visible": True},
                # _capture_element_state after
                {"tagName": "BUTTON", "textContent": "Clicks: 1", "value": None, "visible": True},
            ]

            actions = WebviewActions(self.mock_session)
            geom = await actions.click("#counter-btn")

            self.assertEqual(geom.center_x, 60.0)
            self.assertEqual(geom.center_y, 40.0)
            self.assertEqual(len(actions.history), 1)

            receipt = actions.history[0]
            self.assertEqual(receipt.action_type, "click")
            self.assertEqual(receipt.selector, "#counter-btn")
            self.assertEqual(receipt.before_state["textContent"], "Clicks: 0")
            self.assertEqual(receipt.after_state["textContent"], "Clicks: 1")
            self.assertTrue(receipt.success)
            self.assertIsNone(receipt.fallback_used)

        asyncio.run(run())

    def test_click_fallback_to_synthetic_dom_when_native_fails(self):
        async def run():
            self.mock_session.get_bounding_rect.return_value = NodeGeometry(x=10, y=20, width=100, height=40)
            # Native dispatch fails
            self.mock_session.dispatch_mouse_click.side_effect = RuntimeError("CDP Input domain disabled")

            self.mock_session.evaluate_js.side_effect = [
                # _capture_element_state before
                {"tagName": "BUTTON", "textContent": "Submit", "visible": True},
                # synthetic DOM click
                True,
                # _capture_element_state after
                {"tagName": "BUTTON", "textContent": "Submitted", "visible": True},
            ]

            actions = WebviewActions(self.mock_session)
            geom = await actions.click("#submit-btn")

            self.assertEqual(len(actions.history), 1)
            receipt = actions.history[0]
            self.assertEqual(receipt.action_type, "click")
            self.assertEqual(receipt.fallback_used, "synthetic_dom_click")
            self.assertTrue(receipt.success)

        asyncio.run(run())

    def test_type_text_receipt(self):
        async def run():
            self.mock_session.evaluate_js.side_effect = [
                # before state
                {"tagName": "INPUT", "value": "", "visible": True},
                # evaluate_js for typing
                True,
                # after state
                {"tagName": "INPUT", "value": "Hello Desktop", "visible": True}
            ]

            actions = WebviewActions(self.mock_session)
            await actions.type_text("#username", "Hello Desktop")

            self.assertEqual(len(actions.history), 1)
            receipt = actions.history[0]
            self.assertEqual(receipt.action_type, "type_text")
            self.assertEqual(receipt.before_state["value"], "")
            self.assertEqual(receipt.after_state["value"], "Hello Desktop")
            self.assertTrue(receipt.success)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
