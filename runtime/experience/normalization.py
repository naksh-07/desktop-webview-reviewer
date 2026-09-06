"""
Deterministic Failure Normalization & Signature Engine (Architecture H / 2.1 Prompt 2).

Normalizes heterogeneous runtime exceptions, diagnostics classifications,
verification reasons, and action receipts into the authoritative 19-category
FailureCategory taxonomy. Derives privacy-preserving, deterministic SHA-256
failure signatures for historical cross-session aggregation and trend detection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Dict, Optional, Tuple, Union

from runtime.diagnostics import FailureCategory, DiagnosticDiagnosis
from runtime.evidence_models import UnverifiedReason, VerificationVerdict
from runtime.action_models import ActionType, DispatchStatus, ActionOutcomeStatus
from runtime.state import TargetPlane
from runtime.experience.models import (
    NormalizedFailureRecord,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
)
from runtime.experience.privacy import PrivacyEnforcer

logger = logging.getLogger("desktop_webview.experience.normalization")

# Exception class name mapping to authoritative FailureCategory
EXCEPTION_CATEGORY_MAP: Dict[str, FailureCategory] = {
    "TargetNotFoundException": FailureCategory.TARGET_NOT_FOUND,
    "InvalidTargetException": FailureCategory.TARGET_NOT_FOUND,
    "TargetExitedException": FailureCategory.PROCESS_CRASH,
    "TargetHungException": FailureCategory.PROCESS_HANG,
    "TargetMismatchException": FailureCategory.PROCESS_CRASH,
    "StaleReferenceException": FailureCategory.TARGET_NOT_ACTIONABLE,
    "NativeBridgeException": FailureCategory.ENVIRONMENT_FAILURE,
    "ActionExecutionException": FailureCategory.INPUT_DISPATCH_FAILURE,
    "ActionDispatchRejectedException": FailureCategory.TARGET_NOT_ACTIONABLE,
    "ActionTimeoutException": FailureCategory.ACTION_TIMEOUT,
    "SettlementTimeoutException": FailureCategory.SETTLEMENT_TIMEOUT,
    "TimeoutError": FailureCategory.SETTLEMENT_TIMEOUT,
    "asyncio.TimeoutError": FailureCategory.SETTLEMENT_TIMEOUT,
    "ConnectionRefusedError": FailureCategory.WEBVIEW_ERROR,
    "PermissionError": FailureCategory.PERMISSION_FAILURE,
    "FileNotFoundError": FailureCategory.ENVIRONMENT_FAILURE,
    "OcclusionException": FailureCategory.PHYSICAL_OCCLUSION,
    "WebviewConnectionException": FailureCategory.WEBVIEW_ERROR,
    "VerificationException": FailureCategory.EXPECTED_STATE_NOT_VERIFIED,
    "EvidenceSecurityException": FailureCategory.PERMISSION_FAILURE,
    "IntegrityVerificationException": FailureCategory.HARNESS_FAILURE,
}

# UnverifiedReason mapping to authoritative FailureCategory
UNVERIFIED_REASON_MAP: Dict[UnverifiedReason, FailureCategory] = {
    UnverifiedReason.PHYSICAL_STATE_UNKNOWN: FailureCategory.EXPECTED_STATE_NOT_VERIFIED,
    UnverifiedReason.TARGET_IDENTITY_UNCERTAIN: FailureCategory.TARGET_NOT_FOUND,
    UnverifiedReason.POST_STATE_MISSING: FailureCategory.SETTLEMENT_TIMEOUT,
    UnverifiedReason.PRE_STATE_MISSING: FailureCategory.TARGET_NOT_ACTIONABLE,
    UnverifiedReason.CONTRADICTORY_EVIDENCE: FailureCategory.EXPECTED_STATE_NOT_VERIFIED,
    UnverifiedReason.SCREENSHOT_UNAVAILABLE: FailureCategory.ENVIRONMENT_FAILURE,
    UnverifiedReason.AX_STATE_UNAVAILABLE: FailureCategory.WEBVIEW_ERROR,
    UnverifiedReason.NAVIGATION_RACE: FailureCategory.SETTLEMENT_TIMEOUT,
    UnverifiedReason.TARGET_DISAPPEARED_WITHOUT_EXPECTATION: FailureCategory.TARGET_NOT_FOUND,
    UnverifiedReason.USER_CONFIRMATION_PENDING: FailureCategory.UNKNOWN,
    UnverifiedReason.INSUFFICIENT_PROOF_LEVEL: FailureCategory.EXPECTED_STATE_NOT_VERIFIED,
    UnverifiedReason.WINDOW_CLOAKED_OR_MINIMIZED: FailureCategory.WINDOW_CLOAKED,
    UnverifiedReason.WINDOW_NON_RENDERABLE: FailureCategory.PHYSICAL_OCCLUSION,
    UnverifiedReason.WINDOW_NOT_FOREGROUND: FailureCategory.PHYSICAL_OCCLUSION,
    UnverifiedReason.PID_MISMATCH: FailureCategory.PROCESS_CRASH,
    UnverifiedReason.INSUFFICIENT_EVIDENCE: FailureCategory.EXPECTED_STATE_NOT_VERIFIED,
    UnverifiedReason.TIMED_OUT: FailureCategory.ACTION_TIMEOUT,
}


class FailureNormalizer:
    """
    Deterministic failure normalizer and signature generator.
    Translates runtime failures into durable historical signatures and facts.
    """

    @staticmethod
    def normalize_category(
        source: Union[Exception, DiagnosticDiagnosis, UnverifiedReason, str, None],
    ) -> Tuple[FailureCategory, str]:
        """
        Maps a runtime failure source to a canonical FailureCategory and original classification string.
        """
        if source is None:
            return FailureCategory.UNKNOWN, "UNKNOWN"

        if isinstance(source, DiagnosticDiagnosis):
            return source.failure_category, f"DiagnosticDiagnosis:{source.failure_category.value}"

        if isinstance(source, FailureCategory):
            return source, f"FailureCategory:{source.value}"

        if isinstance(source, UnverifiedReason):
            cat = UNVERIFIED_REASON_MAP.get(source, FailureCategory.EXPECTED_STATE_NOT_VERIFIED)
            return cat, f"UnverifiedReason:{source.value}"

        if isinstance(source, Exception):
            exc_name = source.__class__.__name__
            cat = EXCEPTION_CATEGORY_MAP.get(exc_name)
            if cat:
                return cat, f"Exception:{exc_name}"
            # Check for error codes if available
            code = getattr(source, "code", None)
            if code and isinstance(code, str):
                for fc in FailureCategory:
                    if fc.value == code.upper():
                        return fc, f"ExceptionCode:{code}"
            return FailureCategory.UNKNOWN, f"Exception:{exc_name}"

        if isinstance(source, str):
            clean = source.strip().upper()
            for fc in FailureCategory:
                if fc.value == clean:
                    return fc, f"String:{source}"
            return FailureCategory.UNKNOWN, f"String:{source}"

        return FailureCategory.UNKNOWN, str(type(source).__name__)

    @staticmethod
    def compute_signature(
        category: Union[FailureCategory, str],
        action_type: Optional[Union[ActionType, str]] = None,
        plane: Optional[Union[TargetPlane, str]] = None,
        target_role_or_class: Optional[str] = None,
        verification_verdict: Optional[Union[VerificationVerdict, str]] = None,
        recovery_result: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Derives a deterministic historical failure signature via SHA-256.

        The participating structured fields are:
        1. normalized_category (str)
        2. action_type (str or 'NONE')
        3. execution_plane (str or 'UNKNOWN')
        4. target_role_or_class (str or 'GENERIC')
        5. verification_verdict (str or 'UNSPECIFIED')
        6. recovery_result (str or 'NONE')

        Explicitly excluded:
        - raw user prompts or instructions
        - credentials, tokens, cookies
        - full DOM or screenshot byte arrays
        - agent internal reasoning / scratchpads
        - ephemeral timing / timestamps / PIDs / HWNDs
        """
        role_param = target_role_or_class or kwargs.get("target_role") or kwargs.get("target_class")
        verdict_param = verification_verdict or kwargs.get("verdict")
        cat_str = category.value if isinstance(category, FailureCategory) else str(category).upper()
        act_str = action_type.value if isinstance(action_type, ActionType) else (str(action_type).upper() if action_type else "NONE")
        plane_str = plane.value if isinstance(plane, TargetPlane) else (str(plane).upper() if plane else "UNKNOWN")
        target_str = str(role_param).strip().lower() if role_param else "generic"
        verdict_str = verdict_param.value if isinstance(verdict_param, VerificationVerdict) else (str(verdict_param).upper() if verdict_param else "UNSPECIFIED")
        rec_str = str(recovery_result).strip().upper() if recovery_result else "NONE"

        canonical_payload = (
            f"cat={cat_str}|"
            f"act={act_str}|"
            f"plane={plane_str}|"
            f"role={target_str}|"
            f"verdict={verdict_str}|"
            f"recovery={rec_str}"
        )

        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    # Alias for API ergonomics
    compute_failure_signature = compute_signature

    @classmethod
    def normalize_error(
        cls,
        source: Union[Exception, DiagnosticDiagnosis, UnverifiedReason, str, None],
    ) -> Tuple[FailureCategory, float]:
        """
        Maps a runtime failure source to (category, confidence).
        Convenience helper matching prompt failure normalization expectations.
        """
        cat, _ = cls.normalize_category(source)
        if isinstance(source, DiagnosticDiagnosis):
            conf = getattr(source, "confidence", 1.0)
        elif isinstance(source, Exception):
            if cat != FailureCategory.UNKNOWN:
                conf = 0.9
            else:
                conf = 0.4
        elif isinstance(source, UnverifiedReason):
            conf = 0.85
        else:
            conf = 0.75
        return cat, conf

    @classmethod
    def create_failure_record(
        cls,
        session_id: str,
        failure_source: Union[Exception, DiagnosticDiagnosis, UnverifiedReason, str, None],
        action_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        action_type: Optional[Union[ActionType, str]] = None,
        plane: Optional[Union[TargetPlane, str]] = None,
        target_role_or_class: Optional[str] = None,
        verification_verdict: Optional[Union[VerificationVerdict, str]] = None,
        recovery_result: Optional[str] = None,
        recovery_reference: Optional[str] = None,
        trace_reference: Optional[str] = None,
        evidence_reference: Optional[str] = None,
        confidence: float = 1.0,
        raw_context: Optional[Dict[str, Any]] = None,
    ) -> NormalizedFailureRecord:
        """
        Creates a complete NormalizedFailureRecord ready for durable persistence.
        Guarantees strict privacy redaction and deterministic signature computation.
        """
        category, orig_classification = cls.normalize_category(failure_source)
        signature = cls.compute_signature(
            category=category,
            action_type=action_type,
            plane=plane,
            target_role_or_class=target_role_or_class,
            verification_verdict=verification_verdict,
            recovery_result=recovery_result,
        )

        # Sanitize context defensively
        safe_ctx = PrivacyEnforcer.check_and_sanitize(
            raw_context or {},
            context=f"failure_normalization:{category.value}",
        )

        provenance = ProvenanceRecord(
            source="FailureNormalizer",
            source_type=RecordSourceType.DIAGNOSTICS,
            session_id=session_id,
            mission_id=mission_id,
            confidence=confidence,
            evidence_reference=evidence_reference,
            trace_reference=trace_reference,
            kind=RecordKind.FACT,
        )

        failure_id = f"fail_{uuid.uuid4().hex[:12]}"

        return NormalizedFailureRecord(
            failure_id=failure_id,
            session_id=session_id,
            category=category.value,
            original_classification=orig_classification,
            signature=signature,
            confidence=confidence,
            provenance=provenance,
            mission_id=mission_id,
            action_id=action_id,
            recovery_reference=recovery_reference,
            trace_reference=trace_reference,
            evidence_reference=evidence_reference,
            safe_context=safe_ctx,
        )
