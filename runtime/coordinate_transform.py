"""
Authoritative Coordinate Transformation Subsystem for Desktop WebView Reviewer.
Single authority for all coordinate translations across webview CSS, native client,
physical screen, and normalized SendInput coordinates.
Supports Per-Monitor V2 scaling (100%, 125%, 150%, 175%, 200%), negative multi-monitor origins,
and deterministic multi-display topology simulation. Grounded in SP-03 empirical findings.
"""

from __future__ import annotations
import math
import sys
from dataclasses import dataclass, field
from typing import Dict, Any, Tuple, Optional, List
from runtime.references import Rect
from runtime.errors import InvalidCoordinateSpaceException

# Win32 Constants for Virtual Screen Metrics
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


@dataclass(frozen=True)
class VirtualScreenBounds:
    """Virtual desktop bounding metrics covering all active monitors."""
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains_point(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def to_dict(self) -> Dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class MonitorDescriptor:
    """Descriptor for an individual physical or simulated display monitor."""
    monitor_id: str
    bounds: Rect
    is_primary: bool = False
    dpi_scale: float = 1.0

    def contains_point(self, x: int, y: int) -> bool:
        return (
            self.bounds.x <= x < self.bounds.x + self.bounds.width
            and self.bounds.y <= y < self.bounds.y + self.bounds.height
        )


    def to_dict(self) -> Dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "bounds": self.bounds.to_dict(),
            "is_primary": self.is_primary,
            "dpi_scale": self.dpi_scale,
        }


MonitorInfo = MonitorDescriptor


@dataclass(frozen=True)
class MultiMonitorTopology:
    """Topology describing multi-monitor arrangement and bounding virtual screen."""
    monitors: List[MonitorDescriptor]
    virtual_screen: VirtualScreenBounds

    def get_monitor_for_point(self, x: int, y: int) -> Optional[MonitorDescriptor]:
        """Resolves which display monitor owns the given physical screen point."""
        for m in self.monitors:
            if m.contains_point(x, y):
                return m
        return None

    def get_primary_monitor(self) -> Optional[MonitorDescriptor]:
        """Returns the designated primary monitor."""
        for m in self.monitors:
            if m.is_primary:
                return m
        return self.monitors[0] if self.monitors else None

    @property
    def primary(self) -> Optional[MonitorDescriptor]:
        return self.get_primary_monitor()

    @property
    def virtual_screen_bounds(self) -> VirtualScreenBounds:
        return self.virtual_screen

    def __len__(self) -> int:
        return len(self.monitors)

    def __iter__(self):
        return iter(self.monitors)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "monitor_count": len(self.monitors),
            "monitors": [m.to_dict() for m in self.monitors],
            "virtual_screen": self.virtual_screen.to_dict(),
        }


@dataclass(frozen=True)
class CoordinateTransformContext:
    """Context holding DPR, window origin, and webview offset for a transformation."""
    dpi_scale: float = 1.0                # Per-Monitor V2 scaling (e.g. 1.25 for 125%)
    client_origin_screen: Tuple[int, int] = (0, 0) # Client (0,0) mapped to physical screen (x, y)
    webview_client_offset: Tuple[int, int] = (0, 0) # Webview element offset inside native client area
    virtual_screen: Optional[VirtualScreenBounds] = None


