"""
Electron engine adapter implementing BaseEngineAdapter.
"""

from typing import Any, Dict, List, Optional

from adapters.base import BaseEngineAdapter
from adapters.electron.detector import ElectronDetector
from core.models import CapabilityName, CapabilityStatus, EngineInfo, Target, TargetCriteria, VerificationLevel
from core.capabilities import CapabilityRegistry
from core.discovery import TargetDiscovery


class ElectronAdapter(BaseEngineAdapter):
    """
    Adapter for Electron desktop applications.
    Manages --remote-debugging-port command line arguments, multi-renderer target discovery,
    DevTools/background filtering, and CDP session attachment.
    """

    @property
    def engine_name(self) -> str:
        return "electron"

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
            targets=CapabilityStatus.SUPPORTED,
            multi_target=CapabilityStatus.SUPPORTED,
            navigation=CapabilityStatus.SUPPORTED,
            js=CapabilityStatus.SUPPORTED,
        )
        return EngineInfo(
            engine="electron",
            backend="Electron (Chromium + Node.js)",
            version="Chromium / Node.js bundled",
            protocol="cdp",
            capabilities=caps,
            verification_level=VerificationLevel.RUNTIME_VERIFIED,
            notes=[
                "Remote debugging enabled via --remote-debugging-port command line flag.",
                "Supports full multi-renderer target discovery with intelligent DevTools/worker filtering.",
                "Direct page-level WebSocket CDP connection to application BrowserWindow renderer.",
                "Clean teardown terminates main Electron process and helper renderer/gpu processes."
            ]
        )

    def detect(self, target_path_or_pid: Any) -> bool:
        return ElectronDetector.detect(target_path_or_pid)

    def prepare_environment(self, env: Dict[str, str], port: int = 9222) -> Dict[str, str]:
        # Electron supports command line argument; environment remains pass-through
        return env.copy()

    def get_launch_args(self, port: int = 9222) -> List[str]:
        return [f"--remote-debugging-port={port}"]

    def discover_targets(self, host: str = "127.0.0.1", port: int = 9222, timeout: float = 15.0) -> List[Target]:
        """Discovers active inspectable Electron renderer targets."""
        return TargetDiscovery.poll_for_targets(host=host, port=port, engine=self.engine_name, timeout=timeout)

    def select_target(self, targets: List[Target], criteria: Optional[TargetCriteria] = None) -> Optional[Target]:
        """Selects the primary application renderer target, filtering out DevTools and background workers."""
        return TargetDiscovery.select_target(targets, criteria)
