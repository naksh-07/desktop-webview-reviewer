"""
Runtime package for Desktop WebView Reviewer.
Exposes foundational stateful daemon, session management, multi-dimensional target identity,
native OS supervision, coordinate transformation, and process supervision.
"""

from runtime.state import (
    SessionLifecycleState,
    ConnectionState,
    TargetPlane,
    Verdict,
    HealthState,
    DaemonLifecycleState,
)
from runtime.errors import (
    DesktopAutomationException,
    SessionNotFoundException,
    InvalidTargetException,
    TargetNotFoundException,
    TargetExitedException,
    TargetHungException,
    TargetMismatchException,
    StaleReferenceException,
    TransportErrorException,
    TransportTimeoutException,
    CapabilityUnavailableException,
    UnsupportedOperationException,
    InvalidCoordinateSpaceException,
    SidecarUnavailableException,
    ProtocolErrorException,
    CleanupErrorException,
    TargetAmbiguousException,
    WindowCloakedException,
    NativeModalBlockedException,
    InvalidStateTransitionError,
)
from runtime.references import Rect, ElementRef, ReferenceRegistry
from runtime.capability import (
    CapabilityMatrix,
    CapabilityId,
    CapabilityStatus,
    CapabilityCategory,
    CapabilityEntry,
)
from runtime.coordinate_transform import (
    CoordinateTransformer,
    CoordinateTransformContext,
    VirtualScreenBounds,
    MonitorDescriptor,
    MultiMonitorTopology,
)
from runtime.native_supervisor import (
    NativeOSSupervisor,
    WindowForensicReport,
    OcclusionState,
    CoveringWindowInfo,
    OcclusionReport,
    ModalState,
    ModalDialogInfo,
    NativeModalReport,
    VisibilityStatus,
    PhysicalVisibilityReport,
    ResponsivenessReport,
)
from runtime.process_supervisor import (
    ProcessSupervisor,
    Win32JobObject,
    SupervisedProcess,
)
from runtime.target_manager import (
    TargetManager,
    ProcessIdentity,
    WindowIdentity,
    WindowValidationResult,
    WebviewRuntimeIdentity,
    DebuggingEndpointIdentity,
    NativeAutomationContext,
)
from runtime.transport import (
    ITransport,
    NamedPipeTransport,
    MockTransport,
    PROTOCOL_VERSION,
)
from runtime.session_manager import (
    SessionManager,
    SessionConfig,
    SessionState,
)
from runtime.daemon import DesktopDaemon
from runtime.logging_events import (
    LifecycleEvent,
    EventAuditor,
    UntrustedUIText,
)
from runtime.cdp_transport import (
    ICDPTransport,
    WebSocketCDPTransport,
    MockCDPTransport,
)
from runtime.cdp_target import (
    CDPTargetInfo,
    EndpointProcessCorrelation,
    CDPTargetManager,
)
from runtime.frame_manager import (
    FrameContext,
    FrameManager,
)
from runtime.utility_world import (
    UtilityWorldManager,
    UTILITY_WORLD_NAME,
)
from runtime.ax_runtime import (
    AXNodeInfo,
    AXSnapshot,
    AccessibilityRuntime,
)
from runtime.webview_core import (
    WebviewGeometry,
    WebviewAutomationCore,
)

__all__ = [
    # State & Enums
    "SessionLifecycleState",
    "ConnectionState",
    "TargetPlane",
    "Verdict",
    "HealthState",
    "DaemonLifecycleState",
    "TargetLifecycleState",
    "FrameLifecycleState",
    "AXFreshnessStatus",
    "CDPConnectionStatus",
    # Errors
    "DesktopAutomationException",
    "SessionNotFoundException",
    "InvalidTargetException",
    "TargetNotFoundException",
    "TargetExitedException",
    "TargetHungException",
    "TargetMismatchException",
    "StaleReferenceException",
    "TransportErrorException",
    "TransportTimeoutException",
    "CapabilityUnavailableException",
    "UnsupportedOperationException",
    "InvalidCoordinateSpaceException",
    "SidecarUnavailableException",
    "ProtocolErrorException",
    "CleanupErrorException",
    "TargetAmbiguousException",
    "WindowCloakedException",
    "NativeModalBlockedException",
    "InvalidStateTransitionError",
    "CDPConnectionException",
    "CDPProtocolException",
    "CDPTimeoutException",
    "CDPTargetClosedException",
    "CDPTargetCrashedException",
    "CDPNavigationRaceException",
    "ExecutionContextDestroyedException",
    "FrameDetachedException",
    "FrameNotFoundException",
    "AXFreezeDetectedException",
    "CrossDomainFrameAccessException",
    # References
    "Rect",
    "ElementRef",
    "ReferenceRegistry",
    # Capability
    "CapabilityMatrix",
    "CapabilityId",
    "CapabilityStatus",
    "CapabilityCategory",
    "CapabilityEntry",
    # Coordinates
    "CoordinateTransformer",
    "CoordinateTransformContext",
    "VirtualScreenBounds",
    "MonitorDescriptor",
    "MultiMonitorTopology",
    # Native
    "NativeOSSupervisor",
    "WindowForensicReport",
    "OcclusionState",
    "CoveringWindowInfo",
    "OcclusionReport",
    "ModalState",
    "ModalDialogInfo",
    "NativeModalReport",
    "VisibilityStatus",
    "PhysicalVisibilityReport",
    "ResponsivenessReport",
    # Process
    "ProcessSupervisor",
    "Win32JobObject",
    "SupervisedProcess",
    # Targets
    "TargetManager",
    "ProcessIdentity",
    "WindowIdentity",
    "WindowValidationResult",
    "WebviewRuntimeIdentity",
    "DebuggingEndpointIdentity",
    "NativeAutomationContext",
    # Sidecar Transport
    "ITransport",
    "NamedPipeTransport",
    "MockTransport",
    "PROTOCOL_VERSION",
    # CDP Transport & Target Management (Phase 3)
    "ICDPTransport",
    "WebSocketCDPTransport",
    "MockCDPTransport",
    "CDPTargetInfo",
    "EndpointProcessCorrelation",
    "CDPTargetManager",
    "FrameContext",
    "FrameManager",
    "UtilityWorldManager",
    "UTILITY_WORLD_NAME",
    "AXNodeInfo",
    "AXSnapshot",
    "AccessibilityRuntime",
    "WebviewGeometry",
    "WebviewAutomationCore",
    # Session & Daemon
    "SessionManager",
    "SessionConfig",
    "SessionState",
    "DesktopDaemon",
    # Logging & Untrusted UI
    "LifecycleEvent",
    "EventAuditor",
    "UntrustedUIText",
]

