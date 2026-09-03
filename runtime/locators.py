"""
Deterministic Locator Foundation & Stale Reference Recovery Engine.
Implements evidence-based, strict-by-default element resolution across dual perspectives
without LLM-based hallucination or silent first-element fallback.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

from runtime.references import ReferenceRegistry, ElementRef
from runtime.state import TargetPlane
from runtime.errors import TargetNotFoundException, TargetAmbiguousException, StaleReferenceException
from runtime.observation_models import (
    DualPerspectiveSnapshot,
    WebElementObservation,
    NativeElementObservation,
)

logger = logging.getLogger("desktop_webview.locators")


@dataclass(frozen=True)
class LocatorQuery:
    """Structured query specification for element targeting."""
    role: Optional[str] = None
    name: Optional[str] = None
    text: Optional[str] = None
    placeholder: Optional[str] = None
    automation_id: Optional[str] = None
    test_id: Optional[str] = None
    frame_id: Optional[str] = None
    plane: Optional[TargetPlane] = None
    exact: bool = False
    index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "name": self.name,
            "text": self.text,
            "placeholder": self.placeholder,
            "automation_id": self.automation_id,
            "test_id": self.test_id,
            "frame_id": self.frame_id,
            "plane": self.plane.value if isinstance(self.plane, TargetPlane) else str(self.plane) if self.plane else None,
            "exact": self.exact,
            "index": self.index,
        }


@dataclass(frozen=True)
class LocatorMatch:
    """Unambiguous target match with forensic evidence."""
    reference: str
    confidence: float
    match_strategy: str
    element: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference": self.reference,
            "confidence": self.confidence,
            "match_strategy": self.match_strategy,
            "element": self.element.to_dict() if hasattr(self.element, "to_dict") else vars(self.element),
        }


class DeterministicLocatorEngine:
    """
    Deterministic Locator Engine enforcing Strictness Mode by Default.
    Guarantees that queries matching multiple candidates halt with TargetAmbiguousException.
    """

    def resolve(
        self,
        query: LocatorQuery,
        snapshot: DualPerspectiveSnapshot,
        strict: bool = True,
    ) -> LocatorMatch:
        """
        Resolves a LocatorQuery against a DualPerspectiveSnapshot.
        Enforces frame-awareness, ranking precedence, and strict single-cardinality.
        """
        candidates: List[Tuple[float, str, Any]] = []

        # 1. Search Web Perspective
        if query.plane != TargetPlane.NATIVE_SHELL and snapshot.web_observation:
            for elem in snapshot.web_observation.elements:
                # Frame check
                if query.frame_id and elem.frame_id != query.frame_id:
                    continue

                match = self._score_web_element(query, elem)
                if match:
                    score, strategy = match
                    candidates.append((score, strategy, elem))

        # 2. Search Native Perspective
        if query.plane != TargetPlane.WEBVIEW_DOM and snapshot.native_observation:
            for elem in snapshot.native_observation.elements:
                match = self._score_native_element(query, elem)
                if match:
                    score, strategy = match
                    candidates.append((score, strategy, elem))

        if not candidates:
            raise TargetNotFoundException(
                message=f"No element matched query: {query.to_dict()}",
                details={"query": query.to_dict()},
            )

        # Sort candidates by descending score
        candidates.sort(key=lambda c: c[0], reverse=True)
        best_score = candidates[0][0]
        top_candidates = [c for c in candidates if abs(c[0] - best_score) < 0.001]

        # Explicit index bypass
        if query.index is not None:
            if 0 <= query.index < len(candidates):
                selected = candidates[query.index]
                return LocatorMatch(
                    reference=selected[2].reference,
                    confidence=selected[0],
                    match_strategy=f"{selected[1]}_indexed",
                    element=selected[2],
                )
            raise TargetNotFoundException(
                message=f"Query matched {len(candidates)} elements, but index {query.index} was out of bounds.",
                details={"query": query.to_dict(), "total_matches": len(candidates)},
            )

        # Strictness check
        if strict and len(top_candidates) > 1:
            candidate_details = [
                {
                    "ref": c[2].reference,
                    "role": getattr(c[2], "normalized_role", getattr(c[2], "control_type", "")),
                    "name": getattr(c[2], "accessible_name", getattr(c[2], "name", "")),
                    "text": getattr(c[2], "visible_text", ""),
                    "bounds": c[2].bounds.to_dict() if hasattr(c[2], "bounds") else None,
                }
                for c in top_candidates
            ]
            raise TargetAmbiguousException(
                message=f"Query resolved to {len(top_candidates)} elements with equal score ({best_score}). Strict mode requires an unambiguous match.",
                candidates=candidate_details,
                query=query.to_dict(),
                remediation="Refine query with specific text, role, frame_id, or explicit index.",
            )

        winner = top_candidates[0]
        return LocatorMatch(
            reference=winner[2].reference,
            confidence=winner[0],
            match_strategy=winner[1],
            element=winner[2],
        )

    def re_resolve_stale_ref(
        self,
        stale_ref_id: str,
        registry: ReferenceRegistry,
        snapshot: DualPerspectiveSnapshot,
    ) -> ElementRef:
        """
        Performs explicit re-resolution of a stale element reference using its stored recipe.
        Fails safely if ambiguous or if 0 candidates remain.
        """
        stale_ref = registry._stale_refs.get(stale_ref_id)
        if not stale_ref:
            # Check active refs
            if stale_ref_id in registry._active_refs:
                return registry._active_refs[stale_ref_id]
            raise StaleReferenceException(
                ref_id=stale_ref_id,
                current_epoch=registry.current_epoch,
                ref_epoch=None,
            )

        recipe = stale_ref.locator_recipe
        if not recipe:
            raise TargetNotFoundException(
                message=f"Stale reference '{stale_ref_id}' lacks a stored locator recipe for re-resolution.",
                details={"stale_ref_id": stale_ref_id},
            )

        # Build query from recipe
        plane = stale_ref.plane
        query = LocatorQuery(
            role=recipe.get("role") or recipe.get("control_type"),
            name=recipe.get("name") or recipe.get("accessible_name"),
            text=recipe.get("text"),
            placeholder=recipe.get("placeholder"),
            automation_id=recipe.get("automation_id"),
            frame_id=recipe.get("frame_id"),
            plane=plane,
            exact=True,
        )

        match = self.resolve(query, snapshot, strict=True)
        # Verify matched ref exists in active epoch
        new_ref = registry.resolve_ref(match.reference)
        logger.info(f"Re-resolved stale ref '{stale_ref_id}' -> active ref '{new_ref.ref_id}' (strategy: {match.match_strategy})")
        return new_ref

    def _score_web_element(self, query: LocatorQuery, elem: WebElementObservation) -> Optional[Tuple[float, str]]:
        """Scores how well a WebElementObservation matches the LocatorQuery."""
        elem_role = elem.normalized_role.lower()
        elem_name = (elem.accessible_name or "").lower()
        elem_text = (elem.visible_text or "").lower()
        elem_ph = (elem.placeholder or "").lower()
        elem_test_id = elem.attributes.get("data-testid", "").lower()
        elem_id = elem.attributes.get("id", "").lower()

        # 1. TestId or Automation ID exact match
        if query.test_id and (query.test_id.lower() == elem_test_id or query.test_id.lower() == elem_id):
            return 1.0, "test_id_exact"
        if query.automation_id and query.automation_id.lower() == elem_id:
            return 1.0, "automation_id_exact"

        # 2. Role + Accessible Name exact match
        if query.role and query.name:
            if query.role.lower() == elem_role and query.name.lower() == elem_name:
                return 0.95, "role_and_name_exact"

        # 3. Role + Visible Text exact match
        if query.role and query.text:
            if query.role.lower() == elem_role and query.text.lower() == elem_text:
                return 0.90, "role_and_text_exact"

        # 4. Role + Placeholder exact match
        if query.role and query.placeholder:
            if query.role.lower() == elem_role and query.placeholder.lower() == elem_ph:
                return 0.85, "role_and_placeholder_exact"

        # 5. Accessible Name exact match
        if query.name and query.name.lower() == elem_name:
            return 0.80, "name_exact"

        # 6. Role + Text substring match (if not exact)
        if query.role and query.text and not query.exact:
            if query.role.lower() == elem_role and query.text.lower() in elem_text:
                return 0.75, "role_and_text_substring"

        # 7. Text substring match
        if query.text and not query.exact and query.text.lower() in elem_text:
            return 0.65, "text_substring"

        # 8. Role only match
        if query.role and not query.name and not query.text:
            if query.role.lower() == elem_role:
                return 0.50, "role_only"

        return None

    def _score_native_element(self, query: LocatorQuery, elem: NativeElementObservation) -> Optional[Tuple[float, str]]:
        """Scores how well a NativeElementObservation matches the LocatorQuery."""
        elem_type = elem.control_type.lower()
        elem_name = (elem.name or "").lower()
        elem_auto_id = (elem.automation_id or "").lower()

        # 1. Automation ID exact match
        if query.automation_id and query.automation_id.lower() == elem_auto_id:
            return 1.0, "native_automation_id_exact"

        # 2. Control Type + Name exact match
        if query.role and query.name:
            if query.role.lower() == elem_type and query.name.lower() == elem_name:
                return 0.95, "native_type_and_name_exact"

        # 3. Name exact match
        if query.name and query.name.lower() == elem_name:
            return 0.85, "native_name_exact"

        # 4. Name substring match
        if query.name and not query.exact and query.name.lower() in elem_name:
            return 0.70, "native_name_substring"

        # 5. Type only match
        if query.role and not query.name and query.role.lower() == elem_type:
            return 0.50, "native_type_only"

        return None
