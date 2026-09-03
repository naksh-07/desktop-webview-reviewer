# Architecture Document 13: Component Contracts

**Document ID:** `docs/architecture/13_COMPONENT_CONTRACTS.md`  
**Status:** APPROVED (Phase 0 Deliverable)  
**Author:** Principal Software Architect  
**Target Repository:** `desktop-webview-reviewer`  
**Language Specification:** Python 3.11+ Type Annotations / Pydantic V2 Models  

---

## 1. Domain Types & Shared Models

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Any, Union
from datetime import datetime

class Verdict(str, Enum):
    """The authoritative tripartite verdict model."""
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"

class TargetPlane(str, Enum):
    """Execution plane classification for automation targets."""
    NATIVE_SHELL = "NATIVE_SHELL"
    NATIVE_MODAL = "NATIVE_MODAL"
    WEBVIEW_DOM = "WEBVIEW_DOM"
    UNKNOWN = "UNKNOWN"

class Capability(str, Enum):
    """Discrete capabilities negotiated across targets."""
    NATIVE_WIN32 = "NATIVE_WIN32"
    NATIVE_UIA3 = "NATIVE_UIA3"
    WEB_CDP = "WEB_CDP"
    WEB_DOM = "WEB_DOM"
    ACCESSIBILITY_TREE = "ACCESSIBILITY_TREE"
    HARDWARE_SCREENSHOT = "HARDWARE_SCREENSHOT"
    COMPOSITOR_SCREENSHOT = "COMPOSITOR_SCREENSHOT"
    CONSOLE_TELEMETRY = "CONSOLE_TELEMETRY"
    NETWORK_TELEMETRY = "NETWORK_TELEMETRY"
    PERFORMANCE_TRACE = "PERFORMANCE_TRACE"

@dataclass(frozen=True)
class Rect:
    """Screen or viewport bounding rectangle in integer pixels."""
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

@dataclass(frozen=True)
class ElementRef:
    """Synthetic, epoch-scoped interaction reference token."""
    epoch_id: int
    ref_id: str          # e.g., "w1e4", "n1e2"
    plane: TargetPlane
    role: str
    name: Optional[str]
    bounds: Rect

@dataclass
class ActionReceipt:
    """Deterministic confirmation of action execution."""
    action_name: str
    target_ref: str
    executed: bool
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: float = 0.0
    error: Optional[str] = None
    post_snapshot: Optional[str] = None
    observation_epoch: int = 0
```

---

## 2. Session Manager Contract

```python
from abc import ABC, abstractmethod

@dataclass
class SessionConfig:
    session_id: str
    target_executable: Optional[str] = None
    target_pid: Optional[int] = None
    target_hwnd: Optional[int] = None
    cdp_port: Optional[int] = None
    lease_timeout_sec: int = 300
    headless_audit: bool = False

@dataclass
class SessionState:
    session_id: str
    is_active: bool
    created_at: datetime
    last_heartbeat: datetime
    active_plane: TargetPlane
    bound_pid: int
    bound_hwnd: int
    bound_cdp_target: Optional[str]
    capabilities: set[Capability]

class ISessionManager(ABC):
    @abstractmethod
    async def create_session(self, config: SessionConfig) -> SessionState:
        """Initialize, bind, and register an automation session."""
        ...

    @abstractmethod
    async def get_session(self, session_id: str) -> SessionState:
        """Retrieve active session state; throws SessionNotFoundException if absent."""
        ...

    @abstractmethod
    async def heartbeat(self, session_id: str) -> None:
        """Extend the lease of an active session."""
        ...

    @abstractmethod
    async def terminate_session(self, session_id: str, kill_process: bool = True) -> None:
        """Release session resources, close sockets, and optionally terminate process tree."""
        ...

    @abstractmethod
    async def list_active_sessions(self) -> List[SessionState]:
        """Return all currently leased sessions."""
        ...
```

---

## 3. Target Manager Contract

```python
@dataclass
class ProcessIdentity:
    pid: int
    creation_time: datetime
    binary_path: str
    command_line: str
    is_elevated: bool

@dataclass
class WindowIdentity:
    hwnd: int
    pid: int
    title: str
    class_name: str
    bounds: Rect
    is_visible: bool
    is_cloaked: bool
    is_minimized: bool

@dataclass
class CDPIdentity:
    target_id: str
    type: str             # "page", "iframe", "worker"
    url: str
    title: str
    ws_url: str

