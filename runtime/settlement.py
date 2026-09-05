"""
Generic Bounded Settlement Subsystem for Desktop WebView Reviewer (Architecture H).
Detects layout stabilization, CSS transitions, DOM re-renders, navigation commits,
and modal appearances using bounded polling without arbitrary long sleeps.
"""

from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Optional, Any, Awaitable

from runtime.native_supervisor import NativeSupervisor
from runtime.webview_core import WebviewAutomationCore
from runtime.references import ElementRef, Rect

logger = logging.getLogger("desktop_webview.settlement")


class SettlementType(str, Enum):
    STABLE = "STABLE"
    NAVIGATED = "NAVIGATED"
    MODAL_APPEARED = "MODAL_APPEARED"
    TARGET_DISAPPEARED = "TARGET_DISAPPEARED"
    DOM_MUTATED = "DOM_MUTATED"
    FOCUS_ACQUIRED = "FOCUS_ACQUIRED"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class SettlementResult:
    """Forensic report of action settlement."""
    settled: bool
    settlement_type: SettlementType
    elapsed_ms: float
    iterations: int
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def settle_duration_ms(self) -> float:
        return self.elapsed_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "settled": self.settled,
            "settlement_type": self.settlement_type.value,
            "elapsed_ms": self.elapsed_ms,
            "iterations": self.iterations,
            "details": self.details,
        }


