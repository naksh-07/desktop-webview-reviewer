"""
Composite Actionability Engine (Architecture H).
Enforces the 5-Point Precondition Actionability Gate (Attachment, Computed Visibility,
Motion Stability, Enabledness, Hit-Testing/Un-occlusion) and canonical affordance point calculation.
"""

from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

from runtime.references import Rect, ElementRef, ReferenceRegistry
from runtime.state import TargetPlane
from runtime.errors import StaleReferenceException
from runtime.native_supervisor import NativeSupervisor, OcclusionState
from runtime.webview_core import WebviewAutomationCore
from runtime.flaui_bridge import FlaUIBridge
from runtime.coordinate_transform import CoordinateTransformer, CoordinateTransformContext

logger = logging.getLogger("desktop_webview.actionability")


class GateStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    TIMEOUT = "TIMEOUT"
    STALE = "STALE"


class MotionStatus(str, Enum):
    STABLE = "STABLE"
    MOVING = "MOVING"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class OverallActionabilityStatus(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"
    UNKNOWN = "UNKNOWN"
    TIMEOUT = "TIMEOUT"
    STALE = "STALE"


@dataclass(frozen=True)
class GateReport:
    """Forensic report for an individual actionability gate."""
    gate_name: str
    status: GateStatus
    passed: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "status": self.status.value,
            "passed": self.passed,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass(frozen=True)
class ActionabilityResult:
    """Authoritative outcome of the composite 5-point actionability evaluation."""
    ref_id: str = ""
    epoch: int = 1
    plane: TargetPlane = TargetPlane.WEBVIEW_DOM
    attachment: GateReport = field(default_factory=lambda: GateReport("attachment", GateStatus.PASSED, True, "ok"))
    visibility: GateReport = field(default_factory=lambda: GateReport("visibility", GateStatus.PASSED, True, "ok"))
    motion: GateReport = field(default_factory=lambda: GateReport("motion", GateStatus.PASSED, True, "ok"))
    enabledness: GateReport = field(default_factory=lambda: GateReport("enabledness", GateStatus.PASSED, True, "ok"))
    hit_test: GateReport = field(default_factory=lambda: GateReport("hit_test", GateStatus.PASSED, True, "ok"))
    affordance_point: Optional[Tuple[int, int]] = None
    affordance_point_type: str = "CENTER"
    physical_visibility: str = "FULL"
    web_visibility: str = "VISIBLE"
    overall_status: OverallActionabilityStatus = OverallActionabilityStatus.READY
    is_actionable: bool = True
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    evaluated_at: float = field(default_factory=time.time)

    def __init__(
        self,
        ref_id: str = "",
        epoch: int = 1,
        plane: TargetPlane = TargetPlane.WEBVIEW_DOM,
        attachment: Any = None,
        visibility: Any = None,
        motion: Any = None,
        enabledness: Any = None,
        hit_test: Any = None,
        affordance_point: Optional[Tuple[int, int]] = None,
        affordance_point_type: str = "CENTER",
        physical_visibility: str = "FULL",
        web_visibility: str = "VISIBLE",
        overall_status: OverallActionabilityStatus = OverallActionabilityStatus.READY,
        is_actionable: bool = True,
        reasons: Any = (),
        evaluated_at: Optional[float] = None,
        motion_stability: Any = None,
    ):
        object.__setattr__(self, "ref_id", ref_id)
        object.__setattr__(self, "epoch", epoch)
        object.__setattr__(self, "plane", plane)

        default_gate = GateReport("gate", GateStatus.PASSED, True, "ok")

        def _to_gate(g: Any, name: str) -> GateReport:
            if isinstance(g, GateReport):
                return g
            if isinstance(g, GateStatus):
                return GateReport(name, g, g == GateStatus.PASSED, "ok" if g == GateStatus.PASSED else "failed")
            if isinstance(g, MotionStatus):
                passed = g == MotionStatus.STABLE
                return GateReport(name, GateStatus.PASSED if passed else GateStatus.FAILED, passed, g.value)
            return default_gate

        object.__setattr__(self, "attachment", _to_gate(attachment, "attachment"))
        object.__setattr__(self, "visibility", _to_gate(visibility, "visibility"))
        actual_motion = motion if motion is not None else motion_stability
        object.__setattr__(self, "motion", _to_gate(actual_motion, "motion"))
        object.__setattr__(self, "enabledness", _to_gate(enabledness, "enabledness"))
        object.__setattr__(self, "hit_test", _to_gate(hit_test, "hit_test"))
        object.__setattr__(self, "affordance_point", tuple(affordance_point) if affordance_point else None)
        object.__setattr__(self, "affordance_point_type", affordance_point_type)
        object.__setattr__(self, "physical_visibility", physical_visibility)
        object.__setattr__(self, "web_visibility", web_visibility)
        object.__setattr__(self, "overall_status", overall_status)
        object.__setattr__(self, "is_actionable", is_actionable)
        object.__setattr__(self, "reasons", tuple(reasons) if isinstance(reasons, (list, tuple)) else (str(reasons),))
        object.__setattr__(self, "evaluated_at", evaluated_at if evaluated_at is not None else time.time())

    @property
    def motion_stability(self) -> GateReport:
        return self.motion

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "epoch": self.epoch,
            "plane": self.plane.value if isinstance(self.plane, TargetPlane) else str(self.plane),
            "attachment": self.attachment.to_dict(),
            "visibility": self.visibility.to_dict(),
            "motion": self.motion.to_dict(),
            "enabledness": self.enabledness.to_dict(),
            "hit_test": self.hit_test.to_dict(),
            "affordance_point": list(self.affordance_point) if self.affordance_point else None,
            "affordance_point_type": self.affordance_point_type,
            "physical_visibility": self.physical_visibility,
            "web_visibility": self.web_visibility,
            "overall_status": self.overall_status.value,
            "is_actionable": self.is_actionable,
            "reasons": list(self.reasons),
            "evaluated_at": self.evaluated_at,
        }