class ITargetManager(ABC):
    @abstractmethod
    async def discover_targets(self) -> List[WindowIdentity]:
        """Scan desktop for accessible application windows."""
        ...

    @abstractmethod
    async def correlate_process(self, pid: int) -> ProcessIdentity:
        """Verify process existence, creation time, and security elevation."""
        ...

    @abstractmethod
    async def correlate_window(self, hwnd: int) -> WindowIdentity:
        """Perform full DWM and Win32 inspection of the specified window."""
        ...

    @abstractmethod
    async def correlate_cdp_targets(self, port: int) -> List[CDPIdentity]:
        """Query HTTP endpoint (http://127.0.0.1:port/json/list) and parse CDP targets."""
        ...

    @abstractmethod
    async def match_window_to_cdp(self, hwnd: int, cdp_targets: List[CDPIdentity]) -> Optional[CDPIdentity]:
        """Correlate a native window HWND with its embedded CDP page target."""
        ...
```

---

## 4. Native OS Supervisor Contract (Win32 Forensics)

```python
@dataclass
class WindowForensicReport:
    hwnd: int
    pid: int
    title: str
    class_name: str
    rect: Rect
    client_rect: Rect
    is_visible: bool
    is_iconic: bool               # Minimized
    is_cloaked: bool              # DWM Virtual Desktop or hidden
    has_focus: bool
    is_hung: bool                 # SendMessageTimeout(WM_NULL) check
    dpi_scaling: float            # Per-Monitor V2 scaling factor (e.g. 1.25)
    non_client_borders: Rect      # Drop shadow & title bar margins

class INativeSupervisor(ABC):
    @abstractmethod
    def inspect_window(self, hwnd: int) -> WindowForensicReport:
        """Inspect native window state via User32 and DWM APIs."""
        ...

    @abstractmethod
    def capture_window_screenshot(self, hwnd: int) -> bytes:
        """Capture hardware-rendered bitmap via PrintWindow or WGC; returns PNG bytes."""
        ...

    @abstractmethod
    def capture_desktop_crop(self, rect: Rect) -> bytes:
        """Capture physical desktop bounding box; returns PNG bytes."""
        ...

    @abstractmethod
    def bring_to_foreground(self, hwnd: int) -> bool:
        """Safely bring window to foreground without focus race conditions."""
        ...

    @abstractmethod
    def scan_modal_dialogs(self, parent_pid: int) -> List[WindowIdentity]:
        """Detect blocking Win32 modal dialogs (#32770) owned by the process tree."""
        ...
```

---

## 5. Native UIA3 Bridge Worker Contract (.NET 9 FlaUI Sidecar)

```python
@dataclass
class UIAElementDTO:
    automation_id: str
    name: str
    class_name: str
    control_type: str             # "Button", "Edit", "Pane", etc.
    bounds: Rect
    is_enabled: bool
    is_offscreen: bool
    supported_patterns: List[str] # ["Invoke", "Value", "SelectionItem"]

class IFlaUIBridge(ABC):
    @abstractmethod
    async def start_worker(self) -> None:
        """Spawn and handshake with the out-of-process .NET FlaUI bridge worker."""
        ...

    @abstractmethod
    async def query_tree(self, hwnd: int, max_depth: int = 5) -> List[UIAElementDTO]:
        """Traverse unmanaged UIA3 tree using native CacheRequest bulk property pre-fetching."""
        ...

    @abstractmethod
    async def invoke_element(self, automation_id: str) -> bool:
        """Execute InvokePattern.Invoke() on native UIA control."""
        ...

    @abstractmethod
    async def set_value(self, automation_id: str, value: str) -> bool:
        """Execute ValuePattern.SetValue() on native UIA control."""
        ...

    @abstractmethod
    async def stop_worker(self) -> None:
        """Cleanly terminate the sidecar process."""
        ...
