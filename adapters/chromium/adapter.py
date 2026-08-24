"""
Generic Chromium and CEF (Chromium Embedded Framework) adapter implementing BaseEngineAdapter.
"""

from typing import Any, Dict, List, Optional

from adapters.base import BaseEngineAdapter
from adapters.chromium.detector import ChromiumDetector
from core.models import CapabilityName, CapabilityStatus, EngineInfo, Target, TargetCriteria, VerificationLevel
from core.capabilities import CapabilityRegistry
from core.discovery import TargetDiscovery


class ChromiumAdapter(BaseEngineAdapter):
    """
    Adapter for Generic Chromium embeds, CEF applications (Spotify, Steam, OBS, CefSharp, CEF Python),
    and Chromium Embedded Shells exposing standard CDP.
    """

    def __init__(self, is_cef: bool = False):
        self._is_cef = is_cef

    @property
    def engine_name(self) -> str:
        return "chromium"

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
            targets=CapabilityStatus.DEGRADED,  # Embedded Chromium often lacks full browser context management
            multi_target=CapabilityStatus.SUPPORTED,
            navigation=CapabilityStatus.SUPPORTED,
            js=CapabilityStatus.SUPPORTED,
        )
        ver_level = (
            VerificationLevel.PROTOCOL_VERIFIED if self._is_cef
            else VerificationLevel.RUNTIME_VERIFIED
        )
        return EngineInfo(
            engine="chromium",
            backend="Generic Chromium / CEF (Chromium Embedded Framework)",
            version="Chromium Embedded Core",
            protocol="cdp",
            framework="cef" if self._is_cef else None,
            capabilities=caps,
            verification_level=ver_level,
            notes=[
                "Remote debugging enabled via --remote-debugging-port command line flag or CefSettings.",
                "Operates via generic Chrome DevTools Protocol over WebSocket.",
                "Direct page-level WebSocket attachment is required.",
                "Generic Chromium/CDP: RUNTIME_VERIFIED on standard Chromium hosts.",
                "CEF (Chromium Embedded Framework): PROTOCOL_VERIFIED (standalone native CEF runtime pending host fixture).",
                "Teardown terminates main embed host and subprocesses (e.g. CefSharp.BrowserSubprocess)."
            ]
        )

    def detect(self, target_path_or_pid: Any) -> bool:
        detected = ChromiumDetector.detect(target_path_or_pid)
        if detected and isinstance(target_path_or_pid, str):
            self._is_cef = ChromiumDetector.is_cef(target_path_or_pid)
        return detected

    def prepare_environment(self, env: Dict[str, str], port: int = 9222) -> Dict[str, str]:
        return env.copy()

    def get_launch_args(self, port: int = 9222) -> List[str]:
        return [f"--remote-debugging-port={port}"]

    def discover_targets(self, host: str = "127.0.0.1", port: int = 9222, timeout: float = 15.0) -> List[Target]:
        return TargetDiscovery.poll_for_targets(host=host, port=port, engine=self.engine_name, timeout=timeout)
