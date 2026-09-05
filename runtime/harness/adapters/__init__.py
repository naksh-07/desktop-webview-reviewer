"""
Framework Adapters Package for Reviewer Test Harness.
"""

from __future__ import annotations
from typing import Dict, Optional

from runtime.harness.adapters.base import BaseHarnessAdapter
from runtime.harness.adapters.electron import ElectronHarnessAdapter
from runtime.harness.adapters.webview2 import WebView2HarnessAdapter
from runtime.harness.adapters.qt import QtHarnessAdapter

_ADAPTERS: Dict[str, BaseHarnessAdapter] = {
    "electron": ElectronHarnessAdapter(),
    "webview2": WebView2HarnessAdapter(),
    "qt": QtHarnessAdapter(),
    "qtwebengine": QtHarnessAdapter(),
}


def get_adapter_for_framework(framework: str) -> Optional[BaseHarnessAdapter]:
    """Returns the registered adapter for a given framework name."""
    clean_name = framework.strip().lower()
    return _ADAPTERS.get(clean_name)


def list_registered_adapters() -> Dict[str, BaseHarnessAdapter]:
    """Returns all registered framework adapters."""
    return dict(_ADAPTERS)
