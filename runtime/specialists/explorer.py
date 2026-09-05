"""
Explorer Specialist Subagent (Architecture H / Phase 15).
Mandate: "What exists in the application right now?"
Enumerates windows, webview targets, frames, elements, topology, and capabilities.
Enforces read-only operation; strictly forbids state mutation or mission expansion.
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

logger = logging.getLogger("desktop_webview.specialist.explorer")


class ExplorerSpecialist(BaseSpecialistRuntime):
    """Subordinate specialist answering: 'What exists in the application right now?'"""

    @property
    def role(self) -> SpecialistRole:
        return SpecialistRole.EXPLORER

    async def execute(self) -> SpecialistResult:
        self._record_lifecycle(SpecialistLifecycleState.OBSERVING, "Enumerating application surfaces and targets.")

        windows: List[Dict[str, Any]] = []
        webviews: List[Dict[str, Any]] = []
        frames: List[Dict[str, Any]] = []
        elements: List[Dict[str, Any]] = []
        capabilities: Dict[str, Any] = {}
        contradictions: List[str] = []
        limitations: List[str] = []
        evidence_refs: List[str] = []
        trace_refs: List[str] = []

        # 1. Capabilities inspection
        caps = getattr(self.session_state, "capabilities", None)
        if caps:
            capabilities = caps.to_dict()

        # 2. Native Window Enumeration
        supervisor = getattr(self.session_state, "native_supervisor", None)
        target_win = getattr(self.session_state, "target_window", None)
        target_hwnd = target_win.hwnd if target_win else getattr(self.session_state, "target_hwnd", None)

        if supervisor and "desktop_inspect" in self.delegation.permitted_tools:
            try:
                # If target_hwnd known, inspect specifically
                if target_hwnd:
                    insp = supervisor.inspect_window(target_hwnd)
                    windows.append({
                        "hwnd": hex(target_hwnd),
                        "title": self.sanitize_untrusted_content(insp.title),
                        "pid": insp.pid,
                        "bounds": [insp.bounds.x, insp.bounds.y, insp.bounds.width, insp.bounds.height],
                        "is_visible": insp.is_visible,
                        "is_cloaked": insp.is_cloaked,
                        "is_iconic": insp.is_iconic,
                        "is_foreground": supervisor.get_foreground_window() == target_hwnd,
                    })
                else:
                    for h in supervisor.list_top_level_windows(visible_only=True)[:10]:
                        insp = supervisor.inspect_window(h)
                        windows.append({
                            "hwnd": hex(h),
                            "title": self.sanitize_untrusted_content(insp.title),
                            "pid": insp.pid,
                            "bounds": [insp.bounds.x, insp.bounds.y, insp.bounds.width, insp.bounds.height],
                            "is_visible": insp.is_visible,
                            "is_cloaked": insp.is_cloaked,
                        })
            except Exception as e:
                limitations.append(f"Window enumeration failed: {e}")

        # 3. WebView Targets & Frames
        wv_core = getattr(self.session_state, "webview_core", None)
        if wv_core and "desktop_query_targets" in self.delegation.permitted_tools or "desktop_inspect" in self.delegation.permitted_tools:
            try:
                if hasattr(wv_core, "target_manager") and wv_core.target_manager:
                    for t in wv_core.target_manager.get_all_targets():
                        webviews.append({
                            "target_id": t.target_id,
                            "title": self.sanitize_untrusted_content(t.title),
                            "url": self.sanitize_untrusted_content(t.url),
                            "type": t.target_type,
                        })
                elif hasattr(wv_core, "active_target_id"):
                    webviews.append({
                        "target_id": wv_core.active_target_id,
                        "title": self.sanitize_untrusted_content(getattr(wv_core, "active_title", "webview")),
                        "url": self.sanitize_untrusted_content(getattr(wv_core, "active_url", "")),
                    })

                if hasattr(wv_core, "frame_manager") and wv_core.frame_manager:
                    for f_id, frame in wv_core.frame_manager.get_all_frames().items():
                        frames.append({
                            "frame_id": f_id,
                            "url": self.sanitize_untrusted_content(frame.url),
                            "is_main_frame": frame.is_main_frame,
                        })
            except Exception as e:
                limitations.append(f"WebView enumeration failed: {e}")

        # 4. Interactive Elements (Observation snapshot)
        obs_engine = getattr(self.session_state, "observation_engine", None)
        if obs_engine and "desktop_inspect" in self.delegation.permitted_tools:
            try:
                async def _get_obs():
                    return await obs_engine.capture_observation(max_depth=5, visible_only=True)

                obs = await self.invoke_tool("desktop_inspect", _get_obs)
                if obs:
                    if hasattr(obs, "nodes"):
                        for node in obs.nodes[:50]:
                            elements.append({
                                "ref": node.reference,
                                "role": node.role,
                                "name": self.sanitize_untrusted_content(node.name),
                                "bounds": [node.bounds.x, node.bounds.y, node.bounds.width, node.bounds.height] if node.bounds else None,
                            })
                    if hasattr(obs, "epoch"):
                        capabilities["active_epoch"] = obs.epoch
            except Exception as e:
                limitations.append(f"Element observation failed: {e}")

        # 5. Screenshot Capture if requested
        screenshot_artifact = None
        if "desktop_screenshot" in self.delegation.permitted_tools:
            try:
                native_sup = getattr(self.session_state, "native_supervisor", None)
                if native_sup and target_hwnd:
                    async def _cap_shot():
                        return native_sup.capture_window_screenshot(target_hwnd)
                    shot = await self.invoke_tool("desktop_screenshot", _cap_shot)
                    if shot:
                        evidence_refs.append(f"screenshot_{target_hwnd}")
            except Exception as e:
                limitations.append(f"Screenshot capture failed: {e}")

        # Check for contradictions
        if windows and webviews:
            # Check if webview URL implies blank or unloaded while window is visible
            for wv in webviews:
                if wv.get("url") in ("about:blank", "chrome-error://"):
                    contradictions.append(f"WebView target '{wv.get('title')}' is on error/blank URL: {wv.get('url')}")

        answer = (
            f"Explorer enumerated {len(windows)} top-level window(s), {len(webviews)} webview target(s), "
            f"{len(frames)} frame(s), and {len(elements)} interactive element(s)."
        )

        return SpecialistResult(
            specialist_id=self.specialist_id,
            role=self.role,
            delegation_id=self.delegation.delegation_id,
            session_id=self.session_state.session_id,
            status=SpecialistResultStatus.SUCCESS,
            answer=answer,
            observations={
                "windows": windows,
                "webviews": webviews,
                "frames": frames,
                "elements_count": len(elements),
                "elements_sample": elements[:20],
                "capabilities": capabilities,
                "contradictions": contradictions,
            },
            evidence_refs=evidence_refs,
            trace_refs=trace_refs,
            limitations=limitations,
            confidence=0.95 if not limitations else 0.8,
        )
