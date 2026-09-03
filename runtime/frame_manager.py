"""
Hierarchical Frame Context Management, Lifecycle Tracking, and Controlled Frame Piercing.
Maintains the frame hierarchy of webview targets, supports same-origin and cross-origin
iframes, tracks execution contexts, and drives epoch invalidation on navigation.
"""

from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Set, Tuple

from runtime.state import FrameLifecycleState
from runtime.cdp_transport import ICDPTransport
from runtime.references import ReferenceRegistry
from runtime.errors import (
    FrameDetachedException,
    FrameNotFoundException,
    ExecutionContextDestroyedException,
    CrossDomainFrameAccessException,
)

logger = logging.getLogger("desktop_webview.frame_manager")


@dataclass(frozen=True)
class FrameContext:
    """Immutable identity and metadata of a document frame within a webview."""
    frame_id: str
    parent_frame_id: Optional[str]
    loader_id: str
    url: str
    security_origin: str
    name: Optional[str] = None
    mime_type: Optional[str] = None
    lifecycle_state: FrameLifecycleState = FrameLifecycleState.ATTACHED
    is_root: bool = False
    is_out_of_process: bool = False
    is_accessible: bool = True
    access_restriction: Optional[str] = None  # None or "CROSS_ORIGIN_RESTRICTED"
    execution_context_id: Optional[int] = None
    utility_context_id: Optional[int] = None
    children_frame_ids: Tuple[str, ...] = field(default_factory=tuple)
    attached_at: float = field(default_factory=time.time)
    navigated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "parent_frame_id": self.parent_frame_id,
            "loader_id": self.loader_id,
            "url": self.url,
            "security_origin": self.security_origin,
            "name": self.name,
            "mime_type": self.mime_type,
            "lifecycle_state": self.lifecycle_state.value,
            "is_root": self.is_root,
            "is_out_of_process": self.is_out_of_process,
            "is_accessible": self.is_accessible,
            "access_restriction": self.access_restriction,
            "execution_context_id": self.execution_context_id,
            "utility_context_id": self.utility_context_id,
            "children_frame_ids": list(self.children_frame_ids),
            "attached_at": self.attached_at,
            "navigated_at": self.navigated_at,
        }


