# Engine Adapter Contract Specification

All desktop webview engine adapters (`qtwebengine`, `webview2`, `electron`, `chromium`, `webkit`) implement the `BaseEngineAdapter` interface located in `adapters/base.py`.

## Required Abstract Methods

```text
class BaseEngineAdapter(ABC):
    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Unique engine identifier (e.g. 'qtwebengine', 'webview2', 'electron')."""
        pass

    @abstractmethod
    def get_engine_info(self) -> EngineInfo:
        """Returns engine metadata and capability matrix."""
        pass

    @abstractmethod
    def detect(self, target_path_or_pid: Any) -> bool:
        """Heuristic check whether target matches this engine."""
        pass

    @abstractmethod
    def prepare_environment(self, env: Dict[str, str], port: int = 9222) -> Dict[str, str]:
        """Injects engine-specific debugging environment variables."""
        pass

    @abstractmethod
    def get_launch_args(self, port: int = 9222) -> List[str]:
        """Returns engine-specific command line arguments."""
        pass
```

## Shared Core Methods

The base class provides default, shared implementations for:
- `discover_targets()`: Polling target endpoints via `TargetDiscovery`.
- `select_target()`: Selecting application-owned renderers via ranking heuristics.
- `attach()`: Initializing and connecting `CDPSession` over WebSocket.
- `detach()`: Gracefully closing active sessions.
- `create_actions()`, `create_assertions()`, `create_evidence_collector()`, `cleanup_process()`.
