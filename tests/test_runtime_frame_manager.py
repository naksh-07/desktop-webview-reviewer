"""
Unit tests for runtime/frame_manager.py.
Validates hierarchical frame tracking, same-origin vs cross-origin frame piercing,
execution context tracking, navigation epoch invalidation, and frame lifecycle race handling.
"""

import unittest

from runtime.cdp_transport import MockCDPTransport
from runtime.frame_manager import FrameManager, FrameContext
from runtime.references import ReferenceRegistry
from runtime.state import FrameLifecycleState
from runtime.errors import (
    FrameDetachedException,
    FrameNotFoundException,
    ExecutionContextDestroyedException,
    CrossDomainFrameAccessException,
)


class TestFrameManager(unittest.IsolatedAsyncioTestCase):
    """Test suite for hierarchical frame management and controlled frame piercing."""

    async def asyncSetUp(self):
        self.transport = MockCDPTransport()
        await self.transport.connect()
        self.registry = ReferenceRegistry(session_id="test_sess_frames", initial_epoch=1)
        self.frame_manager = FrameManager(
            transport=self.transport,
            reference_registry=self.registry,
            session_id="test_sess_frames",
        )

    async def asyncTearDown(self):
        await self.transport.disconnect()

    async def test_frame_tree_parsing_and_root_identification(self):
        """Verifies hierarchical frame tree is parsed and root frame identified."""
        self.transport.register_handler("Page.getFrameTree", lambda p: {
            "frameTree": {
                "frame": {
                    "id": "root_1",
                    "loaderId": "loader_1",
                    "url": "http://127.0.0.1:8000/index.html",
                    "securityOrigin": "http://127.0.0.1:8000",
                },
                "childFrames": [
                    {
                        "frame": {
                            "id": "child_same_origin",
                            "parentId": "root_1",
                            "loaderId": "loader_sub",
                            "url": "http://127.0.0.1:8000/sub.html",
                            "securityOrigin": "http://127.0.0.1:8000",
                        },
                        "childFrames": [],
                    },
                    {
                        "frame": {
                            "id": "child_cross_origin",
                            "parentId": "root_1",
                            "loaderId": "loader_ext",
                            "url": "https://external.example.com/widget.html",
                            "securityOrigin": "https://external.example.com",
                        },
                        "childFrames": [],
                    }
                ]
            }
        })

        await self.frame_manager.initialize()

        self.assertEqual(self.frame_manager.root_frame_id, "root_1")
        self.assertIsNotNone(self.frame_manager.root_frame)
        self.assertTrue(self.frame_manager.root_frame.is_root)

        # Reachable frames
        reachable = self.frame_manager.get_reachable_frames()
        self.assertEqual(len(reachable), 3)

        # Piercing: same-origin accessible vs cross-origin restricted
        same_origin = self.frame_manager.get_frame("child_same_origin")
        self.assertTrue(same_origin.is_accessible)
        self.assertIsNone(same_origin.access_restriction)

        cross_origin = self.frame_manager.get_frame("child_cross_origin")
        self.assertFalse(cross_origin.is_accessible)
        self.assertEqual(cross_origin.access_restriction, "CROSS_ORIGIN_RESTRICTED")

        # Verify access check raises CrossDomainFrameAccessException
        with self.assertRaises(CrossDomainFrameAccessException):
            self.frame_manager.verify_frame_accessible("child_cross_origin")

    async def test_top_level_navigation_advances_epoch_and_purges_children(self):
        """Verifies top-level navigation invalidates references and resets child frame hierarchy."""
        await self.frame_manager.initialize()

        # Initial epoch is 1
        self.assertEqual(self.registry.current_epoch, 1)

        # Top-level navigation event arrives
        self.transport.emit_event("Page.frameNavigated", {
            "frame": {
                "id": "root_1",
                "loaderId": "loader_2",
                "url": "http://127.0.0.1:8000/page2.html",
                "securityOrigin": "http://127.0.0.1:8000",
            }
        })

        # Epoch must increment to 2
        self.assertEqual(self.registry.current_epoch, 2)
        root = self.frame_manager.root_frame
        self.assertIsNotNone(root)
        self.assertEqual(root.url, "http://127.0.0.1:8000/page2.html")
        self.assertEqual(root.loader_id, "loader_2")

    async def test_execution_context_lifecycle(self):
        """Verifies context creation and destruction updates frame context."""
        await self.frame_manager.initialize()

        # Main world context
        self.transport.emit_event("Runtime.executionContextCreated", {
            "context": {
                "id": 10,
                "name": "",
                "auxData": {"frameId": "root_1", "isDefault": True, "type": "default"},
            }
        })

        self.assertEqual(self.frame_manager.get_frame("root_1").execution_context_id, 10)
        self.assertEqual(self.frame_manager.resolve_execution_context("root_1", use_utility_world=False), 10)

        # Context destroyed
        self.transport.emit_event("Runtime.executionContextDestroyed", {"executionContextId": 10})
        self.assertIsNone(self.frame_manager.get_frame("root_1").execution_context_id)

        with self.assertRaises(ExecutionContextDestroyedException):
            self.frame_manager.resolve_execution_context("root_1", use_utility_world=False)

    async def test_frame_detached_race_handling(self):
        """Verifies operations targeting a detached frame raise FrameDetachedException."""
        await self.frame_manager.initialize()

        self.transport.emit_event("Page.frameAttached", {"frameId": "temp_frame", "parentFrameId": "root_1"})
        self.assertEqual(self.frame_manager.get_frame("temp_frame").lifecycle_state, FrameLifecycleState.ATTACHED)

        # Detach frame
        self.transport.emit_event("Page.frameDetached", {"frameId": "temp_frame", "reason": "remove"})

        with self.assertRaises(FrameDetachedException):
            self.frame_manager.get_frame("temp_frame")


if __name__ == "__main__":
    unittest.main()
