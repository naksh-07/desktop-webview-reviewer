"""
Unified Dual-Perspective Observation Engine Facade.
Orchestrates native OS supervision, webview CDP inspection, context reconciliation,
compact YAML formatting, pagination, and differential snapshot generation.
"""

from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional, Any, Tuple, Set

from runtime.references import ReferenceRegistry
from runtime.native_supervisor import NativeSupervisor
from runtime.webview_core import WebviewAutomationCore
from runtime.flaui_bridge import FlaUIBridge
from runtime.native_observation import NativeObservationExtractor
from runtime.web_observation import WebObservationExtractor
from runtime.reconciliation import ContextReconciler, RealityReconciler
from runtime.reality_models import RealityReconciliationSnapshot
from runtime.observation_compaction import format_observation_yaml
from runtime.observation_pagination import ObservationPaginator
from runtime.observation_diff import ObservationDiffer, ObservationDiffResult
from runtime.observation_models import (
    DualPerspectiveSnapshot,
    NativeObservation,
    WebObservation,
    ReconciliationObservation,
)

logger = logging.getLogger("desktop_webview.observation_engine")


class ObservationEngine:
    """
    Central Observation Engine (Architecture H).
    Preserves independent dual perspectives while providing synchronized reconciliation.
    """

    def __init__(
        self,
        session_id: str,
        reference_registry: ReferenceRegistry,
        native_supervisor: NativeSupervisor,
        webview_core: Optional[WebviewAutomationCore] = None,
        flaui_bridge: Optional[FlaUIBridge] = None,
    ):
        self.session_id = session_id
        self.reference_registry = reference_registry
        self.native_supervisor = native_supervisor
        self.webview_core = webview_core
        self.flaui_bridge = flaui_bridge

        # Extractors & Subsystems
        self.native_extractor = NativeObservationExtractor(
            native_supervisor=self.native_supervisor,
            reference_registry=self.reference_registry,
            flaui_bridge=self.flaui_bridge,
        )
        self.web_extractor: Optional[WebObservationExtractor] = None
        if self.webview_core:
            self.web_extractor = WebObservationExtractor(
                webview_core=self.webview_core,
                reference_registry=self.reference_registry,
            )

        self.reconciler = ContextReconciler()
        self.reality_reconciler = RealityReconciler(self.reconciler)
        self.paginator = ObservationPaginator(self.reference_registry)
        self.differ = ObservationDiffer()

        # Historical snapshots by epoch: epoch -> DualPerspectiveSnapshot
        self._snapshots: Dict[int, DualPerspectiveSnapshot] = {}
        self._last_snapshot: Optional[DualPerspectiveSnapshot] = None
        self._last_reality_snapshot: Optional[RealityReconciliationSnapshot] = None

    @property
    def current_epoch(self) -> int:
        return self.reference_registry.current_epoch

    @property
    def last_snapshot(self) -> Optional[DualPerspectiveSnapshot]:
        return self._last_snapshot

    @property
    def last_reality_snapshot(self) -> Optional[RealityReconciliationSnapshot]:
        return self._last_reality_snapshot

    async def observe(
        self,
        hwnd: Optional[int] = None,
        target_id: Optional[str] = None,
        diff_only: bool = False,
        max_depth: int = 5,
        role_filter: Optional[Set[str]] = None,
        actionable_only: bool = False,
        visible_only: bool = True,
        frame_id: Optional[str] = None,
    ) -> DualPerspectiveSnapshot:
        """
        Executes a full dual-perspective observation pass.
        If diff_only=True and a prior epoch exists, populates the text_representation with diff syntax.
        """
        now = time.time()
        epoch = self.reference_registry.current_epoch

        # 1. Observe Native Perspective
        native_obs: Optional[NativeObservation] = None
        target_hwnd = hwnd or (self.webview_core.native_hwnd if self.webview_core else None)
        if not target_hwnd and self.webview_core and self.webview_core.native_pid and self.native_supervisor:
            try:
                candidate_pids = {self.webview_core.native_pid}
                import psutil
                proc = psutil.Process(self.webview_core.native_pid)
                candidate_pids.update(c.pid for c in proc.children(recursive=True))
                for c_pid in candidate_pids:
                    for h in self.native_supervisor.find_windows_by_pid(c_pid):
                        if self.native_supervisor.is_window_visible(h):
                            target_hwnd = h
                            self.webview_core.native_hwnd = h
                            break
                    if target_hwnd:
                        break
            except Exception:
                pass

        if target_hwnd:
            native_obs = await self.native_extractor.observe_native_window(
                session_id=self.session_id,
                hwnd=target_hwnd,
                max_depth=min(max_depth, 3),
                actionable_only=actionable_only,
            )

        # 2. Observe Web Perspective
        web_obs: Optional[WebObservation] = None
        if self.web_extractor and self.webview_core and self.webview_core.is_connected:
            web_obs = await self.web_extractor.observe_webview(
                session_id=self.session_id,
                target_id=target_id,
                max_depth=max_depth,
                role_filter=role_filter,
                actionable_only=actionable_only,
                visible_only=visible_only,
                frame_id=frame_id,
            )

        # 3. Reconcile perspectives
        reconciliation: Optional[ReconciliationObservation] = None
        if native_obs and web_obs:
            reconciliation = self.reconciler.reconcile(native_obs, web_obs)

        # 4. Check diff vs standard formatting
        text_rep = ""
        is_diff_mode = False
        if diff_only and self._last_snapshot is not None:
            prev = self._last_snapshot
            temp_curr = DualPerspectiveSnapshot(
                session_id=self.session_id,
                epoch=epoch,
                timestamp=now,
                native_observation=native_obs,
                web_observation=web_obs,
                reconciliation=reconciliation,
                text_representation="",
                is_diff=True,
            )
            diff_res = self.differ.diff(prev, temp_curr)
            text_rep = diff_res.text_diff
            is_diff_mode = True
        else:
            text_rep = format_observation_yaml(native_obs, web_obs, reconciliation)

        snapshot = DualPerspectiveSnapshot(
            session_id=self.session_id,
            epoch=epoch,
            timestamp=now,
            native_observation=native_obs,
            web_observation=web_obs,
            reconciliation=reconciliation,
            text_representation=text_rep,
            is_diff=is_diff_mode,
        )

        # 5. Authoritative Reality Model Reconciliation
        try:
            self._last_reality_snapshot = self.reality_reconciler.reconcile_snapshot(
                session_id=self.session_id,
                epoch=epoch,
                native_obs=native_obs,
                web_obs=web_obs,
                reference_registry=self.reference_registry,
            )
        except Exception as e:
            logger.warning(f"Reality reconciliation failed: {e}")

        self._snapshots[epoch] = snapshot
        self._last_snapshot = snapshot
        return snapshot

    async def observe_reality(
        self,
        hwnd: Optional[int] = None,
        target_id: Optional[str] = None,
    ) -> RealityReconciliationSnapshot:
        """
        Executes an observation pass and returns the authoritative RealityReconciliationSnapshot.
        """
        await self.observe(hwnd=hwnd, target_id=target_id)
        if self._last_reality_snapshot is not None:
            return self._last_reality_snapshot
        # Fallback snapshot
        return RealityReconciliationSnapshot(
            session_id=self.session_id,
            observation_epoch=self.current_epoch,
        )

    async def observe_desktop(
        self,
        capture_screenshot: bool = False,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Captures the physical desktop environment:
        virtual screen bounds, multi-monitor topology, active top-level windows,
        and optional full desktop screenshot.
        """
        topology = self.native_supervisor.get_monitor_topology()
        windows: List[Dict[str, Any]] = []
        try:
            hwnds = self.native_supervisor.list_top_level_windows(visible_only=True)
            for h in hwnds[:30]:
                try:
                    insp = self.native_supervisor.inspect_window(h)
                    windows.append({
                        "hwnd": hex(h),
                        "title": insp.title,
                        "class_name": insp.class_name,
                        "pid": insp.pid,
                        "bounds": insp.bounds.to_dict(),
                        "is_cloaked": insp.is_cloaked,
                        "is_minimized": insp.is_iconic,
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Error enumerating windows during desktop observation: {e}")

        res: Dict[str, Any] = {
            "session_id": self.session_id,
            "timestamp": time.time(),
            "virtual_screen": topology.virtual_screen.to_dict(),
            "monitors": [m.to_dict() for m in topology.monitors],
            "windows": windows,
        }

        if capture_screenshot:
            ok, _, sha256_hash, meta = self.native_supervisor.capture_full_desktop_screenshot(output_path=output_path)
            res["screenshot"] = {
                "success": ok,
                "sha256": sha256_hash,
                "output_path": meta.get("output_path"),
            }

        return res

    def compute_diff(self, from_epoch: int, to_epoch: int) -> Optional[ObservationDiffResult]:
        """Calculates difference between two stored epoch snapshots."""
        snap_a = self._snapshots.get(from_epoch)
        snap_b = self._snapshots.get(to_epoch)
        if not snap_a or not snap_b:
            return None
        return self.differ.diff(snap_a, snap_b)
