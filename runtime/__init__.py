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
)
from runtime.native_supervisor import NativeOSSupervisor, WindowForensicReport
from runtime.process_supervisor import (
    ProcessSupervisor,
    Win32JobObject,
    SupervisedProcess,
)
from runtime.target_manager import (
    TargetManager,
    ProcessIdentity,
    WindowIdentity,
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

__all__ = [
    # State & Enums
    "SessionLifecycleState",
    "ConnectionState",
    "TargetPlane",
    "Verdict",
    "HealthState",
    "DaemonLifecycleState",
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
    # Native
    "NativeOSSupervisor",
    "WindowForensicReport",
    # Process
    "ProcessSupervisor",
    "Win32JobObject",
    "SupervisedProcess",
    # Targets
    "TargetManager",
    "ProcessIdentity",
    "WindowIdentity",
    "WebviewRuntimeIdentity",
    "DebuggingEndpointIdentity",
    "NativeAutomationContext",
    # Transport
    "ITransport",
    "NamedPipeTransport",
    "MockTransport",
    "PROTOCOL_VERSION",
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
