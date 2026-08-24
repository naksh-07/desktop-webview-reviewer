"""
Adapter registry and discovery for desktop webview engines.
"""

import sys
from typing import Dict, List, Optional
from .base import BaseEngineAdapter
from .qtwebengine.adapter import QtWebEngineAdapter
from .webview2.adapter import WebView2Adapter
from .electron.adapter import ElectronAdapter
from .chromium.adapter import ChromiumAdapter
from .webkit.adapter import WebKitAdapter

_ADAPTERS: Dict[str, BaseEngineAdapter] = {}


def register_adapter(adapter: BaseEngineAdapter) -> None:
    """Registers an engine adapter instance."""
    _ADAPTERS[adapter.engine_name.lower()] = adapter


def get_adapter(engine_name_or_alias: str) -> Optional[BaseEngineAdapter]:
    """
    Retrieves an adapter by engine name or framework alias (tauri, wails, cef, pyside, pyqt, etc.).
    Routes platform-dependent frameworks to the underlying native engine.
    """
    if not engine_name_or_alias:
        return None

    key = engine_name_or_alias.strip().lower()

    # Direct match
    if key in _ADAPTERS:
        return _ADAPTERS[key]

    # Framework aliases & routing
    if key in ("tauri", "wails", "pywebview"):
        if sys.platform == "win32":
            return _ADAPTERS.get("webview2")
        else:
            return _ADAPTERS.get("webkit")

    if key in ("cef", "cefsharp", "chrome", "chromium-embed"):
        return _ADAPTERS.get("chromium")

    if key in ("pyqt", "pyqt5", "pyqt6", "pyside", "pyside2", "pyside6", "qt"):
        return _ADAPTERS.get("qtwebengine")

    if key in ("webkitgtk", "wkwebview", "safari", "wpe"):
        return _ADAPTERS.get("webkit")

    if key in ("edge", "edgechromium", "msedge", "webview2loader"):
        return _ADAPTERS.get("webview2")

    return None


def list_adapters() -> List[str]:
    """Returns names of all registered primary adapters."""
    return list(_ADAPTERS.keys())


def get_default_adapter() -> BaseEngineAdapter:
    """Returns the default adapter (QtWebEngine)."""
    return _ADAPTERS.get("qtwebengine", QtWebEngineAdapter())


# Auto-register all production adapters
register_adapter(QtWebEngineAdapter())
register_adapter(WebView2Adapter())
register_adapter(ElectronAdapter())
register_adapter(ChromiumAdapter())
register_adapter(WebKitAdapter())

__all__ = [
    "BaseEngineAdapter",
    "QtWebEngineAdapter",
    "WebView2Adapter",
    "ElectronAdapter",
    "ChromiumAdapter",
    "WebKitAdapter",
    "register_adapter",
    "get_adapter",
    "list_adapters",
    "get_default_adapter",
]