class SettlementEngine:
    """
    Evaluates bounded state stabilization post-action dispatch.
    Avoids arbitrary static sleep delays by polling target stability indicators.
    """

    def __init__(
        self,
        native_supervisor: NativeSupervisor,
        webview_core: Optional[WebviewAutomationCore] = None,
        default_timeout_ms: int = 1500,
        poll_interval_ms: int = 40,
    ):
        self.native_supervisor = native_supervisor
        self.webview_core = webview_core
        self.default_timeout_ms = default_timeout_ms
        self.poll_interval_ms = poll_interval_ms

    async def settle(
        self,
        target_pid: Optional[int] = None,
        target_hwnd: Optional[int] = None,
        ref: Optional[ElementRef] = None,
        initial_url: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        check_modal: bool = True,
        check_navigation: bool = True,
    ) -> SettlementResult:
        """
        Executes bounded settlement after an action.
        Detects modals, navigations, motion settling, or timeout.
        """
        start = time.time()
        timeout = (timeout_ms or self.default_timeout_ms) / 1000.0
        interval = self.poll_interval_ms / 1000.0
        iterations = 0

        # Check immediate modal before anything
        if check_modal and target_pid:
            modals = self.native_supervisor.scan_modal_dialogs(target_pid)
            if modals:
                elapsed = (time.time() - start) * 1000.0
                return SettlementResult(
                    settled=True,
                    settlement_type=SettlementType.MODAL_APPEARED,
                    elapsed_ms=elapsed,
                    iterations=1,
                    details={"modal_dialogs": [m.to_dict() for m in modals]},
                )

        last_rect: Optional[Dict[str, float]] = None
        consecutive_stable = 0

        while (time.time() - start) < timeout:
            iterations += 1

            # 1. Detect native modal appearance
            if check_modal and target_pid:
                modals = self.native_supervisor.scan_modal_dialogs(target_pid)
                if modals:
                    elapsed = (time.time() - start) * 1000.0
                    return SettlementResult(
                        settled=True,
                        settlement_type=SettlementType.MODAL_APPEARED,
                        elapsed_ms=elapsed,
                        iterations=iterations,
                        details={"modal_dialogs": [m.to_dict() for m in modals]},
                    )

            # 2. Detect page navigation
            if check_navigation and self.webview_core and initial_url:
                try:
                    curr_url = self.webview_core.frame_manager.root_frame.url if self.webview_core.frame_manager.root_frame else ""
                    if curr_url and curr_url != initial_url:
                        elapsed = (time.time() - start) * 1000.0
                        return SettlementResult(
                            settled=True,
                            settlement_type=SettlementType.NAVIGATED,
                            elapsed_ms=elapsed,
                            iterations=iterations,
                            details={"initial_url": initial_url, "navigated_url": curr_url},
                        )
                except Exception:
                    pass

            # 3. Check element motion stability if ref is provided
            if ref and self.webview_core and self.webview_core.is_connected:
                curr_rect = await self._query_element_rect(ref)
                if curr_rect is None:
                    # Target disappeared from DOM!
                    elapsed = (time.time() - start) * 1000.0
                    return SettlementResult(
                        settled=True,
                        settlement_type=SettlementType.TARGET_DISAPPEARED,
                        elapsed_ms=elapsed,
                        iterations=iterations,
                        details={"ref_id": ref.ref_id},
                    )

                if last_rect is not None:
                    dx = abs(curr_rect.get("x", 0) - last_rect.get("x", 0))
                    dy = abs(curr_rect.get("y", 0) - last_rect.get("y", 0))
                    if dx <= 0.5 and dy <= 0.5:
                        consecutive_stable += 1
                        if consecutive_stable >= 2:
                            # Settled
                            elapsed = (time.time() - start) * 1000.0
                            return SettlementResult(
                                settled=True,
                                settlement_type=SettlementType.STABLE,
                                elapsed_ms=elapsed,
                                iterations=iterations,
                                details={"rect": curr_rect, "consecutive_stable": consecutive_stable},
                            )
                    else:
                        consecutive_stable = 0
                last_rect = curr_rect

            # 4. Native window motion stability if native hwnd provided
            elif target_hwnd and self.native_supervisor.is_window(target_hwnd):
                phys = self.native_supervisor.inspect_window(target_hwnd)
                curr_b = phys.bounds
                if last_rect is not None:
                    dx = abs(curr_b.x - last_rect["x"])
                    dy = abs(curr_b.y - last_rect["y"])
                    if dx == 0 and dy == 0:
                        consecutive_stable += 1
                        if consecutive_stable >= 2:
                            elapsed = (time.time() - start) * 1000.0
                            return SettlementResult(
                                settled=True,
                                settlement_type=SettlementType.STABLE,
                                elapsed_ms=elapsed,
                                iterations=iterations,
                                details={"bounds": curr_b.to_dict()},
                            )
                    else:
                        consecutive_stable = 0
                last_rect = {"x": curr_b.x, "y": curr_b.y}

            await asyncio.sleep(interval)

        elapsed = (time.time() - start) * 1000.0
        return SettlementResult(
            settled=consecutive_stable > 0,
            settlement_type=SettlementType.STABLE if consecutive_stable > 0 else SettlementType.TIMEOUT,
            elapsed_ms=elapsed,
            iterations=iterations,
            details={"timeout_reached": True},
        )

    async def _query_element_rect(self, ref: ElementRef) -> Optional[Dict[str, float]]:
        """Queries the live bounding rect of the target element."""
        if not self.webview_core or not self.webview_core.is_connected:
            return None
        recipe = ref.locator_recipe or {}
        name = recipe.get("name") or recipe.get("text") or ""
        role = recipe.get("role") or ""

        script = f"""
        (() => {{
            const targetName = {repr(name.strip().lower())};
            const targetRole = {repr(role.strip().lower())};
            const all = document.querySelectorAll('*');
            for (const el of all) {{
                const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                const r = (el.getAttribute('role') || el.tagName).trim().toLowerCase();
                if (targetName && (text === targetName || aria === targetName)) {{
                    const b = el.getBoundingClientRect();
                    return {{ found: true, x: b.x, y: b.y, width: b.width, height: b.height }};
                }}
                if (targetRole && r === targetRole) {{
                    const b = el.getBoundingClientRect();
                    return {{ found: true, x: b.x, y: b.y, width: b.width, height: b.height }};
                }}
            }}
            return {{ found: false }};
        }})()
        """
        try:
            frame_id = ref.frame_id or self.webview_core.frame_manager.root_frame_id
            res = await self.webview_core.utility_world.evaluate(
                expression=script,
                frame_id=frame_id,
                return_by_value=True,
            )
            if isinstance(res, dict) and res.get("found"):
                return res
            return None
        except Exception:
            return None
