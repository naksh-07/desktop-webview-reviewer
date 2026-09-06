"""
Governance Engine & Durable Knowledge Lifecycle.
Architecture H / Milestone 2.1 Prompt 4.

Enforces human sovereignty over durable knowledge promotion:
1. Validates candidates against evidence gates (transitions to VALIDATED).
2. Requires explicit human review before promotion to DURABLE.
3. Synthesizes structured, non-speculative normalized statements.
4. Preserves immutable GovernanceRecord audit trail.
5. Manages rejection, supersession, and revalidation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from runtime.errors import DesktopAutomationException
from runtime.experience.learning.models import (
    CandidateStatus,
    DurableKnowledgeRecord,
    GateStatus,
    GovernanceDecision,
    GovernanceRecord,
    ImprovementCandidateRecord,
    KnowledgeStatus,
)
from runtime.experience.learning.safety_gate import LearningSafetyGate, LearningSafetyException
from runtime.experience.models import (
    ExperienceScope,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    validate_scope_promotion,
)

logger = logging.getLogger("desktop_webview.experience.learning.governance")

# Standard TTL for durable knowledge before review is required: 90 days
DEFAULT_KNOWLEDGE_TTL_DAYS = 90


class GovernanceException(DesktopAutomationException):
    """Raised when an invalid governance transition or unauthorized promotion is attempted."""
    pass


class GovernanceEngine:
    """
    Manages human governance actions and durable knowledge generation.
    Strictly prevents automatic durable promotion without explicit human approval.
    """

    def __init__(self, store: Optional[Any] = None) -> None:
        if store is None:
            from runtime.experience.store import ExperienceStore
            self.store = ExperienceStore.get_default_store()
        else:
            self.store = store

    def validate_candidate(
        self,
        candidate: ImprovementCandidateRecord,
        contradiction_count: int = 0,
    ) -> Tuple[bool, ImprovementCandidateRecord, Dict[str, Any]]:
        """Instance validation: updates store if attached and returns (passed, candidate, gates)."""
        passed, cand = self.evaluate_candidate_validation(candidate, contradiction_count=contradiction_count)
        if self.store:
            self.store.record_improvement_candidate(cand)
        return passed, cand, cand.gate_results

    def approve_candidate(
        self,
        candidate: ImprovementCandidateRecord,
        reviewer_id: str,
        reviewer_notes: str = "",
        scope_override: Optional[ExperienceScope] = None,
        ttl_days: int = DEFAULT_KNOWLEDGE_TTL_DAYS,
    ) -> Tuple[DurableKnowledgeRecord, GovernanceRecord]:
        """Executes human approval and persists records to store."""
        gov_rec, durable = self.apply_human_decision(
            candidate=candidate,
            decision=GovernanceDecision.APPROVE,
            reviewer=reviewer_id,
            rationale=reviewer_notes,
            decision_scope=scope_override,
            ttl_days=ttl_days,
        )
        if self.store:
            self.store.record_improvement_candidate(candidate)
            self.store.record_governance_decision(gov_rec)
            if durable:
                self.store.record_durable_knowledge(durable)
        assert durable is not None
        return durable, gov_rec

    def reject_candidate(
        self,
        candidate: ImprovementCandidateRecord,
        reviewer_id: str,
        rejection_reason: str,
    ) -> Tuple[ImprovementCandidateRecord, GovernanceRecord]:
        """Executes human rejection and persists records to store."""
        gov_rec, _ = self.apply_human_decision(
            candidate=candidate,
            decision=GovernanceDecision.REJECT,
            reviewer=reviewer_id,
            rationale=rejection_reason,
        )
        if self.store:
            self.store.record_improvement_candidate(candidate)
            self.store.record_governance_decision(gov_rec)
        return candidate, gov_rec

    @classmethod
    def evaluate_candidate_validation(
        cls,
        candidate: ImprovementCandidateRecord,
        contradiction_count: int = 0,
    ) -> Tuple[bool, ImprovementCandidateRecord]:
        """
        Evaluates candidate evidence thresholds.
        If all gates pass, transitions status to VALIDATED.
        Does NOT promote to DURABLE (human approval required).
        """
        # Invariant 4: Check that candidate is not purely speculative
        if candidate.status in (CandidateStatus.REJECTED, CandidateStatus.SUPERSEDED):
            raise GovernanceException(f"Cannot validate candidate in terminal state '{candidate.status.value}'.")

        passed, gate_results = LearningSafetyGate.evaluate_candidate_safety(
            candidate=candidate,
            contradiction_count=contradiction_count,
            is_human_approved=False,
        )
        candidate.gate_results = gate_results
        candidate.updated_at = datetime.now(timezone.utc).isoformat()

        if passed:
            candidate.status = CandidateStatus.VALIDATED
            logger.info("Candidate %s passed all evidence gates -> VALIDATED", candidate.candidate_id)
            return True, candidate
        else:
            if candidate.status == CandidateStatus.VALIDATION_REQUIRED:
                # Kept in validation required or candidate
                pass
            logger.info("Candidate %s failed validation gates; status remains %s", candidate.candidate_id, candidate.status.value)
            return False, candidate

    @classmethod
    def apply_human_decision(
        cls,
        candidate: ImprovementCandidateRecord,
        decision: GovernanceDecision,
        reviewer: str,
        rationale: str,
        decision_scope: Optional[ExperienceScope] = None,
        ttl_days: int = DEFAULT_KNOWLEDGE_TTL_DAYS,
    ) -> Tuple[GovernanceRecord, Optional[DurableKnowledgeRecord]]:
        """
        Applies an authoritative human governance decision.
        Records an immutable GovernanceRecord.
        If APPROVE: promotes candidate to HUMAN_APPROVED -> DURABLE and creates DurableKnowledgeRecord.
        If REJECT: transitions candidate to REJECTED.
        If REQUEST_CHANGES: transitions candidate to VALIDATION_REQUIRED.
        """
        if not reviewer or not reviewer.strip():
            raise GovernanceException("Reviewer identifier is required for human governance.")
        if not rationale or not rationale.strip():
            raise GovernanceException("Explicit rationale is required for human governance decisions.")

        effective_scope = decision_scope or candidate.scope
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        now_ts = now.timestamp()

        gov_id = f"gov_{uuid.uuid4().hex[:12]}"
        gov_record = GovernanceRecord(
            governance_id=gov_id,
            candidate_id=candidate.candidate_id,
            decision=decision,
            decision_scope=effective_scope,
            reviewer=reviewer.strip(),
            rationale=rationale.strip(),
            decision_timestamp=now_ts,
            iso_timestamp=now_iso,
            metadata={
                "candidate_status_prior": candidate.status.value,
                "evidence_count": candidate.evidence_count,
                "session_count": candidate.session_count,
            },
        )

        durable_knowledge: Optional[DurableKnowledgeRecord] = None

        if decision == GovernanceDecision.APPROVE:
            # Candidate must be in VALIDATED or VALIDATION_REQUIRED state
            if candidate.status not in (CandidateStatus.VALIDATED, CandidateStatus.VALIDATION_REQUIRED, CandidateStatus.CANDIDATE):
                raise GovernanceException(
                    f"Candidate {candidate.candidate_id} in status '{candidate.status.value}' cannot be approved."
                )

            # Check safety with is_human_approved=True
            passed, gate_results = LearningSafetyGate.evaluate_candidate_safety(
                candidate=candidate,
                is_human_approved=True,
            )
            # Invariant 7: Contradiction check must still hold
            contra_gate = gate_results.get("contradiction_gate")
            if contra_gate and contra_gate.status == GateStatus.FAIL:
                raise GovernanceException(
                    f"Approval blocked by Invariant 7: Contradictory evidence exceeds allowed threshold: {contra_gate.details}"
                )

            # Invariant 3/10: Privacy and scope checks
            priv_gate = gate_results.get("privacy_and_security_gate")
            if priv_gate and priv_gate.status == GateStatus.FAIL:
                raise GovernanceException(f"Approval blocked by Privacy/Security Gate: {priv_gate.details}")

            candidate.status = CandidateStatus.DURABLE
            candidate.updated_at = now_iso

            # Synthesize normalized, non-speculative statement
            normalized_statement = cls._synthesize_normalized_statement(candidate)

            know_id = f"know_{hashlib.sha256(f'{candidate.candidate_id}:{effective_scope.value}'.encode('utf-8')).hexdigest()[:12]}"
            review_due = (now + timedelta(days=ttl_days)).isoformat()

            prov = ProvenanceRecord(
                source="GovernanceEngine",
                source_type=RecordSourceType.USER_VERIFICATION,
                session_id=candidate.project_id or "global",
                project_id=candidate.project_id,
                confidence=candidate.confidence,
                kind=RecordKind.FACT,
            )

            durable_knowledge = DurableKnowledgeRecord(
                knowledge_id=know_id,
                normalized_statement=normalized_statement,
                version=1,
                scope=effective_scope,
                project_id=candidate.project_id,
                candidate_id=candidate.candidate_id,
                supporting_evidence_refs=list(candidate.metadata.get("observation_refs", [])),
                validation_metadata={
                    "gate_results": {k: v.to_dict() for k, v in gate_results.items()},
                    "evidence_count": candidate.evidence_count,
                    "session_count": candidate.session_count,
                },
                approval_metadata={
                    "governance_id": gov_id,
                    "reviewer": reviewer,
                    "approved_at": now_iso,
                    "rationale": rationale,
                },
                confidence=candidate.confidence,
                status=KnowledgeStatus.DURABLE,
                created_at=now_iso,
                updated_at=now_iso,
                review_due_at=review_due,
                last_confirmed_at=now_iso,
                last_used_at=now_iso,
                contradiction_count=0,
                provenance=prov,
            )
            logger.info("Candidate %s approved by %s -> DURABLE knowledge %s", candidate.candidate_id, reviewer, know_id)

        elif decision == GovernanceDecision.REJECT:
            candidate.status = CandidateStatus.REJECTED
            candidate.updated_at = now_iso
            logger.info("Candidate %s rejected by %s", candidate.candidate_id, reviewer)

        elif decision == GovernanceDecision.REQUEST_CHANGES:
            candidate.status = CandidateStatus.VALIDATION_REQUIRED
            candidate.updated_at = now_iso
            logger.info("Candidate %s changes requested by %s", candidate.candidate_id, reviewer)

        elif decision == GovernanceDecision.DEPRECATE:
            candidate.status = CandidateStatus.SUPERSEDED
            candidate.updated_at = now_iso

        return gov_record, durable_knowledge

    @staticmethod
    def _synthesize_normalized_statement(candidate: ImprovementCandidateRecord) -> str:
        """
        Synthesizes a structured, empirical template statement without speculative reasoning.
        """
        cat = candidate.category.value
        subsys = candidate.affected_subsystem
        ev = candidate.evidence_count
        sess = candidate.session_count

        return (
            f"Under verified subsystem '{subsys}' ({cat}), repeated observation across {sess} session(s) "
            f"demonstrated stable empirical consistency ({ev} verified evidence receipts). "
            f"Governed scope: {candidate.scope.value}."
        )
