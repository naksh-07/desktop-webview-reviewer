"""
Observation Data Models for Desktop WebView Reviewer (Architecture H).
Defines the dual-perspective observation domain models preserving physical reality primacy,
explicit provenance, and strict epoch scoping without creating a false universal element abstraction.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

from runtime.references import Rect
from runtime.state import TargetPlane, AXFreshnessStatus


class RelationshipType(str, Enum):
    """Spatial and structural relationships between native windows and webview targets."""
    CONTAINS = "CONTAINS"
    HOSTS = "HOSTS"
    OVERLAPS = "OVERLAPS"
    ALIGNS_WITH = "ALIGNS_WITH"
    UNKNOWN = "UNKNOWN"


class RoleSource(str, Enum):
    """Provenance indicator for normalized control roles."""
    ACCESSIBILITY = "ACCESSIBILITY"
    DOM = "DOM"
    INFERRED = "INFERRED"


class Certainty(str, Enum):
    """Confidence / certainty assessment."""
    DEFINITIVE = "DEFINITIVE"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    CONTRADICTORY = "CONTRADICTORY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ObservationEpoch:
    """Monotonic observation epoch identifier and metadata."""
    epoch_id: int
    session_id: str
    target_id: Optional[str]
    created_at: float = field(default_factory=time.time)
    reason: str = "snapshot"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "session_id": self.session_id,
            "target_id": self.target_id,
            "created_at": self.created_at,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GeometryObservation:
    """Authoritative geometric measurements of an observed element."""
    bounds: Rect
    screen_bounds: Rect
    client_rect: Optional[Rect] = None
    dpr: float = 1.0
    is_in_viewport: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bounds": self.bounds.to_dict(),
            "screen_bounds": self.screen_bounds.to_dict(),
            "client_rect": self.client_rect.to_dict() if self.client_rect else None,
            "dpr": self.dpr,
            "is_in_viewport": self.is_in_viewport,
        }


@dataclass(frozen=True)
class VisibilityObservation:
    """Multi-layer visibility assessment preserving Physical Reality Primacy."""
    attached: bool
    visible: bool
    in_viewport: bool
    physically_occluded: bool
    minimized: bool = False
    cloaked: bool = False
    modal_blocked: bool = False
    certainty: Certainty = Certainty.DEFINITIVE
    contradiction_detected: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_interactable(self) -> bool:
        return (
            self.attached
            and self.visible
            and self.in_viewport
            and not self.physically_occluded
            and not self.minimized
            and not self.cloaked
            and not self.modal_blocked
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attached": self.attached,
            "visible": self.visible,
            "in_viewport": self.in_viewport,
            "physically_occluded": self.physically_occluded,
            "minimized": self.minimized,
            "cloaked": self.cloaked,
            "modal_blocked": self.modal_blocked,
            "certainty": self.certainty.value,
            "contradiction_detected": self.contradiction_detected,
            "is_interactable": self.is_interactable,
            "details": self.details,
        }


@dataclass(frozen=True)
class InteractionObservation:
    """Interaction affordances and preferred point for an actionable target."""
    is_enabled: bool
    is_focused: bool = False
    is_selected: bool = False
    is_checked: Optional[bool] = None
    is_expanded: Optional[bool] = None
    affordance_point: Optional[Tuple[int, int]] = None
    supported_actions: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_enabled": self.is_enabled,
            "is_focused": self.is_focused,
            "is_selected": self.is_selected,
            "is_checked": self.is_checked,
            "is_expanded": self.is_expanded,
            "affordance_point": list(self.affordance_point) if self.affordance_point else None,
            "supported_actions": list(self.supported_actions),
        }


# -----------------------------------------------------------------------------
# Base Observation Model
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Observation:
    """
    Authoritative base observation record.
    Every observation MUST preserve session_id, epoch, timestamp, plane, target,
    reference, and confidence.
    """
    session_id: str
    observation_epoch: int
    timestamp: float
    source_plane: TargetPlane
    target_id: str
    reference: str                   # e.g., "w1e1" or "n1e1"
    confidence: Certainty = Certainty.HIGH

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "observation_epoch": self.observation_epoch,
            "timestamp": self.timestamp,
            "source_plane": self.source_plane.value if isinstance(self.source_plane, TargetPlane) else str(self.source_plane),
            "target_id": self.target_id,
            "reference": self.reference,
            "confidence": self.confidence.value,
        }


# -----------------------------------------------------------------------------
# Perspective Elements (Strict Separation — No UniversalUIElement)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class NativeElementObservation(Observation):
    """
    Element observation grounded strictly in Native Win32 / UIA3 perspective.
    Maintains native-specific identities without pretending to be a web DOM node.
    """
    control_type: str = "Window"      # "Button", "Edit", "MenuItem", etc.
    name: Optional[str] = None
    automation_id: Optional[str] = None
    class_name: Optional[str] = None
    hwnd: Optional[int] = None
    bounds: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    geometry: Optional[GeometryObservation] = None
    visibility: Optional[VisibilityObservation] = None
    interaction: Optional[InteractionObservation] = None
    supported_patterns: Tuple[str, ...] = field(default_factory=tuple)
    depth: int = 0
    raw_properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "control_type": self.control_type,
            "name": self.name,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "hwnd": hex(self.hwnd) if self.hwnd else None,
            "bounds": self.bounds.to_dict(),
            "geometry": self.geometry.to_dict() if self.geometry else None,
            "visibility": self.visibility.to_dict() if self.visibility else None,
            "interaction": self.interaction.to_dict() if self.interaction else None,
            "supported_patterns": list(self.supported_patterns),
            "depth": self.depth,
        })
        return d


@dataclass(frozen=True)
class WebElementObservation(Observation):
    """
    Element observation grounded strictly in Webview CDP / DOM / AX perspective.
    Maintains web-specific identities without pretending to be an OS HWND control.
    """
    role: str = "generic"             # Raw accessibility or DOM role
    normalized_role: str = "generic"  # Canonical normalized role
    role_source: RoleSource = RoleSource.DOM
    accessible_name: Optional[str] = None
    visible_text: Optional[str] = None
    placeholder: Optional[str] = None
    value_summary: Optional[str] = None
    tag_name: str = "div"
    input_type: Optional[str] = None
    frame_id: str = ""
    backend_node_id: Optional[int] = None
    bounds: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    geometry: Optional[GeometryObservation] = None
    visibility: Optional[VisibilityObservation] = None
    interaction: Optional[InteractionObservation] = None
    depth: int = 0
    attributes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "role": self.role,
            "normalized_role": self.normalized_role,
            "role_source": self.role_source.value,
            "accessible_name": self.accessible_name,
            "visible_text": self.visible_text,
            "placeholder": self.placeholder,
            "value_summary": self.value_summary,
            "tag_name": self.tag_name,
            "input_type": self.input_type,
            "frame_id": self.frame_id,
            "backend_node_id": self.backend_node_id,
            "bounds": self.bounds.to_dict(),
            "geometry": self.geometry.to_dict() if self.geometry else None,
            "visibility": self.visibility.to_dict() if self.visibility else None,
            "interaction": self.interaction.to_dict() if self.interaction else None,
            "depth": self.depth,
            "attributes": self.attributes,
        })
        return d


@dataclass(frozen=True)
class FrameObservation:
    """Authoritative observation of an embedded webview frame context."""
    frame_id: str
    parent_frame_id: Optional[str]
    url: str
    security_origin: str
    is_accessible: bool
    depth: int
    element_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "parent_frame_id": self.parent_frame_id,
            "url": self.url,
            "security_origin": self.security_origin,
            "is_accessible": self.is_accessible,
            "depth": self.depth,
            "element_count": self.element_count,
        }


# -----------------------------------------------------------------------------
# Plane Snapshot Containers
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class NativeObservation:
    """Comprehensive snapshot of the Native OS perspective."""
    session_id: str
    epoch: int
    timestamp: float
    hwnd: int
    title: str
    class_name: str
    pid: int
    bounds: Rect
    client_bounds: Rect
    is_visible: bool
    is_minimized: bool
    is_cloaked: bool
    is_responsive: bool
    elements: Tuple[NativeElementObservation, ...] = field(default_factory=tuple)
    modal_dialogs: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    confidence: Certainty = Certainty.DEFINITIVE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
            "hwnd": hex(self.hwnd),
            "title": self.title,
            "class_name": self.class_name,
            "pid": self.pid,
            "bounds": self.bounds.to_dict(),
            "client_bounds": self.client_bounds.to_dict(),
            "is_visible": self.is_visible,
            "is_minimized": self.is_minimized,
            "is_cloaked": self.is_cloaked,
            "is_responsive": self.is_responsive,
            "elements_count": len(self.elements),
            "elements": [e.to_dict() for e in self.elements],
            "modal_dialogs": list(self.modal_dialogs),
            "confidence": self.confidence.value,
        }


@dataclass(frozen=True)
class WebObservation:
    """Comprehensive snapshot of the Webview perspective."""
    session_id: str
    epoch: int
    timestamp: float
    target_id: str
    target_title: str
    target_url: str
    root_frame_id: str
    frames: Tuple[FrameObservation, ...] = field(default_factory=tuple)
    elements: Tuple[WebElementObservation, ...] = field(default_factory=tuple)
    ax_freshness: AXFreshnessStatus = AXFreshnessStatus.FRESH
    dom_count: Optional[int] = None
    ax_count: Optional[int] = None
    confidence: Certainty = Certainty.HIGH

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
            "target_id": self.target_id,
            "target_title": self.target_title,
            "target_url": self.target_url,
            "root_frame_id": self.root_frame_id,
            "frames": [f.to_dict() for f in self.frames],
            "elements_count": len(self.elements),
            "elements": [e.to_dict() for e in self.elements],
            "ax_freshness": self.ax_freshness.value,
            "dom_count": self.dom_count,
            "ax_count": self.ax_count,
            "confidence": self.confidence.value,
        }


# -----------------------------------------------------------------------------
# Reconciliation Model
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class ReconciliationObservation:
    """
    Explicit cross-perspective relationship establishing spatial and semantic links
    between Native Windows and Webview elements with Physical Reality Primacy.
    """
    session_id: str
    epoch: int
    timestamp: float
    native_hwnd: int
    native_bounds: Rect
    webview_bounds: Rect
    cdp_target_id: str
    frame_id: str
    relationship_type: RelationshipType
    confidence: Certainty
    physical_visibility_status: str
    web_visibility_status: str
    contradictions: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
            "native_hwnd": hex(self.native_hwnd),
            "native_bounds": self.native_bounds.to_dict(),
            "webview_bounds": self.webview_bounds.to_dict(),
            "cdp_target_id": self.cdp_target_id,
            "frame_id": self.frame_id,
            "relationship_type": self.relationship_type.value,
            "confidence": self.confidence.value,
            "physical_visibility_status": self.physical_visibility_status,
            "web_visibility_status": self.web_visibility_status,
            "contradictions": list(self.contradictions),
        }


# -----------------------------------------------------------------------------
# Combined Snapshot Container
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class DualPerspectiveSnapshot:
    """
    Authoritative snapshot containing independent native and web perspectives
    and their reconciled relationship for a specific observation epoch.
    """
    session_id: str
    epoch: int
    timestamp: float
    native_observation: Optional[NativeObservation] = None
    web_observation: Optional[WebObservation] = None
    reconciliation: Optional[ReconciliationObservation] = None
    text_representation: str = ""
    is_diff: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
            "native": self.native_observation.to_dict() if self.native_observation else None,
            "web": self.web_observation.to_dict() if self.web_observation else None,
            "reconciliation": self.reconciliation.to_dict() if self.reconciliation else None,
            "text_representation": self.text_representation,
            "is_diff": self.is_diff,
        }