```

---

## 6. Web Backend Contract (CDP Multiplexer & Utility Realm)

```python
class IWebviewBackend(ABC):
    @abstractmethod
    async def connect(self, ws_url: str) -> None:
        """Open WebSocket connection and initialize CDP domains."""
        ...

    @abstractmethod
    async def inject_utility_realm(self) -> int:
        """Execute Page.createIsolatedWorld('__utility_world__'); returns executionContextId."""
        ...

    @abstractmethod
    async def evaluate_script(self, expression: str, in_utility_world: bool = True) -> Any:
        """Evaluate JS expression in the isolated utility realm or main world."""
        ...

    @abstractmethod
    async def get_accessibility_tree(self) -> Dict[str, Any]:
        """Query Accessibility.getFullAXTree with interesting_only=True."""
        ...

    @abstractmethod
    async def capture_viewport(self) -> bytes:
        """Execute Page.captureScreenshot(format='png'); returns raw PNG bytes."""
        ...

    @abstractmethod
    async def dispatch_mouse_event(self, event_type: str, x: int, y: int, button: str = "left") -> None:
        """Dispatch Input.dispatchMouseEvent to Chromium rendering pipeline."""
        ...

    @abstractmethod
    async def dispatch_key_event(self, event_type: str, key: str, text: Optional[str] = None) -> None:
        """Dispatch Input.dispatchKeyEvent with keydown, char, and keyup event streams."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanly close WebSocket channels."""
        ...
```

---

## 7. Observation Engine & Ref Registry Contract

```python
@dataclass
class ObservationSnapshot:
    epoch_id: int
    plane: TargetPlane
    text_tree: str                 # Compact YAML / Markdown accessibility representation
    refs: Dict[str, ElementRef]    # Lookup table: "w1e4" -> ElementRef
    is_diff: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)

class IObservationEngine(ABC):
    @abstractmethod
    async def capture_snapshot(self, session_id: str, diff_only: bool = False) -> ObservationSnapshot:
        """Generate a compact semantic tree annotated with sequential interaction references."""
        ...

    @abstractmethod
    def resolve_ref(self, ref_id: str) -> ElementRef:
        """Resolve ref token; raises StaleReferenceException if epoch is expired."""
        ...

    @abstractmethod
    def invalidate_epoch(self) -> int:
        """Increment epoch counter and clear transient reference lookup tables."""
        ...
```

---

## 8. Action Engine & Actionability Pipeline Contract

```python
class ActionabilityStatus(str, Enum):
    READY = "READY"
    DETACHED = "DETACHED"
    HIDDEN = "HIDDEN"
    ANIMATING = "ANIMATING"
    DISABLED = "DISABLED"
    OCCLUDED = "OCCLUDED"

@dataclass
class ActionabilityCheckResult:
    status: ActionabilityStatus
    is_actionable: bool
    resolved_point: Optional[tuple[int, int]] = None
    diagnostics: Optional[str] = None

class IActionEngine(ABC):
    @abstractmethod
    async def check_actionability(self, ref: ElementRef, timeout_ms: int = 5000) -> ActionabilityCheckResult:
        """Run 5-point actionability gate: attached, visible, stable, enabled, un-occluded."""
        ...

    @abstractmethod
    async def click(self, ref_id: str, click_count: int = 1, timeout_ms: int = 5000) -> ActionReceipt:
        """Wait for actionability, dispatch click, wait for settlement, return receipt."""
        ...

    @abstractmethod
    async def type_text(self, ref_id: str, text: str, clear_existing: bool = True) -> ActionReceipt:
        """Focus target, optionally clear existing content, and type text via full event stream."""
        ...

    @abstractmethod
    async def press_key(self, key_combination: str) -> ActionReceipt:
        """Send hardware or synthetic keyboard combination (e.g., 'Enter', 'Control+Shift+S')."""
        ...
```

---

## 9. Assertion Engine Contract

```python
@dataclass
class AssertionResult:
    passed: bool
    assertion_type: str           # "text_equals", "is_visible", "attribute_matches"
    target_ref: str
    expected: Any
    actual: Any
    duration_ms: float
    error_message: Optional[str] = None

class IAssertionEngine(ABC):
    @abstractmethod
    async def assert_visible(self, ref_id: str, timeout_ms: int = 5000) -> AssertionResult:
        """Poll until element is visible on screen or timeout expires."""
        ...

    @abstractmethod
    async def assert_text(self, ref_id: str, expected_text: str, exact: bool = False, timeout_ms: int = 5000) -> AssertionResult:
        """Poll until element text matches expected value."""
        ...

    @abstractmethod
    async def assert_attribute(self, ref_id: str, attribute_name: str, expected_value: str, timeout_ms: int = 5000) -> AssertionResult:
        """Poll until element attribute matches expected value."""
        ...
