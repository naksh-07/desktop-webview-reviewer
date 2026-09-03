"""
Observation Tree Pagination Engine.
Provides deterministic, bounded pagination over large observation collections with
cryptographically safe, epoch-scoped cursor invalidation.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional, Any, Tuple

from runtime.references import ReferenceRegistry
from runtime.observation_models import WebElementObservation, NativeElementObservation
from runtime.errors import StaleReferenceException

logger = logging.getLogger("desktop_webview.observation_pagination")


class ObservationPaginator:
    """
    Paginates element collections using epoch-scoped, session-scoped cursors.
    Guarantees that cursors from superseded epochs immediately raise StaleReferenceException.
    """

    def __init__(self, reference_registry: ReferenceRegistry):
        self.reference_registry = reference_registry

    def paginate_web_elements(
        self,
        elements: List[WebElementObservation],
        page_size: int = 25,
        cursor: Optional[str] = None,
        target_id: str = "",
        frame_id: str = "",
    ) -> Tuple[List[WebElementObservation], Optional[str], Dict[str, Any]]:
        """
        Paginates a list of WebElementObservation items.
        Returns (page_elements, next_cursor, pagination_metadata).
        """
        page = 1
        current_epoch = self.reference_registry.current_epoch

        if cursor:
            # Validate cursor against active epoch
            payload = self.reference_registry.validate_cursor(cursor)
            cursor_epoch = payload.get("epoch")
            if cursor_epoch != current_epoch:
                raise StaleReferenceException(
                    ref_id=f"cursor_epoch_{cursor_epoch}",
                    current_epoch=current_epoch,
                    ref_epoch=cursor_epoch,
                )
            page = int(payload.get("page", 1))

        if page_size < 1:
            page_size = 25

        total_items = len(elements)
        start_idx = (page - 1) * page_size
        end_idx = min(start_idx + page_size, total_items)

        if start_idx >= total_items:
            page_elements = []
        else:
            page_elements = elements[start_idx:end_idx]

        has_more = end_idx < total_items
        next_cursor = None
        if has_more:
            next_cursor = self.reference_registry.create_cursor(
                target_id=target_id,
                frame_id=frame_id,
                page=page + 1,
                page_size=page_size,
            )

        meta = {
            "epoch": current_epoch,
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": max(1, (total_items + page_size - 1) // page_size),
            "has_more": has_more,
        }

        return page_elements, next_cursor, meta
