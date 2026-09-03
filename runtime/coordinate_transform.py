"""
Authoritative Coordinate Transformation Subsystem for Desktop WebView Reviewer.
Single authority for all coordinate translations across webview CSS, native client,
physical screen, and normalized SendInput coordinates. Grounded in SP-03 empirical findings.
"""

from __future__ import annotations
import math
import sys
from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional
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

    def to_dict(self) -> Dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


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
    physical display pixels, and SendInput normalized 0..65535 units.
    """

    @staticmethod
    def get_system_virtual_screen() -> VirtualScreenBounds:
        """Queries Win32 system metrics for the bounding virtual desktop."""
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
                y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
                w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
                h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
                if w > 0 and h > 0:
                    return VirtualScreenBounds(left=x, top=y, width=w, height=h)
            except Exception:
                pass
        # Fallback to standard 1080p primary display
        return VirtualScreenBounds(left=0, top=0, width=1920, height=1080)

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
        Validates that logical rounding error is < 0.5px and physical delta is <= 1.0px.
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