```

---

## 10. Evidence Store Contract

```python
@dataclass
class EvidenceBundle:
    evidence_id: str
    session_id: str
    verdict: Verdict
    timestamp: datetime
    native_screenshot_path: str
    webview_screenshot_path: Optional[str]
    forensic_metadata_path: str
    action_timeline_path: str
    manifest_sha256: str

class IEvidenceStore(ABC):
    @abstractmethod
    async def record_screenshot(self, session_id: str, screenshot_type: str, image_bytes: bytes) -> str:
        """Save image artifact to session evidence directory; returns absolute path."""
        ...

    @abstractmethod
    async def record_action_receipt(self, session_id: str, receipt: ActionReceipt) -> None:
        """Append action receipt to chronological timeline trace."""
        ...

    @abstractmethod
    async def package_bundle(self, session_id: str, verdict: Verdict, summary: str) -> EvidenceBundle:
        """Hash all files (SHA-256), generate manifest evidence.json, and finalize bundle."""
        ...

    @abstractmethod
    async def get_bundle(self, evidence_id: str) -> EvidenceBundle:
        """Retrieve historical evidence bundle by ID."""
        ...
```

---

## 11. Security Policy Gate Contract

```python
class ISecurityPolicyGate(ABC):
    @abstractmethod
    def validate_executable_launch(self, executable_path: str) -> bool:
        """Validate binary against security allowlist and path traversal rules."""
        ...

    @abstractmethod
    def validate_filesystem_path(self, target_path: str, must_exist: bool = False) -> str:
        """Normalize and sandbox path to ensure it does not escape permitted working directories."""
        ...

    @abstractmethod
    def sanitize_ui_text_for_agent(self, raw_text: str) -> str:
        """Escape and wrap untrusted UI strings to prevent indirect prompt injection."""
        ...

    @abstractmethod
    def verify_uipi_elevation(self, target_pid: int) -> bool:
        """Check if target process runs at higher integrity level than daemon."""
        ...
```

---

## 12. Structured Exception Hierarchy

```python
class DesktopAutomationException(Exception):
    """Base class for all structured platform exceptions."""
    def __init__(self, message: str, recoverable: bool = False, agent_action_hint: Optional[str] = None):
        super().__init__(message)
        self.recoverable = recoverable
        self.agent_action_hint = agent_action_hint

class SessionNotFoundException(DesktopAutomationException):
    """Target session ID is unknown or expired."""
    def __init__(self, session_id: str):
        super().__init__(f"Session '{session_id}' not found or lease expired.", False, "Call desktop_launch or desktop_attach to start a new session.")

class TargetNotFoundException(DesktopAutomationException):
    """Specified HWND, PID, or element could not be resolved."""
    pass

class TargetAmbiguousException(DesktopAutomationException):
    """Locator resolved to multiple matching elements in strict mode."""
    def __init__(self, locator: str, match_count: int):
        super().__init__(f"Query '{locator}' resolved to {match_count} elements. Strict mode requires a unique match.", True, "Refine locator with get_by_role, index, or unique text.")

class StaleReferenceException(DesktopAutomationException):
    """Interaction ref belongs to an older observation epoch."""
    def __init__(self, ref_id: str, current_epoch: int):
        super().__init__(f"Ref '{ref_id}' is stale (active epoch: {current_epoch}).", True, "Request a fresh observation snapshot via desktop_inspect.")

class ActionNotReadyException(DesktopAutomationException):
    """Actionability preconditions failed to settle within timeout."""
    def __init__(self, ref_id: str, status: ActionabilityStatus, details: str):
        super().__init__(f"Element '{ref_id}' not actionable: {status} ({details}).", True, "Ensure element is visible, not animated, and not covered by modal dialogs.")

class WindowCloakedException(DesktopAutomationException):
    """Target window is cloaked by DWM (minimized, virtual desktop, or lock screen)."""
    def __init__(self, hwnd: int):
        super().__init__(f"Window HWND {hwnd} is cloaked by DWM.", True, "Bring window to foreground or switch to the appropriate desktop.")

class NativeModalBlockedException(DesktopAutomationException):
    """An unhandled native Win32 modal dialog is blocking the application."""
    def __init__(self, dialog_title: str, dialog_hwnd: int):
        super().__init__(f"Native modal dialog '{dialog_title}' (HWND {dialog_hwnd}) is blocking UI.", True, "Invoke desktop_handle_dialog to dismiss or interact with modal.")
```
