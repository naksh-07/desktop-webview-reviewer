"""
Base Framework Adapter Contract for Reviewer Test Harness (Architecture H).
Defines framework-neutral interface for lifecycle hooks, client code generation,
and honest capability reporting across Electron, WebView2, and Qt/QtWebEngine.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Any, Optional

from runtime.capability import CapabilityStatus


class BaseHarnessAdapter(ABC):
    """
    Common contract implemented by framework-specific harness adapters.
    Translates framework runtime realities into the unified Harness protocol.
    """

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Unique adapter name (e.g. 'electron', 'webview2', 'qtwebengine')."""
        pass

    @property
    @abstractmethod
    def framework(self) -> str:
        """Standard framework identifier."""
        pass

    @abstractmethod
    def get_supported_capabilities(self) -> Dict[str, CapabilityStatus]:
        """
        Reports honest capability support for this framework.
        Must report DEGRADED or UNAVAILABLE if unsupported. Never fake support.
        """
        pass

    @abstractmethod
    def generate_harness_client_file(self, project_path: str, config: Dict[str, Any]) -> Tuple[str, str]:
        """
        Generates the framework-specific in-process harness client file.
        Returns (relative_file_path, file_content).
        """
        pass

    @abstractmethod
    def get_injection_snippet(self, client_rel_path: str) -> str:
        """
        Returns minimal, bounded code snippet to inject into the application entry point.
        Must be cleanly wrapped in dev-only markers.
        """
        pass

    @abstractmethod
    def get_dev_marker_pair(self) -> Tuple[str, str]:
        """Returns (begin_marker, end_marker) comments appropriate for the language."""
        pass
