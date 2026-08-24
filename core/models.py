"""
Core data models and types for desktop-webview-reviewer.
"""

from dataclasses import dataclass, field
from enum import Enum
import sys
from typing import Any, Callable, Dict, List, Optional


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class VerificationLevel(str, Enum):
    IMPLEMENTED = "implemented"
    UNIT_VERIFIED = "unit_verified"
    PROTOCOL_VERIFIED = "protocol_verified"
    RUNTIME_VERIFIED = "runtime_verified"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class CapabilityStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class CapabilityName(str, Enum):
    DOM = "DOM"
    INPUT = "INPUT"
    KEYBOARD = "KEYBOARD"
    MOUSE = "MOUSE"
    RUNTIME = "RUNTIME"
    SCREENSHOT = "SCREENSHOT"
    CONSOLE = "CONSOLE"
    NETWORK = "NETWORK"
    TARGETS = "TARGETS"
    MULTI_TARGET = "MULTI_TARGET"
    NAVIGATION = "NAVIGATION"
    JS = "JS"


@dataclass
class DetectionSignal:
    """Individual signal contributing to framework/engine detection."""
    source: str          # e.g., "manifest", "process", "port", "header", "launch_arg", "override"
    indicator: str       # e.g., "package.json dependencies", "msedgewebview2.exe", "User-Agent"
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    weight: float = 1.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "indicator": self.indicator,
            "confidence": self.confidence.value if isinstance(self.confidence, ConfidenceLevel) else str(self.confidence),
            "weight": self.weight,
            "details": self.details
        }


@dataclass
class EngineInfo:
    """Metadata describing a desktop webview engine."""
    engine: str
    backend: str
    version: str = "unknown"
    protocol: str = "cdp"
    framework: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    signals: List[DetectionSignal] = field(default_factory=list)
    capabilities: Dict[str, CapabilityStatus] = field(default_factory=dict)
    probed_capabilities: Dict[str, CapabilityStatus] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    verification_level: VerificationLevel = VerificationLevel.IMPLEMENTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "backend": self.backend,
            "version": self.version,
            "protocol": self.protocol,
            "framework": self.framework,
            "confidence": self.confidence.value if isinstance(self.confidence, ConfidenceLevel) else str(self.confidence),
            "signals": [s.to_dict() if hasattr(s, "to_dict") else s for s in self.signals],
            "capabilities": {k: v.value if isinstance(v, CapabilityStatus) else str(v) for k, v in self.capabilities.items()},
            "probed_capabilities": {k: v.value if isinstance(v, CapabilityStatus) else str(v) for k, v in self.probed_capabilities.items()},
            "notes": self.notes,
            "verification_level": self.verification_level.value if isinstance(self.verification_level, VerificationLevel) else str(self.verification_level)
        }


@dataclass
class Target:
    """A generic inspectable web surface / page target."""
    id: str
    type: str  # e.g., 'page', 'webview', 'background_page', 'node'
    title: str
    url: str
    engine: str
    framework: Optional[str] = None
    process_id: Optional[int] = None
    debug_endpoint: Optional[str] = None
    websocket_endpoint: Optional[str] = None
    is_application: bool = True
    rank_score: int = 0
    filter_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "url": self.url,
            "engine": self.engine,
            "framework": self.framework,
            "process_id": self.process_id,
            "debug_endpoint": self.debug_endpoint,
            "websocket_endpoint": self.websocket_endpoint,
            "is_application": self.is_application,
            "rank_score": self.rank_score,
            "filter_reason": self.filter_reason,
            "metadata": self.metadata
        }


@dataclass
class TargetCriteria:
    """Criteria for filtering and selecting targets."""
    title_pattern: Optional[str] = None
    url_pattern: Optional[str] = None
    target_type: Optional[str] = "page"
    engine: Optional[str] = None
    framework: Optional[str] = None
    index: int = 0
    custom_filter: Optional[Callable[[Target], bool]] = None


@dataclass
class NodeGeometry:
    """Bounding box coordinates for an element."""
    x: float
    y: float
    width: float
    height: float

    @property
    def center_x(self) -> float:
        return self.x + (self.width / 2.0)

    @property
    def center_y(self) -> float:
        return self.y + (self.height / 2.0)


@dataclass
class ActionReceipt:
    """Standardized receipt documenting an action before and after state."""
    action_type: str
    selector: Optional[str] = None
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    fallback_used: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "selector": self.selector,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "fallback_used": self.fallback_used
        }


@dataclass
class ProcessOwnership:
    """Process lifecycle and ownership metadata for safety."""
    pid: int
    create_time: Optional[float] = None
    launched_by_reviewer: bool = False
    command: Optional[List[str]] = None
    port: int = 9222

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "create_time": self.create_time,
            "launched_by_reviewer": self.launched_by_reviewer,
            "command": self.command,
            "port": self.port
        }


@dataclass
class EvidenceReport:
    """Collected verification evidence from an inspection session."""
    target: Target
    engine_info: EngineInfo
    framework: Optional[str] = None
    engine: Optional[str] = None
    platform: str = field(default_factory=lambda: sys.platform)
    verification_level: VerificationLevel = VerificationLevel.RUNTIME_VERIFIED
    dom_snapshot: Optional[str] = None
    screenshot_path: Optional[str] = None
    screenshot_sha256: Optional[str] = None
    console_messages: List[Dict[str, Any]] = field(default_factory=list)
    state_assertions: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[ActionReceipt] = field(default_factory=list)
    process_ownership: Optional[ProcessOwnership] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        fw = self.framework or self.engine_info.framework or self.target.framework
        eng = self.engine or self.engine_info.engine or self.target.engine
        return {
            "framework": fw,
            "engine": eng,
            "platform": self.platform,
            "verification_level": self.verification_level.value if isinstance(self.verification_level, VerificationLevel) else str(self.verification_level),
            "target": self.target.to_dict(),
            "engine_info": self.engine_info.to_dict(),
            "actions": [a.to_dict() if hasattr(a, "to_dict") else a for a in self.actions],
            "dom_snapshot_length": len(self.dom_snapshot) if self.dom_snapshot else 0,
            "screenshot_path": self.screenshot_path,
            "screenshot_sha256": self.screenshot_sha256,
            "console_messages": self.console_messages,
            "state_assertions": self.state_assertions,
            "process_ownership": self.process_ownership.to_dict() if self.process_ownership else None,
            "diagnostics": self.diagnostics,
            "metadata": self.metadata
        }
