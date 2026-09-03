"""
Native OS Supervisor Foundation for Desktop WebView Reviewer.
Python-side authority for physical desktop truth, HWND validation, DWM extended frame bounds,
pre-flight responsiveness checks via SendMessageTimeout(WM_NULL), Z-order and physical occlusion,
native modal dialog detection, and leak-free GDI screenshot capture.
Grounded in Phase 0.1 empirical findings and Phase 2 hardening specifications.
"""

from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import logging
import os
import struct
import sys
import time
import zlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Set

from runtime.references import Rect
from runtime.state import HealthState
from runtime.errors import (
    TargetHungException,
    WindowCloakedException,
    InvalidTargetException,
    TargetExitedException,
)
from runtime.coordinate_transform import (
    CoordinateTransformContext,
    CoordinateTransformer,
    VirtualScreenBounds,
)
import runtime.win32 as w32

logger = logging.getLogger("desktop_webview.native_supervisor")


# -----------------------------------------------------------------------------
# 1. State Models: Occlusion, Visibility, Modals, Responsiveness
# -----------------------------------------------------------------------------
class OcclusionState(str, Enum):
    """Physical window occlusion states."""
    NOT_OCCLUDED = "NOT_OCCLUDED"
    PARTIALLY_OCCLUDED = "PARTIALLY_OCCLUDED"
    LIKELY_OCCLUDED = "LIKELY_OCCLUDED"  # >= 95% covered by foreground windows
    UNKNOWN = "UNKNOWN"


class ModalState(str, Enum):
    """Native modal dialog states."""
    NO_MODAL = "NO_MODAL"
    MODAL_DETECTED = "MODAL_DETECTED"
    UNKNOWN = "UNKNOWN"


class VisibilityStatus(str, Enum):
    """Truthful capability/diagnostic states."""
    SUPPORTED = "SUPPORTED"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ResponsivenessReport:
    """Structured pre-flight health gate report."""
    hwnd: int
    pid: int
    health_state: HealthState
    elapsed_ms: float
    is_timeout: bool
    timestamp: float = field(default_factory=time.time)
    last_error: Optional[int] = None

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, HealthState):
            return self.health_state == other
        if isinstance(other, str):
            return self.health_state.value == other
        if isinstance(other, ResponsivenessReport):
            return (
                self.hwnd == other.hwnd
                and self.pid == other.pid
                and self.health_state == other.health_state
                and self.is_timeout == other.is_timeout
            )
        return False

    def __hash__(self) -> int:
        return hash((self.hwnd, self.pid, self.health_state, self.is_timeout))

    @property
    def value(self) -> str:
        return self.health_state.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd),
            "pid": self.pid,
            "health_state": self.health_state.value,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "is_timeout": self.is_timeout,
            "timestamp": self.timestamp,
            "last_error": self.last_error,
        }


@dataclass(frozen=True)
class PhysicalVisibilityReport:
    """Multi-dimensional physical visibility diagnostics."""
    hwnd: int
    exists: bool
    visible: bool
    minimized: bool
    cloaked: bool
    foreground: bool
    enabled: bool
    responsive: bool
    physically_bounded: bool
    status: VisibilityStatus = VisibilityStatus.SUPPORTED
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_interactable(self) -> bool:
        return (
            self.exists
            and self.visible
            and not self.minimized
            and not self.cloaked
            and self.enabled
            and self.responsive
            and self.physically_bounded
        )

    @property
    def is_window(self) -> bool:
        return self.exists

    @property
    def is_visible(self) -> bool:
        return self.visible

    @property
    def is_iconic(self) -> bool:
        return self.minimized

    @property
    def is_cloaked(self) -> bool:
        return self.cloaked

    @property
    def is_bounded(self) -> bool:
        return self.physically_bounded

    @property
    def is_responsive(self) -> bool:
        return self.responsive

    @property
    def bounds(self) -> Optional[Rect]:
        b = self.details.get("bounds")
        if isinstance(b, Rect):
            return b
        if isinstance(b, dict):
            return Rect.from_dict(b)
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd),
            "exists": self.exists,
            "visible": self.visible,
            "minimized": self.minimized,
            "cloaked": self.cloaked,
            "foreground": self.foreground,
            "enabled": self.enabled,
            "responsive": self.responsive,
            "physically_bounded": self.physically_bounded,
            "is_interactable": self.is_interactable,
            "status": self.status.value,
            "details": self.details,
        }


@dataclass(frozen=True)
class CoveringWindowInfo:
    """Details of a top-level window obscuring the target window."""
    hwnd: int
    pid: int
    title: str
    class_name: str
    bounds: Rect
    intersection_rect: Rect
    overlap_area: int
    overlap_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd),
            "pid": self.pid,
            "title": self.title,
            "class_name": self.class_name,
            "bounds": self.bounds.to_dict(),
            "intersection_rect": self.intersection_rect.to_dict(),
            "overlap_area": self.overlap_area,
            "overlap_ratio": round(self.overlap_ratio, 4),
        }


@dataclass(frozen=True)
class OcclusionReport:
    """Z-order inspection and occlusion analysis report."""
    state: OcclusionState
    occlusion_ratio: float
    covering_windows: List[CoveringWindowInfo] = field(default_factory=list)
    z_order_rank: int = 0  # 0 indicates top of the desktop Z-order
    is_topmost: bool = False
    diagnostic_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "occlusion_ratio": round(self.occlusion_ratio, 4),
            "covering_windows": [w.to_dict() for w in self.covering_windows],
            "z_order_rank": self.z_order_rank,
            "is_topmost": self.is_topmost,
            "diagnostic_notes": self.diagnostic_notes,
        }


