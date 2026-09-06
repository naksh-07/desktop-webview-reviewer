"""
Observation Engine for Learning Subsystem.
Architecture H / Milestone 2.1 Prompt 4.

Derives compact, normalized, deterministic ObservationRecords on top of existing
Experience Store facts (NormalizedFailures, RecoveryAttempts, Outcomes, Agent Activity).
Preserves full provenance, derives stable signatures, and enforces payload boundaries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from runtime.experience.antigravity.models import AgentCorrectionRecord, AgentToolCallRecord
from runtime.experience.learning.models import (
    ObservationRecord,
    ObservationStatus,
    ObservationType,
)
from runtime.experience.learning.safety_gate import LearningSafetyGate
from runtime.experience.models import (
    ActionReferenceRecord,
    ExperienceScope,
    NormalizedFailureRecord,
    OutcomeRecord,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    RecoveryExperienceRecord,
)
from runtime.experience.normalization import FailureNormalizer

logger = logging.getLogger("desktop_webview.experience.learning.observation_engine")


class LearningObservationEngine:
    """
    Synthesizes normalized observations from authoritative Experience Store records.
    Never duplicates raw DOM/screenshot payloads; computes deterministic signatures.
    """

    def __init__(self, store: Optional[Any] = None) -> None:
        self.store = store

    def create_observation_from_failure(self, failure: NormalizedFailureRecord, project_id: Optional[str] = None) -> ObservationRecord:
        return self.derive_from_failure(failure, project_id=project_id)

    def create_observation_from_recovery(self, recovery: RecoveryExperienceRecord, project_id: Optional[str] = None) -> ObservationRecord:
        return self.derive_from_recovery(recovery, project_id=project_id)

    def create_observation_from_outcome(self, outcome: OutcomeRecord, project_id: Optional[str] = None) -> Optional[ObservationRecord]:
        return self.derive_from_outcome(outcome, project_id=project_id)

    def create_observation_from_tool_call(self, tool_call: AgentToolCallRecord, preceding_failure: Optional[NormalizedFailureRecord] = None, project_id: Optional[str] = None) -> Optional[ObservationRecord]:
        return self.derive_from_agent_tool_call(tool_call, preceding_failure=preceding_failure, project_id=project_id)

    def create_observation_from_correction(self, correction: AgentCorrectionRecord, related_failure: Optional[NormalizedFailureRecord] = None, project_id: Optional[str] = None) -> ObservationRecord:
        return self.derive_from_user_correction(correction, related_failure=related_failure, project_id=project_id)

    @classmethod
    def derive_from_failure(
        cls,
        failure: NormalizedFailureRecord,
        project_id: Optional[str] = None,
    ) -> ObservationRecord:
        """
        Derives an observation from a normalized failure record using its stable signature.
        """
        obs_id = f"obs_fail_{uuid.uuid4().hex[:12]}"
        safe_ctx = dict(failure.safe_context or {})
        clean_ctx = LearningSafetyGate.validate_learning_payload(safe_ctx, context="observation.failure")

        # Reuse existing stable failure signature from FailureNormalizer
        sig = failure.signature or FailureNormalizer.compute_signature(
            category=failure.category,
            action_type=clean_ctx.get("action_type"),
            plane=clean_ctx.get("plane"),
            target_role_or_class=clean_ctx.get("target_role") or clean_ctx.get("target_class"),
        )

        obs_type = (
            ObservationType.TARGET_RESOLUTION_FAILURE
            if failure.category in ("TARGET_NOT_FOUND", "TARGET_NOT_ACTIONABLE", "TARGET_OCCLUDED", "TARGET_OFFSCREEN")
            else ObservationType.FAILURE_SIGNATURE
        )
        obs_id = f"obs_fail_{hashlib.sha256(f'{obs_type.value}:{sig}'.encode()).hexdigest()[:12]}"

        provenance = ProvenanceRecord(
            source="LearningObservationEngine",
            source_type=RecordSourceType.RUNTIME,
            session_id=failure.session_id,
            project_id=project_id,
            confidence=failure.confidence,
            evidence_reference=failure.evidence_reference,
            trace_reference=failure.trace_reference,
            kind=RecordKind.OBSERVATION,
            timestamp=failure.timestamp,
            iso_timestamp=failure.iso_timestamp,
        )

        return ObservationRecord(
            observation_id=obs_id,
            observation_type=obs_type,
            signature=sig,
            scope=ExperienceScope.SESSION,
            project_id=project_id,
            session_id=failure.session_id,
            occurrence_count=1,
            confidence=failure.confidence,
            status=ObservationStatus.OBSERVED,
            first_observed_at=failure.iso_timestamp,
            last_observed_at=failure.iso_timestamp,
            first_observed_ts=failure.timestamp,
            last_observed_ts=failure.timestamp,
            source_refs=[failure.failure_id],
            provenance=provenance,
            details={
                "category": failure.category,
                "original_classification": failure.original_classification,
                "safe_context": clean_ctx,
            },
        )

    @classmethod
    def derive_from_recovery(
        cls,
        recovery: RecoveryExperienceRecord,
        project_id: Optional[str] = None,
    ) -> ObservationRecord:
        """
        Derives an observation from a recovery attempt and its result.
        """
        sig_payload = f"rec_cat={recovery.failure_category}|action={recovery.recovery_action}|res={recovery.result}"
        sig = hashlib.sha256(sig_payload.encode("utf-8")).hexdigest()
        obs_id = f"obs_rec_{sig[:12]}"

        provenance = ProvenanceRecord(
            source="LearningObservationEngine",
            source_type=RecordSourceType.RUNTIME,
            session_id=recovery.session_id,
            project_id=project_id,
            confidence=1.0,
            evidence_reference=recovery.evidence_refs[0] if recovery.evidence_refs else None,
            trace_reference=recovery.trace_event_id,
            kind=RecordKind.OBSERVATION,
            timestamp=recovery.timestamp,
            iso_timestamp=recovery.iso_timestamp,
        )

        return ObservationRecord(
            observation_id=obs_id,
            observation_type=ObservationType.RECOVERY_PATTERN,
            signature=sig,
            scope=ExperienceScope.SESSION,
            project_id=project_id,
            session_id=recovery.session_id,
            occurrence_count=1,
            confidence=1.0,
            status=ObservationStatus.OBSERVED,
            first_observed_at=recovery.iso_timestamp,
            last_observed_at=recovery.iso_timestamp,
            first_observed_ts=recovery.timestamp,
            last_observed_ts=recovery.timestamp,
            source_refs=[recovery.recovery_id] + ([recovery.failure_id] if recovery.failure_id else []),
            provenance=provenance,
            details={
                "failure_category": recovery.failure_category,
                "recovery_action": recovery.recovery_action,
                "result": recovery.result,
                "duration_ms": recovery.duration_ms,
            },
        )

    @classmethod
    def derive_from_outcome(
        cls,
        outcome: OutcomeRecord,
        project_id: Optional[str] = None,
    ) -> Optional[ObservationRecord]:
        """
        Derives an observation from a tripartite verification outcome.
        Focuses on UNVERIFIED or FAIL outcomes that reveal runtime verification ambiguity.
        """
        if outcome.verdict == "PASS":
            return None

        sig_payload = f"verdict={outcome.verdict}|err_cat={outcome.error_category or 'NONE'}"
        sig = hashlib.sha256(sig_payload.encode("utf-8")).hexdigest()
        obs_id = f"obs_ver_{sig[:12]}"

        ev_ref = getattr(outcome, "evidence_reference", None)
        tr_ref = getattr(outcome, "trace_reference", None)
        if outcome.provenance:
            ev_ref = ev_ref or getattr(outcome.provenance, "evidence_reference", None)
            tr_ref = tr_ref or getattr(outcome.provenance, "trace_reference", None)

        provenance = ProvenanceRecord(
            source="LearningObservationEngine",
            source_type=RecordSourceType.RUNTIME,
            session_id=outcome.session_id,
            project_id=project_id,
            confidence=outcome.confidence,
            evidence_reference=ev_ref,
            trace_reference=tr_ref,
            kind=RecordKind.OBSERVATION,
            timestamp=outcome.timestamp,
            iso_timestamp=outcome.iso_timestamp,
        )

        return ObservationRecord(
            observation_id=obs_id,
            observation_type=ObservationType.VERIFICATION_UNKNOWN if outcome.verdict == "UNVERIFIED" else ObservationType.FAILURE_SIGNATURE,
            signature=sig,
            scope=ExperienceScope.SESSION,
            project_id=project_id,
            session_id=outcome.session_id,
            occurrence_count=1,
            confidence=outcome.confidence,
            status=ObservationStatus.OBSERVED,
            first_observed_at=outcome.iso_timestamp,
            last_observed_at=outcome.iso_timestamp,
            first_observed_ts=outcome.timestamp,
            last_observed_ts=outcome.timestamp,
            source_refs=[outcome.outcome_id],
            provenance=provenance,
            details={
                "verdict": outcome.verdict,
                "error_category": outcome.error_category,
                "details": outcome.details,
            },
        )

    @classmethod
    def derive_from_agent_tool_call(
        cls,
        tool_call: AgentToolCallRecord,
        preceding_failure: Optional[NormalizedFailureRecord] = None,
        project_id: Optional[str] = None,
    ) -> Optional[ObservationRecord]:
        """
        Derives an observation linking an agent tool category to an outcome or failure.
        """
        if not preceding_failure and tool_call.success:
            return None

        fail_sig = preceding_failure.signature if preceding_failure else "NONE"
        sig_payload = f"tool_name={tool_call.tool_name}|cat={tool_call.tool_category}|success={tool_call.success}|fail_sig={fail_sig}"
        sig = hashlib.sha256(sig_payload.encode("utf-8")).hexdigest()
        obs_id = f"obs_tool_{sig[:12]}"

        provenance = ProvenanceRecord(
            source="LearningObservationEngine",
            source_type=RecordSourceType.AGENT,
            session_id=tool_call.conversation_id or "unknown",
            project_id=project_id,
            confidence=0.9,
            kind=RecordKind.OBSERVATION,
            timestamp=tool_call.timestamp,
            iso_timestamp=tool_call.iso_timestamp,
        )

        source_refs = [tool_call.tool_call_id]
        if preceding_failure:
            source_refs.append(preceding_failure.failure_id)

        return ObservationRecord(
            observation_id=obs_id,
            observation_type=ObservationType.TOOL_PRECEDING_FAILURE if preceding_failure else ObservationType.FAILURE_SIGNATURE,
            signature=sig,
            scope=ExperienceScope.SESSION,
            project_id=project_id,
            session_id=tool_call.agent_session_id,
            occurrence_count=1,
            confidence=0.9,
            status=ObservationStatus.OBSERVED,
            first_observed_at=tool_call.iso_timestamp,
            last_observed_at=tool_call.iso_timestamp,
            first_observed_ts=tool_call.timestamp,
            last_observed_ts=tool_call.timestamp,
            source_refs=source_refs,
            provenance=provenance,
            details={
                "tool_name": tool_call.tool_name,
                "tool_category": tool_call.tool_category,
                "success": tool_call.success,
                "error_class": tool_call.error_class,
                "associated_failure_signature": fail_sig,
            },
        )

    @classmethod
    def derive_from_user_correction(
        cls,
        correction: AgentCorrectionRecord,
        related_failure: Optional[NormalizedFailureRecord] = None,
        project_id: Optional[str] = None,
    ) -> ObservationRecord:
        """
        Derives an observation when a user correction follows an action or failure.
        """
        fail_sig = related_failure.signature if related_failure else "NONE"
        sig_payload = f"corr_type={correction.correction_type}|fail_sig={fail_sig}"
        sig = hashlib.sha256(sig_payload.encode("utf-8")).hexdigest()
        obs_id = f"obs_corr_{sig[:12]}"

        provenance = ProvenanceRecord(
            source="LearningObservationEngine",
            source_type=RecordSourceType.USER_VERIFICATION,
            session_id=correction.related_dwr_session_id or correction.conversation_id or "unknown",
            project_id=project_id,
            confidence=1.0,
            kind=RecordKind.OBSERVATION,
            timestamp=correction.timestamp,
            iso_timestamp=correction.iso_timestamp,
        )

        source_refs = [correction.correction_id]
        if related_failure:
            source_refs.append(related_failure.failure_id)

        return ObservationRecord(
            observation_id=obs_id,
            observation_type=ObservationType.USER_CORRECTION_FOLLOWING_FAILURE,
            signature=sig,
            scope=ExperienceScope.SESSION,
            project_id=project_id,
            session_id=correction.related_dwr_session_id,
            occurrence_count=1,
            confidence=1.0,
            status=ObservationStatus.OBSERVED,
            first_observed_at=correction.iso_timestamp,
            last_observed_at=correction.iso_timestamp,
            first_observed_ts=correction.timestamp,
            last_observed_ts=correction.timestamp,
            source_refs=source_refs,
            provenance=provenance,
            details={
                "correction_type": correction.correction_type,
                "associated_failure_signature": fail_sig,
                "classification_details": correction.classification_details,
            },
        )
