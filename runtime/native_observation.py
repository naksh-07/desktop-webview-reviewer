"""
Native Semantic Observation Extractor for Desktop WebView Reviewer.
Leverages the Phase 2 Native OS Supervisor for desktop physical truth (HWND, DWM, Z-order,
modals, responsiveness) and the .NET FlaUI UIA3 bridge worker for native control hierarchy.
"""

from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional, Any, Tuple

from runtime.references import Rect, ReferenceRegistry
from runtime.state import TargetPlane
from runtime.native_supervisor import NativeSupervisor, WindowForensicReport, PhysicalVisibilityReport
from runtime.flaui_bridge import FlaUIBridge, UIAElementDTO
from runtime.observation_models import (
    NativeObservation,
    NativeElementObservation,
    GeometryObservation,
    VisibilityObservation,
    InteractionObservation,
    Certainty,
)
import runtime.win32 as w32

logger = logging.getLogger("desktop_webview.native_observation")


class NativeObservationExtractor:
    """
    Extracts semantic native OS observations for an active top-level window.
    Binds physical Win32 / DWM ground truth with UIA3 control trees.
    """

    def __init__(
        self,
        native_supervisor: NativeSupervisor,
        reference_registry: ReferenceRegistry,
        flaui_bridge: Optional[FlaUIBridge] = None,
    ):
        self.native_supervisor = native_supervisor
        self.reference_registry = reference_registry
        self.flaui_bridge = flaui_bridge

    async def observe_native_window(
        self,
        session_id: str,
        hwnd: int,
        max_depth: int = 2,
        actionable_only: bool = False,
    ) -> NativeObservation:
        """
        Produces a comprehensive NativeObservation for a top-level native window.
        """
        now = time.time()
        epoch = self.reference_registry.current_epoch

        # 1. Physical inspection via Phase 2 NativeSupervisor
        try:
            forensics = self.native_supervisor.inspect_window(hwnd)
        except Exception as e:
            logger.warning(f"Native window inspection failed for HWND {hwnd}: {e}")
            # Minimal fallback if HWND closed/invalid
            return NativeObservation(
                session_id=session_id,
                epoch=epoch,
                timestamp=now,
                hwnd=hwnd,
                title="",
                class_name="",
                pid=0,
                bounds=Rect(0, 0, 0, 0),
                client_bounds=Rect(0, 0, 0, 0),
                is_visible=False,
                is_minimized=False,
                is_cloaked=False,
                is_responsive=False,
                confidence=Certainty.LOW,
            )

        # 2. Modals check
        modal_list: List[Dict[str, Any]] = []
        try:
            modals = self.native_supervisor.scan_modal_dialogs(forensics.pid)
            modal_list = [m.to_dict() if hasattr(m, "to_dict") else vars(m) for m in modals]
        except Exception:
            pass

        has_blocking_modal = len(modal_list) > 0

        # 3. Register root native window reference
        root_recipe = {
            "hwnd": hwnd,
            "title": forensics.title,
            "class_name": forensics.class_name,
            "control_type": "Window",
        }
        root_ref = self.reference_registry.register_ref(
            plane=TargetPlane.NATIVE_SHELL,
            role="Window",
            name=forensics.title,
            bounds=forensics.bounds,
            locator_recipe=root_recipe,
            target_id=str(hwnd),
            backend_id=hwnd,
            confidence=1.0,
        )

        root_vis = VisibilityObservation(
            attached=True,
            visible=forensics.is_visible,
            in_viewport=not forensics.is_iconic and not forensics.is_cloaked,
            physically_occluded=False,
            minimized=forensics.is_iconic,
            cloaked=forensics.is_cloaked,
            modal_blocked=has_blocking_modal,
            certainty=Certainty.DEFINITIVE,
        )

        root_elem = NativeElementObservation(
            session_id=session_id,
            observation_epoch=epoch,
            timestamp=now,
            source_plane=TargetPlane.NATIVE_SHELL,
            target_id=str(hwnd),
            reference=root_ref.ref_id,
            control_type="Window",
            name=forensics.title,
            class_name=forensics.class_name,
            hwnd=hwnd,
            bounds=forensics.bounds,
            geometry=GeometryObservation(
                bounds=forensics.bounds,
                screen_bounds=forensics.bounds,
                client_rect=forensics.client_rect,
                dpr=forensics.dpi_scaling,
                is_in_viewport=not forensics.is_iconic and not forensics.is_cloaked,
            ),
            visibility=root_vis,
            interaction=InteractionObservation(
                is_enabled=not forensics.is_hung,
                is_focused=getattr(forensics, "has_focus", False) or bool(w32.user32.GetForegroundWindow() == hwnd),
                affordance_point=forensics.bounds.center,
                supported_actions=("focus", "window_move"),
            ),
            depth=0,
            confidence=Certainty.DEFINITIVE,
        )

        elements: List[NativeElementObservation] = [root_elem]

        # 4. Enumerate UIA child controls if FlaUI bridge is available
        if self.flaui_bridge and self.flaui_bridge.is_connected:
            try:
                child_dtos = await self.flaui_bridge.find_children(
                    hwnd=hwnd,
                    max_depth=max_depth,
                    use_cache=True,
                    epoch=epoch,
                )

                for dto in child_dtos:
                    # Filter actionable if requested
                    if actionable_only and not dto.is_enabled and dto.is_offscreen:
                        continue

                    ref_recipe = {
                        "hwnd": hwnd,
                        "automation_id": dto.automation_id,
                        "name": dto.name,
                        "control_type": dto.control_type,
                        "class_name": dto.class_name,
                    }
                    elem_ref = self.reference_registry.register_ref(
                        plane=TargetPlane.NATIVE_SHELL,
                        role=dto.control_type,
                        name=dto.name,
                        bounds=dto.bounds,
                        locator_recipe=ref_recipe,
                        target_id=str(hwnd),
                        backend_id=dto.automation_id or dto.name,
                        confidence=0.95 if dto.automation_id else 0.85,
                    )

                    elem_vis = VisibilityObservation(
                        attached=True,
                        visible=not dto.is_offscreen and forensics.is_visible,
                        in_viewport=not dto.is_offscreen and not forensics.is_iconic,
                        physically_occluded=False,
                        minimized=forensics.is_iconic,
                        cloaked=forensics.is_cloaked,
                        modal_blocked=has_blocking_modal,
                        certainty=Certainty.HIGH,
                    )

                    supported_acts = []
                    if "Invoke" in dto.supported_patterns or dto.control_type in ("Button", "MenuItem"):
                        supported_acts.append("click")
                    if "Value" in dto.supported_patterns or dto.control_type in ("Edit", "TextBox"):
                        supported_acts.append("type_text")
                    if "Toggle" in dto.supported_patterns:
                        supported_acts.append("toggle")

                    elem_obs = NativeElementObservation(
                        session_id=session_id,
                        observation_epoch=epoch,
                        timestamp=now,
                        source_plane=TargetPlane.NATIVE_SHELL,
                        target_id=str(hwnd),
                        reference=elem_ref.ref_id,
                        control_type=dto.control_type,
                        name=dto.name,
                        automation_id=dto.automation_id,
                        class_name=dto.class_name,
                        hwnd=dto.hwnd or hwnd,
                        bounds=dto.bounds,
                        geometry=GeometryObservation(
                            bounds=dto.bounds,
                            screen_bounds=dto.bounds,
                            dpr=forensics.dpi_scaling,
                            is_in_viewport=not dto.is_offscreen,
                        ),
                        visibility=elem_vis,
                        interaction=InteractionObservation(
                            is_enabled=dto.is_enabled and not forensics.is_hung,
                            affordance_point=dto.bounds.center if dto.bounds.area > 0 else None,
                            supported_actions=tuple(supported_acts),
                        ),
                        supported_patterns=dto.supported_patterns,
                        depth=dto.depth,
                        confidence=Certainty.HIGH,
                    )
                    elements.append(elem_obs)

            except Exception as e:
                logger.debug(f"Failed to enumerate UIA child controls for HWND {hwnd}: {e}")

        return NativeObservation(
            session_id=session_id,
            epoch=epoch,
            timestamp=now,
            hwnd=hwnd,
            title=forensics.title,
            class_name=forensics.class_name,
            pid=forensics.pid,
            bounds=forensics.bounds,
            client_bounds=forensics.client_rect,
            is_visible=forensics.is_visible,
            is_minimized=forensics.is_iconic,
            is_cloaked=forensics.is_cloaked,
            is_responsive=not forensics.is_hung,
            elements=tuple(elements),
            modal_dialogs=tuple(modal_list),
            confidence=Certainty.DEFINITIVE,
        )
