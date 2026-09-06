"""
Improvement Candidate Generator & Evidence Threshold Engine.
Architecture H / Milestone 2.1 Prompt 4.

Translates stable, verified patterns into governed ImprovementCandidateRecords.
Applies transparent evidence gates:
- Occurrence threshold (>= 3 for CANDIDATE, >= 5 for VALIDATION_REQUIRED)
- Session threshold (>= 2 distinct sessions)
- Contradiction ratio check (<= 20%)
- Learning Safety Gate invariant checks
- Risk classification (LOW, MEDIUM, HIGH, CRITICAL)

Never auto-promotes candidates to DURABLE.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from runtime.experience.learning.models import (
    CandidateCategory,
    CandidateStatus,
    DetectedPatternRecord,
    GateResult,
    GateStatus,
    ImprovementCandidateRecord,
    PatternType,
    RiskLevel,
)
from runtime.experience.learning.safety_gate import LearningSafetyGate
from runtime.experience.models import (
    ExperienceScope,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
)

logger = logging.getLogger("desktop_webview.experience.learning.candidate_generator")


class ImprovementCandidateGenerator:
    """
    Generates governed ImprovementCandidateRecords from DetectedPatternRecords.
    Evaluates evidence thresholds and attaches transparent gate results.
    """

    @classmethod
    def generate_candidate(
        cls,
        pattern: DetectedPatternRecord,
        contradiction_count: int = 0,
        subsystem_override: Optional[str] = None,
    ) -> ImprovementCandidateRecord:
        """
        Formulates an ImprovementCandidateRecord from a DetectedPatternRecord.
        """
        # Determine candidate category and affected subsystem
        category, affected_subsystem = cls._classify_candidate(pattern.pattern_type)
        if subsystem_override:
            affected_subsystem = subsystem_override

        # Determine risk level
        risk = cls._assess_risk(pattern.pattern_type, category, affected_subsystem)

        # Build initial candidate ID
        cand_id_hash = hashlib.sha256(f"cand:{pattern.pattern_id}:{pattern.signature}".encode("utf-8")).hexdigest()[:12]
        candidate_id = f"cand_{cand_id_hash}"

        # Generate fact-grounded rationale
        rationale = cls._generate_rationale(pattern, category, affected_subsystem)

        # Initial status based on evidence count
        if pattern.occurrence_count >= LearningSafetyGate.MIN_VALIDATION_OCCURRENCES and pattern.session_count >= LearningSafetyGate.MIN_CANDIDATE_SESSIONS:
            initial_status = CandidateStatus.VALIDATION_REQUIRED
        elif pattern.occurrence_count >= LearningSafetyGate.MIN_CANDIDATE_OCCURRENCES:
            initial_status = CandidateStatus.CANDIDATE
        else:
            initial_status = CandidateStatus.OBSERVED

        now_iso = datetime.now(timezone.utc).isoformat()
        provenance = ProvenanceRecord(
            source="ImprovementCandidateGenerator",
            source_type=RecordSourceType.RUNTIME,
            session_id=pattern.project_id or "global",
            project_id=pattern.project_id,
            confidence=pattern.confidence,
            kind=RecordKind.CANDIDATE_KNOWLEDGE,
        )

        candidate = ImprovementCandidateRecord(
            candidate_id=candidate_id,
            category=category,
            affected_subsystem=affected_subsystem,
            rationale_summary=rationale,
            pattern_id=pattern.pattern_id,
            scope=pattern.scope,
            project_id=pattern.project_id,
            evidence_count=pattern.occurrence_count,
            session_count=pattern.session_count,
            confidence=pattern.confidence,
            risk_level=risk,
            status=initial_status,
            first_seen_at=pattern.first_seen_at,
            last_seen_at=pattern.last_seen_at,
            created_at=now_iso,
            updated_at=now_iso,
            gate_results={},
            provenance=provenance,
            metadata={
                "pattern_type": pattern.pattern_type.value,
                "signature": pattern.signature,
                "observation_refs": pattern.observation_refs,
                "contradiction_count": contradiction_count,
            },
        )

        # Evaluate all evidence gates via LearningSafetyGate
        passed, gate_results = LearningSafetyGate.evaluate_candidate_safety(
            candidate=candidate,
            contradiction_count=contradiction_count,
            is_human_approved=False,
        )
        candidate.gate_results = gate_results

        # If any gate failed, status cannot be VALIDATION_REQUIRED
        if not passed and candidate.status == CandidateStatus.VALIDATION_REQUIRED:
            candidate.status = CandidateStatus.CANDIDATE

        return candidate

    @staticmethod
    def _classify_candidate(pat_type: PatternType) -> Tuple[CandidateCategory, str]:
        if pat_type == PatternType.REPEATED_RECOVERY_REQUIRED:
            return CandidateCategory.RECOVERY_IMPROVEMENT, "recovery_engine"
        elif pat_type == PatternType.VERIFICATION_AMBIGUITY_CONDITION:
            return CandidateCategory.VERIFICATION_STABILITY, "verification_engine"
        elif pat_type == PatternType.REPEATED_TARGET_RESOLUTION_FAILURE:
            return CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS, "target_manager"
        elif pat_type == PatternType.AGENT_TOOL_FAILURE_CORRELATION:
            return CandidateCategory.TOOL_COORDINATION, "antigravity_bridge"
        elif pat_type == PatternType.USER_CORRECTION_SEQUENCE:
            return CandidateCategory.VERIFICATION_STABILITY, "user_verification"
        else:
            return CandidateCategory.ENVIRONMENT_ADAPTATION, "runtime"

    @staticmethod
    def _assess_risk(pat_type: PatternType, category: CandidateCategory, subsystem: str) -> RiskLevel:
        if subsystem in ("action_engine", "recovery_engine"):
            return RiskLevel.HIGH
        elif category in (CandidateCategory.RECOVERY_IMPROVEMENT, CandidateCategory.TARGET_RESOLUTION_ROBUSTNESS):
            return RiskLevel.MEDIUM
        elif pat_type == PatternType.AGENT_TOOL_FAILURE_CORRELATION:
            return RiskLevel.LOW
        return RiskLevel.MEDIUM

    @staticmethod
    def _generate_rationale(
        pattern: DetectedPatternRecord,
        category: CandidateCategory,
        subsystem: str,
    ) -> str:
        """
        Formulates a structured rationale grounded strictly in empirical metrics.
        No speculative agent intent is allowed.
        """
        return (
            f"Pattern '{pattern.pattern_type.value}' detected with {pattern.occurrence_count} evidence "
            f"occurrences across {pattern.session_count} session(s). Subsystem '{subsystem}' exhibits "
            f"reproducible behavior under signature {pattern.signature[:16]}... Category: {category.value}."
        )
