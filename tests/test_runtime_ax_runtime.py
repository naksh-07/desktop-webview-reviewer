"""
Unit tests for runtime/ax_runtime.py.
Validates Accessibility domain priming, AX tree snapshot acquisition,
SP-02 freeze suspicion detection (ratio < 0.1, AX=0 while DOM>0), and recovery procedures.
"""

import unittest

from runtime.cdp_transport import MockCDPTransport
from runtime.ax_runtime import AccessibilityRuntime, AXSnapshot
from runtime.state import AXFreshnessStatus


class TestAccessibilityRuntime(unittest.IsolatedAsyncioTestCase):
    """Test suite for Chromium Accessibility domain runtime and freeze detection."""

    async def asyncSetUp(self):
        self.transport = MockCDPTransport()
        await self.transport.connect()
        self.ax_runtime = AccessibilityRuntime(transport=self.transport, session_id="test_sess_ax")

    async def asyncTearDown(self):
        await self.transport.disconnect()

    async def test_enable_disable_domain(self):
        """Verifies Accessibility.enable and disable lifecycle."""
        self.assertFalse(self.ax_runtime.is_enabled)
        await self.ax_runtime.enable()
        self.assertTrue(self.ax_runtime.is_enabled)

        # Idempotent enable
        await self.ax_runtime.enable()
        self.assertTrue(self.ax_runtime.is_enabled)

        await self.ax_runtime.disable()
        self.assertFalse(self.ax_runtime.is_enabled)

    async def test_acquire_snapshot_fresh(self):
        """Verifies snapshot acquisition returns FRESH status when AX tree populated."""
        self.transport.register_handler("Accessibility.getFullAXTree", lambda p: {
            "nodes": [
                {
                    "nodeId": "1",
                    "role": {"value": "WebArea"},
                    "name": {"value": "Document Root"},
                    "childIds": ["2", "3"],
                },
                {
                    "nodeId": "2",
                    "role": {"value": "heading"},
                    "name": {"value": "Title"},
                },
                {
                    "nodeId": "3",
                    "role": {"value": "button"},
                    "name": {"value": "Submit"},
                },
            ]
        })

        snapshot = await self.ax_runtime.acquire_snapshot(
            loader_id="loader_test",
            epoch=1,
            dom_element_count=5,
        )

        self.assertEqual(snapshot.node_count, 3)
        self.assertEqual(snapshot.dom_element_count, 5)
        self.assertEqual(snapshot.ratio, 0.6)
        self.assertEqual(snapshot.freshness, AXFreshnessStatus.FRESH)
        self.assertEqual(len(snapshot.nodes), 3)
        self.assertEqual(snapshot.nodes[0].role, "WebArea")

    async def test_freeze_detection_zero_nodes(self):
        """Verifies zero AX nodes while DOM > 0 flags SUSPECTED_STALE."""
        self.transport.register_handler("Accessibility.getFullAXTree", lambda p: {"nodes": []})

        snapshot = await self.ax_runtime.acquire_snapshot(
            loader_id="loader_test",
            epoch=1,
            dom_element_count=20,
        )

        self.assertEqual(snapshot.node_count, 0)
        self.assertEqual(snapshot.freshness, AXFreshnessStatus.SUSPECTED_STALE)

    async def test_freeze_detection_ratio_below_threshold(self):
        """Verifies ratio < 0.1 flags SUSPECTED_STALE (unmaterialized tree)."""
        # 2 AX nodes vs 50 DOM elements -> ratio = 0.04
        self.transport.register_handler("Accessibility.getFullAXTree", lambda p: {
            "nodes": [
                {"nodeId": "1", "role": {"value": "WebArea"}},
                {"nodeId": "2", "role": {"value": "RootWebArea"}},
            ]
        })

        snapshot = await self.ax_runtime.acquire_snapshot(
            loader_id="loader_test",
            epoch=1,
            dom_element_count=50,
        )

        self.assertEqual(snapshot.node_count, 2)
        self.assertLess(snapshot.ratio, 0.1)
        self.assertEqual(snapshot.freshness, AXFreshnessStatus.SUSPECTED_STALE)

    async def test_recover_freeze_cycles_domain_and_flushes_layout(self):
        """Verifies recover_freeze cycles enable/disable, flushes layout, and re-queries AX tree."""
        query_count = 0

        def get_ax_tree(params):
            nonlocal query_count
            query_count += 1
            if query_count == 1:
                return {"nodes": []}  # Initial stale call
            return {
                "nodes": [
                    {"nodeId": "1", "role": {"value": "WebArea"}},
                    {"nodeId": "2", "role": {"value": "button"}, "name": {"value": "Refreshed"}},
                ]
            }

        self.transport.register_handler("Accessibility.getFullAXTree", get_ax_tree)
        self.transport.register_handler("Runtime.evaluate", lambda p: {"result": {"value": 2}})

        # Initial snapshot before recovery
        initial = await self.ax_runtime.acquire_snapshot(
            loader_id="loader_test",
            epoch=1,
            dom_element_count=2,
        )
        self.assertEqual(initial.node_count, 0)
        self.assertEqual(initial.freshness, AXFreshnessStatus.SUSPECTED_STALE)

        # Execute recovery
        recovered = await self.ax_runtime.recover_freeze(
            loader_id="loader_test",
            epoch=1,
            dom_element_count=2,
        )

        self.assertEqual(recovered.node_count, 2)
        self.assertEqual(recovered.freshness, AXFreshnessStatus.FRESH)
        self.assertEqual(query_count, 2)


if __name__ == "__main__":
    unittest.main()
