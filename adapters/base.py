"""
Base contract and abstract interface for desktop webview engine adapters.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from core.models import EngineInfo, Target, TargetCriteria, NodeGeometry, EvidenceReport
from core.session import CDPSession
from core.actions import WebviewActions
from core.assertions import WebviewAssertions
from core.evidence import EvidenceCollector
from core.discovery import TargetDiscovery
from core.cleanup import ProcessCleanup


class BaseEngineAdapter(ABC):
    """
    Abstract Base Class for engine adapters.
    Each engine (QtWebEngine, WebView2, Electron, CEF, etc.) implements this contract.
    """

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Returns the unique name of the engine (e.g. 'qtwebengine')."""
        pass

    @abstractmethod
    def get_engine_info(self) -> EngineInfo:
        """Returns EngineInfo metadata and capability matrix."""
        pass

    @abstractmethod
    def detect(self, target_path_or_pid: Any) -> bool:
        """Detects whether a given binary, script path, or process belongs to this engine."""
        pass

    @abstractmethod
    def prepare_environment(self, env: Dict[str, str], port: int = 9222) -> Dict[str, str]:
        """Prepares environment variables needed to enable remote debugging for this engine."""
        pass

    @abstractmethod
    def get_launch_args(self, port: int = 9222) -> List[str]:
        """Returns engine-specific command line arguments for remote debugging."""
        pass

    def discover_targets(self, host: str = "127.0.0.1", port: int = 9222, timeout: float = 15.0) -> List[Target]:
        """Discovers active inspectable targets. Default implementation polls HTTP /json/list."""
        return TargetDiscovery.poll_for_targets(host=host, port=port, engine=self.engine_name, timeout=timeout)

    def select_target(self, targets: List[Target], criteria: Optional[TargetCriteria] = None) -> Optional[Target]:
        """Selects a target according to criteria."""
        return TargetDiscovery.select_target(targets, criteria)

    async def attach(self, target: Target, timeout: float = 15.0) -> CDPSession:
        """Attaches a CDP WebSocket session to the given target and probes live capabilities."""
        session = CDPSession(target=target, timeout=timeout)
        await session.connect()
        await session.enable_domains(["DOM", "Runtime", "Page"])

        # Probe live capabilities
        try:
            from core.capabilities import CapabilityRegistry
            info = self.get_engine_info()
            await CapabilityRegistry.probe_runtime_capabilities(session, info)
        except Exception:
            pass

        return session

    async def detach(self, session: CDPSession) -> None:
        """Detaches and closes the CDP session."""
        if session:
            await session.close()

    # High-level convenience wrappers bridging session + actions + assertions + evidence

    def create_actions(self, session: CDPSession) -> WebviewActions:
        return WebviewActions(session)

    def create_assertions(self, session: CDPSession) -> WebviewAssertions:
        return WebviewAssertions(session)

    def create_evidence_collector(self, session: CDPSession) -> EvidenceCollector:
        return EvidenceCollector(session, self.get_engine_info())

    def cleanup_process(self, pid: int, timeout: float = 3.0, expected_create_time: Optional[float] = None) -> bool:
        """Terminates process tree for this engine."""
        return ProcessCleanup.terminate_process_tree(pid, timeout=timeout, expected_create_time=expected_create_time)

