"""
Unit tests for runtime/references.py.
Validates epoch-scoped reference generation, resolution, stale reference invalidation,
and invalidation triggers (navigation, mutation).
"""

import unittest
from runtime.references import ReferenceRegistry, ElementRef, Rect
from runtime.state import TargetPlane
from runtime.errors import StaleReferenceException


class TestRuntimeReferences(unittest.TestCase):
    """Test suite for epoch-scoped interaction references."""

    def setUp(self):
        self.registry = ReferenceRegistry(session_id="session_test_123", initial_epoch=1)

    def test_register_and_resolve_ref(self):
        """Verifies creating and resolving a reference in the active epoch."""
        bounds = Rect(x=10, y=20, width=100, height=30)
        ref = self.registry.register_ref(
            plane=TargetPlane.WEBVIEW_DOM,
            role="button",
            name="Submit",
            bounds=bounds,
            locator_recipe={"role": "button", "name": "Submit"},
        )

        self.assertEqual(ref.epoch_id, 1)
        self.assertEqual(ref.ref_id, "w1e1")
        self.assertEqual(ref.role, "button")
        self.assertEqual(ref.name, "Submit")
        self.assertEqual(ref.bounds, bounds)

        # Resolve ref
        resolved = self.registry.resolve_ref("w1e1")
        self.assertEqual(resolved, ref)
        self.assertTrue(self.registry.is_ref_valid("w1e1"))

    def test_native_ref_prefix(self):
        """Verifies native shell references receive 'n' prefix."""
        ref = self.registry.register_ref(
            plane=TargetPlane.NATIVE_SHELL,
            role="menuitem",
            name="File",
            bounds=Rect(0, 0, 50, 20),
        )
        self.assertEqual(ref.ref_id, "n1e1")

    def test_stale_ref_invalidation_on_epoch_increment(self):
        """Verifies references from epoch 1 become invalid and throw StaleReferenceException in epoch 2."""
        ref1 = self.registry.register_ref(
            plane=TargetPlane.WEBVIEW_DOM,
            role="button",
            name="Play",
            bounds=Rect(0, 0, 100, 50),
        )
        self.assertEqual(ref1.ref_id, "w1e1")
        self.assertTrue(self.registry.is_ref_valid("w1e1"))

        # Increment epoch (e.g. following layout settlement)
        new_epoch = self.registry.increment_epoch("ui_mutation")
        self.assertEqual(new_epoch, 2)
        self.assertFalse(self.registry.is_ref_valid("w1e1"))

        # Resolving old ref now raises StaleReferenceException
        with self.assertRaises(StaleReferenceException) as ctx:
            self.registry.resolve_ref("w1e1")

        self.assertEqual(ctx.exception.ref_id, "w1e1")
        self.assertEqual(ctx.exception.current_epoch, 2)
        self.assertEqual(ctx.exception.ref_epoch, 1)

    def test_navigation_invalidation(self):
        """Verifies target navigation triggers epoch invalidation."""
        self.registry.register_ref(TargetPlane.WEBVIEW_DOM, "link", "Home", Rect(0, 0, 50, 20))
        self.assertEqual(self.registry.current_epoch, 1)

        new_epoch = self.registry.invalidate_for_navigation("http://localhost:8080/dashboard")
        self.assertEqual(new_epoch, 2)
        self.assertEqual(len(self.registry.list_active_refs()), 0)

        with self.assertRaises(StaleReferenceException):
            self.registry.resolve_ref("w1e1")

    def test_mutation_invalidation(self):
        """Verifies DOM/UI mutation triggers epoch invalidation."""
        self.registry.register_ref(TargetPlane.WEBVIEW_DOM, "input", "Search", Rect(0, 0, 200, 30))
        new_epoch = self.registry.invalidate_for_mutation("DOM node inserted")
        self.assertEqual(new_epoch, 2)
        self.assertFalse(self.registry.is_ref_valid("w1e1"))

    def test_nonexistent_ref_raises_stale_reference(self):
        """Verifies querying arbitrary nonexistent ref raises StaleReferenceException."""
        with self.assertRaises(StaleReferenceException):
            self.registry.resolve_ref("w99e99")


if __name__ == "__main__":
    unittest.main()
