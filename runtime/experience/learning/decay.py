"""
Knowledge Decay & Revalidation Engine.
Architecture H / Milestone 2.1 Prompt 4.

Implements bounded knowledge decay:
- Durable knowledge must not remain permanently authoritative.
- Tracks review due dates, last confirmed/used timestamps, and contradiction counts.
- Executes deterministic transitions:
  DURABLE -> REVIEW_DUE -> STALE -> SUPERSEDED / REVALIDATED
- Preserves historical evidence permanently in the forensic ledger.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from runtime.experience.learning.models import (
    DurableKnowledgeRecord,
    KnowledgeStatus,
)

logger = logging.getLogger("desktop_webview.experience.learning.decay")

# Grace period after review_due_at before transitioning REVIEW_DUE -> STALE: 30 days
STALENESS_GRACE_PERIOD_DAYS = 30
MAX_CONTRADICTION_TOLERANCE = 3


class KnowledgeDecayEngine:
    """
    Evaluates knowledge freshness and enforces deterministic staleness transitions.
    Never erases historical records.
    """

    def __init__(self, store: Optional[Any] = None) -> None:
        if store is None:
            from runtime.experience.store import ExperienceStore
            self.store = ExperienceStore.get_default_store()
        else:
            self.store = store

    def evaluate_staleness(self, reference_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Scans durable knowledge in store and classifies active, review_due, and stale items.
        """
        records = self.store.get_durable_knowledge(limit=500)
        active = []
        review_due = []
        stale = []
        ref_time = reference_time or datetime.now(timezone.utc)

        for rec in records:
            _, updated_rec = self.evaluate_knowledge(rec, reference_time=ref_time)
            item_summary = {
                "knowledge_id": updated_rec.knowledge_id,
                "statement": updated_rec.normalized_statement[:80],
                "status": updated_rec.status.value,
                "review_due": updated_rec.review_due_at,
            }
            if updated_rec.status == KnowledgeStatus.STALE:
                stale.append(item_summary)
            elif updated_rec.status == KnowledgeStatus.REVIEW_DUE:
                review_due.append(item_summary)
            else:
                active.append(item_summary)

        return {
            "active": active,
            "review_due": review_due,
            "stale": stale,
        }

    def apply_decay_transitions(self, reference_time: Optional[datetime] = None) -> Dict[str, int]:
        """
        Evaluates and persists state transitions (e.g. DURABLE -> REVIEW_DUE -> STALE).
        """
        records = self.store.get_durable_knowledge(limit=500)
        counts = {"review_due": 0, "stale": 0, "unchanged": 0}
        ref_time = reference_time or datetime.now(timezone.utc)

        for rec in records:
            changed, updated_rec = self.evaluate_knowledge(rec, reference_time=ref_time)
            if changed:
                self.store.record_durable_knowledge(updated_rec)
                if updated_rec.status == KnowledgeStatus.STALE:
                    counts["stale"] += 1
                elif updated_rec.status == KnowledgeStatus.REVIEW_DUE:
                    counts["review_due"] += 1
            else:
                counts["unchanged"] += 1

        return counts

    @classmethod
    def evaluate_knowledge(
        cls,
        knowledge: DurableKnowledgeRecord,
        reference_time: Optional[datetime] = None,
        new_contradictions: int = 0,
    ) -> Tuple[bool, DurableKnowledgeRecord]:
        """
        Evaluates a DurableKnowledgeRecord against staleness criteria.
        Returns (state_changed, updated_knowledge).
        """
        if knowledge.status in (KnowledgeStatus.SUPERSEDED, KnowledgeStatus.RETIRED):
            return False, knowledge

        ref_time = reference_time or datetime.now(timezone.utc)
        original_status = knowledge.status

        # Accumulate contradictions
        if new_contradictions > 0:
            knowledge.contradiction_count += new_contradictions

        # Check contradiction-based staleness
        if knowledge.contradiction_count > MAX_CONTRADICTION_TOLERANCE:
            knowledge.status = KnowledgeStatus.STALE
            knowledge.updated_at = ref_time.isoformat()
            logger.warning(
                "Knowledge %s transitioned to STALE due to excessive contradictions (%d)",
                knowledge.knowledge_id,
                knowledge.contradiction_count,
            )
            return True, knowledge

        # Check time-based review_due_at
        if knowledge.review_due_at:
            try:
                due_dt = datetime.fromisoformat(knowledge.review_due_at)
                if ref_time >= due_dt:
                    # Past review due date: check if grace period expired
                    stale_dt = due_dt + timedelta(days=STALENESS_GRACE_PERIOD_DAYS)
                    if ref_time >= stale_dt:
                        knowledge.status = KnowledgeStatus.STALE
                        logger.info(
                            "Knowledge %s transitioned to STALE (past grace period: %s)",
                            knowledge.knowledge_id,
                            stale_dt.isoformat(),
                        )
                    else:
                        knowledge.status = KnowledgeStatus.REVIEW_DUE
                        logger.info(
                            "Knowledge %s transitioned to REVIEW_DUE (due: %s)",
                            knowledge.knowledge_id,
                            due_dt.isoformat(),
                        )
            except ValueError:
                pass

        state_changed = knowledge.status != original_status
        if state_changed:
            knowledge.updated_at = ref_time.isoformat()

        return state_changed, knowledge

    @classmethod
    def revalidate_knowledge(
        cls,
        knowledge: DurableKnowledgeRecord,
        reviewer: str,
        rationale: str,
        ttl_days: int = 90,
    ) -> DurableKnowledgeRecord:
        """
        Explicitly revalidates a REVIEW_DUE or STALE knowledge record.
        Resets review_due_at and transitions status back to DURABLE.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        knowledge.status = KnowledgeStatus.DURABLE
        knowledge.version += 1
        knowledge.last_confirmed_at = now_iso
        knowledge.updated_at = now_iso
        knowledge.review_due_at = (now + timedelta(days=ttl_days)).isoformat()
        knowledge.contradiction_count = 0

        # Append revalidation audit entry
        reval_audit = knowledge.approval_metadata.setdefault("revalidations", [])
        reval_audit.append({
            "version": knowledge.version,
            "reviewer": reviewer,
            "rationale": rationale,
            "timestamp": now_iso,
        })

        logger.info("Knowledge %s successfully revalidated by %s to v%d", knowledge.knowledge_id, reviewer, knowledge.version)
        return knowledge

    @classmethod
    def supersede_knowledge(
        cls,
        old_knowledge: DurableKnowledgeRecord,
        superseded_by_id: str,
    ) -> DurableKnowledgeRecord:
        """
        Marks an existing knowledge item as SUPERSEDED by a newer knowledge item.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        old_knowledge.status = KnowledgeStatus.SUPERSEDED
        old_knowledge.superseded_by = superseded_by_id
        old_knowledge.updated_at = now_iso
        logger.info("Knowledge %s marked SUPERSEDED by %s", old_knowledge.knowledge_id, superseded_by_id)
        return old_knowledge
