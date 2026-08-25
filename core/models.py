"""
Core data models and types for desktop-webview-reviewer.
"""

from dataclasses import dataclass, field
from enum import Enum
import sys
import time
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


class Verdict(str, Enum):
    """Tripartite verification verdict states."""
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class ScreenshotType(str, Enum):
    """Explicit provenance type for captured screenshots."""
    NATIVE_DESKTOP = "native_desktop"
    WEBVIEW_VIEWPORT = "webview_viewport"
    CDP_PAGE_CAPTURE = "cdp_page_capture"


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
    desktop_capture_path: Optional[str] = None
    native_capture_path: Optional[str] = None
    webview_capture_path: Optional[str] = None
    user_confirmation: bool = False
    input_delivery_verified: bool = False

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
            "metadata": self.metadata,
            "desktop_capture_path": self.desktop_capture_path,
            "native_capture_path": self.native_capture_path,
            "webview_capture_path": self.webview_capture_path,
            "user_confirmation": self.user_confirmation,
            "input_delivery_verified": self.input_delivery_verified
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
class WindowForensics:
    """Native OS window identity and forensic state."""
    hwnd: Optional[int] = None
    pid: Optional[int] = None
    executable: Optional[str] = None
    cmdline: List[str] = field(default_factory=list)
    window_title: str = ""
    class_name: str = ""
    window_visible: bool = False
    is_iconic: bool = False
    is_cloaked: bool = False
    is_real_gui: bool = False
    geometry: Dict[str, int] = field(default_factory=dict)
    hwnd_pid_matched: bool = False
    foreground_hwnd: Optional[int] = None
    foreground_match: bool = False
    monitor_rect: Dict[str, int] = field(default_factory=dict)
    intersection_area: int = 0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "pid": self.pid,
            "executable": self.executable,
            "cmdline": self.cmdline,
            "window_title": self.window_title,
            "class_name": self.class_name,
            "window_visible": self.window_visible,
            "is_iconic": self.is_iconic,
            "is_cloaked": self.is_cloaked,
            "is_real_gui": self.is_real_gui,
            "geometry": self.geometry,
            "hwnd_pid_matched": self.hwnd_pid_matched,
            "foreground_hwnd": self.foreground_hwnd,
            "foreground_match": self.foreground_match,
            "monitor_rect": self.monitor_rect,
            "intersection_area": self.intersection_area,
            "notes": self.notes
        }


@dataclass
class ScreenshotMetadata:
    """Screenshot provenance and cryptographic hash metadata."""
    screenshot_type: ScreenshotType = ScreenshotType.CDP_PAGE_CAPTURE
    screenshot_hash: str = ""
    path: str = ""
    source: str = ""
    dimensions: Dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "screenshot_type": self.screenshot_type.value if isinstance(self.screenshot_type, ScreenshotType) else str(self.screenshot_type),
            "screenshot_hash": self.screenshot_hash,
            "path": self.path,
            "source": self.source,
            "dimensions": self.dimensions,
            "timestamp": self.timestamp
        }


