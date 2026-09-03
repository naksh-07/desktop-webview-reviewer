"""
Unit tests for Deterministic Semantic Role Normalization (Phase 4).
Verifies role mapping precedence, provenance retention, and bounded inference.
"""

import unittest
from runtime.semantic_normalization import (
    normalize_web_role,
    is_actionable_role,
    RoleSource,
    CANONICAL_ROLES,
    ACTIONABLE_ROLES,
)


class TestSemanticNormalization(unittest.TestCase):
    def test_canonical_roles_defined(self):
        """Standard canonical roles must be covered."""
        expected = {"button", "link", "textbox", "checkbox", "radio", "combobox", "listbox", "dialog", "heading"}
        self.assertTrue(expected.issubset(CANONICAL_ROLES))

    def test_accessibility_role_precedence(self):
        """Accessibility roles take highest precedence."""
        role, source = normalize_web_role(
            ax_role="PushButton",
            tag_name="div",
            input_type=None,
        )
        self.assertEqual(role, "button")
        self.assertEqual(source, RoleSource.ACCESSIBILITY)

        role, source = normalize_web_role(
            ax_role="SearchBox",
            tag_name="input",
            input_type="text",
        )
        self.assertEqual(role, "textbox")
        self.assertEqual(source, RoleSource.ACCESSIBILITY)

    def test_aria_role_attribute_precedence(self):
        """Explicit role attribute takes priority when valid."""
        role, source = normalize_web_role(
            ax_role=None,
            tag_name="div",
            aria_role="button",
        )
        self.assertEqual(role, "button")
        self.assertEqual(source, RoleSource.ACCESSIBILITY)

    def test_dom_fallback_semantics(self):
        """Native HTML elements without explicit AX role fall back to DOM semantics."""
        # Button
        role, source = normalize_web_role(tag_name="button")
        self.assertEqual(role, "button")
        self.assertEqual(source, RoleSource.DOM)

        # Anchor with href -> link
        role, source = normalize_web_role(tag_name="a", attributes={"href": "/home"})
        self.assertEqual(role, "link")
        self.assertEqual(source, RoleSource.DOM)

        # Anchor without href -> generic
        role, source = normalize_web_role(tag_name="a", attributes={})
        self.assertEqual(role, "generic")
        self.assertEqual(source, RoleSource.DOM)

        # Input text
        role, source = normalize_web_role(tag_name="input", input_type="text")
        self.assertEqual(role, "textbox")
        self.assertEqual(source, RoleSource.DOM)

        # Input submit
        role, source = normalize_web_role(tag_name="input", input_type="submit")
        self.assertEqual(role, "button")
        self.assertEqual(source, RoleSource.DOM)

        # Input checkbox
        role, source = normalize_web_role(tag_name="input", input_type="checkbox")
        self.assertEqual(role, "checkbox")
        self.assertEqual(source, RoleSource.DOM)

        # Select
        role, source = normalize_web_role(tag_name="select")
        self.assertEqual(role, "combobox")
        self.assertEqual(source, RoleSource.DOM)

        # Heading
        role, source = normalize_web_role(tag_name="h1")
        self.assertEqual(role, "heading")
        self.assertEqual(source, RoleSource.DOM)

    def test_inferred_roles_from_behavior(self):
        """Interactive div with onclick or button class is classified as inferred button."""
        role, source = normalize_web_role(
            tag_name="div",
            attributes={"onclick": "submitForm()"}
        )
        self.assertEqual(role, "button")
        self.assertEqual(source, RoleSource.INFERRED)

        role, source = normalize_web_role(
            tag_name="div",
            attributes={"tabindex": "0", "class": "btn primary"}
        )
        self.assertEqual(role, "button")
        self.assertEqual(source, RoleSource.INFERRED)

    def test_no_over_inference_on_generic_divs(self):
        """Plain div remains generic layout container."""
        role, source = normalize_web_role(tag_name="div", attributes={"class": "container flex"})
        self.assertEqual(role, "generic")
        self.assertEqual(source, RoleSource.DOM)

    def test_is_actionable_role_truth(self):
        """Only interactive affordances return True for is_actionable_role."""
        self.assertTrue(is_actionable_role("button"))
        self.assertTrue(is_actionable_role("link"))
        self.assertTrue(is_actionable_role("textbox"))
        self.assertTrue(is_actionable_role("checkbox"))
        self.assertTrue(is_actionable_role("radio"))
        self.assertTrue(is_actionable_role("combobox"))

        self.assertFalse(is_actionable_role("heading"))
        self.assertFalse(is_actionable_role("paragraph"))
        self.assertFalse(is_actionable_role("generic"))
        self.assertFalse(is_actionable_role("table"))


if __name__ == "__main__":
    unittest.main()
