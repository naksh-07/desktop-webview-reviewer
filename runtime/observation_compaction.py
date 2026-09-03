"""
Compact Observation Formatting & Token Compression Engine.
Transforms dual-perspective observation structures into token-efficient, indented YAML
representations suitable for LLM reasoning without context bloat.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any

from runtime.observation_models import (
    NativeObservation,
    WebObservation,
    ReconciliationObservation,
    NativeElementObservation,
    WebElementObservation,
)


def format_observation_yaml(
    native_obs: Optional[NativeObservation],
    web_obs: Optional[WebObservation],
    reconciliation: Optional[ReconciliationObservation] = None,
) -> str:
    """
    Renders a compact, human/agent-readable YAML representation of dual-perspective observations.
    Follows docs/architecture/16_OBSERVATION_MODEL.md specifications.
    """
    lines: List[str] = []
    epoch = 1
    if web_obs:
        epoch = web_obs.epoch
    elif native_obs:
        epoch = native_obs.epoch
    elif reconciliation:
        epoch = reconciliation.epoch

    lines.append(f"# Observation Epoch: {epoch}")

    # 1. Native Perspective Header
    if native_obs:
        focused_flag = " [focused]" if any(e.interaction and e.interaction.is_focused for e in native_obs.elements) else ""
        min_flag = " [minimized]" if native_obs.is_minimized else ""
        cloak_flag = " [cloaked]" if native_obs.is_cloaked else ""
        hung_flag = " [HUNG]" if not native_obs.is_responsive else ""
        bounds_str = f" [bounds={native_obs.bounds.x},{native_obs.bounds.y},{native_obs.bounds.width},{native_obs.bounds.height}]"
        
        root_ref = next((e.reference for e in native_obs.elements if e.depth == 0), "")
        ref_str = f" [ref={root_ref}]" if root_ref else ""

        lines.append(f"@@ native_window: [hwnd={hex(native_obs.hwnd)}, title=\"{native_obs.title or 'Desktop Window'}\"] @@")
        lines.append(f"- window: \"{native_obs.title or 'Desktop Window'}\" [hwnd={hex(native_obs.hwnd)}]{ref_str}{bounds_str}{focused_flag}{min_flag}{cloak_flag}{hung_flag}")

        # Native child elements
        child_native = [e for e in native_obs.elements if e.depth > 0]
        if child_native:
            lines.append("  - native_controls:")
            for ne in child_native:
                name_str = f" \"{ne.name}\"" if ne.name else ""
                auto_id_str = f" [id={ne.automation_id}]" if ne.automation_id else ""
                dis_flag = " [disabled]" if (ne.interaction and not ne.interaction.is_enabled) else ""
                foc_flag = " [focused]" if (ne.interaction and ne.interaction.is_focused) else ""
                lines.append(f"    - {ne.control_type.lower()}{name_str} [ref={ne.reference}]{auto_id_str}{dis_flag}{foc_flag}")

    # 2. Reconciliation & Warning Header
    if reconciliation:
        if reconciliation.relationship_type:
            lines.append(f"@@ reconciliation: [relationship={reconciliation.relationship_type.value}, confidence={reconciliation.confidence.value}] @@")
        if reconciliation.contradictions:
            for c in reconciliation.contradictions:
                lines.append(f"  [warning=\"{c}\"]")

    # 3. Webview Perspective
    if web_obs:
        target_info = f"[target={web_obs.target_id}, title=\"{web_obs.target_title}\"]" if web_obs.target_title else f"[target={web_obs.target_id}]"
        lines.append(f"@@ webview: {target_info} @@")

        # Group elements by frame if multi-frame
        frames_seen = set()
        for we in web_obs.elements:
            indent = "  "
            if we.frame_id and we.frame_id != web_obs.root_frame_id:
                if we.frame_id not in frames_seen:
                    frames_seen.add(we.frame_id)
                    lines.append(f"  - iframe [frame_id={we.frame_id}]:")
                indent = "    "

            role = we.normalized_role
            name_text = we.accessible_name or we.visible_text or ""
            name_str = f" \"{name_text}\"" if name_text else ""
            ref_str = f" [ref={we.reference}]"

            flags = [f"role={role}"]
            if we.placeholder:
                flags.append(f"placeholder=\"{we.placeholder}\"")
            if we.interaction:
                if not we.interaction.is_enabled:
                    flags.append("disabled")
                if we.interaction.is_focused:
                    flags.append("focused")
                if we.interaction.is_checked is True:
                    flags.append("checked=true")
                elif we.interaction.is_checked is False:
                    flags.append("checked=false")
                if we.interaction.is_selected:
                    flags.append("selected")
                if we.interaction.is_expanded is not None:
                    flags.append(f"expanded={'true' if we.interaction.is_expanded else 'false'}")

            flag_str = " [" + "] [".join(flags) + "]" if flags else ""
            lines.append(f"{indent}- {role}{name_str}{ref_str}{flag_str}")

    return "\n".join(lines)
