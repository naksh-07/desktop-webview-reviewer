"""
CDP Target Discovery, Multiplexing, and Process Correlation.
Tracks multiple inspectable targets, validates debugging endpoint ownership against
the expected native process, manages target sessions, and handles target lifecycle events.
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set, Callable

from runtime.state import TargetLifecycleState
from runtime.cdp_transport import ICDPTransport
from runtime.errors import (
    CDPTargetClosedException,
    CDPTargetCrashedException,
    InvalidTargetException,
    TargetNotFoundException,
)

logger = logging.getLogger("desktop_webview.cdp_target")


@dataclass(frozen=True)
class CDPTargetInfo:
    """Immutable identity and metadata of a discovered CDP target."""
    target_id: str
    type: str                     # "page", "iframe", "worker", "service_worker", "browser", "other"
    title: str
    url: str
    attached: bool = False
    opener_id: Optional[str] = None
    browser_context_id: Optional[str] = None
    cdp_session_id: Optional[str] = None  # Flat session ID if attached via Target.attachToTarget
    lifecycle_state: TargetLifecycleState = TargetLifecycleState.CREATED
    discovered_at: float = field(default_factory=time.time)
    ws_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "type": self.type,
            "title": self.title,
            "url": self.url,
            "attached": self.attached,
            "opener_id": self.opener_id,
            "browser_context_id": self.browser_context_id,
            "cdp_session_id": self.cdp_session_id,
            "lifecycle_state": self.lifecycle_state.value,
            "discovered_at": self.discovered_at,
            "ws_url": self.ws_url,
        }


@dataclass(frozen=True)
class EndpointProcessCorrelation:
    """Verification result correlating a debugging endpoint to an expected application process."""
    port: int
    host: str
    expected_pid: Optional[int]
    listening_pid: Optional[int]
    is_verified: bool
    proof_status: str             # "VERIFIED", "UNKNOWN", "MISMATCH"
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "port": self.port,
            "host": self.host,
            "expected_pid": self.expected_pid,
            "listening_pid": self.listening_pid,
            "is_verified": self.is_verified,
            "proof_status": self.proof_status,
            "reason": self.reason,
        }


class CDPTargetManager:
    """
    Manages CDP targets across one daemon session.
    Responsibilities:
    1. Validates remote debugging endpoint against owning native PID.
    2. Discovers inspectable page, iframe, and worker targets.
    3. Handles target multiplexing (attaching, detaching, and routing commands).
    4. Subscribes to Target domain lifecycle events (targetCreated, targetDestroyed, targetCrashed).
    5. Enforces target crash and close safety (marking dead targets, preventing misrouted commands).
    """

    def __init__(self, transport: ICDPTransport, session_id: str):
        self.transport = transport
        self.session_id = session_id
        # target_id -> CDPTargetInfo
        self._targets: Dict[str, CDPTargetInfo] = {}
        # cdp_session_id -> target_id
        self._session_to_target: Dict[str, str] = {}
        # target_id -> cdp_session_id
        self._target_to_session: Dict[str, str] = {}
        self._primary_target_id: Optional[str] = None
        self._correlation: Optional[EndpointProcessCorrelation] = None
        self._target_event_callbacks: List[Callable[[str, CDPTargetInfo], Any]] = []
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def primary_target(self) -> Optional[CDPTargetInfo]:
        """Returns the current primary page target."""
        if self._primary_target_id and self._primary_target_id in self._targets:
            return self._targets[self._primary_target_id]
        # Fallback to first active page target
        for t in self._targets.values():
            if t.type == "page" and t.lifecycle_state not in (TargetLifecycleState.CLOSED, TargetLifecycleState.CRASHED):
                return t
        return None

    @property
    def active_target_id(self) -> Optional[str]:
        """Returns the target ID of the primary active target if available."""
        target = self.primary_target
        return target.target_id if target else None

    @property
    def correlation(self) -> Optional[EndpointProcessCorrelation]:
        return self._correlation

    # -------------------------------------------------------------------------
    # 1. Endpoint & Process Correlation
    # -------------------------------------------------------------------------
    @staticmethod
    def verify_endpoint_ownership(
        port: int,
        host: str = "127.0.0.1",
        expected_pid: Optional[int] = None,
        expected_pids: Optional[Set[int]] = None,
    ) -> EndpointProcessCorrelation:
        """
        Validates that the debugging endpoint on `port` belongs to the expected process tree.
        Uses native OS netstat / Win32 table inspection via WindowForensicsEngine.
        Where process-level proof is unavailable, returns 'UNKNOWN' rather than claiming certainty.
        """
        target_pids = set(expected_pids or [])
        if expected_pid is not None and expected_pid > 0:
            target_pids.add(expected_pid)

        if not target_pids:
            return EndpointProcessCorrelation(
                port=port,
                host=host,
                expected_pid=expected_pid,
                listening_pid=None,
                is_verified=False,
                proof_status="UNKNOWN",
                reason="No expected PIDs provided for correlation proof.",
            )

        try:
            from core.window_forensics import WindowForensicsEngine
            is_owned, actual_pid, reason = WindowForensicsEngine.verify_port_listening_process(
                port=port,
                expected_pids=target_pids,
            )
            proof = "VERIFIED" if is_owned else ("MISMATCH" if actual_pid else "UNKNOWN")
            return EndpointProcessCorrelation(
                port=port,
                host=host,
                expected_pid=expected_pid,
                listening_pid=actual_pid,
                is_verified=is_owned,
                proof_status=proof,
                reason=reason,
            )
        except Exception as e:
            return EndpointProcessCorrelation(
                port=port,
                host=host,
                expected_pid=expected_pid,
                listening_pid=None,
                is_verified=False,
                proof_status="UNKNOWN",
                reason=f"Failed to inspect port ownership: {e}",
            )

    # -------------------------------------------------------------------------
    # 2. HTTP Target Discovery (/json/list)
    # -------------------------------------------------------------------------
    @staticmethod
    def discover_http_targets(host: str = "127.0.0.1", port: int = 9222, timeout: float = 3.0) -> List[CDPTargetInfo]:
        """Queries the /json/list endpoint once and returns parsed CDPTargetInfo records."""
        url = f"http://{host}:{port}/json/list"
        results: List[CDPTargetInfo] = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DesktopWebviewReviewer/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    raw = response.read().decode("utf-8")
                    data = json.loads(raw)
                    if isinstance(data, list):
                        for item in data:
                            results.append(
                                CDPTargetInfo(
                                    target_id=item.get("id", ""),
                                    type=item.get("type", "page"),
                                    title=item.get("title", ""),
                                    url=item.get("url", ""),
                                    ws_url=item.get("webSocketDebuggerUrl"),
                                    lifecycle_state=TargetLifecycleState.CREATED,
                                )
                            )
        except Exception as e:
            logger.debug(f"HTTP target discovery on {url} failed: {e}")
        return results

    # -------------------------------------------------------------------------
    # 3. Target Domain Initialization & Lifecycle Subscriptions
    # -------------------------------------------------------------------------
    async def initialize(self) -> None:
        """
        Enables Target domain auto-discovery and attaches listeners for target lifecycle events.
        """
        async with self._lock:
            if self._initialized:
                return

            # Register event listeners on the transport
            self.transport.add_event_listener("Target.targetCreated", self._on_target_created)
            self.transport.add_event_listener("Target.targetDestroyed", self._on_target_destroyed)
            self.transport.add_event_listener("Target.targetCrashed", self._on_target_crashed)
            self.transport.add_event_listener("Target.attachedToTarget", self._on_attached_to_target)
            self.transport.add_event_listener("Target.detachedFromTarget", self._on_detached_from_target)

            try:
                # Enable target discovery across the browser/webview
                await self.transport.send_command("Target.setDiscoverTargets", {"discover": True})
            except Exception as e:
                logger.debug(f"Target.setDiscoverTargets returned: {e}")

            # Populate initial targets via Target.getTargets
            try:
                resp = await self.transport.send_command("Target.getTargets")
                target_infos = resp.get("targetInfos", [])
                for info in target_infos:
                    self._update_or_add_target(info)
            except Exception as e:
                logger.debug(f"Target.getTargets query failed: {e}")

            self._initialized = True
            logger.debug(f"CDPTargetManager initialized for session {self.session_id}")

    def add_target_event_listener(self, callback: Callable[[str, CDPTargetInfo], Any]) -> None:
        """Registers a callback for target lifecycle changes: ('created'|'destroyed'|'crashed'|'attached', target)."""
        self._target_event_callbacks.append(callback)

    def _notify_target_event(self, event_type: str, target: CDPTargetInfo) -> None:
        for cb in self._target_event_callbacks:
            try:
                cb(event_type, target)
            except Exception as e:
                logger.error(f"Error in target lifecycle callback: {e}")

    # -------------------------------------------------------------------------
    # 4. Target Lifecycle Event Handlers
    # -------------------------------------------------------------------------
    def _on_target_created(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        info = params.get("targetInfo", {})
        target = self._update_or_add_target(info, lifecycle_state=TargetLifecycleState.CREATED)
        logger.debug(f"Target created: ID={target.target_id}, Type={target.type}, Title='{target.title}'")
        self._notify_target_event("created", target)

    def _on_target_destroyed(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        target_id = params.get("targetId", "")
        if target_id in self._targets:
            old = self._targets[target_id]
            updated = CDPTargetInfo(
                target_id=old.target_id,
                type=old.type,
                title=old.title,
                url=old.url,
                attached=False,
                opener_id=old.opener_id,
                browser_context_id=old.browser_context_id,
                cdp_session_id=None,
                lifecycle_state=TargetLifecycleState.CLOSED,
                discovered_at=old.discovered_at,
                ws_url=old.ws_url,
            )
            self._targets[target_id] = updated
            # Clean up session maps
            if target_id in self._target_to_session:
                sess_id = self._target_to_session.pop(target_id)
                self._session_to_target.pop(sess_id, None)

            logger.info(f"Target destroyed: ID={target_id}")
            self._notify_target_event("destroyed", updated)

    def _on_target_crashed(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        target_id = params.get("targetId", "")
        status = params.get("status", "crashed")
        error_code = params.get("errorCode", 0)

        if target_id in self._targets:
            old = self._targets[target_id]
            updated = CDPTargetInfo(
                target_id=old.target_id,
                type=old.type,
                title=old.title,
                url=old.url,
                attached=False,
                opener_id=old.opener_id,
                browser_context_id=old.browser_context_id,
                cdp_session_id=None,
                lifecycle_state=TargetLifecycleState.CRASHED,
                discovered_at=old.discovered_at,
                ws_url=old.ws_url,
            )
            self._targets[target_id] = updated
            logger.error(f"Target crashed: ID={target_id}, Status={status}, Code={error_code}")
            self._notify_target_event("crashed", updated)

    def _on_attached_to_target(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        session_id = params.get("sessionId", "")
        info = params.get("targetInfo", {})
        target_id = info.get("targetId", "")

        if target_id:
            old = self._targets.get(target_id)
            updated = CDPTargetInfo(
                target_id=target_id,
                type=info.get("type", old.type if old else "page"),
                title=info.get("title", old.title if old else ""),
                url=info.get("url", old.url if old else ""),
                attached=True,
                opener_id=info.get("openerId", old.opener_id if old else None),
                browser_context_id=info.get("browserContextId", old.browser_context_id if old else None),
                cdp_session_id=session_id,
                lifecycle_state=TargetLifecycleState.ATTACHED,
                discovered_at=old.discovered_at if old else time.time(),
                ws_url=old.ws_url if old else None,
            )
            self._targets[target_id] = updated
            self._session_to_target[session_id] = target_id
            self._target_to_session[target_id] = session_id
            logger.debug(f"Target attached: ID={target_id} -> Session={session_id}")
            self._notify_target_event("attached", updated)

    def _on_detached_from_target(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        session_id = params.get("sessionId", "")
        target_id = params.get("targetId") or self._session_to_target.get(session_id)

        if target_id and target_id in self._targets:
            old = self._targets[target_id]
            updated = CDPTargetInfo(
                target_id=old.target_id,
                type=old.type,
                title=old.title,
                url=old.url,
                attached=False,
                opener_id=old.opener_id,
                browser_context_id=old.browser_context_id,
                cdp_session_id=None,
                lifecycle_state=TargetLifecycleState.DETACHED,
                discovered_at=old.discovered_at,
                ws_url=old.ws_url,
            )
            self._targets[target_id] = updated
            self._session_to_target.pop(session_id, None)
            self._target_to_session.pop(target_id, None)
            logger.debug(f"Target detached: ID={target_id} (Session={session_id})")
            self._notify_target_event("detached", updated)

    def _update_or_add_target(
        self,
        info: Dict[str, Any],
        lifecycle_state: TargetLifecycleState = TargetLifecycleState.CREATED,
    ) -> CDPTargetInfo:
        target_id = info.get("targetId", "")
        old = self._targets.get(target_id)
        target = CDPTargetInfo(
            target_id=target_id,
            type=info.get("type", old.type if old else "page"),
            title=info.get("title", old.title if old else ""),
            url=info.get("url", old.url if old else ""),
            attached=info.get("attached", old.attached if old else False),
            opener_id=info.get("openerId", old.opener_id if old else None),
            browser_context_id=info.get("browserContextId", old.browser_context_id if old else None),
            cdp_session_id=old.cdp_session_id if old else None,
            lifecycle_state=lifecycle_state,
            discovered_at=old.discovered_at if old else time.time(),
            ws_url=old.ws_url if old else None,
        )
        self._targets[target_id] = target
        if self._primary_target_id is None and target.type == "page":
            self._primary_target_id = target_id
        return target

    # -------------------------------------------------------------------------
    # 5. Multiplexing & Target Control
    # -------------------------------------------------------------------------
    async def attach_target(self, target_id: str, flatten: bool = True) -> str:
        """
        Attaches to a specific target via Target.attachToTarget.
        Returns the assigned cdp_session_id for flat command routing.
        """
        target = self.get_target(target_id)
        if target.lifecycle_state in (TargetLifecycleState.CLOSED, TargetLifecycleState.CRASHED):
            raise CDPTargetClosedException(target_id, f"Cannot attach to target in {target.lifecycle_state.value} state")

        # If already attached, return existing session ID
        if target.cdp_session_id and target.attached:
            return target.cdp_session_id

        resp = await self.transport.send_command(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": flatten},
        )
        session_id = resp.get("sessionId", "")
        if not session_id:
            raise InvalidTargetException(f"Target.attachToTarget failed to return sessionId for target {target_id}")

        self._session_to_target[session_id] = target_id
        self._target_to_session[target_id] = session_id

        updated = CDPTargetInfo(
            target_id=target.target_id,
            type=target.type,
            title=target.title,
            url=target.url,
            attached=True,
            opener_id=target.opener_id,
            browser_context_id=target.browser_context_id,
            cdp_session_id=session_id,
            lifecycle_state=TargetLifecycleState.ATTACHED,
            discovered_at=target.discovered_at,
            ws_url=target.ws_url,
        )
        self._targets[target_id] = updated
        return session_id

    async def detach_target(self, target_id: str) -> None:
        """Detaches from target session."""
        session_id = self._target_to_session.get(target_id)
        if session_id:
            try:
                await self.transport.send_command("Target.detachFromTarget", {"sessionId": session_id})
            except Exception as e:
                logger.debug(f"Target.detachFromTarget error: {e}")
            self._session_to_target.pop(session_id, None)
            self._target_to_session.pop(target_id, None)

        if target_id in self._targets:
            old = self._targets[target_id]
            self._targets[target_id] = CDPTargetInfo(
                target_id=old.target_id,
                type=old.type,
                title=old.title,
                url=old.url,
                attached=False,
                opener_id=old.opener_id,
                browser_context_id=old.browser_context_id,
                cdp_session_id=None,
                lifecycle_state=TargetLifecycleState.DETACHED,
                discovered_at=old.discovered_at,
                ws_url=old.ws_url,
            )

    async def close_target(self, target_id: str) -> bool:
        """Closes target page via Target.closeTarget."""
        try:
            resp = await self.transport.send_command("Target.closeTarget", {"targetId": target_id})
            success = resp.get("success", True)
            if target_id in self._targets:
                old = self._targets[target_id]
                self._targets[target_id] = CDPTargetInfo(
                    target_id=old.target_id,
                    type=old.type,
                    title=old.title,
                    url=old.url,
                    attached=False,
                    opener_id=old.opener_id,
                    browser_context_id=old.browser_context_id,
                    cdp_session_id=None,
                    lifecycle_state=TargetLifecycleState.CLOSED,
                    discovered_at=old.discovered_at,
                    ws_url=old.ws_url,
                )
            return success
        except Exception as e:
            logger.warning(f"Failed to close target {target_id}: {e}")
            return False

    def select_primary_target(self, target_id: str) -> None:
        """Explicitly sets the active primary page target."""
        if target_id not in self._targets:
            raise TargetNotFoundException(f"Target ID '{target_id}' not found in registry", target_id=target_id)
        self._primary_target_id = target_id
        logger.info(f"Primary target set to ID={target_id} ('{self._targets[target_id].title}')")

    def get_target(self, target_id: str) -> CDPTargetInfo:
        """Retrieves target info by ID. Raises TargetNotFoundException if missing."""
        if target_id not in self._targets:
            raise TargetNotFoundException(f"Target ID '{target_id}' not found", target_id=target_id)
        return self._targets[target_id]

    def get_session_id_for_target(self, target_id: str) -> Optional[str]:
        """Returns the CDP session ID associated with a target if attached."""
        return self._target_to_session.get(target_id)

    def list_targets(self, active_only: bool = True) -> List[CDPTargetInfo]:
        """Lists all registered targets."""
        if active_only:
            return [
                t for t in self._targets.values()
                if t.lifecycle_state not in (TargetLifecycleState.CLOSED, TargetLifecycleState.CRASHED)
            ]
        return list(self._targets.values())

    def register_discovered_target(self, target: CDPTargetInfo) -> None:
        """Manually registers an externally discovered target record."""
        self._targets[target.target_id] = target
        if self._primary_target_id is None and target.type == "page":
            self._primary_target_id = target.target_id
