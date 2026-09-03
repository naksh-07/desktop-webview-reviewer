"""
Semantic Web Observation Extractor for Desktop WebView Reviewer.
Coordinates with Phase 3 WebviewAutomationCore (CDP, Blink AXTree, Utility World, FrameManager)
to extract compact, frame-aware, actionable web observations without dumping the entire DOM.
"""

from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional, Any, Tuple, Set

from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane, AXFreshnessStatus
from runtime.webview_core import WebviewAutomationCore
from runtime.semantic_normalization import normalize_web_role, is_actionable_role, RoleSource
from runtime.observation_models import (
    WebObservation,
    WebElementObservation,
    FrameObservation,
    GeometryObservation,
    VisibilityObservation,
    InteractionObservation,
    Certainty,
)
from runtime.coordinate_transform import CoordinateTransformer

logger = logging.getLogger("desktop_webview.web_observation")


CANDIDATE_EXTRACTION_SCRIPT = """
(() => {
    const candidates = [];
    const elements = document.querySelectorAll(
        'button, a, input, select, textarea, [role], [tabindex], h1, h2, h3, h4, h5, h6, [onclick], summary, details, dialog, [data-testid], [aria-label]'
    );

    const maxItems = 200; // Hard bounded context limit per snapshot
    let count = 0;

    for (const el of elements) {
        if (count >= maxItems) break;

        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);

        const isDisplayed = style.display !== 'none' && style.visibility !== 'hidden';
        const hasSize = rect.width > 0 && rect.height > 0;

        // Skip completely invisible layout stubs unless they are dialogs or inputs
        if (!isDisplayed && el.tagName !== 'DIALOG') continue;

        const text = (el.innerText || el.textContent || '').trim().substring(0, 100);
        const ariaLabel = el.getAttribute('aria-label') || '';
        const placeholder = el.getAttribute('placeholder') || '';
        const roleAttr = el.getAttribute('role') || '';
        const value = el.value ? String(el.value).substring(0, 50) : '';

        // Determine states
        const isDisabled = el.disabled === true || el.getAttribute('aria-disabled') === 'true';
        const isChecked = el.checked === true || el.getAttribute('aria-checked') === 'true';
        const isSelected = el.selected === true || el.getAttribute('aria-selected') === 'true';
        const isExpanded = el.getAttribute('aria-expanded') === 'true' ? true : (el.getAttribute('aria-expanded') === 'false' ? false : null);
        const isFocused = document.activeElement === el;

        candidates.push({
            tag: el.tagName.toLowerCase(),
            id: el.id || '',
            name: el.getAttribute('name') || '',
            class: el.className ? String(el.className).substring(0, 100) : '',
            type: el.getAttribute('type') || '',
            role: roleAttr,
            aria_label: ariaLabel,
            text: text,
            placeholder: placeholder,
            value: value,
            is_disabled: isDisabled,
            is_checked: isChecked,
            is_selected: isSelected,
            is_expanded: isExpanded,
            is_focused: isFocused,
            display: style.display,
            visibility: style.visibility,
            opacity: parseFloat(style.opacity || '1.0'),
            rect: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                right: Math.round(rect.right),
                bottom: Math.round(rect.bottom)
            },
            in_viewport: (
                rect.top < window.innerHeight &&
                rect.bottom > 0 &&
                rect.left < window.innerWidth &&
                rect.right > 0
            )
        });
        count++;
    }

    return {
        dpr: window.devicePixelRatio || 1.0,
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        candidates: candidates
    };
})()
"""