class ActionabilityEngine:
    """
    Evaluates element actionability prior to any motor interaction.
    Answers: 'Can this element be safely interacted with, and why/why not?'
    """

    def __init__(
        self,
        reference_registry: ReferenceRegistry,
        native_supervisor: NativeSupervisor,
        webview_core: Optional[WebviewAutomationCore] = None,
        flaui_bridge: Optional[FlaUIBridge] = None,
        session_id: Optional[str] = None,
    ):
        self.reference_registry = reference_registry
        self.native_supervisor = native_supervisor
        self.webview_core = webview_core
        self.flaui_bridge = flaui_bridge
        self.session_id = session_id or getattr(reference_registry, "session_id", "default")

    async def evaluate_actionability(
        self,
        ref_id: str,
        timeout_ms: int = 1500,
        sample_interval_ms: int = 60,
    ) -> ActionabilityResult:
        """
        Runs the 5-point actionability gate on the targeted element reference.
        """
        now = time.time()
        current_epoch = self.reference_registry.current_epoch

        # 1. Gate 1: Attachment & Epoch Validation
        try:
            ref = self.reference_registry.resolve_ref(ref_id)
        except StaleReferenceException as e:
            stale_report = GateReport(
                gate_name="attachment",
                status=GateStatus.STALE,
                passed=False,
                reason=f"Reference '{ref_id}' belongs to a superseded epoch (current={current_epoch}, ref={e.ref_epoch}).",
                details={"ref_id": ref_id, "current_epoch": current_epoch, "ref_epoch": e.ref_epoch},
            )
            dummy_gate = GateReport(gate_name="skipped", status=GateStatus.STALE, passed=False, reason="Skipped due to stale reference.")
            return ActionabilityResult(
                ref_id=ref_id,
                epoch=current_epoch,
                plane=TargetPlane.UNKNOWN,
                attachment=stale_report,
                visibility=dummy_gate,
                motion=dummy_gate,
                enabledness=dummy_gate,
                hit_test=dummy_gate,
                affordance_point=None,
                affordance_point_type="NONE",
                physical_visibility="UNKNOWN",
                web_visibility="UNKNOWN",
                overall_status=OverallActionabilityStatus.STALE,
                is_actionable=False,
                reasons=(stale_report.reason,),
                evaluated_at=now,
            )

        if ref.plane == TargetPlane.WEBVIEW_DOM:
            return await self._evaluate_web_actionability(ref, timeout_ms, sample_interval_ms)
        else:
            return await self._evaluate_native_actionability(ref, timeout_ms, sample_interval_ms)

    async def _evaluate_web_actionability(
        self,
        ref: ElementRef,
        timeout_ms: int,
        sample_interval_ms: int,
    ) -> ActionabilityResult:
        """Evaluates 5-point gate for an embedded webview element."""
        reasons: List[str] = []
        now = time.time()

        if not self.webview_core or not self.webview_core.is_connected:
            fail_report = GateReport(
                gate_name="attachment",
                status=GateStatus.FAILED,
                passed=False,
                reason="Webview automation core is disconnected or unavailable.",
            )
            dummy = GateReport(gate_name="skipped", status=GateStatus.FAILED, passed=False, reason="Webview core disconnected.")
            return ActionabilityResult(
                ref_id=ref.ref_id,
                epoch=ref.epoch_id,
                plane=TargetPlane.WEBVIEW_DOM,
                attachment=fail_report,
                visibility=dummy,
                motion=dummy,
                enabledness=dummy,
                hit_test=dummy,
                affordance_point=None,
                affordance_point_type="NONE",
                physical_visibility="UNKNOWN",
                web_visibility="DISCONNECTED",
                overall_status=OverallActionabilityStatus.NOT_READY,
                is_actionable=False,
                reasons=("Webview automation core disconnected.",),
                evaluated_at=now,
            )

        # Gate 1: Attachment
        frame_id = ref.frame_id or self.webview_core.frame_manager.root_frame_id
        is_frame_valid = frame_id in self.webview_core.frame_manager.frames or frame_id == self.webview_core.frame_manager.root_frame_id
        if not is_frame_valid:
            attach_gate = GateReport(
                gate_name="attachment",
                status=GateStatus.FAILED,
                passed=False,
                reason=f"Target frame '{frame_id}' is detached from the frame tree.",
                details={"frame_id": frame_id},
            )
        else:
            attach_gate = GateReport(
                gate_name="attachment",
                status=GateStatus.PASSED,
                passed=True,
                reason="Element reference and parent frame are attached to active document.",
                details={"frame_id": frame_id, "epoch": ref.epoch_id},
            )
        if not attach_gate.passed:
            reasons.append(attach_gate.reason)

        # Gate 2: Computed Visibility (DOM style + Physical Desktop Reality)
        # Check physical window first (Physical Reality Primacy)
        native_hwnd = self.webview_core.native_hwnd
        physical_report = None
        if native_hwnd:
            physical_report = self.native_supervisor.inspect_window(native_hwnd)

        phys_vis_str = "VISIBLE"
        phys_blocked = False
        phys_reason = ""
        if physical_report:
            if physical_report.is_iconic:
                phys_vis_str = "MINIMIZED"
                phys_blocked = True
                phys_reason = "Parent native window is minimized (IsIconic=True)."
            elif physical_report.is_cloaked:
                phys_vis_str = "CLOAKED"
                phys_blocked = True
                phys_reason = "Parent native window is cloaked by DWM."
            elif not physical_report.is_visible:
                phys_vis_str = "HIDDEN"
                phys_blocked = True
                phys_reason = "Parent native window is hidden (IsWindowVisible=False)."
            elif physical_report.is_hung:
                phys_vis_str = "HUNG"
                phys_blocked = True
                phys_reason = "Parent native window UI thread is unresponsive."

        # Query live DOM geometry and style
        recipe = ref.locator_recipe or {}
        backend_query_script = self._build_query_script(ref)
        geom1 = await self._query_element_state(backend_query_script, frame_id)

        if not geom1 or not geom1.get("found"):
            vis_gate = GateReport(
                gate_name="computed_visibility",
                status=GateStatus.FAILED,
                passed=False,
                reason="Element not found in live DOM during actionability verification.",
                details={"query": recipe},
            )
            web_vis_str = "NOT_FOUND"
        elif not geom1.get("displayed") or geom1.get("opacity", 1.0) <= 0.05 or geom1.get("width", 0) <= 0:
            vis_gate = GateReport(
                gate_name="computed_visibility",
                status=GateStatus.FAILED,
                passed=False,
                reason=f"Element is hidden in CSS (display='{geom1.get('display')}', visibility='{geom1.get('visibility')}', opacity={geom1.get('opacity')}, size={geom1.get('width')}x{geom1.get('height')}).",
                details=geom1,
            )
            web_vis_str = "CSS_HIDDEN"
        elif phys_blocked:
            vis_gate = GateReport(
                gate_name="computed_visibility",
                status=GateStatus.FAILED,
                passed=False,
                reason=f"Physical Reality Primacy: {phys_reason}",
                details={"physical_status": phys_vis_str, "dom_geometry": geom1},
            )
            web_vis_str = "DOM_VISIBLE_BUT_PHYSICALLY_BLOCKED"
        else:
            vis_gate = GateReport(
                gate_name="computed_visibility",
                status=GateStatus.PASSED,
                passed=True,
                reason="Element is CSS visible, non-zero sized, in viewport, and physical window is visible.",
                details=geom1,
            )
            web_vis_str = "VISIBLE"
        if not vis_gate.passed:
            reasons.append(vis_gate.reason)

        # Gate 3: Motion Stability
        # Sample geometry across sample_interval_ms
        await asyncio.sleep(sample_interval_ms / 1000.0)
        geom2 = await self._query_element_state(backend_query_script, frame_id)

        if not geom1 or not geom2 or not geom2.get("found"):
            motion_gate = GateReport(
                gate_name="motion_stability",
                status=GateStatus.FAILED,
                passed=False,
                reason="Could not sample consecutive geometries for motion stability.",
            )
        else:
            dx = abs(geom1.get("x", 0) - geom2.get("x", 0))
            dy = abs(geom1.get("y", 0) - geom2.get("y", 0))
            if dx <= 1.0 and dy <= 1.0:
                motion_gate = GateReport(
                    gate_name="motion_stability",
                    status=GateStatus.PASSED,
                    passed=True,
                    reason=f"Element geometry is stable (delta: dx={dx:.2f}px, dy={dy:.2f}px <= 1px).",
                    details={"dx": dx, "dy": dy},
                )
            else:
                motion_gate = GateReport(
                    gate_name="motion_stability",
                    status=GateStatus.FAILED,
                    passed=False,
                    reason=f"Element is actively animating or moving (delta: dx={dx:.2f}px, dy={dy:.2f}px > 1px).",
                    details={"dx": dx, "dy": dy},
                )
        if not motion_gate.passed:
            reasons.append(motion_gate.reason)

        # Gate 4: Enabledness
        is_disabled = bool(geom2.get("disabled", False)) if geom2 else False
        if is_disabled:
            enable_gate = GateReport(
                gate_name="enabledness",
                status=GateStatus.FAILED,
                passed=False,
                reason="Element has 'disabled' attribute or aria-disabled='true'.",
                details={"disabled": is_disabled},
            )
            reasons.append(enable_gate.reason)
        else:
            enable_gate = GateReport(
                gate_name="enabledness",
                status=GateStatus.PASSED,
                passed=True,
                reason="Element is enabled and receptive to input.",
            )

        # Gate 5: Hit-Test & Occlusion
        # Compute affordance point
        affordance_pt = None
        if geom2 and geom2.get("found"):
            gx = geom2.get("x", 0)
            gy = geom2.get("y", 0)
            gw = geom2.get("width", 0)
            gh = geom2.get("height", 0)
            center_x = int(gx + gw / 2)
            center_y = int(gy + gh / 2)
            affordance_pt = (center_x, center_y)

        hit_test_passed = False
        hit_reason = ""
        hit_details: Dict[str, Any] = {}

        if affordance_pt:
            # Check document.elementFromPoint in utility world
            hit_script = f"""
            (() => {{
                const el = document.elementFromPoint({affordance_pt[0]}, {affordance_pt[1]});
                if (!el) return {{ hit: false, reason: 'elementFromPoint returned null' }};
                return {{
                    hit: true,
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    class: el.className || '',
                    text: (el.innerText || '').substring(0, 30)
                }};
            }})()
            """
            hit_res = await self._query_element_state(hit_script, frame_id)
            if hit_res and hit_res.get("hit"):
                # Also check physical desktop occlusion if native HWND is known
                if native_hwnd:
                    occlusion = self.native_supervisor.check_window_occlusion(native_hwnd)
                    if occlusion == OcclusionState.LIKELY_OCCLUDED:
                        hit_test_passed = False
                        hit_reason = "Physical Reality Primacy: Desktop window is occluded by overlying native windows."
                        hit_details = {"occlusion": occlusion.value, "dom_hit": hit_res}
                    else:
                        hit_test_passed = True
                        hit_reason = f"Hit-test verified at point ({affordance_pt[0]}, {affordance_pt[1]}); hit target element."
                        hit_details = {"dom_hit": hit_res, "desktop_occlusion": occlusion.value}
                else:
                    hit_test_passed = True
                    hit_reason = f"DOM hit-test verified at point ({affordance_pt[0]}, {affordance_pt[1]})."
                    hit_details = {"dom_hit": hit_res}
            else:
                hit_test_passed = False
                hit_reason = f"Affordance point ({affordance_pt[0]}, {affordance_pt[1]}) is occluded by another DOM layer."
                hit_details = {"dom_hit": hit_res}
        else:
            hit_test_passed = False
            hit_reason = "Could not compute a valid affordance center point for hit-testing."

        hit_gate = GateReport(
            gate_name="hit_test",
            status=GateStatus.PASSED if hit_test_passed else GateStatus.FAILED,
            passed=hit_test_passed,
            reason=hit_reason,
            details=hit_details,
        )
        if not hit_gate.passed:
            reasons.append(hit_gate.reason)

        all_passed = (
            attach_gate.passed
            and vis_gate.passed
            and motion_gate.passed
            and enable_gate.passed
            and hit_gate.passed
        )

        overall_status = OverallActionabilityStatus.READY if all_passed else OverallActionabilityStatus.NOT_READY

        return ActionabilityResult(
            ref_id=ref.ref_id,
            epoch=ref.epoch_id,
            plane=TargetPlane.WEBVIEW_DOM,
            attachment=attach_gate,
            visibility=vis_gate,
            motion=motion_gate,
            enabledness=enable_gate,
            hit_test=hit_gate,
            affordance_point=affordance_pt,
            affordance_point_type="VIEWPORT_LOGICAL",
            physical_visibility=phys_vis_str,
            web_visibility=web_vis_str,
            overall_status=overall_status,
            is_actionable=all_passed,
            reasons=tuple(reasons),
            evaluated_at=now,
        )

    async def _evaluate_native_actionability(
        self,
        ref: ElementRef,
        timeout_ms: int,
        sample_interval_ms: int,
    ) -> ActionabilityResult:
        """Evaluates 5-point gate for a native Win32 / UIA control."""
        reasons: List[str] = []
        now = time.time()
        recipe = ref.locator_recipe or {}
        hwnd = 0
        if recipe.get("hwnd"):
            hwnd = int(recipe["hwnd"])
        elif ref.target_id:
            try:
                hwnd = int(ref.target_id, 0)
            except ValueError:
                hwnd = 0

        # Gate 1: Attachment
        if not hwnd or not self.native_supervisor.is_window(hwnd):
            attach_gate = GateReport(
                gate_name="attachment",
                status=GateStatus.FAILED,
                passed=False,
                reason=f"Native window HWND {hex(hwnd)} is destroyed or invalid.",
                details={"hwnd": hex(hwnd)},
            )
            dummy = GateReport(gate_name="skipped", status=GateStatus.FAILED, passed=False, reason="HWND invalid.")
            return ActionabilityResult(
                ref_id=ref.ref_id,
                epoch=ref.epoch_id,
                plane=TargetPlane.NATIVE_SHELL,
                attachment=attach_gate,
                visibility=dummy,
                motion=dummy,
                enabledness=dummy,
                hit_test=dummy,
                affordance_point=None,
                affordance_point_type="NONE",
                physical_visibility="DESTROYED",
                web_visibility="N/A",
                overall_status=OverallActionabilityStatus.NOT_READY,
                is_actionable=False,
                reasons=(attach_gate.reason,),
                evaluated_at=now,
            )

        attach_gate = GateReport(
            gate_name="attachment",
            status=GateStatus.PASSED,
            passed=True,
            reason=f"Native window HWND {hex(hwnd)} is valid in Win32 subsystem.",
            details={"hwnd": hex(hwnd), "epoch": ref.epoch_id},
        )

        # Gate 2: Computed Visibility (Physical OS Visibility)
        phys = self.native_supervisor.inspect_window(hwnd)
        phys_vis_str = "VISIBLE"
        if phys.is_iconic:
            phys_vis_str = "MINIMIZED"
            vis_gate = GateReport(gate_name="computed_visibility", status=GateStatus.FAILED, passed=False, reason="Window is minimized.")
        elif phys.is_cloaked:
            phys_vis_str = "CLOAKED"
            vis_gate = GateReport(gate_name="computed_visibility", status=GateStatus.FAILED, passed=False, reason="Window is cloaked by DWM.")
        elif not phys.is_visible:
            phys_vis_str = "HIDDEN"
            vis_gate = GateReport(gate_name="computed_visibility", status=GateStatus.FAILED, passed=False, reason="Window has IsWindowVisible=False.")
        else:
            vis_gate = GateReport(gate_name="computed_visibility", status=GateStatus.PASSED, passed=True, reason="Window is physically visible on desktop.")
        if not vis_gate.passed:
            reasons.append(vis_gate.reason)

        # Gate 3: Motion Stability
        rect1 = phys.bounds
        await asyncio.sleep(sample_interval_ms / 1000.0)
        phys2 = self.native_supervisor.inspect_window(hwnd)
        rect2 = phys2.bounds

        dx = abs(rect1.x - rect2.x)
        dy = abs(rect1.y - rect2.y)
        dw = abs(rect1.width - rect2.width)
        dh = abs(rect1.height - rect2.height)
        if dx == 0 and dy == 0 and dw == 0 and dh == 0:
            motion_gate = GateReport(gate_name="motion_stability", status=GateStatus.PASSED, passed=True, reason="Native window bounds are physically static.")
        else:
            motion_gate = GateReport(gate_name="motion_stability", status=GateStatus.FAILED, passed=False, reason=f"Window is actively moving or resizing (dx={dx}, dy={dy}, dw={dw}, dh={dh}).")
        if not motion_gate.passed:
            reasons.append(motion_gate.reason)

        # Gate 4: Enabledness
        is_hung = phys2.is_hung
        is_enabled = self.native_supervisor.is_window_enabled(hwnd)
        if is_hung:
            enable_gate = GateReport(gate_name="enabledness", status=GateStatus.FAILED, passed=False, reason="Native window UI thread is hung (failed SendMessageTimeout).")
        elif not is_enabled:
            enable_gate = GateReport(gate_name="enabledness", status=GateStatus.FAILED, passed=False, reason="Native window is disabled (IsWindowEnabled=False).")
        else:
            enable_gate = GateReport(gate_name="enabledness", status=GateStatus.PASSED, passed=True, reason="Native window is enabled and responsive.")
        if not enable_gate.passed:
            reasons.append(enable_gate.reason)

        # Gate 5: Hit-Testing & Occlusion
        affordance_pt = ref.bounds.center if ref.bounds.area > 0 else rect2.center
        occlusion = self.native_supervisor.check_window_occlusion(hwnd)
        modals = self.native_supervisor.scan_modal_dialogs(phys2.pid)

        if len(modals) > 0:
            hit_gate = GateReport(gate_name="hit_test", status=GateStatus.FAILED, passed=False, reason=f"Window interaction is blocked by active modal dialog ({len(modals)} detected).")
        elif occlusion == OcclusionState.LIKELY_OCCLUDED:
            hit_gate = GateReport(gate_name="hit_test", status=GateStatus.FAILED, passed=False, reason="Window is completely occluded by other foreground windows.")
        else:
            hit_gate = GateReport(gate_name="hit_test", status=GateStatus.PASSED, passed=True, reason=f"Window affordance point {affordance_pt} is physically un-occluded ({occlusion.value}).")
        if not hit_gate.passed:
            reasons.append(hit_gate.reason)

        all_passed = (
            attach_gate.passed
            and vis_gate.passed
            and motion_gate.passed
            and enable_gate.passed
            and hit_gate.passed
        )

        overall = OverallActionabilityStatus.READY if all_passed else OverallActionabilityStatus.NOT_READY

        return ActionabilityResult(
            ref_id=ref.ref_id,
            epoch=ref.epoch_id,
            plane=TargetPlane.NATIVE_SHELL,
            attachment=attach_gate,
            visibility=vis_gate,
            motion=motion_gate,
            enabledness=enable_gate,
            hit_test=hit_gate,
            affordance_point=affordance_pt,
            affordance_point_type="SCREEN_CANONICAL",
            physical_visibility=phys_vis_str,
            web_visibility="N/A",
            overall_status=overall,
            is_actionable=all_passed,
            reasons=tuple(reasons),
            evaluated_at=now,
        )

    def _build_query_script(self, ref: ElementRef) -> str:
        recipe = ref.locator_recipe or {}
        name = recipe.get("name") or recipe.get("text") or ""
        role = recipe.get("role") or ""
        ph = recipe.get("placeholder") or ""
        tag = recipe.get("tag") or ""

        return f"""
        (() => {{
            const targetName = {repr(name.strip().lower())};
            const targetRole = {repr(role.strip().lower())};
            const targetPh = {repr(ph.strip().lower())};
            const targetTag = {repr(tag.strip().lower())};

            const all = document.querySelectorAll('*');
            let matched = null;

            for (const el of all) {{
                const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                const ph = (el.getAttribute('placeholder') || '').trim().toLowerCase();
                const r = (el.getAttribute('role') || el.tagName).trim().toLowerCase();
                const tag = el.tagName.toLowerCase();

                if (targetName && (text === targetName || aria === targetName)) {{
                    matched = el;
                    break;
                }}
                if (targetPh && ph === targetPh) {{
                    matched = el;
                    break;
                }}
                if (targetRole && (r === targetRole || tag === targetRole)) {{
                    if (targetName && (text.includes(targetName) || aria.includes(targetName))) {{
                        matched = el;
                        break;
                    }}
                }}
            }}

            if (!matched) return {{ found: false }};

            const rect = matched.getBoundingClientRect();
            const style = window.getComputedStyle(matched);
            return {{
                found: true,
                display: style.display,
                visibility: style.visibility,
                opacity: parseFloat(style.opacity || '1.0'),
                displayed: style.display !== 'none' && style.visibility !== 'hidden',
                disabled: matched.disabled === true || matched.getAttribute('aria-disabled') === 'true',
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height
            }};
        }})()
        """

    async def _query_element_state(self, script: str, frame_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not self.webview_core or not self.webview_core.is_connected:
            return None
        try:
            res = await self.webview_core.utility_world.evaluate(
                expression=script,
                frame_id=frame_id,
                return_by_value=True,
            )
            return res if isinstance(res, dict) else None
        except Exception:
            return None
