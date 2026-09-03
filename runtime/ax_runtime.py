"""
Accessibility Runtime Foundation and Lazy Accessibility Freeze Detection (SP-02).
Provides controlled accessibility domain priming, full AX tree snapshot acquisition,
and automated detection and recovery for un-materialized or frozen Chromium accessibility states.
"""

from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from runtime.state import AXFreshnessStatus
from runtime.cdp_transport import ICDPTransport
from runtime.errors import AXFreezeDetectedException, CDPProtocolException

logger = logging.getLogger("desktop_webview.ax_runtime")


@dataclass(frozen=True)
class AXNodeInfo:
    """Parsed representation of a Chromium CDP Accessibility node."""
    node_id: str
    role: str
    name: Optional[str] = None
    value: Optional[str] = None
    description: Optional[str] = None
    ignored: bool = False
    backend_node_id: Optional[int] = None
    child_ids: Tuple[str, ...] = field(default_factory=tuple)
    parent_id: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "name": self.name,
            "value": self.value,
            "description": self.description,
            "ignored": self.ignored,
            "backend_node_id": self.backend_node_id,
            "child_ids": list(self.child_ids),
            "parent_id": self.parent_id,
            "properties": self.properties,
        }


@dataclass(frozen=True)
class AXSnapshot:
    """Immutable snapshot of the Chromium accessibility tree."""
    nodes: List[AXNodeInfo]
    node_count: int
    dom_element_count: Optional[int]
    ratio: Optional[float]
    freshness: AXFreshnessStatus
    captured_at: float
    loader_id: str
    epoch: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_count": self.node_count,
            "dom_element_count": self.dom_element_count,
            "ratio": self.ratio,
            "freshness": self.freshness.value,
            "captured_at": self.captured_at,
            "loader_id": self.loader_id,
            "epoch": self.epoch,
            "nodes_sample": [n.to_dict() for n in self.nodes[:5]],
        }


