"""
Reality Domain Models for Desktop WebView Reviewer 2.0 (Architecture H).
Defines the unified RealityTarget schema reconciling Native OS, Chromium DOM,
DWM Compositor, and Physical Screen Visuals under the strict Truth Hierarchy:
Physical Desktop Reality > Compositor Reality > DOM/Web Reality.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any

from runtime.state import TargetPlane
from runtime.references import Rect


class TruthHierarchyLevel(str, Enum):
    """
    The canonical truth hierarchy governing desktop observation.
    Higher tiers authoritatively outrank lower tiers during conflict resolution.
    """
    PHYSICAL_DESKTOP = "PHYSICAL_DESKTOP"  # Highest authority: GDI/DirectX framebuffers
    COMPOSITOR = "COMPOSITOR"              # Middle authority: DWM occlusion, cloaking, Z-order
    DOM_WEB = "DOM_WEB"                    # Lowest authority: Internal browser DOM/AX tree


@dataclass(frozen=True)
class TargetIdentity:
    """Canonical identity descriptors for an interactive or observable target."""
    session_id: str
    target_id: str
    reference: str                         # e.g., "w1e7" or "n1e3"
    role: str = ""
    name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_id": self.target_id,
            "reference": self.reference,
            "role": self.role,
            "name": self.name,
        }


@dataclass(frozen=True)
class NativeTargetProps:
    """Native Win32 and UI Automation properties of the target window/element."""
    hwnd: Optional[int] = None
    class_name: Optional[str] = None
    title: Optional[str] = None
    visible: bool = False
    focused: bool = False
    bounds: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd) if self.hwnd is not None else None,
            "class_name": self.class_name,
            "title": self.title,
            "visible": self.visible,
            "focused": self.focused,
            "bounds": self.bounds.to_dict(),
        }


@dataclass(frozen=True)
class WebTargetProps:
    """Chromium DOM and Accessibility properties of the target element."""
    exists: bool = False
    enabled: bool = False
    tag_name: Optional[str] = None
    css_bounds: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    cdp_node_id: Optional[int] = None
    frame_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exists": self.exists,
            "enabled": self.enabled,
            "tag_name": self.tag_name,
            "css_bounds": self.css_bounds.to_dict(),
            "cdp_node_id": self.cdp_node_id,
            "frame_id": self.frame_id,
        }


@dataclass(frozen=True)
class CompositorTargetProps:
    """Windows Desktop Window Manager (DWM) compositor state."""
    is_cloaked: bool = False
    is_minimized: bool = False
    is_occluded: bool = False
    occlusion_percentage: float = 0.0
    dwm_bounds: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_cloaked": self.is_cloaked,
            "is_minimized": self.is_minimized,
            "is_occluded": self.is_occluded,
            "occlusion_percentage": self.occlusion_percentage,
            "dwm_bounds": self.dwm_bounds.to_dict(),
        }


@dataclass(frozen=True)
class VisualTargetProps:
    """Physical screen capture and rendering state."""
    is_physically_rendered: bool = False
    crop_hash: Optional[str] = None
    pixel_confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_physically_rendered": self.is_physically_rendered,
            "crop_hash": self.crop_hash,
            "pixel_confidence": self.pixel_confidence,
        }


@dataclass(frozen=True)
class ActionabilityAssessment:
    """Reconciled determination of whether the element can physically receive input."""
    is_actionable: bool
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    affordance_screen_point: Optional[Tuple[int, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_actionable": self.is_actionable,
            "reasons": list(self.reasons),
            "affordance_screen_point": list(self.affordance_screen_point) if self.affordance_screen_point else None,
        }


@dataclass(frozen=True)
class RealityTarget:
    """
    Canonical reconciled representation of a desktop interaction target.
    Synthesizes Native, Web, Compositor, and Visual data under the Truth Hierarchy.
    """
    identity: TargetIdentity
    source_plane: TargetPlane
    native: NativeTargetProps
    web: WebTargetProps
    compositor: CompositorTargetProps
    visual: VisualTargetProps
    actionability: ActionabilityAssessment
    observation_epoch: int
    truth_rank: TruthHierarchyLevel = TruthHierarchyLevel.PHYSICAL_DESKTOP
    reconciled_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_physically_visible(self) -> bool:
        """
        Calculates physical visibility strictly enforcing Truth Hierarchy.
        If the window is cloaked, minimized, or non-visible at the native/compositor
        layer, this returns False even if the DOM claims it is visible.
        """
        # 1. Check native & compositor truth
        if self.compositor.is_cloaked or self.compositor.is_minimized:
            return False
        if not self.native.visible:
            return False
        if self.compositor.is_occluded and self.compositor.occlusion_percentage >= 1.0:
            return False

        # 2. If target is in webview, check web visibility only after native checks pass
        if self.source_plane in (TargetPlane.WEBVIEW, TargetPlane.HYBRID):
            if not self.web.exists:
                return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "source_plane": self.source_plane.value if isinstance(self.source_plane, TargetPlane) else str(self.source_plane),
            "native": self.native.to_dict(),
            "web": self.web.to_dict(),
            "compositor": self.compositor.to_dict(),
            "visual": self.visual.to_dict(),
            "actionability": self.actionability.to_dict(),
            "observation_epoch": self.observation_epoch,
            "truth_rank": self.truth_rank.value if isinstance(self.truth_rank, TruthHierarchyLevel) else str(self.truth_rank),
            "is_physically_visible": self.is_physically_visible,
            "reconciled_at": self.reconciled_at,
            "metadata": self.metadata,
        }


@dataclass
class RealityReconciliationSnapshot:
    """
    Complete reconciled snapshot of an application session at an observation epoch.
    Surfaces all reality targets and explicit contradictions.
    """
    session_id: str
    observation_epoch: int
    targets: List[RealityTarget] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def add_target(self, target: RealityTarget) -> None:
        self.targets.append(target)

    def find_by_reference(self, reference: str) -> Optional[RealityTarget]:
        for t in self.targets:
            if t.identity.reference == reference:
                return t
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "observation_epoch": self.observation_epoch,
            "targets": [t.to_dict() for t in self.targets],
            "contradictions": self.contradictions,
            "timestamp": self.timestamp,
        }