class WebObservationExtractor:
    """
    Extracts semantic web observations from an active webview target.
    Fuses Accessibility tree nodes with isolated utility world DOM telemetry.
    """

    def __init__(
        self,
        webview_core: WebviewAutomationCore,
        reference_registry: ReferenceRegistry,
    ):
        self.webview_core = webview_core
        self.reference_registry = reference_registry

    async def observe_webview(
        self,
        session_id: str,
        target_id: Optional[str] = None,
        max_depth: int = 5,
        role_filter: Optional[Set[str]] = None,
        actionable_only: bool = False,
        visible_only: bool = True,
        frame_id: Optional[str] = None,
    ) -> WebObservation:
        """
        Extracts structured semantic web observations for a webview target.
        """
        now = time.time()
        epoch = self.reference_registry.current_epoch

        # Target metadata
        tid = target_id or "default_target"
        title = ""
        url = ""
        try:
            target_info = self.webview_core.target_manager.get_target(tid)
            if target_info:
                title = target_info.title
                url = target_info.url
        except Exception:
            pass

        # Frame hierarchy
        root_frame_id = self.webview_core.frame_manager.root_frame_id or tid
        target_frame_id = frame_id or root_frame_id

        frame_observations: List[FrameObservation] = []
        for fid, fctx in self.webview_core.frame_manager.frames.items():
            f_depth = 0 if getattr(fctx, "is_root", False) or not fctx.parent_frame_id else 1
            frame_observations.append(
                FrameObservation(
                    frame_id=fid,
                    parent_frame_id=fctx.parent_frame_id,
                    url=fctx.url,
                    security_origin=fctx.security_origin,
                    is_accessible=fctx.is_accessible,
                    depth=getattr(fctx, "depth", f_depth),
                )
            )

        # 1. Acquire AX Snapshot (if enabled/available)
        ax_snapshot = None
        ax_nodes_by_name: Dict[str, Any] = {}
        try:
            ax_snapshot = await self.webview_core.ax_runtime.acquire_snapshot(
                epoch=epoch,
                max_depth=max_depth,
            )
            for node in ax_snapshot.nodes:
                if node.name:
                    ax_nodes_by_name[node.name.strip().lower()] = node
        except Exception as ex:
            logger.debug(f"AX snapshot acquisition skipped or failed: {ex}")

        # 2. Extract DOM candidates via Utility World
        eval_result = None
        try:
            eval_result = await self.webview_core.utility_world.evaluate(
                expression=CANDIDATE_EXTRACTION_SCRIPT,
                frame_id=target_frame_id,
                return_by_value=True,
            )
        except Exception as ex:
            logger.debug(f"Utility world candidate extraction failed: {ex}")

        candidates_data = []
        dpr = 1.0
        if isinstance(eval_result, dict):
            candidates_data = eval_result.get("candidates", [])
            dpr = float(eval_result.get("dpr", 1.0))

        # 3. Normalize candidates and register references
        elements: List[WebElementObservation] = []
        for raw in candidates_data:
            tag = raw.get("tag", "div")
            itype = raw.get("type") or None
            aria_role = raw.get("role") or None
            aria_label = raw.get("aria_label") or ""
            text = raw.get("text") or ""
            placeholder = raw.get("placeholder") or ""
            val = raw.get("value") or ""

            # Accessible name priority: aria-label -> text -> placeholder -> id
            acc_name = aria_label or text or placeholder or raw.get("id") or None
            if acc_name:
                acc_name = acc_name.strip()

            # Cross-reference with AX tree if available
            ax_role = None
            if acc_name and acc_name.lower() in ax_nodes_by_name:
                matched_ax = ax_nodes_by_name[acc_name.lower()]
                ax_role = matched_ax.role

            # Semantic role normalization
            normalized_role, role_source = normalize_web_role(
                ax_role=ax_role,
                tag_name=tag,
                input_type=itype,
                aria_role=aria_role,
                attributes={"placeholder": placeholder, "type": itype or ""},
            )

            # Filtering
            if actionable_only and not is_actionable_role(normalized_role):
                continue

            if role_filter and normalized_role not in role_filter:
                continue

            rect_dict = raw.get("rect", {})
            bounds = Rect.from_dict(rect_dict)

            is_displayed = raw.get("display") != "none" and raw.get("visibility") != "hidden"
            is_visible = is_displayed and raw.get("opacity", 1.0) > 0.05 and bounds.width > 0 and bounds.height > 0
            is_in_viewport = bool(raw.get("in_viewport", True))

            if visible_only and not is_visible:
                continue

            # Recipe for stale ref recovery and locators
            locator_recipe = {
                "role": normalized_role,
                "name": acc_name,
                "text": text,
                "placeholder": placeholder,
                "tag": tag,
                "type": itype,
                "frame_id": target_frame_id,
            }

            ref = self.reference_registry.register_ref(
                plane=TargetPlane.WEBVIEW_DOM,
                role=normalized_role,
                name=acc_name,
                bounds=bounds,
                locator_recipe=locator_recipe,
                frame_id=target_frame_id,
                backend_id=raw.get("id") or acc_name,
                target_id=tid,
                confidence=0.95 if role_source == RoleSource.ACCESSIBILITY else 0.85,
            )

            vis_obs = VisibilityObservation(
                attached=True,
                visible=is_visible,
                in_viewport=is_in_viewport,
                physically_occluded=False,
                certainty=Certainty.HIGH if is_visible else Certainty.MEDIUM,
                details={
                    "display": raw.get("display"),
                    "visibility": raw.get("visibility"),
                    "opacity": raw.get("opacity"),
                },
            )

            geom_obs = GeometryObservation(
                bounds=bounds,
                screen_bounds=bounds,
                dpr=dpr,
                is_in_viewport=is_in_viewport,
            )

            supported_actions = []
            if is_actionable_role(normalized_role):
                if normalized_role in ("button", "link", "checkbox", "radio", "tab", "option"):
                    supported_actions.append("click")
                if normalized_role in ("textbox", "combobox"):
                    supported_actions.extend(["click", "type_text", "focus"])
                supported_actions.append("hover")

            interact_obs = InteractionObservation(
                is_enabled=not bool(raw.get("is_disabled", False)),
                is_focused=bool(raw.get("is_focused", False)),
                is_selected=bool(raw.get("is_selected", False)),
                is_checked=raw.get("is_checked"),
                is_expanded=raw.get("is_expanded"),
                affordance_point=bounds.center if bounds.area > 0 else None,
                supported_actions=tuple(supported_actions),
            )

            elem_obs = WebElementObservation(
                session_id=session_id,
                observation_epoch=epoch,
                timestamp=now,
                source_plane=TargetPlane.WEBVIEW_DOM,
                target_id=tid,
                reference=ref.ref_id,
                role=raw.get("role") or tag,
                normalized_role=normalized_role,
                role_source=role_source,
                accessible_name=acc_name,
                visible_text=text or None,
                placeholder=placeholder or None,
                value_summary=val or None,
                tag_name=tag,
                input_type=itype,
                frame_id=target_frame_id,
                bounds=bounds,
                geometry=geom_obs,
                visibility=vis_obs,
                interaction=interact_obs,
                confidence=Certainty.HIGH,
            )
            elements.append(elem_obs)

        return WebObservation(
            session_id=session_id,
            epoch=epoch,
            timestamp=now,
            target_id=tid,
            target_title=title,
            target_url=url,
            root_frame_id=root_frame_id,
            frames=tuple(frame_observations),
            elements=tuple(elements),
            ax_freshness=ax_snapshot.freshness if ax_snapshot else AXFreshnessStatus.UNKNOWN,
            dom_count=len(candidates_data),
            ax_count=ax_snapshot.node_count if ax_snapshot else None,
            confidence=Certainty.HIGH if ax_snapshot else Certainty.MEDIUM,
        )
