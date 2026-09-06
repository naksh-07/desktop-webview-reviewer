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


from runtime.reality_models import (
    RealityTarget,
    RealityReconciliationSnapshot,
    TargetIdentity,
    NativeTargetProps,
    WebTargetProps,
    CompositorTargetProps,
    VisualTargetProps,
    ActionabilityAssessment,
    TruthHierarchyLevel,
)
from runtime.state import TargetPlane
from runtime.references import ReferenceRegistry


class RealityReconciler:
    """
    Synthesizes Native OS, Webview DOM, Compositor (DWM), and Visual planes into
    canonical RealityTarget instances under the strict Truth Hierarchy:
    Physical Desktop Reality > Compositor Reality > DOM/Web Reality.
    """

    def __init__(self, context_reconciler: Optional[ContextReconciler] = None):
        self.context_reconciler = context_reconciler or ContextReconciler()

    def reconcile(
        self,
        epoch: int = 1,
        session_id: str = "default",
        native_obs: Optional[Any] = None,
        web_obs: Optional[Any] = None,
        reference_registry: Optional[ReferenceRegistry] = None,
        modal_windows: Optional[List[Any]] = None,
    ) -> RealityReconciliationSnapshot:
        """
        Convenience entrypoint reconciling an observation epoch.
        """
        return self.reconcile_snapshot(
            session_id=session_id,
            epoch=epoch,
            native_obs=native_obs,
            web_obs=web_obs,
            reference_registry=reference_registry,
            modal_windows=modal_windows,
        )

    def reconcile_snapshot(
        self,
        session_id: str,
        epoch: int,
        native_obs: Optional[Any] = None,
        web_obs: Optional[Any] = None,
        reference_registry: Optional[ReferenceRegistry] = None,
        modal_windows: Optional[List[Any]] = None,
    ) -> RealityReconciliationSnapshot:
        """
        Builds an authoritative RealityReconciliationSnapshot for the current epoch,
        reconciling all active references into RealityTarget objects and detecting contradictions.
        """
        snapshot = RealityReconciliationSnapshot(
            session_id=session_id,
            observation_epoch=epoch,
        )

        is_cloaked = getattr(native_obs, "is_cloaked", False) if native_obs else False
        is_minimized = getattr(native_obs, "is_minimized", False) if native_obs else False
        is_native_vis = getattr(native_obs, "is_visible", True) if native_obs else True
        is_responsive = getattr(native_obs, "is_responsive", True) if native_obs else True

        # Check if web elements claim visibility
        has_visible_web = False
        if web_obs and hasattr(web_obs, "elements") and web_obs.elements:
            has_visible_web = any(
                (e.visibility.visible if getattr(e, "visibility", None) else getattr(e, "is_visible", True))
                for e in web_obs.elements
            )

        # 1. Evaluate Truth Hierarchy window-level contradictions
        if is_cloaked and has_visible_web:
            snapshot.contradictions.append(
                "CLOAKED_BUT_DOM_VISIBLE: Webview DOM reports elements are visible, but Native Window is cloaked by DWM (Truth Hierarchy: Compositor > Web)"
            )
        if is_minimized and has_visible_web:
            snapshot.contradictions.append(
                "MINIMIZED_BUT_DOM_VISIBLE: Webview DOM reports elements are visible, but Native Window is minimized (Truth Hierarchy: Compositor > Web)"
            )
        if not is_native_vis and has_visible_web:
            snapshot.contradictions.append(
                "HIDDEN_BUT_DOM_VISIBLE: Webview DOM reports elements are visible, but Native Window is hidden (Truth Hierarchy: Native > Web)"
            )

        # 2. ContextReconciler integration for base spatial alignment
        if native_obs and web_obs and isinstance(native_obs, NativeObservation) and isinstance(web_obs, WebObservation):
            rec_obs = self.context_reconciler.reconcile(native_obs, web_obs)
            for c_str in rec_obs.contradictions:
                snapshot.contradictions.append(
                    f"SPATIAL_CONTRADICTION: {c_str}"
                )

        # Active modals to check for physical occlusion
        active_modals = list(modal_windows or [])
        if native_obs and hasattr(native_obs, "modal_dialogs") and native_obs.modal_dialogs:
            active_modals.extend(native_obs.modal_dialogs)

        # 3. Reconcile Webview Elements into RealityTargets
        if web_obs and hasattr(web_obs, "elements") and web_obs.elements:
            for elem in web_obs.elements:
                ref = getattr(elem, "reference", "unknown")
                ref_obj = reference_registry.resolve_ref(ref) if reference_registry else None
                name = getattr(elem, "name", None) or (ref_obj.name if ref_obj else None)
                role = getattr(elem, "role", None) or (ref_obj.role if ref_obj else "generic")
                elem_bounds = getattr(elem, "bounds", Rect(0, 0, 0, 0))

                identity = TargetIdentity(
                    session_id=session_id,
                    target_id=getattr(elem, "target_id", ref),
                    reference=ref,
                    role=role or "generic",
                    name=name,
                )

                # Native host window props
                native_props = NativeTargetProps(
                    hwnd=getattr(native_obs, "hwnd", None),
                    class_name=getattr(native_obs, "class_name", None),
                    title=getattr(native_obs, "title", None),
                    visible=is_native_vis,
                    focused=getattr(native_obs, "is_focused", False),
                    bounds=getattr(native_obs, "bounds", Rect(0, 0, 0, 0)),
                )

                # Web element props
                elem_vis = getattr(elem, "visibility", None)
                elem_inter = getattr(elem, "interaction", None)
                elem_exists = elem_vis.attached if elem_vis else True
                elem_enabled = elem_inter.is_enabled if elem_inter else getattr(elem, "is_enabled", True)
                elem_visible = elem_vis.visible if elem_vis else getattr(elem, "is_visible", True)

                web_props = WebTargetProps(
                    exists=elem_exists,
                    enabled=elem_enabled,
                    tag_name=getattr(elem, "tag_name", None),
                    css_bounds=elem_bounds,
                    cdp_node_id=getattr(elem, "backend_node_id", None),
                    frame_id=getattr(web_obs, "root_frame_id", None),
                )

                # Modal occlusion check
                is_modal_occluded = False
                for m in active_modals:
                    m_bounds = getattr(m, "bounds", None)
                    if m_bounds and elem_bounds.area > 0:
                        inter = m_bounds.intersection(elem_bounds)
                        if inter is not None and inter.area > 0:
                            is_modal_occluded = True
                            snapshot.contradictions.append(
                                f"OCCLUDED_BY_MODAL: Target {ref} is occluded by modal window ({getattr(m, 'title', hex(getattr(m, 'hwnd', 0)))}) (Modal HWND: {getattr(m, 'hwnd', None)})"
                            )
                            break

                # Compositor props derived from native host, DWM, and modal occlusion
                is_dom_occluded = elem_vis.physically_occluded if elem_vis else False
                is_occluded = is_dom_occluded or is_modal_occluded
                compositor_props = CompositorTargetProps(
                    is_cloaked=is_cloaked,
                    is_minimized=is_minimized,
                    is_occluded=is_occluded,
                    occlusion_percentage=1.0 if is_occluded else 0.0,
                    dwm_bounds=getattr(native_obs, "bounds", Rect(0, 0, 0, 0)),
                )

                # Visual props
                is_physically_rendered = (
                    not is_cloaked
                    and not is_minimized
                    and is_native_vis
                    and elem_visible
                    and not is_modal_occluded
                )
                visual_props = VisualTargetProps(
                    is_physically_rendered=is_physically_rendered,
                    crop_hash=None,
                    pixel_confidence=1.0 if is_physically_rendered else 0.0,
                )

                # Actionability under Truth Hierarchy
                actionable_reasons: List[str] = []
                if is_cloaked:
                    actionable_reasons.append("Native window is cloaked by DWM (Truth Hierarchy: Compositor > Web)")
                if is_minimized:
                    actionable_reasons.append("Native window is minimized (Truth Hierarchy: Compositor > Web)")
                if not is_native_vis:
                    actionable_reasons.append("Native window is hidden (Truth Hierarchy: Native > Web)")
                if not is_responsive:
                    actionable_reasons.append("Native UI thread is hung")
                if is_modal_occluded:
                    actionable_reasons.append("Element is occluded by modal window")
                elif active_modals:
                    actionable_reasons.append("Native modal dialog blocks interaction")
                if not elem_enabled:
                    actionable_reasons.append("Web element is disabled")
                if is_dom_occluded:
                    actionable_reasons.append("Element is occluded by overlapping window")

                affordance_pt = elem_inter.affordance_point if elem_inter else None

                target = RealityTarget(
                    identity=identity,
                    source_plane=TargetPlane.WEBVIEW,
                    native=native_props,
                    web=web_props,
                    compositor=compositor_props,
                    visual=visual_props,
                    actionability=ActionabilityAssessment(
                        is_actionable=len(actionable_reasons) == 0,
                        reasons=tuple(actionable_reasons),
                        affordance_screen_point=affordance_pt,
                    ),
                    observation_epoch=epoch,
                    truth_rank=TruthHierarchyLevel.PHYSICAL_DESKTOP,
                )
                snapshot.add_target(target)

        # 4. Reconcile Native Elements into RealityTargets
        if native_obs and hasattr(native_obs, "elements") and native_obs.elements:
            for elem in native_obs.elements:
                ref = getattr(elem, "reference", "unknown")
                ref_obj = reference_registry.resolve_ref(ref) if reference_registry else None
                name = getattr(elem, "name", None) or (ref_obj.name if ref_obj else None)
                role = getattr(elem, "control_type", None) or (ref_obj.role if ref_obj else "Window")
                elem_bounds = getattr(elem, "bounds", Rect(0, 0, 0, 0))

                identity = TargetIdentity(
                    session_id=session_id,
                    target_id=getattr(elem, "target_id", ref),
                    reference=ref,
                    role=role,
                    name=name,
                )

                elem_vis = getattr(elem, "visibility", None)
                elem_inter = getattr(elem, "interaction", None)
                native_props = NativeTargetProps(
                    hwnd=getattr(elem, "hwnd", None),
                    class_name=getattr(elem, "class_name", None),
                    title=getattr(elem, "name", None),
                    visible=elem_vis.visible if elem_vis else is_native_vis,
                    focused=getattr(elem_inter, "is_focused", False) if elem_inter else False,
                    bounds=elem_bounds,
                )

                web_props = WebTargetProps(
                    exists=False,
                    enabled=False,
                    tag_name=None,
                    css_bounds=Rect(0, 0, 0, 0),
                )

                # Modal occlusion check for native elements
                is_modal_occluded = False
                for m in active_modals:
                    m_bounds = getattr(m, "bounds", None)
                    if m_bounds and elem_bounds.area > 0 and getattr(elem, "hwnd", None) != getattr(m, "hwnd", None):
                        inter = m_bounds.intersection(elem_bounds)
                        if inter is not None and inter.area > 0:
                            is_modal_occluded = True
                            snapshot.contradictions.append(
                                f"OCCLUDED_BY_MODAL: Native target {ref} is occluded by modal dialog ({getattr(m, 'title', hex(getattr(m, 'hwnd', 0)))}) (Modal HWND: {getattr(m, 'hwnd', None)})"
                            )
                            break

                is_dom_occluded = elem_vis.physically_occluded if elem_vis else False
                is_occluded = is_dom_occluded or is_modal_occluded
                compositor_props = CompositorTargetProps(
                    is_cloaked=is_cloaked,
                    is_minimized=is_minimized,
                    is_occluded=is_occluded,
                    occlusion_percentage=1.0 if is_occluded else 0.0,
                    dwm_bounds=elem_bounds,
                )

                is_physically_rendered = (
                    not is_cloaked
                    and not is_minimized
                    and native_props.visible
                    and not is_modal_occluded
                )
                visual_props = VisualTargetProps(
                    is_physically_rendered=is_physically_rendered,
                    crop_hash=None,
                    pixel_confidence=1.0 if is_physically_rendered else 0.0,
                )

                actionable_reasons: List[str] = []
                if is_cloaked:
                    actionable_reasons.append("Window is cloaked by DWM")
                if is_minimized:
                    actionable_reasons.append("Window is minimized")
                if not native_props.visible:
                    actionable_reasons.append("Window is hidden")
                if not is_responsive:
                    actionable_reasons.append("Native UI thread is hung")
                if is_modal_occluded:
                    actionable_reasons.append("Element is occluded by modal window")
                elif active_modals and getattr(elem, "control_type", None) != "Dialog":
                    actionable_reasons.append("Modal dialog blocks interaction")
                if elem_inter and not getattr(elem_inter, "is_enabled", True):
                    actionable_reasons.append("Control is disabled")

                affordance_pt = elem_inter.affordance_point if elem_inter else None

                target = RealityTarget(
                    identity=identity,
                    source_plane=TargetPlane.NATIVE,
                    native=native_props,
                    web=web_props,
                    compositor=compositor_props,
                    visual=visual_props,
                    actionability=ActionabilityAssessment(
                        is_actionable=len(actionable_reasons) == 0,
                        reasons=tuple(actionable_reasons),
                        affordance_screen_point=affordance_pt,
                    ),
                    observation_epoch=epoch,
                    truth_rank=TruthHierarchyLevel.PHYSICAL_DESKTOP,
                )
                snapshot.add_target(target)

        return snapshot

