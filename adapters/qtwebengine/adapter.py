"""
QtWebEngine adapter implementing BaseEngineAdapter.
"""

from typing import Any, Dict, List, Optional
from adapters.base import BaseEngineAdapter
from adapters.qtwebengine.detector import QtWebEngineDetector
from core.models import CapabilityName, CapabilityStatus, EngineInfo, VerificationLevel
from core.capabilities import CapabilityRegistry


class QtWebEngineAdapter(BaseEngineAdapter):
    """
    Adapter for QtWebEngine (PyQt5, PyQt6, PySide2, PySide6, C++ Qt).
    Handles remote debugging environment variables, page-level WebSocket CDP attachment,
    and Qt-specific lifecycle quirks.
    """

    @property
    def engine_name(self) -> str:
        return "qtwebengine"

    def get_engine_info(self) -> EngineInfo:
        caps = CapabilityRegistry.create_capability_matrix(
            dom=CapabilityStatus.SUPPORTED,
            input_actions=CapabilityStatus.SUPPORTED,
            runtime=CapabilityStatus.SUPPORTED,
            screenshot=CapabilityStatus.SUPPORTED,
            console=CapabilityStatus.SUPPORTED,
            network=CapabilityStatus.DEGRADED,
            targets=CapabilityStatus.DEGRADED,  # Lacks Browser.* domain context management
            js=CapabilityStatus.SUPPORTED,
        )
        return EngineInfo(
            engine="qtwebengine",
            backend="QtWebEngine (Embedded Chromium)",
            version="6.x / 5.x",
            protocol="cdp",
            capabilities=caps,
            verification_level=VerificationLevel.RUNTIME_VERIFIED,
            notes=[
                "Remote debugging enabled via QTWEBENGINE_REMOTE_DEBUGGING environment variable.",
                "Does not support Browser.* domain context management (e.g. Browser.setDownloadBehavior).",
                "Direct page-level WebSocket attachment is required.",
                "Child process 'QtWebEngineProcess' must be recursively terminated during cleanup."
            ]
        )

    def detect(self, target_path_or_pid: Any) -> bool:
        return QtWebEngineDetector.detect(target_path_or_pid)

    def prepare_environment(self, env: Dict[str, str], port: int = 9222) -> Dict[str, str]:
        env_copy = env.copy()
        env_copy["QTWEBENGINE_REMOTE_DEBUGGING"] = str(port)
        existing_flags = env_copy.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        allow_origin = f"--remote-allow-origins=http://127.0.0.1:{port},http://localhost:{port}"
        if allow_origin not in existing_flags and "--remote-allow-origins=*" not in existing_flags:
            if existing_flags:
                env_copy["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{existing_flags} {allow_origin}"
            else:
                env_copy["QTWEBENGINE_CHROMIUM_FLAGS"] = allow_origin
        return env_copy

    def get_launch_args(self, port: int = 9222) -> List[str]:
        return []
