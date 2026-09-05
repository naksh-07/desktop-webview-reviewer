"""
Runtime Bridge for Desktop WebView Reviewer MCP Control Plane.
Coordinates delegation to the out-of-process DesktopDaemon, manages session
engine lifecycles, action-observation fusion, and action deduplication (Section 18 & 29).
"""

from __future__ import annotations
import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from runtime.state import TargetPlane, SessionLifecycleState
from runtime.daemon import DesktopDaemon, get_default_daemon
from runtime.session_manager import SessionState, SessionConfig
from runtime.target_manager import ProcessIdentity, WindowIdentity
from runtime.references import ReferenceRegistry
from runtime.native_supervisor import NativeSupervisor
from runtime.flaui_bridge import FlaUIBridge
from runtime.cdp_transport import WebSocketCDPTransport
from runtime.cdp_target import CDPTargetManager
from runtime.webview_core import WebviewAutomationCore
from runtime.observation_engine import ObservationEngine
from runtime.actionability import ActionabilityEngine
from runtime.locators import DeterministicLocatorEngine
from runtime.native_input import NativeInputDispatcher
from runtime.settlement import SettlementEngine
from runtime.web_action_executor import WebActionExecutor
from runtime.native_action_executor import NativeActionExecutor
from runtime.action_engine import ActionExecutionEngine
from runtime.action_models import (
    ActionRequest,
    ActionReceipt,
    ActionOutcome,
    ActionType,
    DispatchMethod,
    DispatchStatus,
    ActionOutcomeStatus,
    StateChangeClassification,
)
from runtime.evidence_store import EvidenceStore
from runtime.evidence_models import ProofLevel
from runtime.verification_engine import VerificationEngine
from runtime.mcp.errors import (
    McpErrorCode,
    McpControlPlaneException,
    map_exception_to_mcp_error,
)
from runtime.mcp.security import SecurityGate

logger = logging.getLogger("desktop_webview.mcp.bridge")


