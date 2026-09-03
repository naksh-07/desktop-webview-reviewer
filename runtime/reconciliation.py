"""
Context Reconciliation Layer & Physical Reality Primacy Enforcer.
Establishes spatial and semantic alignment between Native Windows and Embedded Webviews,
surfacing physical vs DOM visibility contradictions without merging elements into a false universal tree.
"""

from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional, Any, Tuple

from runtime.references import Rect
from runtime.observation_models import (
    NativeObservation,
    WebObservation,
    ReconciliationObservation,
    RelationshipType,
    Certainty,
)

logger = logging.getLogger("desktop_webview.reconciliation")


class ContextReconciler:
    """
    Reconciles Native OS and Webview perspectives while strictly enforcing Physical Reality Primacy.
    Detects contradictions when DOM claims visibility while the OS reports occlusion or minimization.
    """

    def reconcile(
        self,
        native_obs: NativeObservation,
        web_obs: WebObservation,
    ) -> ReconciliationObservation:
        """
        Reconciles native and web perspectives for an observation epoch.
        """
        now = time.time()
        epoch = native_obs.epoch
        session_id = native_obs.session_id

        native_bounds = native_obs.bounds
        native_client = native_obs.client_bounds

        # Compute webview bounding envelope from visible web elements or viewport
        web_bounds = self._calculate_webview_envelope(web_obs)

        # 1. Determine relationship type based on physical screen coordinates
        rel_type = self._determine_relationship(native_client or native_bounds, web_bounds)

        # 2. Evaluate physical vs DOM visibility contradictions
        contradictions: List[str] = []
        has_visible_web_elements = any(
            e.visibility and e.visibility.visible
            for e in web_obs.elements
        )

        physical_status = "VISIBLE"
        if native_obs.is_minimized:
            physical_status = "MINIMIZED"
            if has_visible_web_elements:
                contradictions.append(
                    "CONTRADICTION: Webview DOM reports elements are visible, but Native Window is minimized (IsIconic=True)."
                )

        elif native_obs.is_cloaked:
            physical_status = "CLOAKED"
            if has_visible_web_elements:
                contradictions.append(
                    "CONTRADICTION: Webview DOM reports elements are visible, but Native Window is cloaked by DWM."
                )

        elif not native_obs.is_visible:
            physical_status = "HIDDEN"
            if has_visible_web_elements:
                contradictions.append(
                    "CONTRADICTION: Webview DOM reports elements are visible, but Native Window is hidden (IsWindowVisible=False)."
                )

        if not native_obs.is_responsive:
            contradictions.append(
                "CONTRADICTION: Native window UI thread is hung (failed SendMessageTimeout). OS input message pump will not dispatch."
            )

        if len(native_obs.modal_dialogs) > 0:
            contradictions.append(
                f"CONTRADICTION: Native modal dialog detected ({len(native_obs.modal_dialogs)} dialogs). Webview interactions may be absorbed or blocked by modal loop."
            )

        web_status = "VISIBLE_ELEMENTS" if has_visible_web_elements else "EMPTY_OR_HIDDEN"

        # 3. Certainty scoring
        if contradictions:
            confidence = Certainty.CONTRADICTORY
        elif rel_type in (RelationshipType.CONTAINS, RelationshipType.HOSTS, RelationshipType.ALIGNS_WITH):
            confidence = Certainty.DEFINITIVE if native_obs.is_responsive else Certainty.MEDIUM
        elif rel_type == RelationshipType.OVERLAPS:
            confidence = Certainty.HIGH
        else:
            confidence = Certainty.UNKNOWN

        return ReconciliationObservation(
            session_id=session_id,
            epoch=epoch,
            timestamp=now,
            native_hwnd=native_obs.hwnd,
            native_bounds=native_bounds,
            webview_bounds=web_bounds,
            cdp_target_id=web_obs.target_id,
            frame_id=web_obs.root_frame_id,
            relationship_type=rel_type,
            confidence=confidence,
            physical_visibility_status=physical_status,
            web_visibility_status=web_status,
            contradictions=tuple(contradictions),
        )

    def _determine_relationship(self, native_rect: Rect, web_rect: Rect) -> RelationshipType:
        """Determines spatial relationship between native window/client rect and webview bounds."""
        if native_rect.area == 0 or web_rect.area == 0:
            return RelationshipType.UNKNOWN

        # Check if native contains webview
        if (native_rect.left <= web_rect.left and
            native_rect.top <= web_rect.top and
            native_rect.right >= web_rect.right and
            native_rect.bottom >= web_rect.bottom):
            # If areas are very close (within 10%), it aligns with the client area
            if abs(native_rect.area - web_rect.area) < (0.1 * native_rect.area):
                return RelationshipType.ALIGNS_WITH
            return RelationshipType.HOSTS

        # Check intersection
        intersection = native_rect.intersection(web_rect)
        if intersection is not None and intersection.area > 0:
            return RelationshipType.OVERLAPS

        return RelationshipType.UNKNOWN

    def _calculate_webview_envelope(self, web_obs: WebObservation) -> Rect:
        """Calculates bounding envelope of observed web elements."""
        if not web_obs.elements:
            return Rect(0, 0, 0, 0)

        min_x = min((e.bounds.x for e in web_obs.elements if e.bounds.width > 0), default=0)
        min_y = min((e.bounds.y for e in web_obs.elements if e.bounds.height > 0), default=0)
        max_r = max((e.bounds.right for e in web_obs.elements if e.bounds.width > 0), default=0)
        max_b = max((e.bounds.bottom for e in web_obs.elements if e.bounds.height > 0), default=0)

        width = max(0, max_r - min_x)
        height = max(0, max_b - min_y)
        return Rect(x=min_x, y=min_y, width=width, height=height)
