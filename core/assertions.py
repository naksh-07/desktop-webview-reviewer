"""
Structured assertion framework for desktop webview verification.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from .session import CDPSession

logger = logging.getLogger("desktop_webview.assertions")


class AssertionResult:
    def __init__(self, description: str, passed: bool, expected: Any, actual: Any, error: Optional[str] = None):
        self.description = description
        self.passed = passed
        self.expected = expected
        self.actual = actual
        self.error = error
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "passed": self.passed,
            "expected": str(self.expected),
            "actual": str(self.actual),
            "error": self.error,
            "timestamp": self.timestamp
        }


class WebviewAssertions:
    """Performs verifiable state checks and records evidence."""

    def __init__(self, session: CDPSession):
        self.session = session
        self.history: List[AssertionResult] = []

    def _record(self, desc: str, passed: bool, expected: Any, actual: Any, error: Optional[str] = None) -> AssertionResult:
        res = AssertionResult(desc, passed, expected, actual, error)
        self.history.append(res)
        status_str = "[PASS]" if passed else "[FAIL]"
        logger.info(f"{status_str} {desc} (Expected: {expected} | Actual: {actual})")
        if not passed:
            logger.warning(f"Assertion failed: {desc}. Error: {error}")
        return res

    async def assert_exists(self, selector: str, description: Optional[str] = None) -> bool:
        desc = description or f"Element '{selector}' should exist in DOM"
        js = f"document.querySelector({json.dumps(selector)}) !== null"
        try:
            exists = bool(await self.session.evaluate_js(js))
            res = self._record(desc, exists, expected=True, actual=exists)
            return res.passed
        except Exception as e:
            res = self._record(desc, False, expected=True, actual=None, error=str(e))
            return False

    async def assert_text_equals(self, selector: str, expected_text: str, description: Optional[str] = None) -> bool:
        desc = description or f"Text of '{selector}' should equal '{expected_text}'"
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            return el ? el.textContent.trim() : null;
        }})()
        """
        try:
            actual = await self.session.evaluate_js(js)
            passed = (actual == expected_text)
            res = self._record(desc, passed, expected=expected_text, actual=actual)
            return res.passed
        except Exception as e:
            res = self._record(desc, False, expected=expected_text, actual=None, error=str(e))
            return False

    async def assert_text_contains(self, selector: str, substring: str, description: Optional[str] = None) -> bool:
        desc = description or f"Text of '{selector}' should contain '{substring}'"
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            return el ? el.textContent : null;
        }})()
        """
        try:
            actual = await self.session.evaluate_js(js)
            passed = (actual is not None and substring in actual)
            res = self._record(desc, passed, expected=f"Contains '{substring}'", actual=actual)
            return res.passed
        except Exception as e:
            res = self._record(desc, False, expected=f"Contains '{substring}'", actual=None, error=str(e))
            return False

    async def assert_computed_style(
        self, selector: str, property_name: str, expected_value: str, description: Optional[str] = None
    ) -> bool:
        desc = description or f"Computed style '{property_name}' of '{selector}' should be '{expected_value}'"
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            return window.getComputedStyle(el).getPropertyValue({json.dumps(property_name)});
        }})()
        """
        try:
            actual = await self.session.evaluate_js(js)
            passed = (actual == expected_value)
            res = self._record(desc, passed, expected=expected_value, actual=actual)
            return res.passed
        except Exception as e:
            res = self._record(desc, False, expected=expected_value, actual=None, error=str(e))
            return False

    async def assert_js(self, expression: str, expected_value: Any = True, description: Optional[str] = None) -> bool:
        desc = description or f"Expression '{expression}' should evaluate to '{expected_value}'"
        try:
            actual = await self.session.evaluate_js(expression)
            passed = (actual == expected_value)
            res = self._record(desc, passed, expected=expected_value, actual=actual)
            return res.passed
        except Exception as e:
            res = self._record(desc, False, expected=expected_value, actual=None, error=str(e))
            return False

    @property
    def all_passed(self) -> bool:
        return len(self.history) > 0 and all(r.passed for r in self.history)
