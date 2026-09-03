"""
Phase 5 Test Suite — Native Input Dispatcher.
Tests NativeInputDispatcher in mock mode: mouse moves, clicks, double click,
keyboard keys, text typing, scroll, coordinate normalization.
All tests run in dry_run mode (no actual SendInput calls).
"""

import asyncio
import unittest

from runtime.native_input import (
    NativeInputDispatcher,
    MouseButton,
    KeyAction,
    DispatchedInputRecord,
)


def run_async(coro):
    """Runs an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestNativeInputDispatcherMockMode(unittest.TestCase):
    """Tests NativeInputDispatcher in dry_run mode for CI environments."""

    def setUp(self):
        self.dispatcher = NativeInputDispatcher(dry_run=True)

    def test_dispatcher_creation(self):
        self.assertTrue(self.dispatcher.dry_run)

    def test_move_mouse(self):
        record = run_async(self.dispatcher.move_mouse(500, 300))
        self.assertIsInstance(record, DispatchedInputRecord)
        self.assertIn("MOUSE", record.input_type)
        self.assertEqual(record.coordinates, (500, 300))
        self.assertTrue(record.success)

    def test_click_left(self):
        records = run_async(self.dispatcher.click(200, 150, MouseButton.LEFT))
        self.assertIsInstance(records, list)
        self.assertGreaterEqual(len(records), 1)
        # Should contain move and press/release actions
        for r in records:
            self.assertIsInstance(r, DispatchedInputRecord)
            self.assertTrue(r.success)

    def test_click_right(self):
        records = run_async(self.dispatcher.click(300, 250, MouseButton.RIGHT))
        self.assertIsInstance(records, list)
        self.assertGreaterEqual(len(records), 1)
        for r in records:
            self.assertTrue(r.success)

    def test_double_click(self):
        records = run_async(self.dispatcher.click(400, 350, MouseButton.LEFT, click_count=2))
        self.assertIsInstance(records, list)
        # Double click should dispatch more records than single click
        self.assertGreaterEqual(len(records), 2)

    def test_press_key(self):
        records = run_async(self.dispatcher.press_key("Enter"))
        self.assertIsInstance(records, list)
        self.assertGreaterEqual(len(records), 1)
        for r in records:
            self.assertEqual(r.input_type, "KEYBOARD")
            self.assertTrue(r.success)

    def test_press_key_with_modifiers(self):
        records = run_async(self.dispatcher.press_key("a", modifiers=["ctrl"]))
        self.assertIsInstance(records, list)
        # Modifier down + key down + key up + modifier up = at least 2 records
        self.assertGreaterEqual(len(records), 2)

    def test_type_text(self):
        text = "Hello"
        records = run_async(self.dispatcher.type_text(text))
        self.assertIsInstance(records, list)
        # Should have at least one record per character
        self.assertGreaterEqual(len(records), len(text))
        for r in records:
            self.assertTrue(r.success)

    def test_type_empty_text(self):
        records = run_async(self.dispatcher.type_text(""))
        self.assertIsInstance(records, list)
        self.assertEqual(len(records), 0)

    def test_scroll_vertical(self):
        records = run_async(self.dispatcher.scroll(100, 200, delta_y=-120))
        self.assertIsInstance(records, list)
        self.assertGreaterEqual(len(records), 1)
        for r in records:
            self.assertTrue(r.success)

    def test_scroll_horizontal(self):
        records = run_async(self.dispatcher.scroll(100, 200, delta_x=120))
        self.assertIsInstance(records, list)
        self.assertGreaterEqual(len(records), 1)

    def test_record_serialization(self):
        record = run_async(self.dispatcher.move_mouse(100, 200))
        d = record.to_dict()
        self.assertIn("MOUSE", d["input_type"])
        self.assertEqual(d["coordinates"], [100, 200])
        self.assertTrue(d["success"])
        self.assertIsNone(d["error"])

    def test_mouse_button_enum(self):
        self.assertEqual(MouseButton.LEFT, "LEFT")
        self.assertEqual(MouseButton.RIGHT, "RIGHT")
        self.assertEqual(MouseButton.MIDDLE, "MIDDLE")

    def test_key_action_enum(self):
        self.assertEqual(KeyAction.DOWN, "DOWN")
        self.assertEqual(KeyAction.UP, "UP")
        self.assertEqual(KeyAction.PRESS, "PRESS")


class TestNativeInputDispatcherProduction(unittest.TestCase):
    """Tests NativeInputDispatcher in production mode (dry_run=False) — validation only."""

    def test_creation_production_mode(self):
        d = NativeInputDispatcher(dry_run=False)
        self.assertFalse(d.dry_run)


if __name__ == "__main__":
    unittest.main()
