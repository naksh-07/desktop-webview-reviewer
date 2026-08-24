"""
Capability negotiation and discovery for desktop-webview-reviewer.
"""

from typing import Any, Dict, List, Optional
from .models import CapabilityName, CapabilityStatus, EngineInfo


class CapabilityRegistry:
    """Standard registry for engine capabilities."""

    @staticmethod
    def create_capability_matrix(
        dom: CapabilityStatus = CapabilityStatus.UNKNOWN,
        input_actions: CapabilityStatus = CapabilityStatus.UNKNOWN,
        keyboard: Optional[CapabilityStatus] = None,
        mouse: Optional[CapabilityStatus] = None,
        runtime: CapabilityStatus = CapabilityStatus.UNKNOWN,
        screenshot: CapabilityStatus = CapabilityStatus.UNKNOWN,
        console: CapabilityStatus = CapabilityStatus.UNKNOWN,
        network: CapabilityStatus = CapabilityStatus.UNKNOWN,
        targets: CapabilityStatus = CapabilityStatus.UNKNOWN,
        multi_target: Optional[CapabilityStatus] = None,
        navigation: Optional[CapabilityStatus] = None,
        js: CapabilityStatus = CapabilityStatus.UNKNOWN,
    ) -> Dict[str, CapabilityStatus]:
        kb = keyboard if keyboard is not None else input_actions
        ms = mouse if mouse is not None else input_actions
        mt = multi_target if multi_target is not None else targets
        nav = navigation if navigation is not None else dom

        return {
            CapabilityName.DOM.value: dom,
            CapabilityName.INPUT.value: input_actions,
            CapabilityName.KEYBOARD.value: kb,
            CapabilityName.MOUSE.value: ms,
            CapabilityName.RUNTIME.value: runtime,
            CapabilityName.SCREENSHOT.value: screenshot,
            CapabilityName.CONSOLE.value: console,
            CapabilityName.NETWORK.value: network,
            CapabilityName.TARGETS.value: targets,
            CapabilityName.MULTI_TARGET.value: mt,
            CapabilityName.NAVIGATION.value: nav,
            CapabilityName.JS.value: js,
        }

    @staticmethod
    def assert_capability(engine_info: EngineInfo, capability: CapabilityName) -> None:
        """Raise RuntimeError if capability is unsupported."""
        status = engine_info.capabilities.get(capability.value, CapabilityStatus.UNKNOWN)
        if status == CapabilityStatus.UNSUPPORTED:
            raise RuntimeError(
                f"Capability '{capability.value}' is explicitly UNSUPPORTED by engine '{engine_info.engine}'."
            )

    @staticmethod
    def is_supported(engine_info: EngineInfo, capability: CapabilityName) -> bool:
        status = engine_info.capabilities.get(capability.value, CapabilityStatus.UNKNOWN)
        return status in (CapabilityStatus.SUPPORTED, CapabilityStatus.DEGRADED)

    @staticmethod
    def downgrade_capability(engine_info: EngineInfo, capability: CapabilityName, reason: str) -> None:
        """Dynamically downgrades a capability and adds a diagnostic note."""
        current = engine_info.capabilities.get(capability.value, CapabilityStatus.SUPPORTED)
        if current == CapabilityStatus.SUPPORTED:
            engine_info.capabilities[capability.value] = CapabilityStatus.DEGRADED
            note = f"Capability '{capability.value}' downgraded to DEGRADED: {reason}"
            if note not in engine_info.notes:
                engine_info.notes.append(note)

    @classmethod
    async def probe_runtime_capabilities(
        cls,
        session: Any,
        engine_info: EngineInfo
    ) -> Dict[str, CapabilityStatus]:
        """
        Dynamically probes the live CDP endpoint for domain support.
        Updates engine_info.probed_capabilities and downgrades failing capabilities.
        """
        probed: Dict[str, CapabilityStatus] = {}

        # 1. Probe Runtime & JS
        try:
            val = await session.evaluate_js("1 + 1")
            if val == 2:
                probed[CapabilityName.RUNTIME.value] = CapabilityStatus.SUPPORTED
                probed[CapabilityName.JS.value] = CapabilityStatus.SUPPORTED
            else:
                probed[CapabilityName.RUNTIME.value] = CapabilityStatus.DEGRADED
                probed[CapabilityName.JS.value] = CapabilityStatus.DEGRADED
        except Exception as e:
            probed[CapabilityName.RUNTIME.value] = CapabilityStatus.UNSUPPORTED
            probed[CapabilityName.JS.value] = CapabilityStatus.UNSUPPORTED
            cls.downgrade_capability(engine_info, CapabilityName.RUNTIME, str(e))
            cls.downgrade_capability(engine_info, CapabilityName.JS, str(e))

        # 2. Probe DOM
        try:
            doc = await session.get_document()
            if doc and "nodeId" in doc:
                probed[CapabilityName.DOM.value] = CapabilityStatus.SUPPORTED
            else:
                probed[CapabilityName.DOM.value] = CapabilityStatus.DEGRADED
        except Exception as e:
            probed[CapabilityName.DOM.value] = CapabilityStatus.DEGRADED
            cls.downgrade_capability(engine_info, CapabilityName.DOM, str(e))

        # 3. Probe Screenshot
        try:
            shot_res = await session.send_command("Page.captureScreenshot", {"format": "png"})
            if shot_res and "data" in shot_res:
                probed[CapabilityName.SCREENSHOT.value] = CapabilityStatus.SUPPORTED
            else:
                probed[CapabilityName.SCREENSHOT.value] = CapabilityStatus.DEGRADED
        except Exception as e:
            # Some platforms or restricted WebViews might not support Page.captureScreenshot
            probed[CapabilityName.SCREENSHOT.value] = CapabilityStatus.DEGRADED
            cls.downgrade_capability(engine_info, CapabilityName.SCREENSHOT, str(e))

        # 4. Probe Input
        try:
            # Attempt a non-intrusive mouse move or query
            await session.send_command("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": 0,
                "y": 0
            })
            probed[CapabilityName.INPUT.value] = CapabilityStatus.SUPPORTED
            probed[CapabilityName.MOUSE.value] = CapabilityStatus.SUPPORTED
            probed[CapabilityName.KEYBOARD.value] = CapabilityStatus.SUPPORTED
        except Exception as e:
            probed[CapabilityName.INPUT.value] = CapabilityStatus.DEGRADED
            probed[CapabilityName.MOUSE.value] = CapabilityStatus.DEGRADED
            cls.downgrade_capability(engine_info, CapabilityName.INPUT, f"Native input dispatch failed ({e}); falling back to synthetic DOM events.")
            cls.downgrade_capability(engine_info, CapabilityName.MOUSE, str(e))

        engine_info.probed_capabilities = probed
        return probed

    @staticmethod
    def format_capability_summary(engine_info: EngineInfo) -> str:
        lines = [
            f"Engine: {engine_info.engine} ({engine_info.backend})",
            f"Framework: {engine_info.framework or 'native'} | Confidence: {engine_info.confidence.value if hasattr(engine_info.confidence, 'value') else engine_info.confidence}",
            f"Version: {engine_info.version} | Protocol: {engine_info.protocol}",
            "Capabilities:"
        ]
        for cap, status in engine_info.capabilities.items():
            badge = "[+]" if status == CapabilityStatus.SUPPORTED else ("[-]" if status == CapabilityStatus.UNSUPPORTED else "[~]")
            lines.append(f"  {badge} {cap:<12}: {status.value if hasattr(status, 'value') else status}")
        if engine_info.notes:
            lines.append("Notes:")
            for note in engine_info.notes:
                lines.append(f"  - {note}")
        return "\n".join(lines)
