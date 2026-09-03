"""
Central Action Execution Engine & Action-Observation Transaction Loop (Architecture H).
Coordinates the complete transaction lifecycle:
Resolve -> Validate -> Revalidate Preconditions -> Dispatch -> Receipt -> Settle -> Post-Observe -> Classify Outcome.
Enforces Physical Reality Primacy, Strict Cardinality, and Session Boundary Isolation.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Any

from runtime.state import TargetPlane
from runtime.references import ElementRef, ReferenceRegistry
from runtime.native_supervisor import NativeSupervisor
from runtime.webview_core import WebviewAutomationCore
from runtime.flaui_bridge import FlaUIBridge
from runtime.coordinate_transform import CoordinateTransformer
from runtime.locators import DeterministicLocatorEngine, LocatorQuery
from runtime.actionability import ActionabilityEngine, ActionabilityResult
from runtime.settlement import SettlementEngine, SettlementType, SettlementResult
from runtime.observation_engine import ObservationEngine
from runtime.native_input import NativeInputDispatcher
from runtime.web_action_executor import WebActionExecutor
from runtime.native_action_executor import NativeActionExecutor
from runtime.action_models import (
    ActionRequest,
    ActionTarget,
    ActionPreconditions,
    ActionReceipt,
    ActionOutcome,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
    ActionRiskLevel,
)
from runtime.errors import (
    StaleReferenceException,
    TargetNotFoundException,
    TargetAmbiguousException,
    ActionExecutionException,
    ActionDispatchRejectedException,
)

logger = logging.getLogger("desktop_webview.action_engine")


class ActionExecutionEngine:
    """
    Central stateful engine executing action-observation transactions.
    Preserves strict separation between Native and Web action planes.
    """

    def __init__(
        self,
        session_id: str = "default_session",
        reference_registry: Optional[ReferenceRegistry] = None,
        native_supervisor: Optional[NativeSupervisor] = None,
        observation_engine: Optional[ObservationEngine] = None,
        actionability_engine: Optional[ActionabilityEngine] = None,
        webview_core: Optional[WebviewAutomationCore] = None,
        flaui_bridge: Optional[FlaUIBridge] = None,
        native_input: Optional[NativeInputDispatcher] = None,
        settlement_engine: Optional[SettlementEngine] = None,
        locator_engine: Optional[DeterministicLocatorEngine] = None,
        web_executor: Optional[WebActionExecutor] = None,
        native_executor: Optional[NativeActionExecutor] = None,
    ):
        self.session_id = session_id
        self.reference_registry: ReferenceRegistry = (
            reference_registry
            or (web_executor.reference_registry if web_executor else None)
            or ReferenceRegistry(session_id=session_id)
        )
        self.native_supervisor: NativeSupervisor = (
            native_supervisor
            or (native_executor.native_supervisor if native_executor else None)
            or NativeSupervisor()
        )
        self.webview_core = webview_core or (web_executor.webview_core if web_executor else None)
        self.flaui_bridge = flaui_bridge

        self.actionability_engine: ActionabilityEngine = (
            actionability_engine
            or (web_executor.actionability_engine if web_executor else None)
            or ActionabilityEngine(
                registry=self.reference_registry,
                native_supervisor=self.native_supervisor,
                webview_core=self.webview_core,
                flaui_bridge=self.flaui_bridge,
                session_id=self.session_id,
            )
        )

        self.observation_engine: ObservationEngine = (
            observation_engine
            or ObservationEngine(
                session_id=self.session_id,
                reference_registry=self.reference_registry,
                native_supervisor=self.native_supervisor,
                webview_core=self.webview_core,
                flaui_bridge=self.flaui_bridge,
            )
        )

        # Input & Subsystems
        self.native_input: NativeInputDispatcher = (
            native_input
            or (native_executor.native_input if native_executor else None)
            or NativeInputDispatcher()
        )
        self.settlement_engine: SettlementEngine = (
            settlement_engine
            or SettlementEngine(
                native_supervisor=self.native_supervisor,
                webview_core=self.webview_core,
            )
        )
        self.locator_engine: DeterministicLocatorEngine = locator_engine or DeterministicLocatorEngine()

        # Dedicated plane executors
        if web_executor is not None:
            self.web_executor: Optional[WebActionExecutor] = web_executor
        elif self.webview_core:
            self.web_executor = WebActionExecutor(
                webview_core=self.webview_core,
                actionability_engine=self.actionability_engine,
                reference_registry=self.reference_registry,
            )
        else:
            self.web_executor = None

        if native_executor is not None:
            self.native_executor: NativeActionExecutor = native_executor
        else:
            self.native_executor = NativeActionExecutor(
                native_supervisor=self.native_supervisor,
                native_input=self.native_input,
                actionability_engine=self.actionability_engine,
                reference_registry=self.reference_registry,
                flaui_bridge=self.flaui_bridge,
            )

        self.receipt_history: List[ActionReceipt] = []
        self.outcome_history: List[ActionOutcome] = []
        self._lock = asyncio.Lock()

    async def execute(
        self,
        request: ActionRequest,
    ) -> ActionOutcome:
        """
        Executes the complete action-observation transaction loop:
        1. Resolve target ref and check epoch / handle stale reference recovery.
        2. Precondition revalidation immediately before dispatch.
        3. Dispatch action via WebActionExecutor or NativeActionExecutor.
        4. Capture immutable ActionReceipt.
        5. Bounded settlement (polling layout, modal, navigation).
        6. Advance observation epoch and capture post-action snapshot.
        7. Compute observation diff and classify outcome.
        """
        async with self._lock:
            cycle_start = time.time()
            pre_epoch = self.reference_registry.current_epoch

            # 1. Target Resolution & Stale Recovery
            target, recovered_from = await self._resolve_target(request)

            # 2. Immediate Precondition Revalidation
            preconditions = await self.actionability_engine.evaluate_actionability(
                ref_id=target.reference,
                timeout_ms=min(request.timeout_ms, 1500),
            )

            # 3. Action Dispatch
            receipt: ActionReceipt
            if target.plane == TargetPlane.WEBVIEW_DOM:
                if not self.web_executor:
                    receipt = ActionReceipt(
                        action_id=request.action_id,
                        session_id=self.session_id,
                        target_id=target.target_id,
                        epoch=pre_epoch,
                        plane=TargetPlane.WEBVIEW_DOM,
                        reference=target.reference,
                        action_type=request.action_type,
                        dispatch_method=DispatchMethod.CDP_INPUT,
                        dispatch_timestamp=cycle_start,
                        coordinates=target.affordance_point,
                        precondition_summary="Webview automation core is not attached to this session",
                        dispatch_status=DispatchStatus.FAILED,
                        error="Webview not available",
                        duration_ms=(time.time() - cycle_start) * 1000.0,
                    )
                else:
                    receipt = await self.web_executor.execute_action(
                        request=request,
                        target=target,
                        precondition_result=preconditions,
                    )
            else:
                receipt = await self.native_executor.execute_action(
                    request=request,
                    target=target,
                    precondition_result=preconditions,
                )

            # Record recovery provenance if applicable
            if recovered_from:
                # Update receipt with recovered_from_ref
                receipt = ActionReceipt(
                    action_id=receipt.action_id,
                    session_id=receipt.session_id,
                    target_id=receipt.target_id,
                    epoch=receipt.epoch,
                    plane=receipt.plane,
                    reference=receipt.reference,
                    action_type=receipt.action_type,
                    dispatch_method=receipt.dispatch_method,
                    dispatch_timestamp=receipt.dispatch_timestamp,
                    coordinates=receipt.coordinates,
                    native_hwnd=receipt.native_hwnd,
                    cdp_target_id=receipt.cdp_target_id,
                    frame_id=receipt.frame_id,
                    recovered_from_ref=recovered_from,
                    precondition_summary=receipt.precondition_summary,
                    dispatch_status=receipt.dispatch_status,
                    error=receipt.error,
                    duration_ms=receipt.duration_ms,
                    metadata=receipt.metadata,
                )

            self.receipt_history.append(receipt)

            # If dispatch was rejected or failed, outcome is immediately returned without settlement or epoch bump
            if receipt.dispatch_status != DispatchStatus.DISPATCHED:
                outcome_status = (
                    ActionOutcomeStatus.REJECTED
                    if receipt.dispatch_status == DispatchStatus.REJECTED
                    else ActionOutcomeStatus.FAILED
                )
                outcome = ActionOutcome(
                    action_id=request.action_id,
                    session_id=self.session_id,
                    receipt=receipt,
                    outcome_status=outcome_status,
                    state_change=StateChangeClassification.NO_EFFECT,
                    pre_epoch=pre_epoch,
                    post_epoch=pre_epoch,
                    post_snapshot=None,
                    observation_diff=None,
                    duration_ms=(time.time() - cycle_start) * 1000.0,
                    details={"dispatch_error": receipt.error},
                )
                self.outcome_history.append(outcome)
                return outcome

            # 4. Settlement
            initial_url = (
                self.webview_core.frame_manager.root_frame.url
                if self.webview_core and self.webview_core.frame_manager.root_frame
                else None
            )
            target_pid = (
                self.webview_core.native_pid
                if self.webview_core
                else (self.native_supervisor.inspect_window(target.native_hwnd).pid if target.native_hwnd else None)
            )

            ref_obj: Optional[ElementRef] = None
            try:
                ref_obj = self.reference_registry.resolve_ref(target.reference)
            except Exception:
                pass

            settle_res: SettlementResult = await self.settlement_engine.settle(
                target_pid=target_pid,
                target_hwnd=target.native_hwnd,
                ref=ref_obj,
                initial_url=initial_url,
                timeout_ms=request.settle_timeout_ms,
            )

            # 5. Post-Action Observation & Observation Differ
            # Advance epoch for mutating interaction
            post_epoch = self.reference_registry.advance_epoch(
                reason=f"action:{request.action_type.value}:{target.reference}"
            )

            post_snapshot = await self.observation_engine.observe(
                hwnd=target.native_hwnd,
                target_id=target.cdp_target_id,
            )

            diff = self.observation_engine.compute_diff(pre_epoch, post_epoch)

            # 6. Classify Outcome
            state_change = StateChangeClassification.NO_EFFECT
            nav_url = None
            modal_info = None

            if settle_res.settlement_type == SettlementType.MODAL_APPEARED:
                state_change = StateChangeClassification.MODAL_APPEARED
                modal_info = settle_res.details.get("modal_dialogs")
            elif settle_res.settlement_type == SettlementType.NAVIGATED:
                state_change = StateChangeClassification.NAVIGATED
                nav_url = settle_res.details.get("navigated_url")
            elif settle_res.settlement_type == SettlementType.TARGET_DISAPPEARED:
                state_change = StateChangeClassification.TARGET_DISAPPEARED
            elif diff and (diff.added_count > 0 or diff.removed_count > 0 or diff.mutated_count > 0):
                state_change = StateChangeClassification.STATE_CHANGED
            else:
                # Check if target element exists in post-snapshot
                target_still_exists = False
                if post_snapshot.web_observation and target.plane == TargetPlane.WEBVIEW_DOM:
                    for elem in post_snapshot.web_observation.elements:
                        if elem.target_id == target.target_id:
                            target_still_exists = True
                            break
                elif post_snapshot.native_observation and target.plane == TargetPlane.NATIVE_SHELL:
                    for elem in post_snapshot.native_observation.elements:
                        if elem.hwnd == target.native_hwnd:
                            target_still_exists = True
                            break

                if not target_still_exists and target.plane == TargetPlane.WEBVIEW_DOM:
                    state_change = StateChangeClassification.TARGET_DISAPPEARED
                else:
                    state_change = StateChangeClassification.NO_EFFECT

            total_duration = (time.time() - cycle_start) * 1000.0

            outcome = ActionOutcome(
                action_id=request.action_id,
                session_id=self.session_id,
                receipt=receipt,
                outcome_status=ActionOutcomeStatus.DISPATCHED,
                state_change=state_change,
                pre_epoch=pre_epoch,
                post_epoch=post_epoch,
                post_snapshot=post_snapshot,
                observation_diff=diff,
                modal_details={"modals": modal_info} if modal_info else None,
                navigation_url=nav_url,
                duration_ms=total_duration,
                details={
                    "settlement": settle_res.to_dict(),
                    "diff_summary": diff.to_dict() if diff else None,
                },
            )
            self.outcome_history.append(outcome)
            return outcome

    # -------------------------------------------------------------------------
    # Target Resolution Helper
    # -------------------------------------------------------------------------
    async def _resolve_target(
        self,
        request: ActionRequest,
    ) -> Tuple[ActionTarget, Optional[str]]:
        """
        Resolves reference to an ActionTarget.
        Handles stale reference recovery if requested.
        """
        ref_id = request.reference
        recovered_from: Optional[str] = None

        # 1. Attempt direct resolution
        try:
            ref = self.reference_registry.resolve_ref(ref_id)
            return self._build_action_target(ref), None
        except StaleReferenceException as e:
            if not request.allow_stale_recovery:
                raise e

            # Stale Reference Recovery Pipeline
            logger.info(f"Ref '{ref_id}' is stale (ref_epoch={e.ref_epoch}, current={e.current_epoch}). Attempting recovery...")
            last_snapshot = self.observation_engine.last_snapshot
            if not last_snapshot:
                # Need an active snapshot to re-resolve
                last_snapshot = await self.observation_engine.observe()

            recovered_ref = self.locator_engine.re_resolve_stale_ref(
                stale_ref_id=ref_id,
                registry=self.reference_registry,
                snapshot=last_snapshot,
            )
            recovered_from = ref_id
            return self._build_action_target(recovered_ref), recovered_from

    def _build_action_target(self, ref: ElementRef) -> ActionTarget:
        """Constructs ActionTarget dataclass from resolved ElementRef."""
        hwnd: Optional[int] = None
        cdp_target: Optional[str] = None
        space = "VIEWPORT_LOGICAL"

        if ref.plane == TargetPlane.WEBVIEW_DOM:
            if self.webview_core:
                hwnd = self.webview_core.native_hwnd
                if self.webview_core.target_manager:
                    cdp_target = self.webview_core.target_manager.active_target_id
        else:
            space = "SCREEN_CANONICAL"
            if ref.target_id:
                try:
                    hwnd = int(ref.target_id, 0)
                except ValueError:
                    hwnd = None
            if not hwnd and ref.locator_recipe and "hwnd" in ref.locator_recipe:
                hwnd = int(ref.locator_recipe["hwnd"])

        affordance_pt = ref.bounds.center if ref.bounds.area > 0 else None

        return ActionTarget(
            session_id=self.session_id,
            target_id=ref.target_id or ref.ref_id,
            reference=ref.ref_id,
            plane=ref.plane,
            epoch=ref.epoch_id,
            affordance_point=affordance_pt,
            coordinate_space=space,
            native_hwnd=hwnd,
            cdp_target_id=cdp_target,
            frame_id=ref.frame_id,
            locator_recipe=ref.locator_recipe,
            role=ref.role,
            name=ref.name,
            bounds=ref.bounds,
        )