@dataclass(frozen=True)
class ModalDialogInfo:
    """Identity and metadata of a detected native modal surface."""
    hwnd: int
    pid: int
    owner_hwnd: Optional[int]
    title: str
    class_name: str
    bounds: Rect
    is_system_dialog: bool
    is_blocking: bool
    dialog_type: str  # "win32_dialog", "message_box", "file_picker", "owned_modal"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd),
            "pid": self.pid,
            "owner_hwnd": hex(self.owner_hwnd) if self.owner_hwnd else None,
            "title": self.title,
            "class_name": self.class_name,
            "bounds": self.bounds.to_dict(),
            "is_system_dialog": self.is_system_dialog,
            "is_blocking": self.is_blocking,
            "dialog_type": self.dialog_type,
        }


@dataclass(frozen=True)
class NativeModalReport:
    """Report on native modal dialogs impacting the supervised process/window."""
    state: ModalState
    dialogs: List[ModalDialogInfo] = field(default_factory=list)
    blocking_dialog: Optional[ModalDialogInfo] = None
    owner_disabled: bool = False
    detection_method: str = "win32_class_and_ownership"

    @property
    def modal_state(self) -> ModalState:
        return self.state

    @property
    def active_modals(self) -> List[ModalDialogInfo]:
        return self.dialogs

    @property
    def is_blocked_by_modal(self) -> bool:
        return self.owner_disabled or bool(self.blocking_dialog)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "dialogs": [d.to_dict() for d in self.dialogs],
            "blocking_dialog": self.blocking_dialog.to_dict() if self.blocking_dialog else None,
            "owner_disabled": self.owner_disabled,
            "detection_method": self.detection_method,
        }


@dataclass
class WindowForensicReport:
    """Forensic report capturing physical desktop truth for a window handle."""
    hwnd: int
    pid: int
    title: str
    class_name: str
    bounds: Rect                   # Canonical physical bounds via DWMWA_EXTENDED_FRAME_BOUNDS (AUTHORITATIVE)
    raw_window_rect: Rect          # Raw GetWindowRect (DIAGNOSTIC ONLY; includes drop-shadows)
    client_rect: Rect              # Client bounds via GetClientRect
    client_origin_screen: Tuple[int, int] # Screen origin of client (0,0) via ClientToScreen
    is_valid_window: bool
    is_visible: bool
    is_iconic: bool                # Minimized
    is_cloaked: bool               # DWM virtual desktop / hidden
    is_hung: bool                  # SendMessageTimeout(WM_NULL) check failed
    health_state: HealthState
    dpi_scaling: float             # Per-Monitor V2 scaling factor (e.g. 1.25)
    shadow_margins: Dict[str, int] # Drop shadow margins: left, top, right, bottom
    responsiveness: Optional[ResponsivenessReport] = None
    visibility: Optional[PhysicalVisibilityReport] = None
    occlusion: Optional[OcclusionReport] = None
    modals: Optional[NativeModalReport] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": hex(self.hwnd),
            "pid": self.pid,
            "title": self.title,
            "class_name": self.class_name,
            "bounds": self.bounds.to_dict(),
            "raw_window_rect": self.raw_window_rect.to_dict(),
            "client_rect": self.client_rect.to_dict(),
            "client_origin_screen": {"x": self.client_origin_screen[0], "y": self.client_origin_screen[1]},
            "is_valid_window": self.is_valid_window,
            "is_visible": self.is_visible,
            "is_iconic": self.is_iconic,
            "is_cloaked": self.is_cloaked,
            "is_hung": self.is_hung,
            "health_state": self.health_state.value,
            "dpi_scaling": self.dpi_scaling,
            "shadow_margins": self.shadow_margins,
            "responsiveness": self.responsiveness.to_dict() if self.responsiveness else None,
            "visibility": self.visibility.to_dict() if self.visibility else None,
            "occlusion": self.occlusion.to_dict() if self.occlusion else None,
            "modals": self.modals.to_dict() if self.modals else None,
        }


