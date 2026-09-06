"""
Learning Safety Gate & Invariant Enforcement Engine.
Architecture H / Milestone 2.1 Prompt 4.

Enforces the 10 Non-Bypassable Safety Invariants:
- Invariant 1: No raw chain-of-thought or hidden reasoning can become learning data.
- Invariant 2: No raw prompts or unrestricted transcripts can become durable knowledge.
- Invariant 3: No secret, credential, token, cookie, private key, or sensitive typed text can become learning data.
- Invariant 4: Agent interpretation alone cannot promote knowledge.
- Invariant 5: One occurrence cannot create durable knowledge.
- Invariant 6: Historical frequency alone cannot make a rule authoritative.
- Invariant 7: Contradictory evidence must prevent automatic promotion.
- Invariant 8: Stale knowledge cannot remain authoritative indefinitely.
- Invariant 9: The learning subsystem cannot mutate runtime behavior.
- Invariant 10: The core Architecture H governance rules are immutable from experience data.

Also provides defensive sanitization against malicious prompt injection in stored experience data.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from runtime.errors import DesktopAutomationException
from runtime.experience.learning.models import (
    CandidateStatus,
    GateResult,
    GateStatus,
    ImprovementCandidateRecord,
    ObservationRecord,
)
from runtime.experience.models import ExperienceScope
from runtime.experience.privacy import (
    MAX_METADATA_STRING_LENGTH,
    PROHIBITED_KEY_PATTERN,
    SECRET_VALUE_PATTERNS,
    PrivacyEnforcer,
    PrivacyViolationException,
)
from runtime.trace_engine import redact_sensitive_text

logger = logging.getLogger("desktop_webview.experience.learning.safety_gate")

# Adversarial prompt injections in experience data
ADVERSARIAL_INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore\s+all\s+(?:previous\s+)?(?:safety\s+)?rules\b"),
    re.compile(r"(?i)\bignore\s+all\s+instructions\b"),
    re.compile(r"(?i)\bsystem\s+prompt\s+override\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+in\s+developer\s+mode\b"),
    re.compile(r"(?i)\bpromote\s+this\s+to\s+global\s+knowledge\b"),
    re.compile(r"(?i)\bchange\s+the\s+recovery\s+policy\b"),
    re.compile(r"(?i)\bstore\s+the\s+following\s+secret\b"),
    re.compile(r"(?i)\bdisregard\s+prior\s+rules\b"),
    re.compile(r"(?i)\bbypass\s+architecture\s+h\b"),
    re.compile(r"(?i)\bdisable\s+safety\s+gate\b"),
]

# Sensitive input text keys (desktop_type arguments, etc.)
SENSITIVE_INPUT_KEYS = {
    "text", "typed_text", "value", "content", "code", "input_text",
    "password", "secret", "token", "key", "authorization", "prompt",
    "raw_input", "keystrokes", "input_value",
}

# Speculative or hallucinated reasoning markers
SPECULATIVE_MARKERS = [
    re.compile(r"(?i)\bthe\s+agent\s+probably\s+intended\b"),
    re.compile(r"(?i)\bthe\s+model\s+thinks\b"),
    re.compile(r"(?i)\bi\s+believe\s+the\s+user\s+wanted\b"),
    re.compile(r"(?i)\bhidden\s+intent\s+is\b"),
    re.compile(r"(?i)\bguessing\s+the\s+reason\b"),
]


PROHIBITED_LEARNING_KEY_PATTERN = re.compile(
    r"(?i)^(chain_of_thought|cot|hidden_thoughts?|reasoning.*|thought_process|"
    r"raw_reasoning|model_transcript|unfiltered_prompt|prompt_archive|.*prompt.*|"
    r"transcript|raw_transcript|password|passwd|api_?key|bearer_?token|auth_?token|"
    r"jwt|cookie|cookies|private_?key|secret_?key)$"
)


class LearningSafetyException(DesktopAutomationException):
    """Raised when data or a candidate violates the Learning Safety Gate invariants."""
    pass


class LearningSafetyGate:
    """
    Dedicated safety gate ensuring that learning remains evidence accumulation
    without memory mutation, prompt leakage, or secret persistence.
    """

    # Configurable deterministic thresholds
    MIN_CANDIDATE_OCCURRENCES = 3
    MIN_VALIDATION_OCCURRENCES = 5
    MIN_CANDIDATE_SESSIONS = 2
    MAX_CONTRADICTION_RATIO = 0.20  # Max 20% contradictions allowed for validation
    MAX_STATEMENT_LENGTH = 1024

    _blocked_violations_count: int = 0

    @classmethod
    @property
    def blocked_violations_count(cls) -> int:
        return cls._blocked_violations_count

    @classmethod
    def record_blocked_violation(cls) -> None:
        cls._blocked_violations_count += 1

    @classmethod
    def validate_learning_payload(cls, data: Dict[str, Any], context: str = "learning") -> Dict[str, Any]:
        """
        Validates raw payload against Invariants 1, 2, 3, and adversarial injections.
        """
        if not isinstance(data, dict):
            return {}

        sanitized: Dict[str, Any] = {}
        for key, value in data.items():
            key_str = str(key).strip()

            # Invariant 1 & 2: Prohibited key check (CoT, reasoning, raw prompts, transcripts)
            if PROHIBITED_KEY_PATTERN.match(key_str) or PROHIBITED_LEARNING_KEY_PATTERN.match(key_str):
                cls.record_blocked_violation()
                raise LearningSafetyException(
                    f"Invariant 1/2 violation in {context}: key '{key_str}' is strictly prohibited. "
                    f"Raw chain-of-thought, hidden reasoning, and unrestricted transcripts cannot become learning data."
                )

            # Invariant 3: Sensitive typed text check
            if key_str.lower() in SENSITIVE_INPUT_KEYS:
                if isinstance(value, str) and len(value) > 0:
                    cls.record_blocked_violation()
                    raise LearningSafetyException(
                        f"Invariant 3 violation in {context}: key '{key_str}' contains raw text value. "
                        f"Raw input text, typed text, and secrets cannot become learning data."
                    )

            sanitized[key_str] = cls._validate_value(value, field_name=key_str, context=context)

        return sanitized

    @classmethod
    def _validate_value(cls, val: Any, field_name: str, context: str) -> Any:
        if isinstance(val, dict):
            return cls.validate_learning_payload(val, context=f"{context}.{field_name}")
        elif isinstance(val, list):
            return [cls._validate_value(item, field_name=f"{field_name}[]", context=context) for item in val]
        elif isinstance(val, str):
            # Enforce size limit
            if len(val) > MAX_METADATA_STRING_LENGTH:
                cls.record_blocked_violation()
                raise LearningSafetyException(
                    f"Payload size violation in {context}.{field_name}: string length {len(val)} exceeds {MAX_METADATA_STRING_LENGTH} bytes."
                )

            # Check for adversarial injection patterns
            for pat in ADVERSARIAL_INJECTION_PATTERNS:
                if pat.search(val):
                    cls.record_blocked_violation()
                    raise LearningSafetyException(
                        f"Adversarial payload detected in {context}.{field_name}: matched injection pattern '{pat.pattern}'."
                    )

            # Check for prohibited secret patterns
            for pat in SECRET_VALUE_PATTERNS:
                if pat.search(val):
                    cls.record_blocked_violation()
                    raise LearningSafetyException(
                        f"Invariant 3 violation in {context}.{field_name}: matched secret or credential pattern."
                    )

            # Ensure redaction is applied
            cleaned = redact_sensitive_text(val)
            return cleaned
        else:
            return val

    @classmethod
    def evaluate_candidate_safety(
        cls,
        candidate: ImprovementCandidateRecord,
        contradiction_count: int = 0,
        is_human_approved: bool = False,
    ) -> Tuple[bool, Dict[str, GateResult]]:
        """
        Evaluates an improvement candidate against all evidence gates and safety invariants.
        Returns (passes_all_gates, gate_results_dict).
        """
        gate_results: Dict[str, GateResult] = {}
        all_passed = True

        # Invariant 5: Minimum independent occurrences gate
        occ_threshold = cls.MIN_VALIDATION_OCCURRENCES if candidate.status == CandidateStatus.VALIDATION_REQUIRED else cls.MIN_CANDIDATE_OCCURRENCES
        occ_passed = candidate.evidence_count >= occ_threshold
        gate_results["occurrence_gate"] = GateResult(
            gate_name="occurrence_gate",
            status=GateStatus.PASS if occ_passed else GateStatus.FAIL,
            metric_value=candidate.evidence_count,
            threshold=occ_threshold,
            details=f"Evidence occurrences: {candidate.evidence_count} >= {occ_threshold}",
        )
        if not occ_passed:
            all_passed = False

        # Session diversity gate (temporal / cross-session consistency)
        sess_passed = candidate.session_count >= cls.MIN_CANDIDATE_SESSIONS
        gate_results["session_gate"] = GateResult(
            gate_name="session_gate",
            status=GateStatus.PASS if sess_passed else GateStatus.FAIL,
            metric_value=candidate.session_count,
            threshold=cls.MIN_CANDIDATE_SESSIONS,
            details=f"Distinct sessions: {candidate.session_count} >= {cls.MIN_CANDIDATE_SESSIONS}",
        )
        if not sess_passed:
            all_passed = False

        # Invariant 7: Contradictory evidence gate
        total_evidence = candidate.evidence_count + contradiction_count
        contradiction_ratio = (contradiction_count / total_evidence) if total_evidence > 0 else 0.0
        contra_passed = contradiction_ratio <= cls.MAX_CONTRADICTION_RATIO
        gate_results["contradiction_gate"] = GateResult(
            gate_name="contradiction_gate",
            status=GateStatus.PASS if contra_passed else GateStatus.FAIL,
            metric_value=round(contradiction_ratio, 3),
            threshold=cls.MAX_CONTRADICTION_RATIO,
            details=(
                f"Contradiction ratio {contradiction_ratio:.1%} "
                f"({contradiction_count}/{total_evidence}) <= {cls.MAX_CONTRADICTION_RATIO:.1%}"
            ),
        )
        if not contra_passed:
            all_passed = False

        # Invariant 4: Ground fact vs speculative reasoning gate
        speculative = False
        spec_detail = "Rationale is grounded in structured facts"
        for pat in SPECULATIVE_MARKERS:
            if pat.search(candidate.rationale_summary):
                speculative = True
                spec_detail = f"Rationale contains speculative reasoning marker: '{pat.pattern}'"
                break

        gate_results["epistemic_grounding_gate"] = GateResult(
            gate_name="epistemic_grounding_gate",
            status=GateStatus.FAIL if speculative else GateStatus.PASS,
            metric_value="SPECULATIVE" if speculative else "FACT_GROUNDED",
            threshold="FACT_GROUNDED",
            details=spec_detail,
        )
        if speculative:
            all_passed = False

        # Privacy / Injection safety gate
        payload_safe = True
        payload_detail = "Payload passed all privacy and injection checks"
        try:
            cls.validate_learning_payload(candidate.metadata, context="candidate.metadata")
            cls.validate_learning_payload({"rationale": candidate.rationale_summary}, context="candidate.rationale")
        except (LearningSafetyException, PrivacyViolationException) as e:
            payload_safe = False
            payload_detail = str(e)

        gate_results["privacy_and_security_gate"] = GateResult(
            gate_name="privacy_and_security_gate",
            status=GateStatus.PASS if payload_safe else GateStatus.FAIL,
            metric_value="SAFE" if payload_safe else "VIOLATION",
            threshold="SAFE",
            details=payload_detail,
        )
        if not payload_safe:
            all_passed = False

        # Invariant 6 & Human Governance requirement gate
        # Durable knowledge ALWAYS requires human approval
        if candidate.status in (CandidateStatus.HUMAN_APPROVED, CandidateStatus.DURABLE):
            gov_passed = is_human_approved
            gate_results["human_governance_gate"] = GateResult(
                gate_name="human_governance_gate",
                status=GateStatus.PASS if gov_passed else GateStatus.REVIEW_REQUIRED,
                metric_value="APPROVED" if gov_passed else "PENDING_REVIEW",
                threshold="APPROVED",
                details="Human review decision confirmed" if gov_passed else "Human review required before durable promotion",
            )
            if not gov_passed:
                all_passed = False
        else:
            gate_results["human_governance_gate"] = GateResult(
                gate_name="human_governance_gate",
                status=GateStatus.PASS,
                metric_value="NOT_YET_REQUIRED",
                threshold="NONE",
                details="Candidate is in observation/validation phase; human approval not yet required",
            )

        # Invariant 10: Architecture H sovereignty check
        # Scope cannot be GLOBAL without explicit human validation
        if candidate.scope == ExperienceScope.GLOBAL:
            scope_passed = is_human_approved
            gate_results["global_scope_gate"] = GateResult(
                gate_name="global_scope_gate",
                status=GateStatus.PASS if scope_passed else GateStatus.FAIL,
                metric_value=candidate.scope.value,
                threshold="PROJECT_OR_EXPLICIT_GLOBAL",
                details="Global scope promotion requires explicit human authorization",
            )
            if not scope_passed:
                all_passed = False

        return all_passed, gate_results

    @classmethod
    def assert_zero_runtime_mutation(cls, target_object: Any) -> None:
        """
        Invariant 9 & 10: Ensures learning subsystem cannot mutate runtime engines.
        Raises LearningSafetyException if any attempt to modify runtime configuration is made.
        """
        from runtime.action_engine import ActionExecutionEngine
        from runtime.verification_engine import VerificationEngine
        from runtime.recovery_engine import RecoveryEngine
        from runtime.mission_orchestrator import ReviewMissionOrchestrator

        prohibited_types = (
            ActionExecutionEngine,
            VerificationEngine,
            RecoveryEngine,
            ReviewMissionOrchestrator,
        )
        if isinstance(target_object, prohibited_types):
            raise LearningSafetyException(
                f"Invariant 9 violation: Learning layer is forbidden from mutating runtime engine {type(target_object).__name__}. "
                f"Learning is strictly an observer and proposal generator."
            )
