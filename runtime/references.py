"""
Observation Epoch and Synthetic Reference Registry for Desktop WebView Reviewer.
Ensures references are strictly epoch-scoped, preventing stale node reuse across mutations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import logging
from runtime.state import TargetPlane
from runtime.errors import StaleReferenceException

logger = logging.getLogger("desktop_webview.references")


@dataclass(frozen=True)
class Rect:
    """Screen or viewport bounding rectangle in integer pixels."""
    x: int
    y: int
    width: int
    height: int

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def contains(self, px: int, py: int) -> bool:
        """Returns True if point (px, py) is inside rectangle bounds."""
        return self.left <= px <= self.right and self.top <= py <= self.bottom

    def intersection(self, other: Rect) -> Optional[Rect]:
        """Calculates overlapping rectangle between self and other, or None if disjoint."""
        ix1 = max(self.left, other.left)
        iy1 = max(self.top, other.top)
        ix2 = min(self.right, other.right)
        iy2 = min(self.bottom, other.bottom)
        if ix2 > ix1 and iy2 > iy1:
            return Rect(x=ix1, y=iy1, width=ix2 - ix1, height=iy2 - iy1)
        return None

    def to_dict(self) -> Dict[str, int]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Rect:
        x = int(data.get("x", data.get("left", 0)))
        y = int(data.get("y", data.get("top", 0)))
        width = int(data.get("width", 0))
        height = int(data.get("height", 0))
        if width == 0 and "right" in data:
            width = max(0, int(data["right"]) - x)
        if height == 0 and "bottom" in data:
            height = max(0, int(data["bottom"]) - y)
        return cls(x=x, y=y, width=width, height=height)


@dataclass(frozen=True)
class ElementRef:
    """Synthetic, epoch-scoped interaction reference token."""
    epoch_id: int
    ref_id: str                  # e.g., "w1e1", "n1e2"
    plane: TargetPlane
    role: str
    name: Optional[str]
    bounds: Rect
    locator_recipe: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "ref_id": self.ref_id,
            "plane": self.plane.value if isinstance(self.plane, TargetPlane) else str(self.plane),
            "role": self.role,
            "name": self.name,
            "bounds": self.bounds.to_dict(),
            "locator_recipe": self.locator_recipe,
            "created_at": self.created_at.isoformat(),
        }


class ReferenceRegistry:
    """
    Epoch-scoped reference store for an active session.
    Enforces epoch invalidation on navigation, DOM mutation, or snapshot renewal.
    """

    def __init__(self, session_id: str, initial_epoch: int = 1):
        self.session_id = session_id
        self._current_epoch = initial_epoch
        # Maps ref_id -> ElementRef for current epoch
        self._active_refs: Dict[str, ElementRef] = {}
        # Historical registry of previous epoch refs for diagnostics & fallback
        self._stale_refs: Dict[str, ElementRef] = {}
        self._epoch_history: List[Dict[str, Any]] = [
            {"epoch": initial_epoch, "reason": "initialization", "timestamp": datetime.utcnow()}
        ]

    @property
    def current_epoch(self) -> int:
        return self._current_epoch

    def register_ref(
        self,
        plane: TargetPlane,
        role: str,
        name: Optional[str],
        bounds: Rect,
        locator_recipe: Optional[Dict[str, Any]] = None,
        custom_index: Optional[int] = None,
    ) -> ElementRef:
        """Creates and registers a synthetic reference for the current epoch."""
        prefix = "w" if plane == TargetPlane.WEBVIEW_DOM else "n"
        idx = custom_index if custom_index is not None else (len(self._active_refs) + 1)
        ref_id = f"{prefix}{self._current_epoch}e{idx}"

        ref = ElementRef(
            epoch_id=self._current_epoch,
            ref_id=ref_id,
            plane=plane,
            role=role,
            name=name,
            bounds=bounds,
            locator_recipe=locator_recipe,
        )
        self._active_refs[ref_id] = ref
        return ref

    def add_explicit_ref(self, ref: ElementRef) -> None:
        """Registers a pre-constructed ElementRef, validating its epoch matches current."""
        if ref.epoch_id != self._current_epoch:
            logger.warning(
                f"Registering ref {ref.ref_id} with epoch {ref.epoch_id} != active {self._current_epoch}"
            )
            self._stale_refs[ref.ref_id] = ref
        else:
            self._active_refs[ref.ref_id] = ref

    def resolve_ref(self, ref_id: str) -> ElementRef:
        """
        Resolves ref token for the current epoch.
        Raises StaleReferenceException if the reference is from a prior epoch.
        Raises KeyError if the reference never existed.
        """
        if ref_id in self._active_refs:
            return self._active_refs[ref_id]

        if ref_id in self._stale_refs:
            stale_ref = self._stale_refs[ref_id]
            raise StaleReferenceException(
                ref_id=ref_id,
                current_epoch=self._current_epoch,
                ref_epoch=stale_ref.epoch_id,
            )

        raise StaleReferenceException(
            ref_id=ref_id,
            current_epoch=self._current_epoch,
            ref_epoch=None,
        )

    def is_ref_valid(self, ref_id: str) -> bool:
        """Checks if a reference ID is valid in the current active epoch."""
        return ref_id in self._active_refs

    def increment_epoch(self, reason: str = "mutation") -> int:
        """
        Advances the epoch counter by 1.
        Moves all current active references to stale storage.
        """
        # Move active refs to stale storage
        self._stale_refs.update(self._active_refs)
        self._active_refs.clear()

        self._current_epoch += 1
        self._epoch_history.append({
            "epoch": self._current_epoch,
            "reason": reason,
            "timestamp": datetime.utcnow(),
        })
        logger.debug(f"Session {self.session_id} epoch advanced to {self._current_epoch} ({reason})")
        return self._current_epoch

    def invalidate_for_navigation(self, url: str) -> int:
        """Invalidates references following target navigation."""
        return self.increment_epoch(f"navigation: {url}")

    def invalidate_for_mutation(self, description: str = "dom_mutation") -> int:
        """Invalidates references following structural DOM/UI mutation."""
        return self.increment_epoch(f"mutation: {description}")

    def list_active_refs(self) -> List[ElementRef]:
        """Returns all valid references registered in the current epoch."""
        return list(self._active_refs.values())

    def clear(self) -> None:
        """Clears all registered references and resets registry."""
        self._active_refs.clear()
        self._stale_refs.clear()