class CoordinateTransformer:
    """
    Authoritative deterministic coordinate transformation engine.
    Ensures consistent mapping between webview CSS pixels, native client pixels,
    physical display pixels, and SendInput normalized 0..65535 units across
    single and multi-monitor configurations with negative coordinates.
    """

    @staticmethod
    def get_system_virtual_screen() -> VirtualScreenBounds:
        """Queries Win32 system metrics for the bounding virtual desktop."""
        if sys.platform == "win32":
            try:
                import runtime.win32 as w32
                if w32.user32 is not None:
                    x = w32.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
                    y = w32.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
                    w = w32.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
                    h = w32.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
                    if w > 0 and h > 0:
                        return VirtualScreenBounds(left=x, top=y, width=w, height=h)
            except Exception:
                pass
        # Fallback to standard 1080p primary display
        return VirtualScreenBounds(left=0, top=0, width=1920, height=1080)

    @classmethod
    def get_system_multimonitor_topology(cls) -> MultiMonitorTopology:
        """
        Discovers all active physical display monitors via Win32 EnumDisplayMonitors/GetMonitorInfoW,
        deriving bounding rectangles, primary status, and Per-Monitor V2 DPI scaling.
        """
        virtual_screen = cls.get_system_virtual_screen()
        monitors: List[MonitorDescriptor] = []

        if sys.platform == "win32":
            try:
                import ctypes
                import runtime.win32 as w32
                if w32.user32 is not None and hasattr(w32.user32, "EnumDisplayMonitors"):
                    def _monitor_enum_proc(h_monitor, hdc, lprc, lparam):
                        try:
                            info = w32.MONITORINFOEXW()
                            info.cbSize = ctypes.sizeof(w32.MONITORINFOEXW)
                            if w32.user32.GetMonitorInfoW(h_monitor, ctypes.byref(info)):
                                r = info.rcMonitor
                                bounds = Rect(
                                    x=r.left,
                                    y=r.top,
                                    width=max(0, r.right - r.left),
                                    height=max(0, r.bottom - r.top),
                                )
                                is_primary = bool(info.dwFlags & 1)  # MONITORINFOF_PRIMARY = 1
                                device_name = str(info.szDevice)
                                monitor_id = device_name or f"MONITOR_{len(monitors) + 1}"

                                dpi_scale = 1.0
                                try:
                                    shcore = getattr(ctypes.windll, "shcore", None)
                                    if shcore and hasattr(shcore, "GetDpiForMonitor"):
                                        dpi_x = ctypes.c_uint()
                                        dpi_y = ctypes.c_uint()
                                        # MDT_EFFECTIVE_DPI = 0
                                        if shcore.GetDpiForMonitor(h_monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
                                            dpi_scale = round(dpi_x.value / 96.0, 2)
                                except Exception:
                                    pass

                                monitors.append(
                                    MonitorDescriptor(
                                        monitor_id=monitor_id,
                                        bounds=bounds,
                                        is_primary=is_primary,
                                        dpi_scale=dpi_scale,
                                    )
                                )
                        except Exception:
                            pass
                        return True

                    cb = w32.MONITORENUMPROC(_monitor_enum_proc)
                    w32.user32.EnumDisplayMonitors(None, None, cb, 0)
            except Exception:
                pass

        if not monitors:
            monitors.append(
                MonitorDescriptor(
                    monitor_id="PRIMARY_DISPLAY",
                    bounds=Rect(x=virtual_screen.left, y=virtual_screen.top, width=virtual_screen.width, height=virtual_screen.height),
                    is_primary=True,
                    dpi_scale=1.0,
                )
            )

        return MultiMonitorTopology(monitors=monitors, virtual_screen=virtual_screen)

    # -------------------------------------------------------------------------
    # 1. Web CSS -> Webview Client Coordinates
    # -------------------------------------------------------------------------
    @staticmethod
    def css_to_webview_client(css_x: float, css_y: float, dpr: float = 1.0) -> Tuple[int, int]:
        """
        Maps Web CSS logical pixels to Webview Client physical device pixels.
        css * dpr -> integer device pixels.
        """
        if dpr <= 0:
            raise InvalidCoordinateSpaceException(f"Invalid DPR scale: {dpr}")
        phys_x = round(css_x * dpr)
        phys_y = round(css_y * dpr)
        return (phys_x, phys_y)

    @staticmethod
    def webview_client_to_css(client_x: int, client_y: int, dpr: float = 1.0) -> Tuple[float, float]:
        """
        Maps Webview Client physical pixels back to Web CSS logical pixels.
        client / dpr -> floating point CSS pixels.
        """
        if dpr <= 0:
            raise InvalidCoordinateSpaceException(f"Invalid DPR scale: {dpr}")
        return (round(client_x / dpr, 4), round(client_y / dpr, 4))

    # -------------------------------------------------------------------------
    # 2. Webview Client -> Native Window Client Area
    # -------------------------------------------------------------------------
    @staticmethod
    def webview_client_to_native_client(
        webview_x: int,
        webview_y: int,
        webview_offset_in_native: Tuple[int, int] = (0, 0),
    ) -> Tuple[int, int]:
        """
        Maps Webview client pixels to Native window client coordinates
        by adding the webview host container's offset.
        """
        off_x, off_y = webview_offset_in_native
        return (webview_x + off_x, webview_y + off_y)

    @staticmethod
    def native_client_to_webview_client(
        native_x: int,
        native_y: int,
        webview_offset_in_native: Tuple[int, int] = (0, 0),
    ) -> Tuple[int, int]:
        """Inverse mapping from native client to webview client."""
        off_x, off_y = webview_offset_in_native
        return (native_x - off_x, native_y - off_y)

    # -------------------------------------------------------------------------
    # 3. Native Client -> Physical Screen Coordinates
    # -------------------------------------------------------------------------
    @staticmethod
    def native_client_to_screen(
        native_x: int,
        native_y: int,
        client_origin_screen: Tuple[int, int],
    ) -> Tuple[int, int]:
        """
        Maps Native window client coordinates to physical screen coordinates
        using the window's ClientToScreen origin.
        """
        orig_x, orig_y = client_origin_screen
        return (native_x + orig_x, native_y + orig_y)

    @staticmethod
    def screen_to_native_client(
        screen_x: int,
        screen_y: int,
        client_origin_screen: Tuple[int, int],
    ) -> Tuple[int, int]:
        """Inverse mapping from physical screen coordinates to native client coordinates."""
        orig_x, orig_y = client_origin_screen
        return (screen_x - orig_x, screen_y - orig_y)

    # -------------------------------------------------------------------------
    # 4. Full Chain: Web CSS -> Physical Screen Coordinates
    # -------------------------------------------------------------------------
    @classmethod
    def css_to_screen(
        cls,
        css_x: float,
        css_y: float,
        context: CoordinateTransformContext,
    ) -> Tuple[int, int]:
        """
        Transforms Web CSS logical coordinates directly to Physical Screen coordinates.
        Web CSS -> Webview Client -> Native Client -> Physical Screen.
        """
        wv_x, wv_y = cls.css_to_webview_client(css_x, css_y, context.dpi_scale)
        nat_x, nat_y = cls.webview_client_to_native_client(wv_x, wv_y, context.webview_client_offset)
        screen_x, screen_y = cls.native_client_to_screen(nat_x, nat_y, context.client_origin_screen)
        return (screen_x, screen_y)

    @classmethod
    def screen_to_css(
        cls,
        screen_x: int,
        screen_y: int,
        context: CoordinateTransformContext,
    ) -> Tuple[float, float]:
        """
        Inverse transformation from Physical Screen coordinates back to Web CSS logical coordinates.
        Physical Screen -> Native Client -> Webview Client -> Web CSS.
        """
        nat_x, nat_y = cls.screen_to_native_client(screen_x, screen_y, context.client_origin_screen)
        wv_x, wv_y = cls.native_client_to_webview_client(nat_x, nat_y, context.webview_client_offset)
        css_x, css_y = cls.webview_client_to_css(wv_x, wv_y, context.dpi_scale)
        return (css_x, css_y)

    # -------------------------------------------------------------------------
    # 5. Physical Screen Coordinates -> SendInput Normalized (0..65535)
    # -------------------------------------------------------------------------
    @staticmethod
    def screen_to_sendinput_normalized(
        screen_x: int,
        screen_y: int,
        virtual_screen: Optional[VirtualScreenBounds] = None,
    ) -> Tuple[int, int]:
        """
        Normalizes physical screen pixel coordinates into Win32 MOUSEEVENTF_ABSOLUTE
        normalized space (0..65535) across the virtual desktop bounding box.
        Handles negative screen origins across multi-monitor setups deterministically.
        Formula:
            norm_x = round((screen_x - v_left) * 65535 / (v_width - 1))
            norm_y = round((screen_y - v_top) * 65535 / (v_height - 1))
        """
        v = virtual_screen or CoordinateTransformer.get_system_virtual_screen()
        denom_x = max(v.width - 1, 1)
        denom_y = max(v.height - 1, 1)

        norm_x = round((screen_x - v.left) * 65535 / denom_x)
        norm_y = round((screen_y - v.top) * 65535 / denom_y)

        # Clamp to 0..65535 range
        norm_x = max(0, min(65535, norm_x))
        norm_y = max(0, min(65535, norm_y))
        return (norm_x, norm_y)

    @staticmethod
    def sendinput_normalized_to_screen(
        norm_x: int,
        norm_y: int,
        virtual_screen: Optional[VirtualScreenBounds] = None,
    ) -> Tuple[int, int]:
        """
        Reconstructs physical screen pixel coordinates from SendInput normalized units (0..65535).
        Formula:
            screen_x = round(norm_x * (v_width - 1) / 65535) + v_left
            screen_y = round(norm_y * (v_height - 1) / 65535) + v_top
        """
        v = virtual_screen or CoordinateTransformer.get_system_virtual_screen()
        screen_x = round(norm_x * (v.width - 1) / 65535) + v.left
        screen_y = round(norm_y * (v.height - 1) / 65535) + v.top
        return (screen_x, screen_y)

    # -------------------------------------------------------------------------
    # 6. Affordance Center Calculation & Verification
    # -------------------------------------------------------------------------
    @staticmethod
    def calculate_affordance_center(bounds: Rect) -> Tuple[int, int]:
        """
        Calculates the center targeting point for a bounding box.
        Always targeting affordance centers provides a buffer against sub-pixel rounding errors.
        """
        return bounds.center

    @classmethod
    def verify_round_trip(
        cls,
        css_x: float,
        css_y: float,
        context: CoordinateTransformContext,
    ) -> Dict[str, Any]:
        """
        Performs full round-trip verification:
        CSS -> Screen -> SendInput Normalized -> Screen -> CSS
        Validates that logical rounding error is <= 0.5px and physical delta is <= 1.0px.
        """
        v_screen = context.virtual_screen or cls.get_system_virtual_screen()
        ctx = CoordinateTransformContext(
            dpi_scale=context.dpi_scale,
            client_origin_screen=context.client_origin_screen,
            webview_client_offset=context.webview_client_offset,
            virtual_screen=v_screen,
        )

        screen_x, screen_y = cls.css_to_screen(css_x, css_y, ctx)
        norm_x, norm_y = cls.screen_to_sendinput_normalized(screen_x, screen_y, v_screen)
        unnorm_x, unnorm_y = cls.sendinput_normalized_to_screen(norm_x, norm_y, v_screen)
        rev_css_x, rev_css_y = cls.screen_to_css(unnorm_x, unnorm_y, ctx)

        sendinput_delta = math.sqrt((screen_x - unnorm_x) ** 2 + (screen_y - unnorm_y) ** 2)
        logical_delta = max(abs(css_x - rev_css_x), abs(css_y - rev_css_y))

        return {
            "initial_css": (css_x, css_y),
            "screen_physical": (screen_x, screen_y),
            "sendinput_normalized": (norm_x, norm_y),
            "reconstructed_screen": (unnorm_x, unnorm_y),
            "reconstructed_css": (rev_css_x, rev_css_y),
            "sendinput_physical_delta_px": round(sendinput_delta, 4),
            "logical_css_error_px": round(logical_delta, 4),
            "is_safe": (logical_delta <= 0.5 and sendinput_delta <= 1.0),
        }

    # -------------------------------------------------------------------------
    # 7. Multi-Monitor Simulation Helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def create_simulated_dual_monitor_topology(
        primary_res: Tuple[int, int] = (1920, 1080),
        primary_dpi: float = 1.25,
        secondary_res: Tuple[int, int] = (1920, 1080),
        secondary_dpi: float = 1.0,
        secondary_position: str = "left",  # "left", "right", "top", "bottom"
    ) -> MultiMonitorTopology:
        """
        Creates a deterministic multi-monitor topology for automated testing.
        Clearly marked as simulation for reproducible CI/CD verification.
        """
        p_w, p_h = primary_res
        s_w, s_h = secondary_res

        primary_bounds = Rect(0, 0, p_w, p_h)

        if secondary_position == "left":
            secondary_bounds = Rect(-s_w, 0, s_w, s_h)
            v_left = -s_w
            v_top = 0
            v_w = p_w + s_w
            v_h = max(p_h, s_h)
        elif secondary_position == "right":
            secondary_bounds = Rect(p_w, 0, s_w, s_h)
            v_left = 0
            v_top = 0
            v_w = p_w + s_w
            v_h = max(p_h, s_h)
        elif secondary_position == "top":
            secondary_bounds = Rect(0, -s_h, s_w, s_h)
            v_left = 0
            v_top = -s_h
            v_w = max(p_w, s_w)
            v_h = p_h + s_h
        else:  # bottom
            secondary_bounds = Rect(0, p_h, s_w, s_h)
            v_left = 0
            v_top = 0
            v_w = max(p_w, s_w)
            v_h = p_h + s_h

        monitors = [
            MonitorDescriptor(
                monitor_id="DISPLAY_PRIMARY",
                bounds=primary_bounds,
                is_primary=True,
                dpi_scale=primary_dpi,
            ),
            MonitorDescriptor(
                monitor_id=f"DISPLAY_SECONDARY_{secondary_position.upper()}",
                bounds=secondary_bounds,
                is_primary=False,
                dpi_scale=secondary_dpi,
            ),
        ]
        virtual_screen = VirtualScreenBounds(left=v_left, top=v_top, width=v_w, height=v_h)
        return MultiMonitorTopology(monitors=monitors, virtual_screen=virtual_screen)
