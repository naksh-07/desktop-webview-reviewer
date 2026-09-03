"""
Authoritative state models, enums, and lifecycle state machines for Desktop WebView Reviewer.
Explicitly defines lifecycle transitions and prevents hidden global mutable sources of truth.
"""

from __future__ import annotations
from enum import Enum
from typing import Dict, Set, List
from runtime.errors import InvalidStateTransitionError


class SessionLifecycleState(str, Enum):
    """
    Explicit lifecycle states for a desktop automation session.
    Transitions must be verified against the state machine.
    """
    CREATED = "CREATED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ACTIVE = "ACTIVE"
    DISCONNECTING = "DISCONNECTING"
    CLOSED = "CLOSED"

    # Explicit failure states
    FAILED = "FAILED"
    ERROR = "ERROR"
    ABORTED = "ABORTED"

    @classmethod
    def valid_transitions(cls) -> Dict[SessionLifecycleState, Set[SessionLifecycleState]]:
        """Maps each state to the set of permissible target states."""
        return {
            cls.CREATED: {cls.CONNECTING, cls.FAILED, cls.ABORTED, cls.CLOSED},
            cls.CONNECTING: {cls.CONNECTED, cls.FAILED, cls.ABORTED, cls.CLOSED},
            cls.CONNECTED: {cls.ACTIVE, cls.DISCONNECTING, cls.FAILED, cls.ABORTED, cls.CLOSED},
            cls.ACTIVE: {cls.ACTIVE, cls.DISCONNECTING, cls.ERROR, cls.FAILED, cls.ABORTED, cls.CLOSED},
            cls.DISCONNECTING: {cls.CLOSED, cls.FAILED, cls.ABORTED},
            cls.ERROR: {cls.DISCONNECTING, cls.FAILED, cls.CLOSED},
            cls.FAILED: {cls.CLOSED},
            cls.ABORTED: {cls.CLOSED},
            cls.CLOSED: set(),  # Terminal state
        }

    def can_transition_to(self, target: SessionLifecycleState) -> bool:
        """Returns True if transition to target state is legally permissible."""
        return target in self.valid_transitions().get(self, set())

    def transition_to(self, target: SessionLifecycleState) -> SessionLifecycleState:
        """
        Validates and transitions to target state.
        Raises InvalidStateTransitionError if illegal.
        """
        allowed = [s.value for s in self.valid_transitions().get(self, set())]
        if not self.can_transition_to(target):
            raise InvalidStateTransitionError(self.value, target.value, allowed)
        return target

    @property
    def is_terminal(self) -> bool:
        """Returns True if session has reached a closed/final state."""
        return self == SessionLifecycleState.CLOSED

    @property
    def is_operational(self) -> bool:
        """Returns True if session can accept user actions."""
        return self == SessionLifecycleState.ACTIVE


class ConnectionState(str, Enum):
    """Network / transport connection status to target or sidecars."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


class TargetPlane(str, Enum):
    """Target application execution plane classification."""
    NATIVE_SHELL = "NATIVE_SHELL"
    NATIVE_MODAL = "NATIVE_MODAL"
    WEBVIEW_DOM = "WEBVIEW_DOM"
    UNKNOWN = "UNKNOWN"


class Verdict(str, Enum):
    """Authoritative tripartite forensic verdict model."""
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class HealthState(str, Enum):
    """Health / responsiveness condition of target window and process."""
    HEALTHY = "HEALTHY"
    UNRESPONSIVE = "UNRESPONSIVE"
    HUNG = "HUNG"
    TERMINATED = "TERMINATED"
    UNKNOWN = "UNKNOWN"


class DaemonLifecycleState(str, Enum):
    """Lifecycle progression of the long-lived desktop daemon."""
    UNINITIALIZED = "UNINITIALIZED"
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    STOPPED = "STOPPED"


class TargetLifecycleState(str, Enum):
    """Lifecycle states of an inspectable CDP target."""
    CREATED = "CREATED"
    ATTACHED = "ATTACHED"
    DETACHED = "DETACHED"
    NAVIGATED = "NAVIGATED"
    CRASHED = "CRASHED"
    CLOSED = "CLOSED"


class FrameLifecycleState(str, Enum):
    """Lifecycle states of a document frame within a webview target."""
    ATTACHED = "ATTACHED"
    NAVIGATED = "NAVIGATED"
    DETACHED = "DETACHED"


class AXFreshnessStatus(str, Enum):
    """Authoritative freshness status of the Chromium accessibility tree."""
    FRESH = "FRESH"
    SUSPECTED_STALE = "SUSPECTED_STALE"
    UNKNOWN = "UNKNOWN"


class CDPConnectionStatus(str, Enum):
    """Status of a Chrome DevTools Protocol WebSocket transport connection."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    DEGRADED = "DEGRADED"
    CLOSED = "CLOSED"

