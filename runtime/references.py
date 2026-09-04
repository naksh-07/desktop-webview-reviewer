"""
Observation Epoch and Synthetic Reference Registry for Desktop WebView Reviewer.
Ensures references are strictly epoch-scoped, preventing stale node reuse across mutations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    frame_id: Optional[str] = None
    backend_id: Optional[Any] = None
    target_id: Optional[str] = None
    confidence: float = 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "ref_id": self.ref_id,
            "plane": self.plane.value if isinstance(self.plane, TargetPlane) else str(self.plane),
            "role": self.role,
            "name": self.name,
            "bounds": self.bounds.to_dict(),
            "locator_recipe": self.locator_recipe,
            "frame_id": self.frame_id,
            "backend_id": str(self.backend_id) if self.backend_id is not None else None,
            "target_id": self.target_id,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
        }


class ReferenceRegistry:
    """
    Epoch-scoped reference store for an active session.
    Enforces epoch invalidation on navigation, DOM mutation, or snapshot renewal.
    """

    def __init__(self, session_id: str = "default_session", initial_epoch: int = 1):
        self.session_id = session_id
        self._current_epoch = initial_epoch
        # Maps ref_id -> ElementRef for current epoch
        self._active_refs: Dict[str, ElementRef] = {}
        # Historical registry of previous epoch refs for diagnostics & fallback
        self._stale_refs: Dict[str, ElementRef] = {}
        self._epoch_history: List[Dict[str, Any]] = [
            {"epoch": initial_epoch, "reason": "initialization", "timestamp": datetime.now(timezone.utc)}
        ]

    @property
    def current_epoch(self) -> int:
        return self._current_epoch

    def register_ref(
        self,
        plane: TargetPlane,
        role: str,
        name: Optional[str] = None,
        bounds: Optional[Rect] = None,
        locator_recipe: Optional[Dict[str, Any]] = None,
        custom_index: Optional[int] = None,
        frame_id: Optional[str] = None,
        backend_id: Optional[Any] = None,
        target_id: Optional[str] = None,
        confidence: float = 1.0,
        ref_id: Optional[str] = None,
    ) -> ElementRef:
        """Creates and registers a synthetic reference for the current epoch."""
        prefix = "w" if (plane == TargetPlane.WEBVIEW_DOM or str(plane) == "WEBVIEW_DOM") else "n"
        idx = custom_index if custom_index is not None else (len(self._active_refs) + 1)
        final_ref_id = ref_id if ref_id is not None else f"{prefix}{self._current_epoch}e{idx}"

        actual_bounds = bounds if bounds is not None else Rect(0, 0, 0, 0)
        ref = ElementRef(
            epoch_id=self._current_epoch,
            ref_id=final_ref_id,
            plane=plane,
            role=role,
            name=name,
            bounds=actual_bounds,
            locator_recipe=locator_recipe,
            frame_id=frame_id,
            backend_id=backend_id,
            target_id=target_id,
            confidence=confidence,
        )
        self._active_refs[final_ref_id] = ref
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
            "timestamp": datetime.now(timezone.utc),
        })
        logger.debug(f"Session {self.session_id} epoch advanced to {self._current_epoch} ({reason})")
        return self._current_epoch

    advance_epoch = increment_epoch

    def invalidate_for_navigation(self, url: str) -> int:
        """Invalidates references following target navigation."""
        return self.increment_epoch(f"navigation: {url}")

    def invalidate_for_mutation(self, description: str = "dom_mutation") -> int:
        """Invalidates references following structural DOM/UI mutation."""
        return self.increment_epoch(f"mutation: {description}")

    def list_active_refs(self) -> List[ElementRef]:
        """Returns all valid references registered in the current epoch."""
        return list(self._active_refs.values())

    def get_active_refs(self) -> List[str]:
        """Returns all active ref_id identifiers registered in the current epoch."""
        return list(self._active_refs.keys())

    def get_ref(self, ref_id: str) -> Optional[ElementRef]:
        """Safely returns ElementRef if registered in active or stale storage, or None."""
        return self._active_refs.get(ref_id) or self._stale_refs.get(ref_id)

    def clear(self) -> None:
        """Clears all registered references and resets registry."""
        self._active_refs.clear()
        self._stale_refs.clear()

    def create_cursor(
        self,
        target_id: str,
        frame_id: str,
        page: int,
        page_size: int,
    ) -> str:
        """
        Creates an opaque pagination cursor strictly scoped to session, epoch, target, and frame.
        """
        import base64
        import json
        payload = {
            "session_id": self.session_id,
            "epoch": self._current_epoch,
            "target_id": target_id,
            "frame_id": frame_id,
            "page": page,
            "page_size": page_size,
        }
        json_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(json_bytes).decode("ascii")

    def validate_cursor(self, cursor_str: str) -> Dict[str, Any]:
        """
        Validates an opaque cursor against the active epoch.
        Raises StaleReferenceException if the cursor is from a prior or invalid epoch.
        """
        import base64
        import json
        try:
            json_bytes = base64.urlsafe_b64decode(cursor_str.encode("ascii"))
            payload = json.loads(json_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Malformed pagination cursor: {e}")

        cursor_epoch = payload.get("epoch")
        if cursor_epoch != self._current_epoch:
            raise StaleReferenceException(
                ref_id=f"cursor_epoch_{cursor_epoch}",
                current_epoch=self._current_epoch,
                ref_epoch=cursor_epoch,
            )

        if payload.get("session_id") != self.session_id:
            raise ValueError(f"Cursor session {payload.get('session_id')} does not match active session {self.session_id}")

        return payload