@dataclass
class EvidenceReport:
    """Collected verification evidence from an inspection session."""
    target: Target
    engine_info: EngineInfo
    session_id: Optional[str] = None
    framework: Optional[str] = None
    engine: Optional[str] = None
    platform: str = field(default_factory=lambda: sys.platform)
    verdict: Verdict = Verdict.UNVERIFIED
    verdict_reason: str = ""
    verification_level: VerificationLevel = VerificationLevel.RUNTIME_VERIFIED
    window_forensics: Optional[WindowForensics] = None
    screenshots: Dict[str, ScreenshotMetadata] = field(default_factory=dict)
    dom_snapshot: Optional[str] = None
    screenshot_path: Optional[str] = None
    screenshot_sha256: Optional[str] = None
    console_messages: List[Dict[str, Any]] = field(default_factory=list)
    state_assertions: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[ActionReceipt] = field(default_factory=list)
    process_ownership: Optional[ProcessOwnership] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    desktop_capture_path: Optional[str] = None
    native_capture_path: Optional[str] = None
    webview_capture_path: Optional[str] = None
    user_confirmation: bool = False
    input_delivery_verified: bool = False

    @property
    def hwnd(self) -> Optional[int]:
        return self.window_forensics.hwnd if self.window_forensics else None

    @property
    def pid(self) -> Optional[int]:
        if self.window_forensics and self.window_forensics.pid:
            return self.window_forensics.pid
        return self.process_ownership.pid if self.process_ownership else None

    @property
    def executable(self) -> Optional[str]:
        return self.window_forensics.executable if self.window_forensics else None

    @property
    def window_title(self) -> str:
        return self.window_forensics.window_title if self.window_forensics else ""

    @property
    def window_visible(self) -> bool:
        return self.window_forensics.window_visible if self.window_forensics else False

    @property
    def window_geometry(self) -> Dict[str, int]:
        return self.window_forensics.geometry if self.window_forensics else {}

    @property
    def cdp_port(self) -> int:
        return self.process_ownership.port if self.process_ownership else 9222

    @property
    def cdp_target(self) -> Dict[str, Any]:
        return self.target.to_dict()

    @property
    def screenshot_type(self) -> Optional[str]:
        if self.screenshots:
            first_val = next(iter(self.screenshots.values()))
            return first_val.screenshot_type.value if isinstance(first_val.screenshot_type, ScreenshotType) else str(first_val.screenshot_type)
        return ScreenshotType.CDP_PAGE_CAPTURE.value

    @property
    def screenshot_hash(self) -> Optional[str]:
        if self.screenshot_sha256:
            return self.screenshot_sha256
        if self.screenshots:
            first_val = next(iter(self.screenshots.values()))
            return first_val.screenshot_hash
        return None

    def to_dict(self) -> Dict[str, Any]:
        fw = self.framework or self.engine_info.framework or self.target.framework
        eng = self.engine or self.engine_info.engine or self.target.engine
        
        # Primary screenshot provenance values
        stype = self.screenshot_type
        shash = self.screenshot_hash or self.screenshot_sha256

        return {
            # Forensic Schema Extensions
            "session_id": self.session_id,
            "verdict": self.verdict.value if isinstance(self.verdict, Verdict) else str(self.verdict),
            "verdict_reason": self.verdict_reason,
            "hwnd": self.hwnd,
            "pid": self.pid,
            "executable": self.executable,
            "window_title": self.window_title,
            "window_visible": self.window_visible,
            "window_geometry": self.window_geometry,
            "cdp_port": self.cdp_port,
            "cdp_target": self.cdp_target,
            "screenshot_type": stype,
            "screenshot_hash": shash,
            "window_forensics": self.window_forensics.to_dict() if self.window_forensics else None,
            "screenshots": {k: v.to_dict() if hasattr(v, "to_dict") else v for k, v in self.screenshots.items()},

            # Core & Legacy Fields
            "framework": fw,
            "engine": eng,
            "platform": self.platform,
            "verification_level": self.verification_level.value if isinstance(self.verification_level, VerificationLevel) else str(self.verification_level),
            "target": self.target.to_dict(),
            "engine_info": self.engine_info.to_dict(),
            "actions": [a.to_dict() if hasattr(a, "to_dict") else a for a in self.actions],
            "dom_snapshot_length": len(self.dom_snapshot) if self.dom_snapshot else 0,
            "screenshot_path": self.screenshot_path,
            "screenshot_sha256": shash,
            "console_messages": self.console_messages,
            "state_assertions": self.state_assertions,
            "process_ownership": self.process_ownership.to_dict() if self.process_ownership else None,
            "diagnostics": self.diagnostics,
            "metadata": self.metadata,
            "desktop_capture_path": self.desktop_capture_path,
            "native_capture_path": self.native_capture_path,
            "webview_capture_path": self.webview_capture_path,
            "user_confirmation": self.user_confirmation,
            "input_delivery_verified": self.input_delivery_verified
        }
