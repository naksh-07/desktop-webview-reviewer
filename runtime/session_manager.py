"""
Stateful Session Manager for Desktop WebView Reviewer.
Sole authoritative owner of desktop automation sessions. Enforces explicit lifecycle
state transitions, lease tracking, and multi-session isolation with zero global state leaks.
"""

from __future__ import annotations
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set

from runtime.state import (
    SessionLifecycleState,
    ConnectionState,
    TargetPlane,
    HealthState,
)
from runtime.references import ReferenceRegistry
from runtime.capability import CapabilityMatrix
from runtime.target_manager import (
    ProcessIdentity,
    WindowIdentity,
    WebviewRuntimeIdentity,
    DebuggingEndpointIdentity,
)
from runtime.errors import (
    SessionNotFoundException,
    InvalidStateTransitionError,
)

logger = logging.getLogger("desktop_webview.session_manager")


@dataclass
class SessionConfig:
    """Configuration used to instantiate an automation session."""
    session_id: Optional[str] = None
    target_executable: Optional[str] = None
    target_cmdline: List[str] = field(default_factory=list)
    target_pid: Optional[int] = None
    target_hwnd: Optional[int] = None
    cdp_port: Optional[int] = None
    lease_timeout_sec: int = 300
    headless_audit: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    """Authoritative in-memory state of an active automation session."""
    session_id: str
    lifecycle_state: SessionLifecycleState
    connection_state: ConnectionState
    active_plane: TargetPlane
    created_at: datetime
    updated_at: datetime
    last_heartbeat: datetime
    lease_timeout_sec: int = 300

    # Target identities
    target_process: Optional[ProcessIdentity] = None
    target_window: Optional[WindowIdentity] = None
    target_runtime: Optional[WebviewRuntimeIdentity] = None
    target_endpoint: Optional[DebuggingEndpointIdentity] = None

    # Subsystems
    reference_registry: ReferenceRegistry = field(init=False)
    capabilities: CapabilityMatrix = field(default_factory=CapabilityMatrix)

    # Diagnostic & Cleanup state
    diagnostic_state: Dict[str, Any] = field(default_factory=dict)
    cleanup_state: Dict[str, Any] = field(default_factory=dict)

    # Webview Automation Core & Engine Subsystems
    webview_core: Optional[Any] = None
    observation_engine: Optional[Any] = None
    action_engine: Optional[Any] = None
    actionability_engine: Optional[Any] = None
    native_supervisor: Optional[Any] = None
    flaui_bridge: Optional[Any] = None
    evidence_store: Optional[Any] = None
    verification_engine: Optional[Any] = None
    trace_engine: Optional[Any] = None
    harness_service: Optional[Any] = None
    last_outcome: Optional[Any] = None
    executed_actions: Dict[str, Any] = field(default_factory=dict)
    circuit_breaker: Optional[Any] = None
    recovery_engine: Optional[Any] = None
    diagnostic_aggregator: Optional[Any] = None
    specialist_dispatcher: Optional[Any] = None

    def __post_init__(self):
        self.reference_registry = ReferenceRegistry(session_id=self.session_id)
        if self.trace_engine is None:
            from runtime.trace_engine import DesktopTraceEngine
            self.trace_engine = DesktopTraceEngine(session_id=self.session_id)
        if self.circuit_breaker is None:
            from runtime.recovery_engine import CircuitBreaker
            self.circuit_breaker = CircuitBreaker()
        if self.recovery_engine is None:
            from runtime.recovery_engine import RecoveryEngine
            self.recovery_engine = RecoveryEngine(circuit_breaker=self.circuit_breaker)
        if self.diagnostic_aggregator is None:
            from runtime.diagnostics import DiagnosticAggregator
            self.diagnostic_aggregator = DiagnosticAggregator(trace_engine=self.trace_engine)
        if self.specialist_dispatcher is None:
            from runtime.specialist_dispatcher import SpecialistDispatcher
            self.specialist_dispatcher = SpecialistDispatcher()

    @property
    def is_active(self) -> bool:
        return self.lifecycle_state == SessionLifecycleState.ACTIVE

    @property
    def is_closed(self) -> bool:
        return self.lifecycle_state in (SessionLifecycleState.CLOSED, SessionLifecycleState.TERMINATED)

    @property
    def current_epoch(self) -> int:
        return self.reference_registry.current_epoch

    def is_lease_expired(self, now: Optional[datetime] = None) -> bool:
        """Checks if session lease has expired without heartbeat."""
        current_time = now or datetime.utcnow()
        elapsed = (current_time - self.last_heartbeat).total_seconds()
        return elapsed > self.lease_timeout_sec

    def transition_lifecycle(self, target: SessionLifecycleState) -> None:
        """Transitions to target lifecycle state. Enforces state machine validation."""
        self.lifecycle_state = self.lifecycle_state.transition_to(target)
        self.updated_at = datetime.utcnow()
        logger.debug(f"Session {self.session_id} state transition -> {self.lifecycle_state.value}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "lifecycle_state": self.lifecycle_state.value,
            "connection_state": self.connection_state.value,
            "active_plane": self.active_plane.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "lease_timeout_sec": self.lease_timeout_sec,
            "current_epoch": self.current_epoch,
            "target_process": self.target_process.to_dict() if self.target_process else None,
            "target_window": self.target_window.to_dict() if self.target_window else None,
            "target_runtime": self.target_runtime.to_dict() if self.target_runtime else None,
            "target_endpoint": self.target_endpoint.to_dict() if self.target_endpoint else None,
            "capabilities": self.capabilities.to_dict(),
            "diagnostic_state": self.diagnostic_state,
        }


