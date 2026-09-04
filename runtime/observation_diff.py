"""
Observation Differential Snapshot Engine.
Computes compact semantic diffs between observation epochs by tracking stable
semantic signatures across mutations rather than diffing raw DOM strings.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

from runtime.observation_models import (
    DualPerspectiveSnapshot,
    WebObservation,
    NativeObservation,
    WebElementObservation,
    NativeElementObservation,
)

logger = logging.getLogger("desktop_webview.observation_diff")


@dataclass(frozen=True)
class DiffItem:
    """Represents a single mutation between observation epochs."""
    kind: str                         # "ADDED", "REMOVED", "MODIFIED", "MOVED"
    reference: str
    role: str
    name: Optional[str]
    changes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "reference": self.reference,
            "role": self.role,
            "name": self.name,
            "changes": list(self.changes),
        }


@dataclass(frozen=True)
class ObservationDiffResult:
    """Structured diff summary between two observation snapshots."""
    from_epoch: int
    to_epoch: int
    added: Tuple[DiffItem, ...] = field(default_factory=tuple)
    removed: Tuple[DiffItem, ...] = field(default_factory=tuple)
    modified: Tuple[DiffItem, ...] = field(default_factory=tuple)
    text_diff: str = ""

    @property
    def added_count(self) -> int:
        return len(self.added)

    @property
    def removed_count(self) -> int:
        return len(self.removed)

    @property
    def modified_count(self) -> int:
        return len(self.modified)

    @property
    def mutated_count(self) -> int:
        return len(self.modified)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_epoch": self.from_epoch,
            "to_epoch": self.to_epoch,
            "added": [i.to_dict() for i in self.added],
            "removed": [i.to_dict() for i in self.removed],
            "modified": [i.to_dict() for i in self.modified],
            "text_diff": self.text_diff,
        }


class ObservationDiffer:
    """
    Computes semantic diffs across observation snapshots.
    Uses semantic signatures (role, accessible_name, frame) to track identity.
    """

    def diff(
        self,
        snapshot_a: DualPerspectiveSnapshot,
        snapshot_b: DualPerspectiveSnapshot,
    ) -> ObservationDiffResult:
        """
        Calculates differences from snapshot_a to snapshot_b.
        """
        from_epoch = snapshot_a.epoch
        to_epoch = snapshot_b.epoch

        added: List[DiffItem] = []
        removed: List[DiffItem] = []
        modified: List[DiffItem] = []

        # 1. Diff Web Elements
        web_a = snapshot_a.web_observation
        web_b = snapshot_b.web_observation

        if web_a and web_b:
            map_a: Dict[Tuple[str, str, str], WebElementObservation] = {}
            for e in web_a.elements:
                sig = (e.frame_id, e.normalized_role, (e.accessible_name or e.placeholder or e.tag_name).strip().lower())
                map_a[sig] = e

            map_b: Dict[Tuple[str, str, str], WebElementObservation] = {}
            for e in web_b.elements:
                sig = (e.frame_id, e.normalized_role, (e.accessible_name or e.placeholder or e.tag_name).strip().lower())
                map_b[sig] = e

            # Additions and modifications
            for sig, eb in map_b.items():
                if sig not in map_a:
                    added.append(DiffItem(
                        kind="ADDED",
                        reference=eb.reference,
                        role=eb.normalized_role,
                        name=eb.accessible_name,
                        changes=("element appeared",),
                    ))
                else:
                    ea = map_a[sig]
                    changes = self._compare_web_elements(ea, eb)
                    if changes:
                        modified.append(DiffItem(
                            kind="MODIFIED",
                            reference=eb.reference,
                            role=eb.normalized_role,
                            name=eb.accessible_name,
                            changes=tuple(changes),
                        ))

            # Removals
            for sig, ea in map_a.items():
                if sig not in map_b:
                    removed.append(DiffItem(
                        kind="REMOVED",
                        reference=ea.reference,
                        role=ea.normalized_role,
                        name=ea.accessible_name,
                        changes=("element removed",),
                    ))

        # Render compact text diff
        text_diff = self._render_diff_text(from_epoch, to_epoch, added, removed, modified)

        return ObservationDiffResult(
            from_epoch=from_epoch,
            to_epoch=to_epoch,
            added=tuple(added),
            removed=tuple(removed),
            modified=tuple(modified),
            text_diff=text_diff,
        )

    def _compare_web_elements(self, a: WebElementObservation, b: WebElementObservation) -> List[str]:
        changes = []
        if a.visible_text != b.visible_text:
            changes.append(f"text: '{a.visible_text}' -> '{b.visible_text}'")

        if a.value_summary != b.value_summary:
            changes.append(f"value: '{a.value_summary}' -> '{b.value_summary}'")

        if a.interaction and b.interaction:
            if a.interaction.is_enabled != b.interaction.is_enabled:
                changes.append(f"enabled: {a.interaction.is_enabled} -> {b.interaction.is_enabled}")
            if a.interaction.is_focused != b.interaction.is_focused:
                changes.append(f"focused: {a.interaction.is_focused} -> {b.interaction.is_focused}")
            if a.interaction.is_checked != b.interaction.is_checked:
                changes.append(f"checked: {a.interaction.is_checked} -> {b.interaction.is_checked}")
            if a.interaction.is_expanded != b.interaction.is_expanded:
                changes.append(f"expanded: {a.interaction.is_expanded} -> {b.interaction.is_expanded}")

        if a.visibility and b.visibility:
            if a.visibility.visible != b.visibility.visible:
                changes.append(f"visibility: {a.visibility.visible} -> {b.visibility.visible}")

        # Check geometry movement (> 3 pixels)
        dx = abs(a.bounds.x - b.bounds.x)
        dy = abs(a.bounds.y - b.bounds.y)
        if dx > 3 or dy > 3:
            changes.append(f"moved by ({dx}px, {dy}px)")

        return changes

    def _render_diff_text(
        self,
        from_epoch: int,
        to_epoch: int,
        added: List[DiffItem],
        removed: List[DiffItem],
        modified: List[DiffItem],
    ) -> str:
        lines = [f"# Observation Epoch: {to_epoch} (Diff from Epoch {from_epoch})"]
        for r in removed:
            lines.append(f"- {r.role} \"{r.name or ''}\" [ref={r.reference}]")
        for a in added:
            lines.append(f"+ {a.role} \"{a.name or ''}\" [ref={a.reference}]")
        for m in modified:
            ch_str = "; ".join(m.changes)
            lines.append(f"~ {m.role} \"{m.name or ''}\" [ref={m.reference}] [{ch_str}]")
        return "\n".join(lines)
