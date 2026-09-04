"""
Action Domain Models for Desktop WebView Reviewer (Architecture H).
Defines immutable data models for ActionRequest, ActionTarget, ActionPreconditions,
ActionReceipt, and ActionOutcome according to docs/architecture/17_ACTION_MODEL.md.
"""

from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any

from runtime.state import TargetPlane
from runtime.references import Rect


class ActionType(str, Enum):
    """Supported interaction primitives."""
    CLICK = "CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    RIGHT_CLICK = "RIGHT_CLICK"
    TYPE = "TYPE"
    KEY_PRESS = "KEY_PRESS"
    SCROLL = "SCROLL"
    FOCUS = "FOCUS"
    HOVER = "HOVER"
    WAIT = "WAIT"


class DispatchMethod(str, Enum):
    """Provenance tracking for the exact mechanism used to deliver input."""
    PHYSICAL_INPUT = "PHYSICAL_INPUT"
    CDP_INPUT = "CDP_INPUT"
    SEMANTIC_CONTROL_PATTERN = "SEMANTIC_CONTROL_PATTERN"
    SCRIPTED_FALLBACK = "SCRIPTED_FALLBACK"
    NATIVE_SENDINPUT = "NATIVE_SENDINPUT"


class ActionRiskLevel(str, Enum):
    """Deterministic safety classification of requested actions."""
    LOW_RISK = "LOW_RISK"
    INTERACTIVE = "INTERACTIVE"
    POTENTIALLY_DESTRUCTIVE = "POTENTIALLY_DESTRUCTIVE"


class DispatchStatus(str, Enum):
    """Immediate result of input dispatch placing events into the queue/stream."""
    DISPATCHED = "DISPATCHED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ActionOutcomeStatus(str, Enum):
    """Higher-level status of the action transaction cycle."""
    DISPATCHED = "DISPATCHED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class StateChangeClassification(str, Enum):
    """Classification of observed state change between pre- and post-action snapshots."""
    NO_EFFECT = "NO_EFFECT"
    STATE_CHANGED = "STATE_CHANGED"
    TARGET_DISAPPEARED = "TARGET_DISAPPEARED"
    NAVIGATED = "NAVIGATED"
    TARGET_CLOSED = "TARGET_CLOSED"
    MODAL_APPEARED = "MODAL_APPEARED"


@dataclass(frozen=True)
class ActionTarget:
    """Resolved and validated interaction target metadata."""
    session_id: str
    target_id: str
    reference: str                   # e.g. "w1e3" or "n1e4"
    plane: TargetPlane
    epoch: int
    affordance_point: Optional[Tuple[int, int]] = None
    coordinate_space: str = "VIEWPORT_LOGICAL" # or "SCREEN_CANONICAL"
    native_hwnd: Optional[int] = None
    cdp_target_id: Optional[str] = None
    frame_id: Optional[str] = None
    locator_recipe: Optional[Dict[str, Any]] = None
    role: str = ""
    name: Optional[str] = None
    bounds: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_id": self.target_id,
            "reference": self.reference,
            "plane": self.plane.value if isinstance(self.plane, TargetPlane) else str(self.plane),
            "epoch": self.epoch,
            "affordance_point": list(self.affordance_point) if self.affordance_point else None,
            "coordinate_space": self.coordinate_space,
            "native_hwnd": hex(self.native_hwnd) if self.native_hwnd else None,
            "cdp_target_id": self.cdp_target_id,
            "frame_id": self.frame_id,
            "locator_recipe": self.locator_recipe,
            "role": self.role,
            "name": self.name,
            "bounds": self.bounds.to_dict(),
        }


@dataclass(frozen=True)
class ActionPreconditions:
    """Forensic report of the immediate pre-dispatch gate revalidation."""
    attachment: bool
    visibility: bool
    motion_stable: bool
    enabled: bool
    unoccluded: bool
    physical_valid: bool
    modal_clear: bool
    epoch_match: bool
    is_all_passed: bool
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attachment": self.attachment,
            "visibility": self.visibility,
            "motion_stable": self.motion_stable,
            "enabled": self.enabled,
            "unoccluded": self.unoccluded,
            "physical_valid": self.physical_valid,
            "modal_clear": self.modal_clear,
            "epoch_match": self.epoch_match,
            "is_all_passed": self.is_all_passed,
            "reasons": list(self.reasons),
            "evaluated_at": self.evaluated_at,
        }


