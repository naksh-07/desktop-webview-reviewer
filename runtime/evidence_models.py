"""
Evidence and Verification Domain Models for Desktop WebView Reviewer (Architecture H).
Defines immutable data models for VerificationVerdict, ProofLevel, EvidenceType,
ClaimType, UnverifiedReason, EvidenceItem, VerificationClaim, EvidenceArtifact,
ScreenshotEvidence, and EvidenceManifest according to docs/architecture/18_EVIDENCE_MODEL.md.
"""

from __future__ import annotations
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any, Sequence

from runtime.state import TargetPlane


class VerificationVerdict(str, Enum):
    """
    The tripartite verification verdict model.
    Never reduce uncertainty into a boolean or premature PASS.
    """
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class ProofLevel(str, Enum):
    """
    Progressive proof levels governing the depth of forensic verification required.
    """
    LEVEL_0_DISPATCH_EVIDENCE = "LEVEL_0_DISPATCH_EVIDENCE"
    LEVEL_1_TARGET_EVIDENCE = "LEVEL_1_TARGET_EVIDENCE"
    LEVEL_2_STATE_CHANGE_EVIDENCE = "LEVEL_2_STATE_CHANGE_EVIDENCE"
    LEVEL_3_DUAL_PERSPECTIVE_PROOF = "LEVEL_3_DUAL_PERSPECTIVE_PROOF"
    LEVEL_4_FORENSIC_COMPLETE = "LEVEL_4_FORENSIC_COMPLETE"


class EvidenceType(str, Enum):
    """Normalized evidence categories."""
    NATIVE_WINDOW_STATE = "NATIVE_WINDOW_STATE"
    NATIVE_VISIBILITY = "NATIVE_VISIBILITY"
    NATIVE_OCCLUSION = "NATIVE_OCCLUSION"
    NATIVE_MODAL = "NATIVE_MODAL"
    NATIVE_SCREENSHOT = "NATIVE_SCREENSHOT"
    WEB_DOM_SNAPSHOT = "WEB_DOM_SNAPSHOT"
    WEB_AX_SNAPSHOT = "WEB_AX_SNAPSHOT"
    WEB_GEOMETRY = "WEB_GEOMETRY"
    WEB_VISIBILITY = "WEB_VISIBILITY"
    WEB_FRAME_STATE = "WEB_FRAME_STATE"
    ACTION_RECEIPT = "ACTION_RECEIPT"
    ACTION_OUTCOME = "ACTION_OUTCOME"
    OBSERVATION_DIFF = "OBSERVATION_DIFF"
    PROCESS_IDENTITY = "PROCESS_IDENTITY"
    TARGET_IDENTITY = "TARGET_IDENTITY"
    CONTRADICTION = "CONTRADICTION"


class ClaimType(str, Enum):
    """Explicit verification claim types evaluated by the verification engine."""
    ActionWasDispatched = "ActionWasDispatched"
    InputReachedTarget = "InputReachedTarget"
    TargetWasPhysicallyVisible = "TargetWasPhysicallyVisible"
    ExpectedStateOccurred = "ExpectedStateOccurred"
    ElementAppeared = "ElementAppeared"
    ElementDisappeared = "ElementDisappeared"
    NavigationOccurred = "NavigationOccurred"
    NativeModalAppeared = "NativeModalAppeared"
    WindowClosed = "WindowClosed"


class UnverifiedReason(str, Enum):
    """Explicit structural reasons explaining why an action or claim remains UNVERIFIED."""
    PHYSICAL_STATE_UNKNOWN = "PHYSICAL_STATE_UNKNOWN"
    TARGET_IDENTITY_UNCERTAIN = "TARGET_IDENTITY_UNCERTAIN"
    POST_STATE_MISSING = "POST_STATE_MISSING"
    PRE_STATE_MISSING = "PRE_STATE_MISSING"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    SCREENSHOT_UNAVAILABLE = "SCREENSHOT_UNAVAILABLE"
    AX_STATE_UNAVAILABLE = "AX_STATE_UNAVAILABLE"
    NAVIGATION_RACE = "NAVIGATION_RACE"
    TARGET_DISAPPEARED_WITHOUT_EXPECTATION = "TARGET_DISAPPEARED_WITHOUT_EXPECTATION"
    USER_CONFIRMATION_PENDING = "USER_CONFIRMATION_PENDING"
    INSUFFICIENT_PROOF_LEVEL = "INSUFFICIENT_PROOF_LEVEL"
    WINDOW_CLOAKED_OR_MINIMIZED = "WINDOW_CLOAKED_OR_MINIMIZED"
    WINDOW_NON_RENDERABLE = "WINDOW_NON_RENDERABLE"
    WINDOW_NOT_FOREGROUND = "WINDOW_NOT_FOREGROUND"
    PID_MISMATCH = "PID_MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    TIMED_OUT = "TIMED_OUT"


