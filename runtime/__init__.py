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
    NativeSupervisor,
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
from runtime.observation_models import (
    ObservationEpoch,
    GeometryObservation,
    VisibilityObservation,
    InteractionObservation,
    Observation,
    NativeElementObservation,
    WebElementObservation,
    FrameObservation,
    NativeObservation,
    WebObservation,
    ReconciliationObservation,
    DualPerspectiveSnapshot,
    RelationshipType,
    RoleSource,
    Certainty,
)
from runtime.semantic_normalization import (
    normalize_web_role,
    is_actionable_role,
    CANONICAL_ROLES,
    ACTIONABLE_ROLES,
)
from runtime.flaui_bridge import (
    UIAElementDTO,
    FlaUIBridge,
)
from runtime.native_observation import NativeObservationExtractor
from runtime.web_observation import WebObservationExtractor
from runtime.reconciliation import ContextReconciler
from runtime.observation_compaction import format_observation_yaml
from runtime.observation_pagination import ObservationPaginator
from runtime.observation_diff import (
    DiffItem,
    ObservationDiffResult,
    ObservationDiffer,
)
from runtime.observation_engine import ObservationEngine
from runtime.locators import (
    LocatorQuery,
    LocatorMatch,
    DeterministicLocatorEngine,
)
from runtime.actionability import (
    GateStatus,
    MotionStatus,
    OverallActionabilityStatus,
    GateReport,
    ActionabilityResult,
    ActionabilityEngine,
)
from runtime.observation_security import (
    sanitize_observed_text,
    create_safe_ui_envelope,
)
# Phase 5: Action Execution Engine
from runtime.action_models import (
    ActionType,
    DispatchMethod,
    ActionRiskLevel,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
    ActionTarget,
    ActionPreconditions,
    ActionRequest,
    ActionReceipt,
    ActionOutcome,
)
from runtime.native_input import (
    NativeInputDispatcher,
    MouseButton,
    KeyAction,
    DispatchedInputRecord,
)
from runtime.settlement import (
    SettlementType,
    SettlementResult,
    SettlementEngine,
)
from runtime.web_action_executor import WebActionExecutor
from runtime.native_action_executor import NativeActionExecutor
from runtime.action_engine import ActionExecutionEngine

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
    "NativeSupervisor",
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
    # Observation Models (Phase 4)
    "ObservationEpoch",
    "GeometryObservation",
    "VisibilityObservation",
    "InteractionObservation",
    "Observation",
    "NativeElementObservation",
    "WebElementObservation",
    "FrameObservation",
    "NativeObservation",
    "WebObservation",
    "ReconciliationObservation",
    "DualPerspectiveSnapshot",
    "RelationshipType",
    "RoleSource",
    "Certainty",
    # Semantic Normalization (Phase 4)
    "normalize_web_role",
    "is_actionable_role",
    "CANONICAL_ROLES",
    "ACTIONABLE_ROLES",
    # FlaUI Bridge & Native Observation (Phase 4)
    "UIAElementDTO",
    "FlaUIBridge",
    "NativeObservationExtractor",
    # Web Observation & Reconciliation (Phase 4)
    "WebObservationExtractor",
    "ContextReconciler",
    # Compaction, Pagination, Diff, Engine (Phase 4)
    "format_observation_yaml",
    "ObservationPaginator",
    "DiffItem",
    "ObservationDiffResult",
    "ObservationDiffer",
    "ObservationEngine",
    # Locators (Phase 4)
    "LocatorQuery",
    "LocatorMatch",
    "DeterministicLocatorEngine",
    # Actionability Engine (Phase 4)
    "GateStatus",
    "MotionStatus",
    "OverallActionabilityStatus",
    "GateReport",
    "ActionabilityResult",
    "ActionabilityEngine",
    # Security (Phase 4)
    "sanitize_observed_text",
    "create_safe_ui_envelope",
    # Session & Daemon
    "SessionManager",
    "SessionConfig",
    "SessionState",
    "DesktopDaemon",
    # Logging & Untrusted UI
    "LifecycleEvent",
    "EventAuditor",
    "UntrustedUIText",
    # Phase 5: Action Models & Engine
    "ActionType",
    "DispatchMethod",
    "ActionRiskLevel",
    "DispatchStatus",
    "ActionOutcomeStatus",
    "StateChangeClassification",
    "ActionTarget",
    "ActionPreconditions",
    "ActionRequest",
    "ActionReceipt",
    "ActionOutcome",
    "NativeInputDispatcher",
    "MouseButton",
    "KeyAction",
    "DispatchedInputRecord",
    "SettlementType",
    "SettlementResult",
    "SettlementEngine",
    "WebActionExecutor",
    "NativeActionExecutor",
    "ActionExecutionEngine",
]

