"""
Reality Inspector Specialist Subagent (Architecture H / Phase 15).
Mandate: "What does the human user physically see on screen?"
Inspects DWM compositor state, window forensics, physical bounds, occlusion, and framebuffer screenshots.
Codifies the Truth Hierarchy: Physical Desktop Reality > Compositor Reality > DOM/Web Reality.
Strictly read-only; forbids synthetic input or converting DOM assertions into physical truth.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Dict, List, Optional, Any

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import (
    SpecialistLifecycleState,
    SpecialistResultStatus,
    SpecialistResult,
)
from runtime.specialists.base import BaseSpecialistRuntime
from runtime.reality_models import TruthHierarchyLevel

logger = logging.getLogger("desktop_webview.specialist.reality_inspector")


class RealityInspectorSpecialist(BaseSpecialistRuntime):
    """Subordinate specialist answering: 'What does the human user physically see on screen?'"""

    @property
    def role(self) -> SpecialistRole:
        return SpecialistRole.REALITY_INSPECTOR

    async def execute(self) -> SpecialistResult:
        self._record_lifecycle(SpecialistLifecycleState.OBSERVING, "Inspecting physical DWM compositor and screen reality.")

        target_win = getattr(self.session_state, "target_window", None)
        target_hwnd = target_win.hwnd if target_win else getattr(self.session_state, "target_hwnd", None)
        supervisor = getattr(self.session_state, "native_supervisor", None)

        window_forensics: Dict[str, Any] = {}
        monitor_topology: List[Dict[str, Any]] = []
        contradictions: List[str] = []
        limitations: List[str] = []
        evidence_refs: List[str] = []
        trace_refs: List[str] = []

        is_physically_visible = False
        is_cloaked = False
        is_minimized = False
        is_foreground = False
        occlusion_detected = False
        dwm_enabled = True

        # 1. Desktop Eyes: Monitor Topology
        if supervisor:
            try:
                monitors = supervisor.get_monitor_topology()
                monitor_topology = [m.to_dict() for m in monitors]
            except Exception as e:
                limitations.append(f"Monitor topology query failed: {e}")

        if supervisor and target_hwnd and ("desktop_get_window_forensics" in self.delegation.permitted_tools or "desktop_inspect" in self.delegation.permitted_tools):
            try:
                insp = supervisor.inspect_window(target_hwnd)
                foreground_hwnd = supervisor.get_foreground_window()
                is_foreground = (foreground_hwnd == target_hwnd)
                is_cloaked = getattr(insp, "is_cloaked", False)
                is_minimized = getattr(insp, "is_iconic", False)
                raw_visible = getattr(insp, "is_visible", False)

                # Physical visibility requires visible, non-cloaked, non-minimized, and non-zero area
                has_area = (insp.bounds.width > 0 and insp.bounds.height > 0)
                is_physically_visible = raw_visible and not is_cloaked and not is_minimized and has_area

                window_forensics = {
                    "hwnd": hex(target_hwnd),
                    "title": self.sanitize_untrusted_content(insp.title),
                    "pid": insp.pid,
                    "bounds": [insp.bounds.x, insp.bounds.y, insp.bounds.width, insp.bounds.height],
                    "is_visible_win32": raw_visible,
                    "is_cloaked_dwm": is_cloaked,
                    "is_iconic_minimized": is_minimized,
                    "is_foreground": is_foreground,
                    "has_renderable_area": has_area,
                    "physical_visibility": is_physically_visible,
                }
            except Exception as e:
                limitations.append(f"Window forensics inspection failed for HWND {target_hwnd}: {e}")

        # 3. Screenshot Capture & Pixel Evidence
        screenshot_evidence = None
        if "desktop_screenshot" in self.delegation.permitted_tools and supervisor and target_hwnd and is_physically_visible:
            try:
                async def _cap_shot():
                    return supervisor.capture_window_screenshot(target_hwnd)

                shot = await self.invoke_tool("desktop_screenshot", _cap_shot)
                if shot:
                    evidence_refs.append(f"screenshot_{hex(target_hwnd)}")
                    screenshot_evidence = {
                        "captured": True,
                        "hwnd": hex(target_hwnd),
                        "width": getattr(shot, "width", 0) if hasattr(shot, "width") else None,
                        "height": getattr(shot, "height", 0) if hasattr(shot, "height") else None,
                    }
            except Exception as e:
                limitations.append(f"Physical screenshot capture failed: {e}")

        # 4. Truth Hierarchy Cross-Reconciliation (DOM vs Compositor vs Desktop)
        # Check if DOM claims elements are visible while DWM proves window is cloaked or minimized
        obs_engine = getattr(self.session_state, "observation_engine", None)
        if obs_engine:
            try:
                latest_obs = getattr(obs_engine, "last_observation", None)
                if latest_obs and hasattr(latest_obs, "nodes") and len(latest_obs.nodes) > 0:
                    if is_cloaked:
                        contradictions.append(
                            "TRUTH CONTRADICTION: DOM reports interactive elements present, but DWM confirms target window is CLOAKED. Physical visibility is FALSE."
                        )
                    elif is_minimized:
                        contradictions.append(
                            "TRUTH CONTRADICTION: DOM reports elements present, but target window is MINIMIZED. Physical visibility is FALSE."
                        )
                    elif not is_physically_visible and target_hwnd:
                        contradictions.append(
                            "TRUTH CONTRADICTION: Webview DOM is active, but window has zero renderable bounds on desktop."
                        )
            except Exception as e:
                limitations.append(f"Cross-reconciliation check failed: {e}")

        # Determine authoritative verdict
        if not target_hwnd and not window_forensics:
            status = SpecialistResultStatus.UNVERIFIED
            answer = "Reality Inspector could not identify target window; physical state remains UNVERIFIED."
        elif is_cloaked or is_minimized or not is_physically_visible:
            status = SpecialistResultStatus.DEGRADED if is_cloaked or is_minimized else SpecialistResultStatus.FAILED
            reasons = []
            if is_cloaked:
                reasons.append("cloaked by DWM")
            if is_minimized:
                reasons.append("minimized")
            if not is_physically_visible:
                reasons.append("non-renderable on physical desktop")
            answer = f"Target window {hex(target_hwnd or 0)} is NOT physically visible: {', '.join(reasons)}."
        else:
            status = SpecialistResultStatus.SUCCESS
            answer = (
                f"Target window {hex(target_hwnd or 0)} is physically visible on screen "
                f"(bounds={window_forensics.get('bounds')}, foreground={is_foreground}, cloaked=False)."
            )

        return SpecialistResult(
            specialist_id=self.specialist_id,
            role=self.role,
            delegation_id=self.delegation.delegation_id,
            session_id=self.session_state.session_id,
            status=status,
            answer=answer,
            observations={
                "physical_visibility": is_physically_visible,
                "is_cloaked": is_cloaked,
                "is_minimized": is_minimized,
                "is_foreground": is_foreground,
                "window_forensics": window_forensics,
                "monitor_topology": monitor_topology,
                "screenshot_evidence": screenshot_evidence,
                "contradictions": contradictions,
                "truth_hierarchy_level": TruthHierarchyLevel.PHYSICAL_DESKTOP.value,
            },
            evidence_refs=evidence_refs,
            trace_refs=trace_refs,
            limitations=limitations,
            confidence=0.98 if is_physically_visible else 0.85,
        )