class AccessibilityRuntime:
    """
    Manages Chromium DevTools Protocol Accessibility domain inspection.
    Responsibilities:
    1. Controlled priming: enables Accessibility domain once per target session.
    2. Snapshot acquisition: queries Accessibility.getFullAXTree.
    3. Freeze detection (SP-02): calculates AX / DOM ratio to diagnose FRESH vs SUSPECTED_STALE.
    4. Self-healing recovery: disable/enable cycling and double-rAF layout flushes.
    """

    def __init__(
        self,
        transport: ICDPTransport,
        session_id: str,
        target_session_id: Optional[str] = None,
    ):
        self.transport = transport
        self.session_id = session_id
        self.target_session_id = target_session_id
        self._is_enabled = False
        self._last_snapshot: Optional[AXSnapshot] = None
        self._lock = asyncio.Lock()

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @property
    def last_snapshot(self) -> Optional[AXSnapshot]:
        return self._last_snapshot

    async def enable(self) -> None:
        """Enables the Accessibility domain if not already active."""
        async with self._lock:
            if self._is_enabled:
                return
            try:
                await self.transport.send_command(
                    "Accessibility.enable",
                    session_id=self.target_session_id,
                )
                self._is_enabled = True
                logger.debug(f"Accessibility domain enabled for session {self.session_id}")
            except Exception as e:
                logger.warning(f"Accessibility.enable failed: {e}")
                raise

    async def disable(self) -> None:
        """Disables the Accessibility domain."""
        async with self._lock:
            if not self._is_enabled:
                return
            try:
                await self.transport.send_command(
                    "Accessibility.disable",
                    session_id=self.target_session_id,
                )
                self._is_enabled = False
                logger.debug(f"Accessibility domain disabled for session {self.session_id}")
            except Exception as e:
                logger.debug(f"Accessibility.disable error: {e}")

    async def acquire_snapshot(
        self,
        loader_id: str = "",
        epoch: int = 1,
        dom_element_count: Optional[int] = None,
        max_depth: Optional[int] = None,
    ) -> AXSnapshot:
        """
        Acquires full accessibility tree snapshot and evaluates freshness.
        """
        await self.enable()

        params: Dict[str, Any] = {}
        if max_depth is not None:
            params["depth"] = max_depth

        t0 = time.perf_counter()
        resp = await self.transport.send_command(
            "Accessibility.getFullAXTree",
            params=params,
            session_id=self.target_session_id,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        raw_nodes = resp.get("nodes", [])
        parsed_nodes: List[AXNodeInfo] = []

        for item in raw_nodes:
            node_id = str(item.get("nodeId", ""))
            raw_role = item.get("role", {})
            role = raw_role.get("value", "") if isinstance(raw_role, dict) else str(raw_role)
            raw_name = item.get("name", {})
            name = raw_name.get("value") if isinstance(raw_name, dict) else None
            raw_val = item.get("value", {})
            val = raw_val.get("value") if isinstance(raw_val, dict) else None
            raw_desc = item.get("description", {})
            desc = raw_desc.get("value") if isinstance(raw_desc, dict) else None

            parsed_nodes.append(
                AXNodeInfo(
                    node_id=node_id,
                    role=role,
                    name=name,
                    value=val,
                    description=desc,
                    ignored=item.get("ignored", False),
                    backend_node_id=item.get("backendDOMNodeId"),
                    child_ids=tuple(str(cid) for cid in item.get("childIds", [])),
                    parent_id=str(item.get("parentId")) if "parentId" in item else None,
                    properties={p.get("name"): p.get("value", {}).get("value") for p in item.get("properties", [])},
                )
            )

        ax_count = len(parsed_nodes)
        ratio: Optional[float] = None
        freshness = AXFreshnessStatus.UNKNOWN

        if dom_element_count is not None and dom_element_count > 0:
            ratio = round(ax_count / dom_element_count, 4)
            # SP-02 Diagnostic thresholds:
            # 1. AX is 0 while DOM > 0 -> SUSPECTED_STALE / unmaterialized
            # 2. Ratio < 0.1 -> SUSPECTED_STALE
            if ax_count == 0 or ratio < 0.1:
                freshness = AXFreshnessStatus.SUSPECTED_STALE
            else:
                freshness = AXFreshnessStatus.FRESH
        elif ax_count > 0:
            freshness = AXFreshnessStatus.FRESH

        snapshot = AXSnapshot(
            nodes=parsed_nodes,
            node_count=ax_count,
            dom_element_count=dom_element_count,
            ratio=ratio,
            freshness=freshness,
            captured_at=time.time(),
            loader_id=loader_id,
            epoch=epoch,
        )

        self._last_snapshot = snapshot
        logger.debug(
            f"AX snapshot captured: {ax_count} nodes in {elapsed_ms:.2f}ms (freshness: {freshness.value})"
        )
        return snapshot

    async def recover_freeze(
        self,
        loader_id: str = "",
        epoch: int = 1,
        dom_element_count: Optional[int] = None,
    ) -> AXSnapshot:
        """
        Executes the SP-02 validated freeze recovery procedure:
        1. Cycle Accessibility.disable -> Accessibility.enable (resets Blink AX cache in <2ms).
        2. Flush pending layout through two consecutive requestAnimationFrame cycles via Runtime.evaluate.
        3. Re-query Accessibility.getFullAXTree.
        """
        logger.warning("Executing SP-02 Accessibility freeze recovery cycle...")

        # Step 1: Rapid cycle disable/enable
        await self.disable()
        await asyncio.sleep(0.01)
        await self.enable()

        # Step 2: Double rAF layout flush
        flush_script = """
        new Promise(resolve => {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    resolve(document.querySelectorAll('*').length);
                });
            });
        })
        """
        try:
            dom_count_result = await self.transport.send_command(
                "Runtime.evaluate",
                params={"expression": flush_script, "awaitPromise": True, "returnByValue": True},
                session_id=self.target_session_id,
                timeout=2.0,
            )
            detected_dom = dom_count_result.get("result", {}).get("value")
            if isinstance(detected_dom, int) and detected_dom > 0:
                dom_element_count = detected_dom
        except Exception as e:
            logger.debug(f"Layout flush evaluation encountered: {e}")

        # Step 3: Re-acquire AX tree
        fresh_snapshot = await self.acquire_snapshot(
            loader_id=loader_id,
            epoch=epoch,
            dom_element_count=dom_element_count,
        )

        logger.info(
            f"Recovery complete: AX nodes={fresh_snapshot.node_count}, DOM={dom_element_count}, status={fresh_snapshot.freshness.value}"
        )
        return fresh_snapshot