@dataclass(frozen=True)
class EvidenceItem:
    """
    Normalized, immutable evidence unit.
    All persisted evidence items must retain an integrity hash and source metadata.
    """
    evidence_id: str
    evidence_type: EvidenceType
    timestamp: float
    monotonic_time: float
    session_id: str
    action_id: Optional[str]
    epoch: int
    source_plane: TargetPlane
    source_component: str
    payload_reference: Optional[str] = None
    integrity_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type.value if isinstance(self.evidence_type, EvidenceType) else str(self.evidence_type),
            "timestamp": self.timestamp,
            "monotonic_time": self.monotonic_time,
            "session_id": self.session_id,
            "action_id": self.action_id,
            "epoch": self.epoch,
            "source_plane": self.source_plane.value if isinstance(self.source_plane, TargetPlane) else str(self.source_plane),
            "source_component": self.source_component,
            "payload_reference": self.payload_reference,
            "integrity_hash": self.integrity_hash,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceItem:
        plane = TargetPlane(data["source_plane"]) if data.get("source_plane") in TargetPlane._value2member_map_ else TargetPlane.UNKNOWN
        ev_type = EvidenceType(data["evidence_type"]) if data.get("evidence_type") in EvidenceType._value2member_map_ else EvidenceType(data["evidence_type"])
        return cls(
            evidence_id=data["evidence_id"],
            evidence_type=ev_type,
            timestamp=data["timestamp"],
            monotonic_time=data.get("monotonic_time", data["timestamp"]),
            session_id=data["session_id"],
            action_id=data.get("action_id"),
            epoch=data.get("epoch", 0),
            source_plane=plane,
            source_component=data.get("source_component", "unknown"),
            payload_reference=data.get("payload_reference"),
            integrity_hash=data.get("integrity_hash", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class VerificationClaim:
    """
    Explicit claim evaluated during verification.
    Specifies what was expected, what was actually observed, and the resulting verdict.
    """
    claim_id: str
    session_id: str
    action_id: str
    observation_epoch: int
    claim_type: ClaimType
    expected: Any
    actual: Any
    status: VerificationVerdict
    confidence: float
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""
    unverified_reason: Optional[UnverifiedReason] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "session_id": self.session_id,
            "action_id": self.action_id,
            "observation_epoch": self.observation_epoch,
            "claim_type": self.claim_type.value if isinstance(self.claim_type, ClaimType) else str(self.claim_type),
            "expected": self.expected,
            "actual": self.actual,
            "status": self.status.value if isinstance(self.status, VerificationVerdict) else str(self.status),
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "reason": self.reason,
            "unverified_reason": self.unverified_reason.value if self.unverified_reason else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VerificationClaim:
        c_type = ClaimType(data["claim_type"]) if data.get("claim_type") in ClaimType._value2member_map_ else ClaimType(data["claim_type"])
        status = VerificationVerdict(data["status"]) if data.get("status") in VerificationVerdict._value2member_map_ else VerificationVerdict(data["status"])
        uv_reason = UnverifiedReason(data["unverified_reason"]) if data.get("unverified_reason") in UnverifiedReason._value2member_map_ else None
        return cls(
            claim_id=data["claim_id"],
            session_id=data["session_id"],
            action_id=data["action_id"],
            observation_epoch=data.get("observation_epoch", 0),
            claim_type=c_type,
            expected=data.get("expected"),
            actual=data.get("actual"),
            status=status,
            confidence=data.get("confidence", 1.0),
            evidence_refs=tuple(data.get("evidence_refs", [])),
            reason=data.get("reason", ""),
            unverified_reason=uv_reason,
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class EvidenceArtifact:
    """
    Metadata for a content-addressed disk artifact.
    """
    artifact_id: str
    filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    created_at: float
    relative_path: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "relative_path": self.relative_path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceArtifact:
        return cls(
            artifact_id=data["artifact_id"],
            filename=data["filename"],
            mime_type=data.get("mime_type", "application/octet-stream"),
            sha256=data["sha256"],
            size_bytes=data.get("size_bytes", 0),
            created_at=data.get("created_at", time.time()),
            relative_path=data.get("relative_path", data["filename"]),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class ScreenshotEvidence:
    """
    Dual-modal screenshot metadata ensuring coordinate space and capture provenance clarity.
    """
    screenshot_id: str
    screenshot_type: str              # "NATIVE_WINDOW", "NATIVE_DESKTOP", "WEBVIEW_VIEWPORT", "ELEMENT_CROP"
    coordinate_space: str             # "SCREEN_PHYSICAL", "WINDOW_EXTENDED_FRAME", "VIEWPORT_LOGICAL"
    dimensions: Tuple[int, int]       # (width, height) in pixels
    pixel_format: str = "RGBA"
    capture_bounds: Tuple[int, int, int, int] = (0, 0, 0, 0) # (x, y, w, h)
    dpi_context: float = 1.0
    target_hwnd: Optional[int] = None
    sha256: str = ""
    relative_path: str = ""
    is_thumbnail: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "screenshot_id": self.screenshot_id,
            "screenshot_type": self.screenshot_type,
            "coordinate_space": self.coordinate_space,
            "dimensions": list(self.dimensions),
            "pixel_format": self.pixel_format,
            "capture_bounds": list(self.capture_bounds),
            "dpi_context": self.dpi_context,
            "target_hwnd": hex(self.target_hwnd) if self.target_hwnd else None,
            "sha256": self.sha256,
            "relative_path": self.relative_path,
            "is_thumbnail": self.is_thumbnail,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class EvidenceManifest:
    """
    Machine-verifiable, cryptographically sealed Evidence Manifest for an action or review session.
    Reproducible from collected evidence and self-verifying via SHA-256 manifest hash.
    """
    manifest_id: str
    session_id: str
    action_id: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_timestamp: float = field(default_factory=time.time)
    monotonic_sequence: int = 1
    proof_level: ProofLevel = ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF
    verdict: VerificationVerdict = VerificationVerdict.PASS
    verdict_rationale: str = ""
    unverified_reason: Optional[UnverifiedReason] = None
    pre_state_epoch: Optional[int] = None
    post_state_epoch: Optional[int] = None
    claims: Tuple[VerificationClaim, ...] = field(default_factory=tuple)
    evidence_chain: Tuple[str, ...] = field(default_factory=tuple)
    artifacts: Tuple[EvidenceArtifact, ...] = field(default_factory=tuple)
    manifest_hash: Optional[str] = None
    manifest_version: str = "2.0.0"
    schema_version: str = "https://desktop-webview-reviewer.org/schemas/evidence-manifest-v2.json"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_hash: bool = True) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "$schema": self.schema_version,
            "manifest_version": self.manifest_version,
            "manifest_id": self.manifest_id,
            "session_id": self.session_id,
            "action_id": self.action_id,
            "created_at": self.created_at,
            "created_timestamp": self.created_timestamp,
            "monotonic_sequence": self.monotonic_sequence,
            "proof_level": self.proof_level.value if isinstance(self.proof_level, ProofLevel) else str(self.proof_level),
            "verdict": self.verdict.value if isinstance(self.verdict, VerificationVerdict) else str(self.verdict),
            "verdict_rationale": self.verdict_rationale,
            "unverified_reason": self.unverified_reason.value if self.unverified_reason else None,
            "pre_state_epoch": self.pre_state_epoch,
            "post_state_epoch": self.post_state_epoch,
            "claims": [c.to_dict() for c in self.claims],
            "evidence_chain": list(self.evidence_chain),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "details": self.details,
        }
        if include_hash:
            d["manifest_hash"] = self.manifest_hash or self.compute_manifest_hash()
        return d

    def compute_manifest_hash(self) -> str:
        """
        Calculates deterministic SHA-256 of canonical JSON without the manifest_hash field.
        """
        canonical_dict = self.to_dict(include_hash=False)
        canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceManifest:
        proof_lvl = ProofLevel(data["proof_level"]) if data.get("proof_level") in ProofLevel._value2member_map_ else ProofLevel(data["proof_level"])
        verdict = VerificationVerdict(data["verdict"]) if data.get("verdict") in VerificationVerdict._value2member_map_ else VerificationVerdict(data["verdict"])
        uv_reason = UnverifiedReason(data["unverified_reason"]) if data.get("unverified_reason") in UnverifiedReason._value2member_map_ else None
        claims = tuple(VerificationClaim.from_dict(c) for c in data.get("claims", []))
        artifacts = tuple(EvidenceArtifact.from_dict(a) for a in data.get("artifacts", []))
        return cls(
            manifest_id=data["manifest_id"],
            session_id=data["session_id"],
            action_id=data["action_id"],
            created_at=data["created_at"],
            created_timestamp=data.get("created_timestamp", 0.0),
            monotonic_sequence=data.get("monotonic_sequence", 0),
            proof_level=proof_lvl,
            verdict=verdict,
            verdict_rationale=data.get("verdict_rationale", ""),
            unverified_reason=uv_reason,
            pre_state_epoch=data.get("pre_state_epoch"),
            post_state_epoch=data.get("post_state_epoch"),
            claims=claims,
            evidence_chain=tuple(data.get("evidence_chain", [])),
            artifacts=artifacts,
            manifest_hash=data.get("manifest_hash"),
            manifest_version=data.get("manifest_version", "2.0.0"),
            schema_version=data.get("schema_version", "https://desktop-webview-reviewer.org/schemas/evidence-manifest-v2.json"),
            details=data.get("details", {}),
        )
