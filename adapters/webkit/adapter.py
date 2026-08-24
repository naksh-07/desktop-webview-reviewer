"""
WebKit (WebKitGTK, WPE, WKWebView) engine adapter implementing BaseEngineAdapter.
"""

import sys
from typing import Any, Dict, List, Optional

from adapters.base import BaseEngineAdapter
from adapters.webkit.detector import WebKitDetector
from core.models import CapabilityName, CapabilityStatus, EngineInfo, Target, TargetCriteria, VerificationLevel
from core.capabilities import CapabilityRegistry
from core.discovery import TargetDiscovery


class WebKitAdapter(BaseEngineAdapter):
    """
    Adapter for WebKit-based desktop environments (WebKitGTK on Linux, WKWebView on macOS, Tauri/Wails on Linux).
    Uses the WebKit Remote Inspector Protocol when available.
    """

    @property
    def engine_name(self) -> str:
        return "webkit"

    def get_engine_info(self) -> EngineInfo:
        caps = CapabilityRegistry.create_capability_matrix(
            dom=CapabilityStatus.SUPPORTED,
            input_actions=CapabilityStatus.DEGRADED,  # WebKit lacks native CDP Input domain; uses synthetic DOM events
            keyboard=CapabilityStatus.DEGRADED,
            mouse=CapabilityStatus.DEGRADED,
            runtime=CapabilityStatus.SUPPORTED,
            screenshot=CapabilityStatus.SUPPORTED,
            console=CapabilityStatus.SUPPORTED,
            network=CapabilityStatus.DEGRADED,
            targets=CapabilityStatus.DEGRADED,
            multi_target=CapabilityStatus.DEGRADED,
            navigation=CapabilityStatus.SUPPORTED,
            js=CapabilityStatus.SUPPORTED,
        )
        
        notes = [
            "Remote debugging enabled via WEBKIT_INSPECTOR_SERVER=<host>:<port> environment variable on Linux/WebKitGTK.",
            "Uses WebKit Remote Inspector protocol semantics.",
            "Input domain uses synthetic DOM event dispatch (dispatchEvent).",
        ]
        if sys.platform == "win32":
            notes.append(
                "NOTE: Native WebKit runtime is not standard on Windows. On Windows, desktop frameworks like "
                "Tauri and Wails automatically compile against Microsoft Edge WebView2 (routed to webview2 adapter)."
            )

        ver_level = (
            VerificationLevel.RUNTIME_UNAVAILABLE if sys.platform == "win32"
            else VerificationLevel.PROTOCOL_VERIFIED
        )

        return EngineInfo(
            engine="webkit",
            backend="WebKit / WebKitGTK / WKWebView",
            version="WebKit2",
            protocol="webkit-inspector",
            capabilities=caps,
            verification_level=ver_level,
            notes=notes
        )

    def detect(self, target_path_or_pid: Any) -> bool:
        return WebKitDetector.detect(target_path_or_pid)

    def prepare_environment(self, env: Dict[str, str], port: int = 9222) -> Dict[str, str]:
        env_copy = env.copy()
        env_copy["WEBKIT_INSPECTOR_SERVER"] = f"127.0.0.1:{port}"
        return env_copy

    def get_launch_args(self, port: int = 9222) -> List[str]:
        return []

    def discover_targets(self, host: str = "127.0.0.1", port: int = 9222, timeout: float = 15.0) -> List[Target]:
        return TargetDiscovery.poll_for_targets(host=host, port=port, engine=self.engine_name, timeout=timeout)
