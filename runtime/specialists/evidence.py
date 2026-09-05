"""
Evidence Specialist Subagent (Architecture H / Phase 15).
Mandate: "Can we cryptographically prove what happened?"
Audits evidence packages, validates EvidenceManifests, verifies SHA-256 artifact hashes,
checks byte-level immutability, and detects tampering or missing proof.
Strictly an immutable auditor; never modifies artifacts, suppresses UNVERIFIED, or fakes hashes.
"""

from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import (
    SpecialistLifecycleState,
    SpecialistResultStatus,
    SpecialistResult,
)
from runtime.specialists.base import BaseSpecialistRuntime
from runtime.evidence_models import VerificationVerdict

logger = logging.getLogger("desktop_webview.specialist.evidence")


class EvidenceSpecialist(BaseSpecialistRuntime):
    """Subordinate specialist answering: 'Can we cryptographically prove what happened?'"""

    @property
    def role(self) -> SpecialistRole:
        return SpecialistRole.EVIDENCE_SPECIALIST

    async def execute(self) -> SpecialistResult:
        self._record_lifecycle(SpecialistLifecycleState.OBSERVING, "Auditing cryptographic evidence integrity.")

        session_id = self.session_state.session_id
        action_id = self.delegation.parameters.get("action_id") or self.delegation.parent_action_id
        evidence_store = getattr(self.session_state, "evidence_store", None)

        if not evidence_store:
            # Try default EvidenceStore
            from runtime.evidence_store import EvidenceStore
            evidence_store = EvidenceStore()

        manifest_found = False
        manifest_id = "unknown"
        verdict = "UNKNOWN"
        violations: List[str] = []
        missing_artifacts: List[str] = []
        tampered_artifacts: List[str] = []
        verified_artifacts_count = 0
        total_artifacts_count = 0
        evidence_refs: List[str] = []
        trace_refs: List[str] = []
        limitations: List[str] = []

        manifest_path_param = self.delegation.parameters.get("manifest_path")

        # ---------------------------------------------------------------------
        # 1. Locate and Verify Manifest
        # ---------------------------------------------------------------------
        target_manifest = None
        if manifest_path_param and Path(manifest_path_param).exists():
            target_path = Path(manifest_path_param)
            try:
                target_manifest = evidence_store.load_manifest(target_path)
                manifest_found = True
            except Exception as e:
                violations.append(f"Failed to load manifest at '{manifest_path_param}': {e}")
        elif action_id:
            try:
                action_dir = evidence_store.get_action_dir(session_id, action_id, create=False)
                manifest_file = action_dir / "manifest.json"
                if manifest_file.exists():
                    target_manifest = evidence_store.load_manifest(manifest_file)
                    manifest_found = True
            except Exception as e:
                limitations.append(f"Could not locate action directory: {e}")

        # ---------------------------------------------------------------------
        # 2. Cryptographic Integrity Audit
        # ---------------------------------------------------------------------
        if target_manifest:
            manifest_id = target_manifest.manifest_id
            verdict = target_manifest.verdict.value if hasattr(target_manifest.verdict, "value") else str(target_manifest.verdict)
            total_artifacts_count = len(target_manifest.artifacts)

            async def _verify():
                return evidence_store.verify_manifest_integrity(target_manifest)

            try:
                is_valid, check_violations = await self.invoke_tool("desktop_verify_manifest", _verify)
                if not is_valid:
                    violations.extend(check_violations)
                    for v in check_violations:
                        if "tampering" in v.lower():
                            tampered_artifacts.append(v)
                        elif "missing" in v.lower():
                            missing_artifacts.append(v)
                else:
                    verified_artifacts_count = total_artifacts_count
            except Exception as e:
                violations.append(f"Manifest verification tool error: {e}")

            evidence_refs.append(manifest_id)
            for art in target_manifest.artifacts:
                evidence_refs.append(f"{art.artifact_id}:{art.relative_path}")
        else:
            limitations.append(f"No evidence manifest found for session '{session_id}', action '{action_id}'.")

        # ---------------------------------------------------------------------
        # 3. Assemble Audit Verdict
        # ---------------------------------------------------------------------
        if not manifest_found:
            status = SpecialistResultStatus.UNVERIFIED
            answer = f"Evidence Specialist found no cryptographic manifest for action '{action_id}'. Audit state is UNVERIFIED."
        elif violations:
            status = SpecialistResultStatus.FAILED
            tamper_msg = f" ({len(tampered_artifacts)} tamper violation(s))" if tampered_artifacts else ""
            missing_msg = f" ({len(missing_artifacts)} missing file(s))" if missing_artifacts else ""
            answer = f"Cryptographic evidence audit FAILED for manifest '{manifest_id}'{tamper_msg}{missing_msg}."
        else:
            status = SpecialistResultStatus.SUCCESS
            answer = (
                f"Evidence manifest '{manifest_id}' cryptographically verified with {verified_artifacts_count} "
                f"unaltered artifact(s). Authoritative verdict: {verdict}."
            )

        return SpecialistResult(
            specialist_id=self.specialist_id,
            role=self.role,
            delegation_id=self.delegation.delegation_id,
            session_id=session_id,
            status=status,
            answer=answer,
            observations={
                "manifest_found": manifest_found,
                "manifest_id": manifest_id,
                "verdict": verdict,
                "total_artifacts": total_artifacts_count,
                "verified_artifacts": verified_artifacts_count,
                "tampered_artifacts": tampered_artifacts,
                "missing_artifacts": missing_artifacts,
                "violations": violations,
                "cryptographic_proof": "VERIFIED" if (manifest_found and not violations) else ("TAMPERED" if tampered_artifacts else "INCOMPLETE"),
            },
            evidence_refs=evidence_refs,
            trace_refs=trace_refs,
            limitations=limitations,
            errors=violations,
            confidence=1.0 if manifest_found and not violations else (0.9 if violations else 0.0),
        )
