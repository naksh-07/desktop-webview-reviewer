"""
Microsoft Edge WebView2 engine adapter implementing BaseEngineAdapter.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapters.base import BaseEngineAdapter
from adapters.webview2.detector import WebView2Detector
from core.models import CapabilityName, CapabilityStatus, EngineInfo, Target, TargetCriteria, VerificationLevel
from core.capabilities import CapabilityRegistry
from core.discovery import TargetDiscovery


class WebView2Adapter(BaseEngineAdapter):
    """
    Adapter for Microsoft Edge WebView2 runtime (WinForms, WPF, WinUI, C++, Tauri Win, Wails Win, pywebview).
    Manages WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS injection, DevToolsActivePort discovery, and CDP routing.
    """

    @property
    def engine_name(self) -> str:
        return "webview2"

    def get_engine_info(self) -> EngineInfo:
        caps = CapabilityRegistry.create_capability_matrix(
            dom=CapabilityStatus.SUPPORTED,
            input_actions=CapabilityStatus.SUPPORTED,
            keyboard=CapabilityStatus.SUPPORTED,
            mouse=CapabilityStatus.SUPPORTED,
            runtime=CapabilityStatus.SUPPORTED,
            screenshot=CapabilityStatus.SUPPORTED,
            console=CapabilityStatus.SUPPORTED,
            network=CapabilityStatus.SUPPORTED,
            targets=CapabilityStatus.DEGRADED,  # Lacks full browser-level profile/window context management
            multi_target=CapabilityStatus.SUPPORTED,
            navigation=CapabilityStatus.SUPPORTED,
            js=CapabilityStatus.SUPPORTED,
        )
        return EngineInfo(
            engine="webview2",
            backend="Microsoft Edge WebView2 (Chromium Core)",
            version="Edge/Chromium (Evergreen / Fixed Version)",
            protocol="cdp",
            capabilities=caps,
            verification_level=VerificationLevel.RUNTIME_VERIFIED,
            notes=[
                "Remote debugging enabled via WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS environment variable.",
                "Supports DevToolsActivePort discovery from User Data Folder (EBWebView/DevToolsActivePort).",
                "Does not support Browser.* domain context management (e.g. Browser.setDownloadBehavior).",
                "Spawns msedgewebview2.exe child processes; requires recursive process tree teardown."
            ]
        )

    def detect(self, target_path_or_pid: Any) -> bool:
        return WebView2Detector.detect(target_path_or_pid)

    def prepare_environment(self, env: Dict[str, str], port: int = 9222) -> Dict[str, str]:
        env_copy = env.copy()
        existing = env_copy.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
        flag = f"--remote-debugging-port={port}"
        if flag not in existing:
            env_copy["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"{existing} {flag}".strip()
        return env_copy

    def get_launch_args(self, port: int = 9222) -> List[str]:
        return [f"--remote-debugging-port={port}"]

    @staticmethod
    def read_devtools_active_port(udf_path: str) -> Optional[Tuple[int, str]]:
        """Reads active debugging port and WS path from DevToolsActivePort file."""
        candidates = [
            Path(udf_path) / "EBWebView" / "DevToolsActivePort",
            Path(udf_path) / "DevToolsActivePort",
        ]
        for p in candidates:
            if p.is_file():
                try:
                    lines = p.read_text(encoding="utf-8").strip().splitlines()
                    if len(lines) >= 2:
                        return int(lines[0].strip()), lines[1].strip()
                except (ValueError, OSError):
                    pass
        return None

    def discover_targets(self, host: str = "127.0.0.1", port: int = 9222, timeout: float = 15.0) -> List[Target]:
        """Discovers active WebView2 inspectable page targets."""
        return TargetDiscovery.poll_for_targets(host=host, port=port, engine=self.engine_name, timeout=timeout)