# -----------------------------------------------------------------------------
# 2. NativeOSSupervisor Implementation
# -----------------------------------------------------------------------------
class NativeOSSupervisor:
    """
    Authoritative Physical Desktop Truth Authority for Windows.
    Enforces 64-bit Win32 pointer correctness, DWM extended frame bounds authority,
    pre-flight SendMessageTimeout responsiveness gates, Z-order occlusion analysis,
    native modal dialog detection, and leak-free GDI screenshot capture.
    """

    # -------------------------------------------------------------------------
    # A. Window Existence & Process Identification
    # -------------------------------------------------------------------------
    @staticmethod
    def is_window_valid(hwnd: int) -> bool:
        """Verifies if an HWND is a currently valid operating system window."""
        if sys.platform != "win32" or w32.user32 is None:
            return True
        try:
            return bool(w32.user32.IsWindow(hwnd))
        except Exception:
            return False

    @staticmethod
    def get_window_pid(hwnd: int) -> int:
        """Retrieves the owning Process ID for a given window handle."""
        if sys.platform != "win32" or w32.user32 is None:
            return 0
        try:
            pid_var = wintypes.DWORD()
            w32.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_var))
            return int(pid_var.value)
        except Exception:
            return 0

    @staticmethod
    def get_window_owner(hwnd: int) -> Optional[int]:
        """Retrieves the owner window HWND via GetWindow(GW_OWNER)."""
        if sys.platform != "win32" or w32.user32 is None:
            return None
        try:
            owner = w32.user32.GetWindow(hwnd, w32.GW_OWNER)
            return int(owner) if owner else None
        except Exception:
            return None

    @staticmethod
    def get_window_root(hwnd: int) -> Optional[int]:
        """Retrieves root owner window via GetAncestor(GA_ROOTOWNER)."""
        if sys.platform != "win32" or w32.user32 is None:
            return None
        try:
            root = w32.user32.GetAncestor(hwnd, w32.GA_ROOTOWNER)
            return int(root) if root else None
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # B. Pre-Flight Responsiveness Gate (SendMessageTimeoutW)
    # -------------------------------------------------------------------------
    @classmethod
    def check_responsiveness(cls, hwnd: int, timeout_ms: int = 500) -> ResponsivenessReport:
        """
        Executes pre-flight SendMessageTimeoutW(WM_NULL, SMTO_ABORTIFHUNG, timeout_ms).
        CRITICAL 64-bit FIX: lpdwResult is a pointer to a 64-bit DWORD_PTR (ULONG_PTR),
        preventing buffer overflow/truncation on x64 Windows.
        """
        if sys.platform != "win32" or w32.user32 is None:
            return ResponsivenessReport(
                hwnd=hwnd,
                pid=0,
                health_state=HealthState.HEALTHY,
                elapsed_ms=0.1,
                is_timeout=False,
            )

        if not w32.user32.IsWindow(hwnd):
            return ResponsivenessReport(
                hwnd=hwnd,
                pid=0,
                health_state=HealthState.TERMINATED,
                elapsed_ms=0.0,
                is_timeout=False,
                last_error=6,  # ERROR_INVALID_HANDLE
            )

        pid = cls.get_window_pid(hwnd)
        result_ptr = w32.DWORD_PTR(0)
        t_start = time.perf_counter()

        res = w32.user32.SendMessageTimeoutW(
            hwnd,
            w32.WM_NULL,
            0,
            0,
            w32.SMTO_ABORTIFHUNG,
            timeout_ms,
            ctypes.byref(result_ptr),
        )
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        if res == 0:
            err = ctypes.GetLastError()
            logger.warning(
                f"HWND {hex(hwnd)} (PID {pid}) failed SendMessageTimeoutW (res=0, err={err}, elapsed={elapsed_ms:.1f}ms) -> HUNG"
            )
            return ResponsivenessReport(
                hwnd=hwnd,
                pid=pid,
                health_state=HealthState.HUNG,
                elapsed_ms=elapsed_ms,
                is_timeout=True,
                last_error=err,
            )

        return ResponsivenessReport(
            hwnd=hwnd,
            pid=pid,
            health_state=HealthState.HEALTHY,
            elapsed_ms=elapsed_ms,
            is_timeout=False,
            last_error=None,
        )

    @classmethod
    def ensure_responsive(cls, hwnd: int, timeout_ms: int = 500) -> ResponsivenessReport:
        """
        Non-blocking health gate. Raises structured TargetHungException or TargetExitedException
        if the window fails responsiveness inspection.
        """
        report = cls.check_responsiveness(hwnd, timeout_ms=timeout_ms)
        if report.health_state == HealthState.TERMINATED:
            raise TargetExitedException(report.pid or hwnd)
        if report.health_state == HealthState.HUNG:
            raise TargetHungException(
                f"Window HWND {hex(hwnd)} (PID {report.pid}) is UNRESPONSIVE (hung after {report.elapsed_ms:.1f}ms)",
                target_id=hex(hwnd),
            )
        return report

    # -------------------------------------------------------------------------
    # C. DWM Physical Boundary Authority
    # -------------------------------------------------------------------------
    @classmethod
    def get_canonical_window_bounds(cls, hwnd: int) -> Tuple[Rect, Rect, Dict[str, int]]:
        """
        Canonical Window Boundary Authority (SP-03):
        Classification:
            - DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS): AUTHORITATIVE physical display bounds.
            - GetWindowRect: DIAGNOSTIC ONLY (includes invisible drop-shadow margins).
            - Raw GetWindowRect for visual cropping: INVALID FOR PHYSICAL BOUNDS.
        Returns:
            canonical_bounds: Physical display pixels via DWM extended frame bounds.
            raw_rect: Raw GetWindowRect.
            shadow_margins: Delta between raw rect and canonical bounds (left, top, right, bottom).
        """
        if sys.platform != "win32" or w32.user32 is None or w32.dwmapi is None:
            default_rect = Rect(100, 100, 800, 600)
            return default_rect, default_rect, {"left": 0, "top": 0, "right": 0, "bottom": 0}

        # 1. Raw GetWindowRect (DIAGNOSTIC ONLY)
        raw_struct = w32.RECT()
        w32.user32.GetWindowRect(hwnd, ctypes.byref(raw_struct))
        raw_rect = Rect(
            x=raw_struct.left,
            y=raw_struct.top,
            width=max(0, raw_struct.right - raw_struct.left),
            height=max(0, raw_struct.bottom - raw_struct.top),
        )

        # 2. Canonical DWM Extended Frame Bounds (AUTHORITATIVE)
        dwm_struct = w32.RECT()
        res = w32.dwmapi.DwmGetWindowAttribute(
            hwnd,
            w32.DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(dwm_struct),
            ctypes.sizeof(w32.RECT),
        )

        if res == 0 and dwm_struct.right > dwm_struct.left and dwm_struct.bottom > dwm_struct.top:
            canonical_rect = Rect(
                x=dwm_struct.left,
                y=dwm_struct.top,
                width=dwm_struct.right - dwm_struct.left,
                height=dwm_struct.bottom - dwm_struct.top,
            )
        else:
            # Fallback to raw rect if DWM is unavailable or window is unrendered
            canonical_rect = raw_rect

        shadow_margins = {
            "left": canonical_rect.x - raw_rect.x,
            "top": canonical_rect.y - raw_rect.y,
            "right": (raw_rect.x + raw_rect.width) - (canonical_rect.x + canonical_rect.width),
            "bottom": (raw_rect.y + raw_rect.height) - (canonical_rect.y + canonical_rect.height),
        }

        return canonical_rect, raw_rect, shadow_margins

    @classmethod
    def get_window_bounds(cls, hwnd: int) -> Rect:
        """Returns canonical physical display bounds for HWND via DWM."""
        canonical, _, _ = cls.get_canonical_window_bounds(hwnd)
        return canonical

    @classmethod
    def get_window_rect(cls, hwnd: int) -> Rect:
        """Authoritative canonical physical rectangle via DWM (backward-compatible alias)."""
        return cls.get_window_bounds(hwnd)

    @classmethod
    def get_raw_window_rect(cls, hwnd: int) -> Rect:
        """Raw Win32 GetWindowRect including drop-shadow margins (diagnostic only)."""
        _, raw, _ = cls.get_canonical_window_bounds(hwnd)
        return raw

    # -------------------------------------------------------------------------
    # D. Physical Visibility Diagnostics
    # -------------------------------------------------------------------------
    @classmethod
    def inspect_physical_visibility(cls, hwnd: int) -> PhysicalVisibilityReport:
        """
        Determines full physical desktop visibility without equating IsWindowVisible == physically visible.
        Checks existence, Win32 visibility, minimization, DWM cloaking, foreground status,
        window enabled state, responsiveness, and non-empty physical bounds.
        """
        if sys.platform != "win32" or w32.user32 is None:
            return PhysicalVisibilityReport(
                hwnd=hwnd,
                exists=True,
                visible=True,
                minimized=False,
                cloaked=False,
                foreground=True,
                enabled=True,
                responsive=True,
                physically_bounded=True,
                status=VisibilityStatus.SUPPORTED,
            )

        if not w32.user32.IsWindow(hwnd):
            return PhysicalVisibilityReport(
                hwnd=hwnd,
                exists=False,
                visible=False,
                minimized=False,
                cloaked=False,
                foreground=False,
                enabled=False,
                responsive=False,
                physically_bounded=False,
                status=VisibilityStatus.SUPPORTED,
                details={"reason": "HWND is not a valid operating system window"},
            )

        exists = True
        visible = bool(w32.user32.IsWindowVisible(hwnd))
        minimized = bool(w32.user32.IsIconic(hwnd))
        enabled = bool(w32.user32.IsWindowEnabled(hwnd))
        fg_hwnd = w32.user32.GetForegroundWindow()
        foreground = (fg_hwnd == hwnd)

        # DWM Cloaking
        cloaked = False
        if w32.dwmapi is not None:
            cloaked_val = wintypes.DWORD(0)
            res = w32.dwmapi.DwmGetWindowAttribute(
                hwnd, w32.DWMWA_CLOAKED, ctypes.byref(cloaked_val), ctypes.sizeof(cloaked_val)
            )
            cloaked = (res == 0 and cloaked_val.value != 0)

        # Canonical Bounds
        canonical_bounds, _, _ = cls.get_canonical_window_bounds(hwnd)
        physically_bounded = (canonical_bounds.width > 0 and canonical_bounds.height > 0)

        # Responsiveness check
        resp = cls.check_responsiveness(hwnd, timeout_ms=300)
        responsive = (resp.health_state == HealthState.HEALTHY)

        return PhysicalVisibilityReport(
            hwnd=hwnd,
            exists=exists,
            visible=visible,
            minimized=minimized,
            cloaked=cloaked,
            foreground=foreground,
            enabled=enabled,
            responsive=responsive,
            physically_bounded=physically_bounded,
            status=VisibilityStatus.SUPPORTED,
            details={
                "bounds": canonical_bounds,
                "foreground_hwnd": hex(fg_hwnd) if fg_hwnd else None,
                "health_state": resp.health_state.value,
                "elapsed_ms": resp.elapsed_ms,
            },
        )

    # -------------------------------------------------------------------------
    # E. Z-Order and Physical Occlusion Inspection
    # -------------------------------------------------------------------------
    @classmethod
    def list_top_level_windows(cls, visible_only: bool = True) -> List[int]:
        """Enumerates top-level HWNDs in native desktop Z-order."""
        if sys.platform != "win32" or w32.user32 is None:
            return []
        hwnds: List[int] = []

        def enum_cb(h, _):
            h_int = int(h)
            if visible_only:
                if w32.user32.IsWindow(h_int) and w32.user32.IsWindowVisible(h_int):
                    hwnds.append(h_int)
            else:
                hwnds.append(h_int)
            return True

        cb = w32.WNDENUMPROC(enum_cb)
        w32.user32.EnumWindows(cb, 0)
        return hwnds

    @classmethod
    def inspect_occlusion(cls, hwnd: int) -> OcclusionReport:
        """
        Native window inspection path determining whether target is covered by another top-level window.
        Traverses top-level windows in native desktop Z-order.
        Calculates geometric overlap between covering window DWM bounds and target DWM bounds.
        Produces: NOT_OCCLUDED, PARTIALLY_OCCLUDED, LIKELY_OCCLUDED (>=95%), or UNKNOWN.
        """
        if sys.platform != "win32" or w32.user32 is None:
            return OcclusionReport(
                state=OcclusionState.NOT_OCCLUDED,
                occlusion_ratio=0.0,
                diagnostic_notes=["Non-Windows platform: occlusion analysis simulated"],
            )

        if not w32.user32.IsWindow(hwnd):
            return OcclusionReport(
                state=OcclusionState.UNKNOWN,
                occlusion_ratio=0.0,
                diagnostic_notes=["Target HWND is not a valid window"],
            )

        # Get target canonical bounds
        target_bounds, _, _ = cls.get_canonical_window_bounds(hwnd)
        target_area = target_bounds.width * target_bounds.height
        if target_area <= 0:
            return OcclusionReport(
                state=OcclusionState.UNKNOWN,
                occlusion_ratio=0.0,
                diagnostic_notes=["Target window has zero or negative physical dimensions"],
            )

        # Enumerate top-level windows in Z-order
        ordered_hwnds: List[int] = []

        def enum_z_order(h, _):
            ordered_hwnds.append(int(h))
            return True

        cb = w32.WNDENUMPROC(enum_z_order)
        w32.user32.EnumWindows(cb, 0)

        if hwnd not in ordered_hwnds:
            return OcclusionReport(
                state=OcclusionState.UNKNOWN,
                occlusion_ratio=0.0,
                diagnostic_notes=["Target window was not found in top-level Z-order enumeration"],
            )

        target_idx = ordered_hwnds.index(hwnd)
        target_pid = cls.get_window_pid(hwnd)
        covering_windows: List[CoveringWindowInfo] = []
        covered_area = 0

        # Examine all top-level windows placed BEFORE target in Z-order
        for h in ordered_hwnds[:target_idx]:
            if not w32.user32.IsWindow(h) or not w32.user32.IsWindowVisible(h) or w32.user32.IsIconic(h):
                continue

            # Exclude cloaked windows
            cloaked_val = wintypes.DWORD(0)
            res = w32.dwmapi.DwmGetWindowAttribute(
                h, w32.DWMWA_CLOAKED, ctypes.byref(cloaked_val), ctypes.sizeof(cloaked_val)
            )
            if res == 0 and cloaked_val.value != 0:
                continue

            # Exclude owned or child windows belonging to the target itself
            h_owner = cls.get_window_owner(h)
            h_root = cls.get_window_root(h)
            if h_owner == hwnd or h_root == hwnd:
                continue

            cov_bounds, _, _ = cls.get_canonical_window_bounds(h)
            if cov_bounds.width <= 0 or cov_bounds.height <= 0:
                continue

            # Calculate intersection
            inter_left = max(target_bounds.x, cov_bounds.x)
            inter_top = max(target_bounds.y, cov_bounds.y)
            inter_right = min(target_bounds.x + target_bounds.width, cov_bounds.x + cov_bounds.width)
            inter_bottom = min(target_bounds.y + target_bounds.height, cov_bounds.y + cov_bounds.height)

            if inter_right > inter_left and inter_bottom > inter_top:
                inter_w = inter_right - inter_left
                inter_h = inter_bottom - inter_top
                overlap_area = inter_w * inter_h
                overlap_ratio = overlap_area / float(target_area)
                covered_area += overlap_area

                # Title and class of covering window
                length = w32.user32.GetWindowTextLengthW(h)
                buf = ctypes.create_unicode_buffer(length + 1)
                w32.user32.GetWindowTextW(h, buf, length + 1)
                cov_title = buf.value

                cls_buf = ctypes.create_unicode_buffer(256)
                w32.user32.GetClassNameW(h, cls_buf, 256)
                cov_class = cls_buf.value

                covering_windows.append(
                    CoveringWindowInfo(
                        hwnd=h,
                        pid=cls.get_window_pid(h),
                        title=cov_title,
                        class_name=cov_class,
                        bounds=cov_bounds,
                        intersection_rect=Rect(inter_left, inter_top, inter_w, inter_h),
                        overlap_area=overlap_area,
                        overlap_ratio=overlap_ratio,
                    )
                )

        occlusion_ratio = min(1.0, covered_area / float(target_area))
        if occlusion_ratio >= 0.95:
            state = OcclusionState.LIKELY_OCCLUDED
        elif occlusion_ratio > 0.0:
            state = OcclusionState.PARTIALLY_OCCLUDED
        else:
            state = OcclusionState.NOT_OCCLUDED

        return OcclusionReport(
            state=state,
            occlusion_ratio=occlusion_ratio,
            covering_windows=covering_windows,
            z_order_rank=target_idx,
            is_topmost=(target_idx == 0),
            diagnostic_notes=[f"Covered area: {covered_area}/{target_area} px ({occlusion_ratio*100:.1f}%)"],
        )

    # -------------------------------------------------------------------------
    # F. Native Modal Dialog Detection
    # -------------------------------------------------------------------------
    @classmethod
    def detect_modals(cls, target_pid: int, main_hwnd: Optional[int] = None) -> NativeModalReport:
        """
        Scans desktop for native modal dialog surfaces:
        - Win32 Dialog Class: #32770 (Standard MessageBox, Open/Save file pickers, Folder pickers)
        - Owned windows where owner is the main window or in the process tree
        - Application-disabled states: Owner window disabled while child/dialog is visible
        Produces structured NativeModalReport with NO_MODAL, MODAL_DETECTED, or UNKNOWN.
        """
        if sys.platform != "win32" or w32.user32 is None:
            return NativeModalReport(state=ModalState.NO_MODAL)

        dialogs: List[ModalDialogInfo] = []
        owner_disabled = False

        if main_hwnd and w32.user32.IsWindow(main_hwnd):
            owner_disabled = not bool(w32.user32.IsWindowEnabled(main_hwnd))

        def enum_dialogs(h, _):
            if not w32.user32.IsWindow(h) or not w32.user32.IsWindowVisible(h) or w32.user32.IsIconic(h):
                return True

            pid_var = wintypes.DWORD()
            w32.user32.GetWindowThreadProcessId(h, ctypes.byref(pid_var))
            win_pid = pid_var.value

            # Check if owned by target PID or target main_hwnd
            owner_h = cls.get_window_owner(h)
            is_pid_match = (win_pid == target_pid)
            is_owner_match = (main_hwnd is not None and owner_h == main_hwnd)

            if is_pid_match or is_owner_match:
                cls_buf = ctypes.create_unicode_buffer(256)
                w32.user32.GetClassNameW(h, cls_buf, 256)
                class_name = cls_buf.value

                length = w32.user32.GetWindowTextLengthW(h)
                buf = ctypes.create_unicode_buffer(length + 1)
                w32.user32.GetWindowTextW(h, buf, length + 1)
                title = buf.value

                bounds, _, _ = cls.get_canonical_window_bounds(h)

                is_dialog_class = (class_name == "#32770")
                is_owned_popup = (owner_h is not None and owner_h != 0)

                if is_dialog_class or (is_owned_popup and owner_disabled):
                    dialog_type = "win32_dialog"
                    title_lower = title.lower()
                    if any(w in title_lower for w in ["open", "browse", "select file", "save as", "save"]):
                        dialog_type = "file_picker"
                    elif any(w in title_lower for w in ["folder", "directory"]):
                        dialog_type = "folder_picker"
                    elif any(w in title_lower for w in ["warning", "error", "information", "confirm"]):
                        dialog_type = "message_box"
                    elif is_owned_popup:
                        dialog_type = "owned_modal"

                    dialogs.append(
                        ModalDialogInfo(
                            hwnd=h,
                            pid=win_pid,
                            owner_hwnd=owner_h,
                            title=title,
                            class_name=class_name,
                            bounds=bounds,
                            is_system_dialog=is_dialog_class,
                            is_blocking=owner_disabled or is_dialog_class,
                            dialog_type=dialog_type,
                        )
                    )
            return True

        cb = w32.WNDENUMPROC(enum_dialogs)
        w32.user32.EnumWindows(cb, 0)

        blocking = next((d for d in dialogs if d.is_blocking), None)
        state = ModalState.MODAL_DETECTED if dialogs else ModalState.NO_MODAL

        return NativeModalReport(
            state=state,
            dialogs=dialogs,
            blocking_dialog=blocking,
            owner_disabled=owner_disabled,
        )

    # -------------------------------------------------------------------------
    # G. Leak-Free Native Screenshot Capture
    # -------------------------------------------------------------------------
    @classmethod
    def capture_window_screenshot(
        cls,
        hwnd: int,
        output_path: Optional[str] = None,
        use_dwm_bounds: bool = True,
    ) -> Tuple[bool, bytes, str, Dict[str, Any]]:
        """
        Captures the OS desktop window surface using Win32 GDI with guaranteed resource cleanup.
        Eliminates GDI DC leaks via strict try...finally blocks.
        Uses canonical DWM extended frame bounds to avoid capturing invisible drop shadows.
        Returns (success, png_bytes, sha256_hash, metadata).
        """
        if sys.platform != "win32" or w32.user32 is None or w32.gdi32 is None:
            return False, b"", "", {"error": "Native window capture is supported only on Windows"}

        # Pre-flight health check to ensure target is responsive
        health = cls.check_responsiveness(hwnd, timeout_ms=500)
        if health.health_state == HealthState.HUNG:
            logger.warning(f"Aborting screenshot for hung window HWND {hex(hwnd)}")
            return False, b"", "", {"error": f"Target HWND {hex(hwnd)} is unresponsive (hung)"}
        if health.health_state == HealthState.TERMINATED:
            return False, b"", "", {"error": f"Target HWND {hex(hwnd)} is terminated"}

        bounds, raw_rect, shadow_margins = cls.get_canonical_window_bounds(hwnd)
        width = bounds.width if use_dwm_bounds else raw_rect.width
        height = bounds.height if use_dwm_bounds else raw_rect.height

        if width <= 0 or height <= 0:
            return False, b"", "", {"error": f"Invalid window dimensions: {width}x{height}"}

        hdc_window = None
        hdc_mem = None
        hbm = None
        hbm_old = None

        try:
            hdc_window = w32.user32.GetWindowDC(hwnd)
            if not hdc_window:
                return False, b"", "", {"error": "GetWindowDC failed"}

            hdc_mem = w32.gdi32.CreateCompatibleDC(hdc_window)
            if not hdc_mem:
                return False, b"", "", {"error": "CreateCompatibleDC failed"}

            hbm = w32.gdi32.CreateCompatibleBitmap(hdc_window, width, height)
            if not hbm:
                return False, b"", "", {"error": "CreateCompatibleBitmap failed"}

            hbm_old = w32.gdi32.SelectObject(hdc_mem, hbm)

            # PW_RENDERFULLCONTENT = 2
            printed = w32.user32.PrintWindow(hwnd, hdc_mem, w32.PW_RENDERFULLCONTENT)
            if not printed:
                printed = w32.user32.PrintWindow(hwnd, hdc_mem, 0)
            if not printed:
                printed = w32.gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_window, 0, 0, w32.SRCCOPY)

            bmi = w32.BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(w32.BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height  # top-down DIB
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = w32.BI_RGB
            bmi.biSizeImage = width * height * 4

            raw_buffer = ctypes.create_string_buffer(bmi.biSizeImage)
            w32.gdi32.GetDIBits(
                hdc_mem,
                hbm,
                0,
                height,
                raw_buffer,
                ctypes.byref(bmi),
                w32.DIB_RGB_COLORS,
            )

            png_bytes = cls._raw_bgra_to_png(bytes(raw_buffer), width, height)
            sha256_hash = hashlib.sha256(png_bytes).hexdigest()

            if output_path:
                os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(png_bytes)

            meta = {
                "hwnd": hex(hwnd),
                "width": width,
                "height": height,
                "bounds": bounds.to_dict(),
                "sha256": sha256_hash,
                "output_path": output_path,
                "capture_time": time.time(),
            }
            return True, png_bytes, sha256_hash, meta

        except Exception as e:
            logger.error(f"Error capturing window screenshot for HWND {hex(hwnd)}: {e}")
            return False, b"", "", {"error": str(e)}

        finally:
            # Guaranteed GDI resource reclamation
            if hdc_mem and hbm_old:
                w32.gdi32.SelectObject(hdc_mem, hbm_old)
            if hbm:
                w32.gdi32.DeleteObject(hbm)
            if hdc_mem:
                w32.gdi32.DeleteDC(hdc_mem)
            if hdc_window:
                w32.user32.ReleaseDC(hwnd, hdc_window)

    @classmethod
    def capture_desktop_crop(
        cls,
        rect: Rect,
        output_path: Optional[str] = None,
    ) -> Tuple[bool, bytes, str, Dict[str, Any]]:
        """
        Captures an arbitrary physical desktop rectangle via GDI BitBlt with guaranteed cleanup.
        """
        if sys.platform != "win32" or w32.user32 is None or w32.gdi32 is None:
            return False, b"", "", {"error": "Desktop capture is supported only on Windows"}

        if rect.width <= 0 or rect.height <= 0:
            return False, b"", "", {"error": f"Invalid crop dimensions: {rect.width}x{rect.height}"}

        hdc_screen = None
        hdc_mem = None
        hbm = None
        hbm_old = None

        try:
            hdc_screen = w32.user32.GetDC(0)
            if not hdc_screen:
                return False, b"", "", {"error": "GetDC(0) failed"}

            hdc_mem = w32.gdi32.CreateCompatibleDC(hdc_screen)
            if not hdc_mem:
                return False, b"", "", {"error": "CreateCompatibleDC failed"}

            hbm = w32.gdi32.CreateCompatibleBitmap(hdc_screen, rect.width, rect.height)
            if not hbm:
                return False, b"", "", {"error": "CreateCompatibleBitmap failed"}

            hbm_old = w32.gdi32.SelectObject(hdc_mem, hbm)

            w32.gdi32.BitBlt(
                hdc_mem,
                0,
                0,
                rect.width,
                rect.height,
                hdc_screen,
                rect.x,
                rect.y,
                w32.SRCCOPY,
            )

            bmi = w32.BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(w32.BITMAPINFOHEADER)
            bmi.biWidth = rect.width
            bmi.biHeight = -rect.height  # top-down DIB
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = w32.BI_RGB
            bmi.biSizeImage = rect.width * rect.height * 4

            raw_buffer = ctypes.create_string_buffer(bmi.biSizeImage)
            w32.gdi32.GetDIBits(
                hdc_mem,
                hbm,
                0,
                rect.height,
                raw_buffer,
                ctypes.byref(bmi),
                w32.DIB_RGB_COLORS,
            )

            png_bytes = cls._raw_bgra_to_png(bytes(raw_buffer), rect.width, rect.height)
            sha256_hash = hashlib.sha256(png_bytes).hexdigest()

            if output_path:
                os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(png_bytes)

            meta = {
                "rect": rect.to_dict(),
                "sha256": sha256_hash,
                "output_path": output_path,
                "capture_time": time.time(),
            }
            return True, png_bytes, sha256_hash, meta

        except Exception as e:
            logger.error(f"Error capturing desktop crop {rect}: {e}")
            return False, b"", "", {"error": str(e)}

        finally:
            if hdc_mem and hbm_old:
                w32.gdi32.SelectObject(hdc_mem, hbm_old)
            if hbm:
                w32.gdi32.DeleteObject(hbm)
            if hdc_mem:
                w32.gdi32.DeleteDC(hdc_mem)
            if hdc_screen:
                w32.user32.ReleaseDC(0, hdc_screen)

    @staticmethod
    def _raw_bgra_to_png(bgra_data: bytes, width: int, height: int) -> bytes:
        """Pure Python uncompressed/deflated PNG encoder from 32-bit BGRA buffer."""
        scanline_len = width * 4
        raw_rows = []
        for y in range(height):
            row_start = y * scanline_len
            row = bytearray(scanline_len + 1)
            row[0] = 0  # Filter type None
            for x in range(width):
                b = bgra_data[row_start + x * 4]
                g = bgra_data[row_start + x * 4 + 1]
                r = bgra_data[row_start + x * 4 + 2]
                a = bgra_data[row_start + x * 4 + 3]
                row[1 + x * 4] = r
                row[1 + x * 4 + 1] = g
                row[1 + x * 4 + 2] = b
                row[1 + x * 4 + 3] = a
            raw_rows.append(bytes(row))

        raw_data = b"".join(raw_rows)
        compressed = zlib.compress(raw_data, level=6)

        def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
            length = struct.pack(">I", len(data))
            crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
            return length + chunk_type + data + crc

        png_header = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        return (
            png_header
            + make_chunk(b"IHDR", ihdr_data)
            + make_chunk(b"IDAT", compressed)
            + make_chunk(b"IEND", b"")
        )

    # -------------------------------------------------------------------------
    # H. Comprehensive Window Inspection
    # -------------------------------------------------------------------------
    @classmethod
    def inspect_window(
        cls,
        hwnd: int,
        check_health: bool = True,
        check_occlusion: bool = True,
        check_modals: bool = True,
    ) -> WindowForensicReport:
        """
        Performs full physical inspection of target window.
        Integrates DWM bounds, responsiveness check, physical visibility,
        Z-order occlusion, and native modal dialogs.
        """
        if sys.platform != "win32" or w32.user32 is None:
            default_rect = Rect(100, 100, 800, 600)
            return WindowForensicReport(
                hwnd=hwnd,
                pid=0,
                title="Mock Window",
                class_name="MockClass",
                bounds=default_rect,
                raw_window_rect=default_rect,
                client_rect=Rect(0, 0, 800, 600),
                client_origin_screen=(100, 100),
                is_valid_window=True,
                is_visible=True,
                is_iconic=False,
                is_cloaked=False,
                is_hung=False,
                health_state=HealthState.HEALTHY,
                dpi_scaling=1.0,
                shadow_margins={"left": 0, "top": 0, "right": 0, "bottom": 0},
            )

        if not w32.user32.IsWindow(hwnd):
            raise InvalidTargetException(f"Invalid window handle HWND: {hex(hwnd)} (or {hwnd})")

        pid = cls.get_window_pid(hwnd)
        vis_report = cls.inspect_physical_visibility(hwnd)

        # Title & Class
        length = w32.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        w32.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        cls_buf = ctypes.create_unicode_buffer(256)
        w32.user32.GetClassNameW(hwnd, cls_buf, 256)
        class_name = cls_buf.value

        # Bounds & Margins
        bounds, raw_rect, shadow_margins = cls.get_canonical_window_bounds(hwnd)

        # Client rect
        client_struct = w32.RECT()
        w32.user32.GetClientRect(hwnd, ctypes.byref(client_struct))
        client_rect = Rect(
            x=client_struct.left,
            y=client_struct.top,
            width=max(0, client_struct.right - client_struct.left),
            height=max(0, client_struct.bottom - client_struct.top),
        )

        # Client screen origin
        origin_pt = w32.POINT(0, 0)
        w32.user32.ClientToScreen(hwnd, ctypes.byref(origin_pt))
        client_origin = (origin_pt.x, origin_pt.y)

        # DPI Scaling
        dpi = 96
        if hasattr(w32.user32, "GetDpiForWindow"):
            try:
                d = w32.user32.GetDpiForWindow(hwnd)
                if d > 0:
                    dpi = d
            except Exception:
                dpi = 96
        dpi_scaling = round(dpi / 96.0, 3)

        # Responsiveness check
        resp_report = None
        health = HealthState.HEALTHY
        is_hung = False
        if check_health:
            resp_report = cls.check_responsiveness(hwnd, timeout_ms=500)
            health = resp_report.health_state
            is_hung = (health == HealthState.HUNG)

        # Occlusion check
        occlusion_report = None
        if check_occlusion and vis_report.visible and not vis_report.minimized:
            occlusion_report = cls.inspect_occlusion(hwnd)

        # Modal dialog check
        modal_report = None
        if check_modals and pid > 0:
            modal_report = cls.detect_modals(target_pid=pid, main_hwnd=hwnd)

        return WindowForensicReport(
            hwnd=hwnd,
            pid=pid,
            title=title,
            class_name=class_name,
            bounds=bounds,
            raw_window_rect=raw_rect,
            client_rect=client_rect,
            client_origin_screen=client_origin,
            is_valid_window=True,
            is_visible=vis_report.visible,
            is_iconic=vis_report.minimized,
            is_cloaked=vis_report.cloaked,
            is_hung=is_hung,
            health_state=health,
            dpi_scaling=dpi_scaling,
            shadow_margins=shadow_margins,
            responsiveness=resp_report,
            visibility=vis_report,
            occlusion=occlusion_report,
            modals=modal_report,
        )

    # -------------------------------------------------------------------------
    # I. Focus & Foreground Management
    # -------------------------------------------------------------------------
    @classmethod
    def set_foreground(cls, hwnd: int) -> bool:
        """Brings the window to top and restores if minimized without focus drop."""
        if sys.platform != "win32" or w32.user32 is None:
            return True

        if not w32.user32.IsWindow(hwnd):
            return False

        if w32.user32.IsIconic(hwnd):
            w32.user32.ShowWindow(hwnd, w32.SW_RESTORE)
            time.sleep(0.05)

        w32.user32.BringWindowToTop(hwnd)
        w32.user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        return True

    # -------------------------------------------------------------------------
    # J. Coordinate Transform Context Integration
    # -------------------------------------------------------------------------
    @classmethod
    def get_coordinate_context(
        cls,
        hwnd: int,
        webview_offset_in_native: Tuple[int, int] = (0, 0),
    ) -> CoordinateTransformContext:
        """
        Creates an authoritative CoordinateTransformContext for a given window HWND.
        Gathers DPI scale, client origin on screen, and virtual screen boundaries.
        """
        report = cls.inspect_window(hwnd, check_health=False, check_occlusion=False, check_modals=False)
        v_screen = CoordinateTransformer.get_system_virtual_screen()
        return CoordinateTransformContext(
            dpi_scale=report.dpi_scaling,
            client_origin_screen=report.client_origin_screen,
            webview_client_offset=webview_offset_in_native,
            virtual_screen=v_screen,
        )

    # -------------------------------------------------------------------------
    # Legacy Compatibility Alias
    # -------------------------------------------------------------------------
    @classmethod
    def find_modal_dialogs(cls, target_pid: int) -> List[Dict[str, Any]]:
        """Legacy compatibility wrapper around detect_modals."""
        report = cls.detect_modals(target_pid=target_pid)
        return [
            {
                "hwnd": d.hwnd,
                "pid": d.pid,
                "title": d.title,
                "class_name": d.class_name,
                "bounds": d.bounds.to_dict(),
            }
            for d in report.dialogs
        ]