class SessionManager:
    """
    Manages the lifecycle, leases, and resource boundaries of all active sessions.
    Guarantees full concurrency without cross-session interference.
    """

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def create_session(self, config: SessionConfig) -> SessionState:
        """
        Instantiates and registers a new session in CREATED state.
        """
        async with self._lock:
            session_id = config.session_id or str(uuid.uuid4())
            if session_id in self._sessions:
                raise ValueError(f"Session with ID '{session_id}' already exists")

            now = datetime.utcnow()
            session = SessionState(
                session_id=session_id,
                lifecycle_state=SessionLifecycleState.CREATED,
                connection_state=ConnectionState.DISCONNECTED,
                active_plane=TargetPlane.UNKNOWN,
                created_at=now,
                updated_at=now,
                last_heartbeat=now,
                lease_timeout_sec=config.lease_timeout_sec,
            )

            self._sessions[session_id] = session
            logger.info(f"Created session {session_id} in state {session.lifecycle_state.value}")
            return session

    def get_session(self, session_id: str) -> SessionState:
        """
        Retrieves an active or known session.
        Raises SessionNotFoundException if absent.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise SessionNotFoundException(session_id)
        return session

    def has_session(self, session_id: str) -> bool:
        """Checks if a session ID exists in registry."""
        return session_id in self._sessions

    async def connect_session(self, session_id: str) -> SessionState:
        """Transitions session: CREATED -> CONNECTING -> CONNECTED."""
        session = self.get_session(session_id)
        async with self._lock:
            session.transition_lifecycle(SessionLifecycleState.CONNECTING)
            session.connection_state = ConnectionState.CONNECTING
            # Perform connection settling
            session.transition_lifecycle(SessionLifecycleState.CONNECTED)
            session.connection_state = ConnectionState.CONNECTED
            return session

    async def activate_session(self, session_id: str, plane: TargetPlane = TargetPlane.NATIVE_SHELL) -> SessionState:
        """Transitions session: CONNECTED -> ACTIVE."""
        session = self.get_session(session_id)
        async with self._lock:
            session.transition_lifecycle(SessionLifecycleState.ACTIVE)
            session.active_plane = plane
            return session

    async def mark_degraded(self, session_id: str, reason: str = "degraded_subsystem") -> SessionState:
        """Transitions session to DEGRADED state when a non-fatal fault occurs (e.g. AX freeze or CDP socket drop)."""
        session = self.get_session(session_id)
        async with self._lock:
            session.transition_lifecycle(SessionLifecycleState.DEGRADED)
            session.diagnostic_state["degraded_reason"] = reason
            logger.warning(f"Session {session_id} entered DEGRADED state: {reason}")
            return session

    async def mark_target_lost(self, session_id: str, reason: str = "target_process_or_window_lost") -> SessionState:
        """Transitions session to TARGET_LOST state when target window or process exits unexpectedly."""
        session = self.get_session(session_id)
        async with self._lock:
            session.transition_lifecycle(SessionLifecycleState.TARGET_LOST)
            session.diagnostic_state["target_lost_reason"] = reason
            logger.error(f"Session {session_id} entered TARGET_LOST state: {reason}")
            return session

    async def mark_recoverable(self, session_id: str, reason: str = "reconnection_candidate") -> SessionState:
        """Transitions session to RECOVERABLE state awaiting explicit agent or supervisor re-attach."""
        session = self.get_session(session_id)
        async with self._lock:
            session.transition_lifecycle(SessionLifecycleState.RECOVERABLE)
            session.diagnostic_state["recoverable_reason"] = reason
            logger.info(f"Session {session_id} entered RECOVERABLE state: {reason}")
            return session

    async def mark_recovered(self, session_id: str) -> SessionState:
        """Transitions session back to ACTIVE state following verified reconnection."""
        session = self.get_session(session_id)
        async with self._lock:
            session.transition_lifecycle(SessionLifecycleState.ACTIVE)
            session.diagnostic_state.pop("target_lost_reason", None)
            session.diagnostic_state.pop("degraded_reason", None)
            session.diagnostic_state.pop("recoverable_reason", None)
            logger.info(f"Session {session_id} successfully RECOVERED to ACTIVE state")
            return session

    async def heartbeat(self, session_id: str) -> None:
        """Extends session lease timeout."""
        session = self.get_session(session_id)
        if session.is_closed:
            raise SessionNotFoundException(session_id)
        session.last_heartbeat = datetime.utcnow()
        session.updated_at = datetime.utcnow()

    async def close_session(self, session_id: str, reason: str = "normal_closure") -> SessionState:
        """
        Cleanly closes a session: ACTIVE/CONNECTED/CREATED -> DISCONNECTING -> CLOSED.
        Idempotent: if already CLOSED, returns without error.
        """
        session = self.get_session(session_id)
        async with self._lock:
            if session.lifecycle_state == SessionLifecycleState.CLOSED:
                logger.debug(f"Session {session_id} is already CLOSED (idempotent call)")
                return session

            if session.lifecycle_state.can_transition_to(SessionLifecycleState.DISCONNECTING):
                session.transition_lifecycle(SessionLifecycleState.DISCONNECTING)
                session.connection_state = ConnectionState.DISCONNECTED

            # Cleanly disconnect webview automation core if present
            if session.webview_core:
                try:
                    await session.webview_core.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting webview_core for session {session_id}: {e}")

            session.transition_lifecycle(SessionLifecycleState.CLOSED)
            session.connection_state = ConnectionState.DISCONNECTED
            session.cleanup_state["closed_at"] = datetime.utcnow().isoformat()
            session.cleanup_state["close_reason"] = reason
            logger.info(f"Closed session {session_id} cleanly ({reason})")
            return session

    async def list_active_sessions(self) -> List[SessionState]:
        """Returns all sessions currently in non-terminal states."""
        async with self._lock:
            return [s for s in self._sessions.values() if not s.is_closed]

    async def list_all_sessions(self) -> List[SessionState]:
        """Returns all sessions regardless of state."""
        async with self._lock:
            return list(self._sessions.values())

    async def prune_expired_sessions(self) -> List[str]:
        """Prunes sessions whose lease timeout has passed without a heartbeat."""
        now = datetime.utcnow()
        pruned: List[str] = []
        async with self._lock:
            for s_id, session in list(self._sessions.items()):
                if not session.is_closed and session.is_lease_expired(now):
                    logger.warning(f"Session {s_id} lease expired (timeout: {session.lease_timeout_sec}s). Closing.")
                    try:
                        session.transition_lifecycle(SessionLifecycleState.DISCONNECTING)
                    except InvalidStateTransitionError:
                        pass
                    try:
                        session.transition_lifecycle(SessionLifecycleState.CLOSED)
                    except InvalidStateTransitionError:
                        session.lifecycle_state = SessionLifecycleState.CLOSED
                    session.cleanup_state["close_reason"] = "lease_timeout"
                    pruned.append(s_id)
        return pruned
