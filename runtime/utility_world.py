"""
Utility World Manager for Desktop WebView Reviewer.
Provides an isolated JavaScript execution realm ('__utility_world__') via Page.createIsolatedWorld.
Guarantees helper scripts and diagnostics do not contaminate page globals or interfere
with the application's runtime JavaScript state.
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Dict, Optional, Any

from runtime.cdp_transport import ICDPTransport
from runtime.frame_manager import FrameManager, FrameContext
from runtime.errors import (
    ExecutionContextDestroyedException,
    FrameDetachedException,
    FrameNotFoundException,
    CDPProtocolException,
)

logger = logging.getLogger("desktop_webview.utility_world")

UTILITY_WORLD_NAME = "__utility_world__"


class UtilityWorldManager:
    """
    Manages isolated execution realms across webview frames.
    Responsibilities:
    1. Injects Page.createIsolatedWorld for specified frames.
    2. Caches and verifies executionContextId for the isolated world.
    3. Invalidates utility contexts when frames navigate or contexts are destroyed.
    4. Evaluates scripts inside the isolated realm with structured error unpacking.
    """

    def __init__(
        self,
        transport: ICDPTransport,
        frame_manager: FrameManager,
        session_id: str,
        target_session_id: Optional[str] = None,
        world_name: str = UTILITY_WORLD_NAME,
    ):
        self.transport = transport
        self.frame_manager = frame_manager
        self.session_id = session_id
        self.target_session_id = target_session_id
        self.world_name = world_name
        # frame_id -> executionContextId
        self._utility_contexts: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    def get_cached_context_id(self, frame_id: str) -> Optional[int]:
        """Returns currently known isolated world executionContextId for frame."""
        return self._utility_contexts.get(frame_id)

    async def ensure_utility_world(self, frame_id: Optional[str] = None) -> int:
        """
        Guarantees that an isolated utility world exists for the target frame.
        If a valid cached context ID exists, returns it; otherwise creates a fresh one.
        """
        target_frame_id = frame_id or self.frame_manager.root_frame_id
        if not target_frame_id:
            raise FrameNotFoundException("No active root frame available for utility world creation")

        # Verify frame is valid and attached
        frame = self.frame_manager.get_frame(target_frame_id)

        async with self._lock:
            # Check cached context
            cached = self._utility_contexts.get(target_frame_id)
            if cached is not None and frame.utility_context_id == cached:
                return cached

            # Create isolated world via CDP
            logger.debug(f"Creating isolated world '{self.world_name}' for frame {target_frame_id}")
            params = {
                "frameId": target_frame_id,
                "worldName": self.world_name,
                "grantUniveralAccess": True,
            }
            try:
                resp = await self.transport.send_command(
                    "Page.createIsolatedWorld",
                    params=params,
                    session_id=self.target_session_id,
                )
                ctx_id = resp.get("executionContextId")
                if not ctx_id:
                    raise ExecutionContextDestroyedException(
                        0,
                        f"Page.createIsolatedWorld failed to return executionContextId for frame '{target_frame_id}'",
                    )

                self._utility_contexts[target_frame_id] = ctx_id
                self.frame_manager.set_utility_context_id(target_frame_id, ctx_id)
                logger.info(f"Isolated world '{self.world_name}' created: Frame={target_frame_id} -> ContextId={ctx_id}")
                return ctx_id
            except Exception as e:
                logger.error(f"Failed to create isolated world for frame {target_frame_id}: {e}")
                raise

    async def evaluate(
        self,
        expression: str,
        frame_id: Optional[str] = None,
        return_by_value: bool = True,
        await_promise: bool = True,
        timeout: Optional[float] = None,
    ) -> Any:
        """
        Evaluates a JavaScript expression inside the isolated utility world.
        Unpacks Runtime.evaluate result and raises RuntimeError on JS exceptions.
        """
        ctx_id = await self.ensure_utility_world(frame_id=frame_id)

        params = {
            "expression": expression,
            "contextId": ctx_id,
            "returnByValue": return_by_value,
            "awaitPromise": await_promise,
        }

        try:
            result = await self.transport.send_command(
                "Runtime.evaluate",
                params=params,
                session_id=self.target_session_id,
                timeout=timeout,
            )
        except CDPProtocolException as e:
            # If context was destroyed mid-flight, clear cache and retry once
            if "Cannot find context with specified id" in e.message or e.error_code == -32000:
                logger.warning(f"Context {ctx_id} invalidated during evaluation. Recreating utility world.")
                target_fid = frame_id or self.frame_manager.root_frame_id
                if target_fid:
                    self._utility_contexts.pop(target_fid, None)
                ctx_id = await self.ensure_utility_world(frame_id=frame_id)
                params["contextId"] = ctx_id
                result = await self.transport.send_command(
                    "Runtime.evaluate",
                    params=params,
                    session_id=self.target_session_id,
                    timeout=timeout,
                )
            else:
                raise

        if "exceptionDetails" in result:
            exc = result["exceptionDetails"]
            text = exc.get("text", "JavaScript execution error in utility world")
            if "exception" in exc and "description" in exc["exception"]:
                text = f"{text}: {exc['exception']['description']}"
            raise RuntimeError(text)

        res_obj = result.get("result", {})
        if return_by_value:
            return res_obj.get("value")
        return res_obj

    def invalidate_frame_contexts(self, frame_id: Optional[str] = None) -> None:
        """Clears cached utility context ID for a frame or all frames."""
        if frame_id:
            self._utility_contexts.pop(frame_id, None)
        else:
            self._utility_contexts.clear()
