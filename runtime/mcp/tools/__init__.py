"""
Tool registration package for Desktop WebView Reviewer MCP Control Plane.
Exposes exactly 12 cohesive, architecture-approved tools (Doc 14 §2).
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer

from runtime.mcp.runtime_bridge import RuntimeBridge
from runtime.mcp.tools.lifecycle import desktop_launch_impl, desktop_attach_impl
from runtime.mcp.tools.observation import desktop_inspect_impl
from runtime.mcp.tools.actions import (
    desktop_click_impl,
    desktop_type_impl,
    desktop_press_key_impl,
    desktop_hover_impl,
    desktop_scroll_impl,
)
from runtime.mcp.tools.dialogs import desktop_handle_dialog_impl
from runtime.mcp.tools.evaluation import desktop_evaluate_impl
from runtime.mcp.tools.verification import desktop_assert_impl
from runtime.mcp.tools.evidence import desktop_collect_evidence_impl


def register_all_tools(server: MCPServer, bridge: RuntimeBridge) -> None:
    """Registers all 12 architecture-mandated tools on the MCP server."""

    # 1. desktop_launch
    @server.tool(
        name="desktop_launch",
        description="Spawns a desktop application under Windows Job Object supervision. Discovers HWND/CDP and captures initial accessibility state.",
    )
    async def desktop_launch(
        executable_path: str,
        args: Optional[List[str]] = None,
        working_directory: Optional[str] = None,
        engine_hint: str = "auto",
        remote_debugging_port: Optional[int] = None,
        timeout_sec: int = 30,
    ) -> Dict[str, Any]:
        return await desktop_launch_impl(
            bridge=bridge,
            executable_path=executable_path,
            args=args,
            working_directory=working_directory,
            engine_hint=engine_hint,
            remote_debugging_port=remote_debugging_port,
            timeout_sec=timeout_sec,
        )

    # 2. desktop_attach
    @server.tool(
        name="desktop_attach",
        description="Attaches to an existing running application window or process by HWND, PID, window title pattern, or CDP port.",
    )
    async def desktop_attach(
        hwnd: Optional[int] = None,
        pid: Optional[int] = None,
        window_title_pattern: Optional[str] = None,
        cdp_port: Optional[int] = None,
        timeout_sec: int = 30,
    ) -> Dict[str, Any]:
        return await desktop_attach_impl(
            bridge=bridge,
            hwnd=hwnd,
            pid=pid,
            window_title_pattern=window_title_pattern,
            cdp_port=cdp_port,
            timeout_sec=timeout_sec,
        )

    # 3. desktop_inspect
    @server.tool(
        name="desktop_inspect",
        description="Captures the dual-perspective accessibility state of the window and returns a compact YAML tree annotated with interaction refs.",
    )
    async def desktop_inspect(
        session_id: str,
        perspective: str = "auto",
        diff_only: bool = False,
        max_depth: int = 7,
        role: Optional[str] = None,
        visible_only: bool = True,
        actionable_only: bool = False,
    ) -> Dict[str, Any]:
        return await desktop_inspect_impl(
            bridge=bridge,
            session_id=session_id,
            perspective=perspective,
            diff_only=diff_only,
            max_depth=max_depth,
            role=role,
            visible_only=visible_only,
            actionable_only=actionable_only,
        )

    # 4. desktop_click
    @server.tool(
        name="desktop_click",
        description="Clicks an interactive affordance identified by an ephemeral reference token with actionability waiting and fused post-observation.",
    )
    async def desktop_click(
        session_id: str,
        ref: str,
        click_count: int = 1,
        button: str = "left",
        include_snapshot: bool = True,
        timeout_ms: int = 5000,
        action_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await desktop_click_impl(
            bridge=bridge,
            session_id=session_id,
            ref=ref,
            click_count=click_count,
            button=button,
            include_snapshot=include_snapshot,
            timeout_ms=timeout_ms,
            action_id=action_id,
        )

    # 5. desktop_type
    @server.tool(
        name="desktop_type",
        description="Types text into an input field with authentic event bubbling across native and web planes.",
    )
    async def desktop_type(
        session_id: str,
        ref: str,
        text: str,
        clear_existing: bool = True,
        press_enter: bool = False,
        include_snapshot: bool = True,
        timeout_ms: int = 5000,
        action_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await desktop_type_impl(
            bridge=bridge,
            session_id=session_id,
            ref=ref,
            text=text,
            clear_existing=clear_existing,
            press_enter=press_enter,
            include_snapshot=include_snapshot,
            timeout_ms=timeout_ms,
            action_id=action_id,
        )

    # 6. desktop_press_key
    @server.tool(
        name="desktop_press_key",
        description="Sends keyboard shortcuts or navigation key combinations (e.g. 'Enter', 'Tab', 'Escape', 'Control+A').",
    )
    async def desktop_press_key(
        session_id: str,
        key: str,
        ref: Optional[str] = None,
        include_snapshot: bool = True,
        timeout_ms: int = 5000,
        action_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await desktop_press_key_impl(
            bridge=bridge,
            session_id=session_id,
            key=key,
            ref=ref,
            include_snapshot=include_snapshot,
            timeout_ms=timeout_ms,
            action_id=action_id,
        )

    # 7. desktop_hover
    @server.tool(
        name="desktop_hover",
        description="Hovers pointer over an element affordance to trigger tooltips or CSS hover states with motion settlement.",
    )
    async def desktop_hover(
        session_id: str,
        ref: str,
        include_snapshot: bool = True,
        timeout_ms: int = 5000,
        action_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await desktop_hover_impl(
            bridge=bridge,
            session_id=session_id,
            ref=ref,
            include_snapshot=include_snapshot,
            timeout_ms=timeout_ms,
            action_id=action_id,
        )

    # 8. desktop_scroll
    @server.tool(
        name="desktop_scroll",
        description="Scrolls a container or window to bring the target element into the visible viewport.",
    )
    async def desktop_scroll(
        session_id: str,
        ref: Optional[str] = None,
        direction: str = "into_view",
        delta_y: int = 300,
        include_snapshot: bool = True,
        timeout_ms: int = 5000,
        action_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await desktop_scroll_impl(
            bridge=bridge,
            session_id=session_id,
            ref=ref,
            direction=direction,
            delta_y=delta_y,
            include_snapshot=include_snapshot,
            timeout_ms=timeout_ms,
            action_id=action_id,
        )

    # 9. desktop_handle_dialog
    @server.tool(
        name="desktop_handle_dialog",
        description="Inspects and interacts with native Win32 modal dialogs (#32770, file pickers) or browser JavaScript alerts.",
    )
    async def desktop_handle_dialog(
        session_id: str,
        action: str,
        file_path: Optional[str] = None,
        timeout_ms: int = 5000,
    ) -> Dict[str, Any]:
        return await desktop_handle_dialog_impl(
            bridge=bridge,
            session_id=session_id,
            action=action,
            file_path=file_path,
            timeout_ms=timeout_ms,
        )

    # 10. desktop_evaluate
    @server.tool(
        name="desktop_evaluate",
        description="Evaluates a JavaScript expression safely inside the webview's isolated utility realm (__utility_world__).",
    )
    async def desktop_evaluate(
        session_id: str,
        expression: str,
        in_main_world: bool = False,
        timeout_ms: int = 5000,
    ) -> Dict[str, Any]:
        return await desktop_evaluate_impl(
            bridge=bridge,
            session_id=session_id,
            expression=expression,
            in_main_world=in_main_world,
            timeout_ms=timeout_ms,
        )

    # 11. desktop_assert
    @server.tool(
        name="desktop_assert",
        description="Performs an auto-retrying polling assertion on UI element state or content before proceeding.",
    )
    async def desktop_assert(
        session_id: str,
        ref: str,
        assertion: str,
        expected_text: Optional[str] = None,
        timeout_ms: int = 5000,
    ) -> Dict[str, Any]:
        return await desktop_assert_impl(
            bridge=bridge,
            session_id=session_id,
            ref=ref,
            assertion=assertion,
            expected_text=expected_text,
            timeout_ms=timeout_ms,
        )

    # 12. desktop_collect_evidence
    @server.tool(
        name="desktop_collect_evidence",
        description="Packages an immutable forensic evidence bundle and evaluates the Tripartite Verdict (PASS, FAIL, UNVERIFIED).",
    )
    async def desktop_collect_evidence(
        session_id: str,
        test_name: str,
        expected_outcome_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await desktop_collect_evidence_impl(
            bridge=bridge,
            session_id=session_id,
            test_name=test_name,
            expected_outcome_summary=expected_outcome_summary,
        )