class FrameManager:
    """
    Authoritative manager for all frames and execution contexts in a webview target.
    Responsibilities:
    1. Reconstructs and maintains the hierarchical frame tree (`root_frame_id` + child branches).
    2. Subscribes to Page and Runtime lifecycle events (`Page.frameNavigated`, `Page.frameDetached`, `Runtime.executionContext*`).
    3. Controls frame piercing: enumerates reachable frames and identifies cross-origin boundaries.
    4. Enforces navigation invalidation: automatically advances observation epoch on root navigation.
    5. Defends against frame lifecycle races (raising FrameDetachedException on detached frame actions).
    """

    def __init__(
        self,
        transport: ICDPTransport,
        reference_registry: ReferenceRegistry,
        session_id: str,
        target_session_id: Optional[str] = None,
    ):
        self.transport = transport
        self.reference_registry = reference_registry
        self.session_id = session_id
        self.target_session_id = target_session_id
        self._frames: Dict[str, FrameContext] = {}
        self._root_frame_id: Optional[str] = None
        # execution_context_id -> frame_id
        self._context_to_frame: Dict[int, str] = {}
        self._navigation_callbacks: List[Callable[[FrameContext, int], Any]] = []
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def root_frame_id(self) -> Optional[str]:
        return self._root_frame_id

    @property
    def root_frame(self) -> Optional[FrameContext]:
        if self._root_frame_id and self._root_frame_id in self._frames:
            return self._frames[self._root_frame_id]
        return None

    @property
    def frames(self) -> Dict[str, FrameContext]:
        """Dictionary of all tracked frames mapped by frame_id."""
        return dict(self._frames)

    # -------------------------------------------------------------------------
    # 1. Lifecycle Event Subscriptions
    # -------------------------------------------------------------------------
    async def initialize(self) -> None:
        """Enables Page and Runtime domains and registers frame listeners."""
        async with self._lock:
            if self._initialized:
                return

            self.transport.add_event_listener("Page.frameNavigated", self._on_frame_navigated, self.target_session_id)
            self.transport.add_event_listener("Page.frameAttached", self._on_frame_attached, self.target_session_id)
            self.transport.add_event_listener("Page.frameDetached", self._on_frame_detached, self.target_session_id)
            self.transport.add_event_listener("Runtime.executionContextCreated", self._on_execution_context_created, self.target_session_id)
            self.transport.add_event_listener("Runtime.executionContextDestroyed", self._on_execution_context_destroyed, self.target_session_id)
            self.transport.add_event_listener("Runtime.executionContextsCleared", self._on_execution_contexts_cleared, self.target_session_id)

            # Enable Page and Runtime domains
            try:
                await self.transport.send_command("Page.enable", session_id=self.target_session_id)
            except Exception as e:
                logger.debug(f"Page.enable returned: {e}")

            try:
                await self.transport.send_command("Runtime.enable", session_id=self.target_session_id)
            except Exception as e:
                logger.debug(f"Runtime.enable returned: {e}")

            # Fetch initial frame tree via Page.getFrameTree
            await self.refresh_frame_tree()
            self._initialized = True
            logger.debug(f"FrameManager initialized for session {self.session_id}")

    async def refresh_frame_tree(self) -> None:
        """Queries Page.getFrameTree to populate all frame nodes."""
        try:
            resp = await self.transport.send_command("Page.getFrameTree", session_id=self.target_session_id)
            frame_tree = resp.get("frameTree", {})
            self._parse_frame_tree_node(frame_tree, is_root=True)
        except Exception as e:
            logger.debug(f"Page.getFrameTree query failed: {e}")

    def _parse_frame_tree_node(
        self,
        node: Dict[str, Any],
        is_root: bool = False,
        root_origin: str = "",
    ) -> Optional[str]:
        raw_frame = node.get("frame", {})
        frame_id = raw_frame.get("id")
        if not frame_id:
            return None

        if is_root or self._root_frame_id is None:
            self._root_frame_id = frame_id
            root_origin = raw_frame.get("securityOrigin", "")

        parent_id = raw_frame.get("parentId")
        children = node.get("childFrames", [])
        child_ids = []
        for child in children:
            cid = self._parse_frame_tree_node(child, is_root=False, root_origin=root_origin)
            if cid:
                child_ids.append(cid)

        # Check for cross-origin security boundary
        security_origin = raw_frame.get("securityOrigin", "")
        is_cross_origin = bool(root_origin and security_origin and root_origin != security_origin)

        existing = self._frames.get(frame_id)
        now_ts = time.time()
        context = FrameContext(
            frame_id=frame_id,
            parent_frame_id=parent_id,
            loader_id=raw_frame.get("loaderId", ""),
            url=raw_frame.get("url", ""),
            security_origin=security_origin,
            name=raw_frame.get("name"),
            mime_type=raw_frame.get("mimeType"),
            lifecycle_state=FrameLifecycleState.ATTACHED,
            is_root=is_root,
            is_out_of_process=is_cross_origin,
            is_accessible=not is_cross_origin,
            access_restriction="CROSS_ORIGIN_RESTRICTED" if is_cross_origin else None,
            execution_context_id=existing.execution_context_id if existing else None,
            utility_context_id=existing.utility_context_id if existing else None,
            children_frame_ids=tuple(child_ids),
            attached_at=existing.attached_at if existing else now_ts,
            navigated_at=now_ts,
        )
        self._frames[frame_id] = context
        return frame_id

    def add_navigation_listener(self, callback: Callable[[FrameContext, int], Any]) -> None:
        """Registers a callback for frame navigations: (frame_context, new_epoch)."""
        self._navigation_callbacks.append(callback)

    # -------------------------------------------------------------------------
    # 2. Frame Event Processing
    # -------------------------------------------------------------------------
    def _on_frame_attached(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        frame_id = params.get("frameId", "")
        parent_id = params.get("parentFrameId")

        if frame_id:
            context = FrameContext(
                frame_id=frame_id,
                parent_frame_id=parent_id,
                loader_id="",
                url="about:blank",
                security_origin="",
                lifecycle_state=FrameLifecycleState.ATTACHED,
                is_root=(parent_id is None),
                attached_at=time.time(),
            )
            self._frames[frame_id] = context
            if parent_id and parent_id in self._frames:
                parent = self._frames[parent_id]
                updated_children = tuple(list(parent.children_frame_ids) + [frame_id])
                self._frames[parent_id] = FrameContext(
                    frame_id=parent.frame_id,
                    parent_frame_id=parent.parent_frame_id,
                    loader_id=parent.loader_id,
                    url=parent.url,
                    security_origin=parent.security_origin,
                    name=parent.name,
                    mime_type=parent.mime_type,
                    lifecycle_state=parent.lifecycle_state,
                    is_root=parent.is_root,
                    is_out_of_process=parent.is_out_of_process,
                    is_accessible=parent.is_accessible,
                    access_restriction=parent.access_restriction,
                    execution_context_id=parent.execution_context_id,
                    utility_context_id=parent.utility_context_id,
                    children_frame_ids=updated_children,
                    attached_at=parent.attached_at,
                    navigated_at=parent.navigated_at,
                )
            logger.debug(f"Frame attached: ID={frame_id}, Parent={parent_id}")

    def _on_frame_navigated(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        raw_frame = params.get("frame", {})
        frame_id = raw_frame.get("id", "")
        if not frame_id:
            return

        parent_id = raw_frame.get("parentId")
        url = raw_frame.get("url", "")
        loader_id = raw_frame.get("loaderId", "")
        security_origin = raw_frame.get("securityOrigin", "")
        is_root = (parent_id is None) or (frame_id == self._root_frame_id)

        if is_root:
            self._root_frame_id = frame_id
            # HARD BOUNDARY: Top-level navigation advances observation epoch
            new_epoch = self.reference_registry.invalidate_for_navigation(url)
            logger.info(f"Top-level frame navigated: {url} -> advanced to epoch {new_epoch}")

            # Invalidate all child frames on document replacement
            to_remove = [fid for fid, f in self._frames.items() if fid != frame_id]
            for fid in to_remove:
                self._frames.pop(fid, None)

            # Clear context mapping for removed frames
            self._context_to_frame.clear()
        else:
            new_epoch = self.reference_registry.current_epoch
            logger.debug(f"Child frame navigated: ID={frame_id} -> {url}")

        existing = self._frames.get(frame_id)
        children = existing.children_frame_ids if existing and not is_root else ()

        context = FrameContext(
            frame_id=frame_id,
            parent_frame_id=parent_id,
            loader_id=loader_id,
            url=url,
            security_origin=security_origin,
            name=raw_frame.get("name"),
            mime_type=raw_frame.get("mimeType"),
            lifecycle_state=FrameLifecycleState.NAVIGATED,
            is_root=is_root,
            is_out_of_process=False,
            is_accessible=True,
            children_frame_ids=children,
            attached_at=existing.attached_at if existing else time.time(),
            navigated_at=time.time(),
        )
        self._frames[frame_id] = context

        for cb in self._navigation_callbacks:
            try:
                cb(context, new_epoch)
            except Exception as e:
                logger.error(f"Error in navigation callback: {e}")

    def _on_frame_detached(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        frame_id = params.get("frameId", "")
        reason = params.get("reason", "remove")

        if frame_id in self._frames:
            old = self._frames[frame_id]
            detached = FrameContext(
                frame_id=old.frame_id,
                parent_frame_id=old.parent_frame_id,
                loader_id=old.loader_id,
                url=old.url,
                security_origin=old.security_origin,
                name=old.name,
                mime_type=old.mime_type,
                lifecycle_state=FrameLifecycleState.DETACHED,
                is_root=old.is_root,
                is_out_of_process=old.is_out_of_process,
                is_accessible=False,
                access_restriction="DETACHED",
                execution_context_id=None,
                utility_context_id=None,
                children_frame_ids=(),
                attached_at=old.attached_at,
                navigated_at=old.navigated_at,
            )
            self._frames[frame_id] = detached
            logger.debug(f"Frame detached: ID={frame_id} ({reason})")

    # -------------------------------------------------------------------------
    # 3. Execution Context Event Handlers
    # -------------------------------------------------------------------------
    def _on_execution_context_created(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        ctx = params.get("context", {})
        ctx_id = ctx.get("id")
        aux_data = ctx.get("auxData", {})
        frame_id = aux_data.get("frameId")
        is_default = aux_data.get("isDefault", False)
        ctx_type = aux_data.get("type", "default")

        if ctx_id and frame_id:
            self._context_to_frame[ctx_id] = frame_id
            is_utility = (ctx_type == "isolated" or "__utility_world__" in ctx.get("name", ""))

            if frame_id in self._frames:
                old = self._frames[frame_id]
                updated = FrameContext(
                    frame_id=old.frame_id,
                    parent_frame_id=old.parent_frame_id,
                    loader_id=old.loader_id,
                    url=old.url,
                    security_origin=old.security_origin,
                    name=old.name,
                    mime_type=old.mime_type,
                    lifecycle_state=old.lifecycle_state,
                    is_root=old.is_root,
                    is_out_of_process=old.is_out_of_process,
                    is_accessible=old.is_accessible,
                    access_restriction=old.access_restriction,
                    execution_context_id=old.execution_context_id if is_utility else ctx_id,
                    utility_context_id=ctx_id if is_utility else old.utility_context_id,
                    children_frame_ids=old.children_frame_ids,
                    attached_at=old.attached_at,
                    navigated_at=old.navigated_at,
                )
                self._frames[frame_id] = updated
            else:
                is_root = (self._root_frame_id is None or self._root_frame_id == frame_id)
                if self._root_frame_id is None:
                    self._root_frame_id = frame_id
                self._frames[frame_id] = FrameContext(
                    frame_id=frame_id,
                    parent_frame_id=None,
                    loader_id="",
                    url="about:blank",
                    security_origin="",
                    lifecycle_state=FrameLifecycleState.ATTACHED,
                    is_root=is_root,
                    execution_context_id=None if is_utility else ctx_id,
                    utility_context_id=ctx_id if is_utility else None,
                )
            logger.debug(f"Execution context {ctx_id} created for frame {frame_id} (utility={is_utility})")

    def _on_execution_context_destroyed(self, event: Dict[str, Any]) -> None:
        params = event.get("params", {})
        ctx_id = params.get("executionContextId")
        if ctx_id:
            frame_id = self._context_to_frame.pop(ctx_id, None)
            if frame_id and frame_id in self._frames:
                old = self._frames[frame_id]
                updated = FrameContext(
                    frame_id=old.frame_id,
                    parent_frame_id=old.parent_frame_id,
                    loader_id=old.loader_id,
                    url=old.url,
                    security_origin=old.security_origin,
                    name=old.name,
                    mime_type=old.mime_type,
                    lifecycle_state=old.lifecycle_state,
                    is_root=old.is_root,
                    is_out_of_process=old.is_out_of_process,
                    is_accessible=old.is_accessible,
                    access_restriction=old.access_restriction,
                    execution_context_id=None if old.execution_context_id == ctx_id else old.execution_context_id,
                    utility_context_id=None if old.utility_context_id == ctx_id else old.utility_context_id,
                    children_frame_ids=old.children_frame_ids,
                    attached_at=old.attached_at,
                    navigated_at=old.navigated_at,
                )
                self._frames[frame_id] = updated
                logger.debug(f"Execution context {ctx_id} destroyed for frame {frame_id}")

    def _on_execution_contexts_cleared(self, event: Dict[str, Any]) -> None:
        self._context_to_frame.clear()
        for fid, old in list(self._frames.items()):
            self._frames[fid] = FrameContext(
                frame_id=old.frame_id,
                parent_frame_id=old.parent_frame_id,
                loader_id=old.loader_id,
                url=old.url,
                security_origin=old.security_origin,
                name=old.name,
                mime_type=old.mime_type,
                lifecycle_state=old.lifecycle_state,
                is_root=old.is_root,
                is_out_of_process=old.is_out_of_process,
                is_accessible=old.is_accessible,
                access_restriction=old.access_restriction,
                execution_context_id=None,
                utility_context_id=None,
                children_frame_ids=old.children_frame_ids,
                attached_at=old.attached_at,
                navigated_at=old.navigated_at,
            )
        logger.debug("All execution contexts cleared across target frames.")

    # -------------------------------------------------------------------------
    # 4. Frame Piercing & Context Resolution
    # -------------------------------------------------------------------------
    def get_frame(self, frame_id: str) -> FrameContext:
        """Retrieves a frame context by ID. Raises FrameNotFoundException if missing or detached."""
        if frame_id not in self._frames:
            raise FrameNotFoundException(frame_id)
        frame = self._frames[frame_id]
        if frame.lifecycle_state == FrameLifecycleState.DETACHED:
            raise FrameDetachedException(frame_id)
        return frame

    def get_reachable_frames(self) -> List[FrameContext]:
        """Returns all reachable non-detached frames in the hierarchy."""
        return [
            f for f in self._frames.values()
            if f.lifecycle_state != FrameLifecycleState.DETACHED
        ]

    def get_accessible_frames(self) -> List[FrameContext]:
        """Returns frames where DOM inspection/evaluation is not restricted by security boundaries."""
        return [
            f for f in self._frames.values()
            if f.lifecycle_state != FrameLifecycleState.DETACHED and f.is_accessible
        ]

    def verify_frame_accessible(self, frame_id: str) -> FrameContext:
        """Verifies that frame exists, is attached, and accessible."""
        frame = self.get_frame(frame_id)
        if not frame.is_accessible:
            raise CrossDomainFrameAccessException(frame.frame_id, frame.security_origin)
        return frame

    def resolve_execution_context(self, frame_id: Optional[str] = None, use_utility_world: bool = True) -> int:
        """
        Resolves the appropriate execution context ID for a frame.
        If use_utility_world is True, returns utility_context_id; else returns execution_context_id.
        Raises ExecutionContextDestroyedException if context is unavailable.
        """
        target_id = frame_id or self._root_frame_id
        if not target_id:
            raise FrameNotFoundException("No active root frame available")

        frame = self.get_frame(target_id)
        ctx_id = frame.utility_context_id if use_utility_world else frame.execution_context_id
        if not ctx_id:
            raise ExecutionContextDestroyedException(
                0,
                f"No {'utility' if use_utility_world else 'main'} execution context available for frame '{target_id}'",
            )
        return ctx_id

    def set_utility_context_id(self, frame_id: str, context_id: int) -> None:
        """Manually records an isolated utility world execution context ID for a frame."""
        if frame_id in self._frames:
            old = self._frames[frame_id]
            self._frames[frame_id] = FrameContext(
                frame_id=old.frame_id,
                parent_frame_id=old.parent_frame_id,
                loader_id=old.loader_id,
                url=old.url,
                security_origin=old.security_origin,
                name=old.name,
                mime_type=old.mime_type,
                lifecycle_state=old.lifecycle_state,
                is_root=old.is_root,
                is_out_of_process=old.is_out_of_process,
                is_accessible=old.is_accessible,
                access_restriction=old.access_restriction,
                execution_context_id=old.execution_context_id,
                utility_context_id=context_id,
                children_frame_ids=old.children_frame_ids,
                attached_at=old.attached_at,
                navigated_at=old.navigated_at,
            )
            self._context_to_frame[context_id] = frame_id
