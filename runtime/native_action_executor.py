"""
Dedicated Native Action Executor for Desktop WebView Reviewer (Architecture H).
Dispatches physical and semantic interactions against native OS controls and Win32 windows.
Enforces Physical Reality Primacy: minimizes, cloaking, UI hangs, and modal dialogs
cause immediate dispatch rejection before sending OS input events.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Any

from runtime.state import TargetPlane
from runtime.references import ElementRef, ReferenceRegistry, Rect
from runtime.native_supervisor import NativeSupervisor, OcclusionState
from runtime.native_input import NativeInputDispatcher, MouseButton
from runtime.actionability import ActionabilityEngine, ActionabilityResult
from runtime.action_models import (
    ActionRequest,
    ActionTarget,
    ActionReceipt,
    ActionType,
    DispatchMethod,
    DispatchStatus,
)
from runtime.flaui_bridge import FlaUIBridge
from runtime.coordinate_transform import CoordinateTransformer

logger = logging.getLogger("desktop_webview.native_action_executor")


class NativeActionExecutor:
    """
    Executes interactions targeting native Win32 windows and UIA controls.
    Binds NativeSupervisor, NativeInputDispatcher, and FlaUIBridge.
    """

    def __init__(
        self,
        native_supervisor: NativeSupervisor,
        native_input: NativeInputDispatcher,
        actionability_engine: ActionabilityEngine,
        reference_registry: ReferenceRegistry,
        flaui_bridge: Optional[FlaUIBridge] = None,
    ):
        self.native_supervisor = native_supervisor
        self.native_input = native_input
        self.actionability_engine = actionability_engine
        self.reference_registry = reference_registry
        self.flaui_bridge = flaui_bridge

    async def execute_action(
        self,
        request: ActionRequest,
        target: ActionTarget,
        precondition_result: Optional[ActionabilityResult] = None,
    ) -> ActionReceipt:
        """
        Executes a validated action request against a native target and returns an ActionReceipt.
        """
        start_time = time.time()
        action_type = request.action_type
        ref_id = target.reference
        current_epoch = self.reference_registry.current_epoch

        # 1. Epoch verification
        if target.epoch != current_epoch:
            duration = (time.time() - start_time) * 1000.0
            return ActionReceipt(
                action_id=request.action_id,
                session_id=request.session_id,
                target_id=target.target_id,
                epoch=current_epoch,
                plane=TargetPlane.NATIVE_SHELL,
                reference=ref_id,
                action_type=action_type,
                dispatch_method=DispatchMethod.NATIVE_SENDINPUT,
                dispatch_timestamp=start_time,
                coordinates=target.affordance_point,
                native_hwnd=target.native_hwnd,
                cdp_target_id=None,
                frame_id=None,
                precondition_summary=f"Epoch mismatch: target epoch {target.epoch} != active epoch {current_epoch}",
                dispatch_status=DispatchStatus.REJECTED,
                error=f"Stale epoch: {target.epoch} != {current_epoch}",
                duration_ms=duration,
            )

        # 2. HWND / Target validation
        hwnd = target.native_hwnd
        if not hwnd or not self.native_supervisor.is_window(hwnd):
            duration = (time.time() - start_time) * 1000.0
            return ActionReceipt(
                action_id=request.action_id,
                session_id=request.session_id,
                target_id=target.target_id,
                epoch=current_epoch,
                plane=TargetPlane.NATIVE_SHELL,
                reference=ref_id,
                action_type=action_type,
                dispatch_method=DispatchMethod.NATIVE_SENDINPUT,
                dispatch_timestamp=start_time,
                coordinates=target.affordance_point,
                native_hwnd=hwnd,
                cdp_target_id=None,
                frame_id=None,
                precondition_summary=f"Invalid or destroyed native window HWND {hex(hwnd) if hwnd else 'None'}",
                dispatch_status=DispatchStatus.FAILED,
                error="Invalid HWND",
                duration_ms=duration,
            )

        # 3. Actionability Gate Recheck (Attachment, Visibility, Motion, Enabledness, Occlusion, Modals)
        actionability = precondition_result or await self.actionability_engine.evaluate_actionability(
            ref_id=ref_id,
            timeout_ms=min(request.timeout_ms, 1500),
        )

        if not actionability.is_actionable:
            reasons_summary = "; ".join(actionability.reasons) or "Actionability gate failed"
            duration = (time.time() - start_time) * 1000.0
            return ActionReceipt(
                action_id=request.action_id,
                session_id=request.session_id,
                target_id=target.target_id,
                epoch=current_epoch,
                plane=TargetPlane.NATIVE_SHELL,
                reference=ref_id,
                action_type=action_type,
                dispatch_method=DispatchMethod.NATIVE_SENDINPUT,
                dispatch_timestamp=start_time,
                coordinates=target.affordance_point,
                native_hwnd=hwnd,
                cdp_target_id=None,
                frame_id=None,
                precondition_summary=reasons_summary,
                dispatch_status=DispatchStatus.REJECTED,
                error=f"Precondition failed: {reasons_summary}",
                duration_ms=duration,
                metadata={"actionability": actionability.to_dict()},
            )

        # 4. Resolve Affordance Point (Physical Screen Coordinates)
        affordance_pt = actionability.affordance_point or target.affordance_point
        if not affordance_pt:
            # Fall back to window bounds center
            phys = self.native_supervisor.inspect_window(hwnd)
            affordance_pt = phys.bounds.center

        # 5. Dispatch Action
        dispatch_method = DispatchMethod.NATIVE_SENDINPUT
        dispatch_error: Optional[str] = None
        dispatch_status = DispatchStatus.DISPATCHED
        metadata: Dict[str, Any] = {}

        try:
            if action_type == ActionType.CLICK:
                assert affordance_pt is not None
                records = await self.native_input.click(
                    screen_x=affordance_pt[0],
                    screen_y=affordance_pt[1],
                    button=MouseButton.LEFT,
                    click_count=1,
                )
                metadata["dispatched_records"] = [r.to_dict() for r in records]
            elif action_type == ActionType.DOUBLE_CLICK:
                assert affordance_pt is not None
                records = await self.native_input.click(
                    screen_x=affordance_pt[0],
                    screen_y=affordance_pt[1],
                    button=MouseButton.LEFT,
                    click_count=2,
                )
                metadata["dispatched_records"] = [r.to_dict() for r in records]
            elif action_type == ActionType.RIGHT_CLICK:
                assert affordance_pt is not None
                records = await self.native_input.click(
                    screen_x=affordance_pt[0],
                    screen_y=affordance_pt[1],
                    button=MouseButton.RIGHT,
                    click_count=1,
                )
                metadata["dispatched_records"] = [r.to_dict() for r in records]
            elif action_type == ActionType.HOVER:
                assert affordance_pt is not None
                rec = await self.native_input.move_mouse(
                    screen_x=affordance_pt[0],
                    screen_y=affordance_pt[1],
                )
                metadata["dispatched_records"] = [rec.to_dict()]
            elif action_type == ActionType.TYPE:
                # 1. Bring window to foreground first to acquire focus
                await self._ensure_window_focus(hwnd)
                text = str(request.params.get("text", ""))
                records = await self.native_input.type_text(text)
                metadata["dispatched_records"] = [r.to_dict() for r in records]
            elif action_type == ActionType.KEY_PRESS:
                # 1. Bring window to foreground first
                await self._ensure_window_focus(hwnd)
                key = str(request.params.get("key", "Enter"))
                modifiers = request.params.get("modifiers", [])
                records = await self.native_input.press_key(key, modifiers)
                metadata["dispatched_records"] = [r.to_dict() for r in records]
            elif action_type == ActionType.SCROLL:
                assert affordance_pt is not None
                delta_x = int(request.params.get("delta_x", 0))
                delta_y = int(request.params.get("delta_y", 0))
                records = await self.native_input.scroll(
                    screen_x=affordance_pt[0],
                    screen_y=affordance_pt[1],
                    delta_y=delta_y,
                    delta_x=delta_x,
                )
                metadata["dispatched_records"] = [r.to_dict() for r in records]
            elif action_type == ActionType.FOCUS:
                success = await self._ensure_window_focus(hwnd)
                metadata["focus_acquired"] = success
            elif action_type == ActionType.WAIT:
                wait_ms = int(request.params.get("duration_ms", 100))
                await asyncio.sleep(wait_ms / 1000.0)
            else:
                dispatch_status = DispatchStatus.FAILED
                dispatch_error = f"Unsupported native action type: {action_type}"
        except Exception as ex:
            logger.warning(f"Native dispatch failed: {ex}")
            dispatch_status = DispatchStatus.FAILED
            dispatch_error = str(ex)

        duration = (time.time() - start_time) * 1000.0
        return ActionReceipt(
            action_id=request.action_id,
            session_id=request.session_id,
            target_id=target.target_id,
            epoch=current_epoch,
            plane=TargetPlane.NATIVE_SHELL,
            reference=ref_id,
            action_type=action_type,
            dispatch_method=dispatch_method,
            dispatch_timestamp=start_time,
            coordinates=affordance_pt,
            native_hwnd=hwnd,
            cdp_target_id=None,
            frame_id=None,
            precondition_summary="Native physical preconditions verified",
            dispatch_status=dispatch_status,
            error=dispatch_error,
            duration_ms=duration,
            metadata=metadata,
        )

    async def _ensure_window_focus(self, hwnd: int) -> bool:
        """Sets foreground focus to native window."""
        try:
            self.native_supervisor.bring_to_foreground(hwnd)
            await asyncio.sleep(0.02)
            active_hwnd = self.native_supervisor.get_foreground_window()
            return active_hwnd == hwnd
        except Exception as e:
            logger.debug(f"bring_to_foreground failed for HWND {hex(hwnd)}: {e}")
            return False