class RuntimeBridge:
    """
    Stateful bridge connecting MCP tool handlers to the underlying DesktopDaemon
    and session automation engines.
    """

    def __init__(self, daemon: Optional[DesktopDaemon] = None):
        self.daemon = daemon or get_default_daemon()
        self._lock = asyncio.Lock()
        from runtime.mission_orchestrator import ReviewMissionOrchestrator
        self.mission_orchestrator = ReviewMissionOrchestrator(session_manager=self.daemon.session_manager)

    async def ensure_initialized(self) -> None:
        """Initializes daemon if not already running."""
        await self.daemon.initialize()

    def get_session(self, session_id: str) -> SessionState:
        """Retrieves active session state or raises INVALID_SESSION."""
        if not session_id or not isinstance(session_id, str):
            raise McpControlPlaneException(
                code=McpErrorCode.INVALID_SESSION,
                message="A valid non-empty 'session_id' is mandatory for all session operations.",
                agent_action_hint="Check active sessions with desktop://sessions or call desktop_launch/desktop_attach.",
            )
        try:
            session = self.daemon.session_manager.get_session(session_id)
            if session.is_closed:
                raise McpControlPlaneException(
                    code=McpErrorCode.INVALID_SESSION,
                    message=f"Session '{session_id}' is closed.",
                    agent_action_hint="Launch or attach a new session.",
                )
            return session
        except Exception as e:
            raise map_exception_to_mcp_error(e)

    async def initialize_session_engines(
        self,
        session: SessionState,
        primary_hwnd: Optional[int] = None,
        cdp_port: Optional[int] = None,
    ) -> None:
        """
        Instantiates and binds all execution engines for a session if not already bound.
        """
        async with self._lock:
            supervisor = session.native_supervisor or NativeSupervisor()
            session.native_supervisor = supervisor

            flaui = session.flaui_bridge or FlaUIBridge()
            session.flaui_bridge = flaui

            registry = session.reference_registry

            # Connect CDP webview if port is supplied and not already connected
            core = session.webview_core
            if not core and cdp_port:
                try:
                    http_targets = CDPTargetManager.discover_http_targets(port=cdp_port)
                    primary_t = next((t for t in http_targets if t.type == "page" and "main" in t.title.lower() and t.ws_url), None)
                    if not primary_t:
                        primary_t = next((t for t in http_targets if t.type == "page" and t.ws_url), None)
                    if not primary_t and http_targets:
                        primary_t = http_targets[0]

                    if primary_t and primary_t.ws_url:
                        transport = WebSocketCDPTransport(endpoint_url=primary_t.ws_url)
                        core = WebviewAutomationCore(
                            session_id=session.session_id,
                            transport=transport,
                            reference_registry=registry,
                            native_hwnd=primary_hwnd or (session.target_window.hwnd if session.target_window else None),
                            native_pid=session.target_process.pid if session.target_process else None,
                            cdp_port=cdp_port,
                        )
                        await core.connect()
                        session.webview_core = core
                        logger.info(f"Connected WebviewAutomationCore to target '{primary_t.title}' ({primary_t.target_id})")
                except Exception as e:
                    logger.warning(f"Could not connect WebviewAutomationCore on port {cdp_port}: {e}")

            # Evidence Store
            if not session.evidence_store:
                session.evidence_store = EvidenceStore()

            # Verification Engine
            if not session.verification_engine:
                session.verification_engine = VerificationEngine(
                    evidence_store=session.evidence_store,
                    default_proof_level=ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
                    require_visible_gui=True,
                )

            # Actionability Engine
            if not session.actionability_engine:
                session.actionability_engine = ActionabilityEngine(
                    reference_registry=registry,
                    native_supervisor=supervisor,
                    webview_core=session.webview_core,
                    flaui_bridge=flaui,
                    session_id=session.session_id,
                )

            # Observation Engine
            if not session.observation_engine:
                session.observation_engine = ObservationEngine(
                    session_id=session.session_id,
                    reference_registry=registry,
                    native_supervisor=supervisor,
                    webview_core=session.webview_core,
                    flaui_bridge=flaui,
                )

            # Action Engine
            if not session.action_engine:
                session.action_engine = ActionExecutionEngine(
                    session_id=session.session_id,
                    reference_registry=registry,
                    native_supervisor=supervisor,
                    observation_engine=session.observation_engine,
                    actionability_engine=session.actionability_engine,
                    webview_core=session.webview_core,
                    flaui_bridge=flaui,
                    evidence_store=session.evidence_store,
                    verification_engine=session.verification_engine,
                )

    async def execute_action_deduplicated(
        self,
        session: SessionState,
        request: ActionRequest,
        include_snapshot: bool = True,
    ) -> Tuple[ActionOutcome, Optional[str]]:
        """
        Executes an action with idempotency / deduplication check (Section 29)
        and action-observation fusion (Section 18).
        Returns (ActionOutcome, post_snapshot_yaml).
        """
        # 1. Deduplication check
        if request.action_id in session.executed_actions:
            logger.info(f"Action ID '{request.action_id}' already executed in session '{session.session_id}'. Returning cached outcome.")
            cached_outcome = session.executed_actions[request.action_id]
            post_snapshot_str = None
            if include_snapshot and cached_outcome.post_snapshot:
                post_snapshot_str = cached_outcome.post_snapshot.text_representation
            return cached_outcome, post_snapshot_str, True

        # Ensure engines are initialized
        await self.initialize_session_engines(
            session,
            primary_hwnd=session.target_window.hwnd if session.target_window else None,
            cdp_port=session.target_endpoint.port if session.target_endpoint else None,
        )

        # 2. Execute action
        outcome: ActionOutcome = await session.action_engine.execute(request=request, verify=True)
        session.executed_actions[request.action_id] = outcome
        session.last_outcome = outcome

        # 3. Action-observation fusion
        post_snapshot_str: Optional[str] = None
        if include_snapshot:
            if outcome.post_snapshot and getattr(outcome.post_snapshot, "text_representation", None):
                post_snapshot_str = outcome.post_snapshot.text_representation
            else:
                try:
                    fresh_snap = await session.observation_engine.observe(
                        hwnd=session.target_window.hwnd if session.target_window else None,
                    )
                    outcome.post_snapshot = fresh_snap
                    post_snapshot_str = fresh_snap.text_representation
                except Exception as e:
                    logger.debug(f"Could not capture fused post-action snapshot: {e}")

        return outcome, post_snapshot_str, False