@dataclass(frozen=True)
class ActionRequest:
    """Agent or supervisor request to execute an interaction."""
    session_id: str
    reference: str                             # ElementRef token or target ID
    action_type: ActionType
    observation_epoch: int
    target_id: Optional[str] = None
    plane: Optional[TargetPlane] = None
    params: Dict[str, Any] = field(default_factory=dict)
    risk_level: ActionRiskLevel = ActionRiskLevel.INTERACTIVE
    timeout_ms: int = 5000
    settle_timeout_ms: int = 1500
    require_strict_locator: bool = True
    allow_stale_recovery: bool = True
    action_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "session_id": self.session_id,
            "reference": self.reference,
            "action_type": self.action_type.value if isinstance(self.action_type, ActionType) else str(self.action_type),
            "observation_epoch": self.observation_epoch,
            "target_id": self.target_id,
            "plane": self.plane.value if isinstance(self.plane, TargetPlane) else str(self.plane) if self.plane else None,
            "params": self.params,
            "risk_level": self.risk_level.value if isinstance(self.risk_level, ActionRiskLevel) else str(self.risk_level),
            "timeout_ms": self.timeout_ms,
            "settle_timeout_ms": self.settle_timeout_ms,
            "require_strict_locator": self.require_strict_locator,
            "allow_stale_recovery": self.allow_stale_recovery,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class ActionReceipt:
    """
    Authoritative, immutable record of an executed action dispatch.
    Records what the runtime attempted; does NOT prove target state outcome.
    """
    action_id: str
    session_id: str
    target_id: str
    epoch: int
    plane: TargetPlane
    reference: str
    action_type: ActionType
    dispatch_method: DispatchMethod
    dispatch_timestamp: float
    coordinates: Optional[Tuple[int, int]] = None
    native_hwnd: Optional[int] = None
    cdp_target_id: Optional[str] = None
    frame_id: Optional[str] = None
    recovered_from_ref: Optional[str] = None
    precondition_summary: str = ""
    dispatch_status: DispatchStatus = DispatchStatus.DISPATCHED
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "session_id": self.session_id,
            "target_id": self.target_id,
            "epoch": self.epoch,
            "plane": self.plane.value if isinstance(self.plane, TargetPlane) else str(self.plane),
            "reference": self.reference,
            "action_type": self.action_type.value if isinstance(self.action_type, ActionType) else str(self.action_type),
            "dispatch_method": self.dispatch_method.value if isinstance(self.dispatch_method, DispatchMethod) else str(self.dispatch_method),
            "dispatch_timestamp": self.dispatch_timestamp,
            "coordinates": list(self.coordinates) if self.coordinates else None,
            "native_hwnd": hex(self.native_hwnd) if self.native_hwnd else None,
            "cdp_target_id": self.cdp_target_id,
            "frame_id": self.frame_id,
            "recovered_from_ref": self.recovered_from_ref,
            "precondition_summary": self.precondition_summary,
            "dispatch_status": self.dispatch_status.value if isinstance(self.dispatch_status, DispatchStatus) else str(self.dispatch_status),
            "error": self.error,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ActionOutcome:
    """
    Comprehensive outcome of the action-observation transaction cycle:
    Action -> Dispatch Receipt -> Settle -> Post-Observation -> Outcome Classification.
    """
    action_id: str
    session_id: str
    receipt: ActionReceipt
    outcome_status: ActionOutcomeStatus
    state_change: StateChangeClassification
    pre_epoch: int
    post_epoch: int
    post_snapshot: Optional[Any] = None
    observation_diff: Optional[Any] = None
    modal_details: Optional[Dict[str, Any]] = None
    navigation_url: Optional[str] = None
    duration_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    verdict: Optional[str] = None
    manifest: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "session_id": self.session_id,
            "receipt": self.receipt.to_dict(),
            "outcome_status": self.outcome_status.value if isinstance(self.outcome_status, ActionOutcomeStatus) else str(self.outcome_status),
            "state_change": self.state_change.value if isinstance(self.state_change, StateChangeClassification) else str(self.state_change),
            "pre_epoch": self.pre_epoch,
            "post_epoch": self.post_epoch,
            "has_post_snapshot": self.post_snapshot is not None,
            "has_diff": self.observation_diff is not None,
            "modal_details": self.modal_details,
            "navigation_url": self.navigation_url,
            "duration_ms": self.duration_ms,
            "details": self.details,
            "timestamp": self.timestamp,
            "verdict": self.verdict,
            "has_manifest": self.manifest is not None,
        }
