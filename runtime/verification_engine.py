"""
Deterministic Verification Engine & Tripartite Proof Evaluator (Architecture H).
Evaluates action-observation transactions, enforces Physical Reality Primacy,
reconciles dual perspectives, detects contradictions, checks epoch/target continuity,
and produces cryptographically verifiable EvidenceManifests with PASS/FAIL/UNVERIFIED verdicts.
Strictly deterministic: Zero LLM, zero probabilistic heuristics.
"""

from __future__ import annotations
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any, Sequence, Set

from runtime.state import TargetPlane
from runtime.evidence_models import (
    VerificationVerdict,
    ProofLevel,
    EvidenceType,
    ClaimType,
    UnverifiedReason,
    EvidenceItem,
    VerificationClaim,
    EvidenceArtifact,
    ScreenshotEvidence,
    EvidenceManifest,
)
from runtime.evidence_store import EvidenceStore
from runtime.action_models import (
    ActionRequest,
    ActionReceipt,
    ActionOutcome,
    DispatchStatus,
    StateChangeClassification,
)
from runtime.observation_models import (
    DualPerspectiveSnapshot,
    NativeObservation,
    WebObservation,
    ReconciliationObservation,
)
from runtime.observation_diff import ObservationDiffResult, DiffItem

logger = logging.getLogger("desktop_webview.verification_engine")


class VerificationEngine:
    """
    Authoritative verification evaluator for Desktop WebView Reviewer.
    Transforms raw transaction traces and dual-perspective observations into
    formal proof evaluations and cryptographically sealed evidence manifests.
    """

    def __init__(
        self,
        evidence_store: Optional[EvidenceStore] = None,
        default_proof_level: ProofLevel = ProofLevel.LEVEL_3_DUAL_PERSPECTIVE_PROOF,
        require_visible_gui: bool = True,
    ):
        self.evidence_store = evidence_store or EvidenceStore()
        self.default_proof_level = default_proof_level
        self.require_visible_gui = require_visible_gui
        self._monotonic_seq = 0

    def evaluate_transaction(
        self,
        session_id: str,
        action_request: ActionRequest,
        action_receipt: ActionReceipt,
        action_outcome: ActionOutcome,
        pre_snapshot: Optional[DualPerspectiveSnapshot] = None,
        post_snapshot: Optional[DualPerspectiveSnapshot] = None,
        observation_diff: Optional[ObservationDiffResult] = None,
        native_screenshot: Optional[ScreenshotEvidence] = None,
        webview_screenshot: Optional[ScreenshotEvidence] = None,
        target_process_info: Optional[Dict[str, Any]] = None,
        execution_mode: str = "automated", # "automated" | "interactive"
        user_confirmed: bool = False,
        required_proof_level: Optional[ProofLevel] = None,
    ) -> Tuple[VerificationVerdict, EvidenceManifest, List[EvidenceItem]]:
        """
        Main entry point for transaction verification:
        1. Normalizes all inputs into immutable EvidenceItems.
        2. Executes structured contradiction detection across native and web planes.
        3. Evaluates discrete verification claims.
        4. Enforces Physical Reality Primacy and Proof Level adequacy.
        5. Computes overall tripartite verdict (PASS, FAIL, UNVERIFIED).
        6. Assembles and cryptographically seals the EvidenceManifest.
        """
        self._monotonic_seq += 1
        proof_lvl = required_proof_level or self.default_proof_level
        action_id = action_request.action_id
        current_epoch = post_snapshot.epoch if post_snapshot else action_outcome.post_epoch
        pre_epoch = pre_snapshot.epoch if pre_snapshot else action_outcome.pre_epoch

        evidence_items: List[EvidenceItem] = []
        contradictions: List[str] = []

        # ---------------------------------------------------------------------
        # 1. Normalize Evidence Items
        # ---------------------------------------------------------------------

        # 1.1 Action Receipt Evidence
        receipt_hash = hashlib.sha256(json.dumps(action_receipt.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()
        evidence_items.append(EvidenceItem(
            evidence_id=f"ev_rec_{uuid.uuid4().hex[:8]}",
            evidence_type=EvidenceType.ACTION_RECEIPT,
            timestamp=action_receipt.dispatch_timestamp,
            monotonic_time=time.monotonic(),
            session_id=session_id,
            action_id=action_id,
            epoch=action_receipt.epoch,
            source_plane=action_receipt.plane,
            source_component="ActionExecutionEngine",
            integrity_hash=receipt_hash,
            metadata=action_receipt.to_dict(),
        ))

        # 1.2 Action Outcome Evidence
        outcome_hash = hashlib.sha256(json.dumps(action_outcome.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()
        evidence_items.append(EvidenceItem(
            evidence_id=f"ev_out_{uuid.uuid4().hex[:8]}",
            evidence_type=EvidenceType.ACTION_OUTCOME,
            timestamp=action_outcome.timestamp,
            monotonic_time=time.monotonic(),
            session_id=session_id,
            action_id=action_id,
            epoch=action_outcome.post_epoch,
            source_plane=action_receipt.plane,
            source_component="ActionExecutionEngine",
            integrity_hash=outcome_hash,
            metadata=action_outcome.to_dict(),
        ))

        # 1.3 Native Physical Evidence
        native_obs = post_snapshot.native_observation if post_snapshot else (
            pre_snapshot.native_observation if pre_snapshot else None
        )
        if native_obs:
            nat_hash = hashlib.sha256(json.dumps(native_obs.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()
            evidence_items.append(EvidenceItem(
                evidence_id=f"ev_nat_{uuid.uuid4().hex[:8]}",
                evidence_type=EvidenceType.NATIVE_WINDOW_STATE,
                timestamp=time.time(),
                monotonic_time=time.monotonic(),
                session_id=session_id,
                action_id=action_id,
                epoch=current_epoch,
                source_plane=TargetPlane.NATIVE_SHELL,
                source_component="NativeSupervisor",
                integrity_hash=nat_hash,
                metadata={
                    "hwnd": hex(native_obs.hwnd) if native_obs.hwnd else None,
                    "pid": native_obs.pid,
                    "is_visible": native_obs.is_visible,
                    "is_iconic": getattr(native_obs, "is_iconic", getattr(native_obs, "is_minimized", False)),
                    "is_cloaked": native_obs.is_cloaked,
                    "is_responsive": native_obs.is_responsive,
                    "bounds": native_obs.bounds.to_dict(),
                    "modal_dialogs": [m if isinstance(m, dict) else getattr(m, "to_dict", lambda: m)() for m in native_obs.modal_dialogs],
                },
            ))

        # 1.4 Web Observation Evidence
        web_obs = post_snapshot.web_observation if post_snapshot else None
        if web_obs:
            web_hash = hashlib.sha256(json.dumps(web_obs.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()
            evidence_items.append(EvidenceItem(
                evidence_id=f"ev_web_{uuid.uuid4().hex[:8]}",
                evidence_type=EvidenceType.WEB_DOM_SNAPSHOT,
                timestamp=time.time(),
                monotonic_time=time.monotonic(),
                session_id=session_id,
                action_id=action_id,
                epoch=current_epoch,
                source_plane=TargetPlane.WEBVIEW_DOM,
                source_component="WebviewAutomationCore",
                integrity_hash=web_hash,
                metadata={
                    "target_id": getattr(web_obs, "target_id", ""),
                    "frame_id": getattr(web_obs, "root_frame_id", getattr(web_obs, "frame_id", "")),
                    "element_count": len(web_obs.elements),
                    "url": getattr(web_obs, "target_url", getattr(web_obs, "url", "")),
                    "title": getattr(web_obs, "target_title", getattr(web_obs, "title", "")),
                },
            ))

        # 1.5 Observation Diff Evidence
        if observation_diff:
            diff_hash = hashlib.sha256(json.dumps(observation_diff.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()
            evidence_items.append(EvidenceItem(
                evidence_id=f"ev_diff_{uuid.uuid4().hex[:8]}",
                evidence_type=EvidenceType.OBSERVATION_DIFF,
                timestamp=time.time(),
                monotonic_time=time.monotonic(),
                session_id=session_id,
                action_id=action_id,
                epoch=current_epoch,
                source_plane=action_receipt.plane,
                source_component="ObservationDiffer",
                integrity_hash=diff_hash,
                metadata=observation_diff.to_dict(),
            ))

        # 1.6 Screenshot Evidence
        if native_screenshot:
            evidence_items.append(EvidenceItem(
                evidence_id=f"ev_snat_{uuid.uuid4().hex[:8]}",
                evidence_type=EvidenceType.NATIVE_SCREENSHOT,
                timestamp=native_screenshot.timestamp,
                monotonic_time=time.monotonic(),
                session_id=session_id,
                action_id=action_id,
                epoch=current_epoch,
                source_plane=TargetPlane.NATIVE_SHELL,
                source_component="WindowForensicsEngine",
                integrity_hash=native_screenshot.sha256,
                payload_reference=native_screenshot.relative_path,
                metadata=native_screenshot.to_dict(),
            ))

        if webview_screenshot:
            evidence_items.append(EvidenceItem(
                evidence_id=f"ev_sweb_{uuid.uuid4().hex[:8]}",
                evidence_type=EvidenceType.WEB_AX_SNAPSHOT,
                timestamp=webview_screenshot.timestamp,
                monotonic_time=time.monotonic(),
                session_id=session_id,
                action_id=action_id,
                epoch=current_epoch,
                source_plane=TargetPlane.WEBVIEW_DOM,
                source_component="CDPSession",
                integrity_hash=webview_screenshot.sha256,
                payload_reference=webview_screenshot.relative_path,
                metadata=webview_screenshot.to_dict(),
            ))

        # 1.7 Process Identity Evidence
        if target_process_info:
            proc_hash = hashlib.sha256(json.dumps(target_process_info, sort_keys=True).encode("utf-8")).hexdigest()
            evidence_items.append(EvidenceItem(
                evidence_id=f"ev_proc_{uuid.uuid4().hex[:8]}",
                evidence_type=EvidenceType.PROCESS_IDENTITY,
                timestamp=time.time(),
                monotonic_time=time.monotonic(),
                session_id=session_id,
                action_id=action_id,
                epoch=current_epoch,
                source_plane=TargetPlane.NATIVE_SHELL,
                source_component="ProcessSupervisor",
                integrity_hash=proc_hash,
                metadata=target_process_info,
            ))

        # ---------------------------------------------------------------------
        # 2. Contradiction Detection
        # ---------------------------------------------------------------------
        # 2.1 DOM claims visibility but Native is iconic / cloaked / hidden
        if web_obs and native_obs:
            is_min = getattr(native_obs, "is_iconic", getattr(native_obs, "is_minimized", False))
            if is_min or native_obs.is_cloaked or not native_obs.is_visible:
                has_web_visible = any(e.visibility.visible for e in web_obs.elements if e.visibility)
                if has_web_visible:
                    msg = (
                        f"Contradiction: Chromium reports visible DOM elements, but Native OS reports window is "
                        f"(iconic={is_min}, cloaked={native_obs.is_cloaked}, visible={native_obs.is_visible})."
                    )
                    contradictions.append(msg)

            # 2.2 DOM claims enabled but Native modal blocks window
            if native_obs.modal_dialogs:
                modal_names = [m.get("title", str(m)) if isinstance(m, dict) else getattr(m, "title", str(m)) for m in native_obs.modal_dialogs]
                msg = f"Contradiction: Native modal dialog(s) {modal_names} occlude and block the window."
                contradictions.append(msg)

        # 2.3 Action Receipt says dispatched, but target process exited before post-observation
        if action_receipt.dispatch_status == DispatchStatus.DISPATCHED:
            if target_process_info and not target_process_info.get("is_running", True):
                msg = "Contradiction: Action was dispatched, but target process terminated prematurely."
                contradictions.append(msg)

        # Record contradictions as evidence items
        for c in contradictions:
            c_hash = hashlib.sha256(c.encode("utf-8")).hexdigest()
            evidence_items.append(EvidenceItem(
                evidence_id=f"ev_contra_{uuid.uuid4().hex[:8]}",
                evidence_type=EvidenceType.CONTRADICTION,
                timestamp=time.time(),
                monotonic_time=time.monotonic(),
                session_id=session_id,
                action_id=action_id,
                epoch=current_epoch,
                source_plane=action_receipt.plane,
                source_component="VerificationEngine",
                integrity_hash=c_hash,
                metadata={"description": c},
            ))

        # ---------------------------------------------------------------------
        # 3. Evaluate Verification Claims
        # ---------------------------------------------------------------------
        claims: List[VerificationClaim] = []

        # Claim 1: ActionWasDispatched
        claim_dispatch = self._evaluate_claim_dispatch(session_id, action_id, pre_epoch, action_receipt, evidence_items)
        claims.append(claim_dispatch)

        # Claim 2: TargetWasPhysicallyVisible
        claim_vis = self._evaluate_claim_physical_visibility(
            session_id, action_id, current_epoch, native_obs, target_process_info, evidence_items
        )
        claims.append(claim_vis)

        # Claim 3: InputReachedTarget
        claim_input = self._evaluate_claim_input_reached_target(
            session_id, action_id, current_epoch, action_receipt, claim_dispatch, claim_vis, native_obs, contradictions, evidence_items
        )
        claims.append(claim_input)

        # Claim 4: ExpectedStateOccurred
        claim_state = self._evaluate_claim_expected_state(
            session_id,
            action_id,
            current_epoch,
            action_request,
            action_outcome,
            pre_snapshot,
            post_snapshot,
            observation_diff,
            contradictions,
            evidence_items,
        )
        claims.append(claim_state)

        # Optional Claim 5: Specific action semantic claim (Navigation, Modal, etc.)
        expected_claim = action_request.params.get("expected_claim") if action_request.params else None
        expected_url = action_request.params.get("expected_url") if action_request.params else None
        if (
            action_outcome.state_change == StateChangeClassification.NAVIGATED
            or expected_claim in (ClaimType.NavigationOccurred, "NavigationOccurred")
            or expected_url is not None
        ):
            claim_nav = self._evaluate_claim_navigation(
                session_id, action_id, current_epoch, action_outcome.navigation_url, pre_snapshot, post_snapshot, evidence_items, expected_url=expected_url
            )
            claims.append(claim_nav)
        elif (
            action_outcome.state_change == StateChangeClassification.MODAL_APPEARED
            or expected_claim in (ClaimType.NativeModalAppeared, "NativeModalAppeared")
        ):
            claim_mod = self._evaluate_claim_modal(
                session_id, action_id, current_epoch, native_obs, evidence_items
            )
            claims.append(claim_mod)
        elif (
            action_outcome.state_change == StateChangeClassification.TARGET_DISAPPEARED
            or expected_claim in (ClaimType.ElementDisappeared, "ElementDisappeared")
        ):
            claim_disapp = self._evaluate_claim_element_disappeared(
                session_id, action_id, current_epoch, action_request.reference, pre_snapshot, post_snapshot, evidence_items
            )
            claims.append(claim_disapp)

        # ---------------------------------------------------------------------
        # 4. Synthesize Final Verdict
        # ---------------------------------------------------------------------
        verdict, rationale, unverified_reason = self._synthesize_verdict(
            claims=claims,
            contradictions=contradictions,
            proof_level=proof_lvl,
            native_screenshot=native_screenshot,
            webview_screenshot=webview_screenshot,
            execution_mode=execution_mode,
            user_confirmed=user_confirmed,
        )

        # ---------------------------------------------------------------------
        # 5. Build Artifact List & Persist Evidence Manifest
        # ---------------------------------------------------------------------
        now_dt = datetime.now(timezone.utc)
        created_iso = now_dt.isoformat().replace("+00:00", "Z")
        now_ts = now_dt.timestamp()

        # Gather artifacts that were created
        artifacts_list: List[EvidenceArtifact] = []

        # Store action receipt JSON artifact
        art_receipt = self.evidence_store.store_json(
            session_id=session_id,
            action_id=action_id,
            relative_path="receipts/action_receipt.json",
            obj=action_receipt.to_dict(),
        )
        artifacts_list.append(art_receipt)

        # Store action outcome JSON artifact
        art_outcome = self.evidence_store.store_json(
            session_id=session_id,
            action_id=action_id,
            relative_path="receipts/action_outcome.json",
            obj=action_outcome.to_dict(),
        )
        artifacts_list.append(art_outcome)

        # Store diff artifact if present
        if observation_diff:
            art_diff = self.evidence_store.store_json(
                session_id=session_id,
                action_id=action_id,
                relative_path="diffs/observation_diff.json",
                obj=observation_diff.to_dict(),
            )
            artifacts_list.append(art_diff)

        # Store screenshots metadata / link artifacts
        if native_screenshot and native_screenshot.relative_path:
            art_snat = EvidenceArtifact(
                artifact_id=f"art_snat_{uuid.uuid4().hex[:8]}",
                filename=native_screenshot.relative_path.split("/")[-1],
                mime_type="image/png",
                sha256=native_screenshot.sha256,
                size_bytes=0,
                created_at=native_screenshot.timestamp,
                relative_path=native_screenshot.relative_path,
                metadata=native_screenshot.to_dict(),
            )
            artifacts_list.append(art_snat)

        if webview_screenshot and webview_screenshot.relative_path:
            art_sweb = EvidenceArtifact(
                artifact_id=f"art_sweb_{uuid.uuid4().hex[:8]}",
                filename=webview_screenshot.relative_path.split("/")[-1],
                mime_type="image/png",
                sha256=webview_screenshot.sha256,
                size_bytes=0,
                created_at=webview_screenshot.timestamp,
                relative_path=webview_screenshot.relative_path,
                metadata=webview_screenshot.to_dict(),
            )
            artifacts_list.append(art_sweb)

        # Evidence chain
        chain = tuple(e.evidence_id for e in evidence_items)

        manifest = EvidenceManifest(
            manifest_id=f"man_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            action_id=action_id,
            created_at=created_iso,
            created_timestamp=now_ts,
            monotonic_sequence=self._monotonic_seq,
            proof_level=proof_lvl,
            verdict=verdict,
            verdict_rationale=rationale,
            unverified_reason=unverified_reason,
            pre_state_epoch=pre_epoch,
            post_state_epoch=current_epoch,
            claims=tuple(claims),
            evidence_chain=chain,
            artifacts=tuple(artifacts_list),
            details={
                "execution_mode": execution_mode,
                "user_confirmed": user_confirmed,
                "contradiction_count": len(contradictions),
                "contradictions": contradictions,
            },
        )

        # Persist manifest and compute hash
        _, manifest_hash = self.evidence_store.store_manifest(manifest)
        # Update manifest object with its sealed hash
        sealed_manifest = EvidenceManifest(
            manifest_id=manifest.manifest_id,
            session_id=manifest.session_id,
            action_id=manifest.action_id,
            created_at=manifest.created_at,
            created_timestamp=manifest.created_timestamp,
            monotonic_sequence=manifest.monotonic_sequence,
            proof_level=manifest.proof_level,
            verdict=manifest.verdict,
            verdict_rationale=manifest.verdict_rationale,
            unverified_reason=manifest.unverified_reason,
            pre_state_epoch=manifest.pre_state_epoch,
            post_state_epoch=manifest.post_state_epoch,
            claims=manifest.claims,
            evidence_chain=manifest.evidence_chain,
            artifacts=manifest.artifacts,
            manifest_hash=manifest_hash,
            manifest_version=manifest.manifest_version,
            schema_version=manifest.schema_version,
            details=manifest.details,
        )

        return verdict, sealed_manifest, evidence_items

    # -------------------------------------------------------------------------
    # Claim Evaluators
    # -------------------------------------------------------------------------

    def _evaluate_claim_dispatch(
        self,
        session_id: str,
        action_id: str,
        epoch: int,
        receipt: ActionReceipt,
        evidence: List[EvidenceItem],
    ) -> VerificationClaim:
        ev_refs = [e.evidence_id for e in evidence if e.evidence_type == EvidenceType.ACTION_RECEIPT]

        if receipt.dispatch_status == DispatchStatus.DISPATCHED:
            return VerificationClaim(
                claim_id=f"clm_disp_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.ActionWasDispatched,
                expected=DispatchStatus.DISPATCHED.value,
                actual=receipt.dispatch_status.value,
                status=VerificationVerdict.PASS,
                confidence=1.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Action successfully dispatched via {receipt.dispatch_method.value} in {receipt.duration_ms:.2f}ms.",
            )
        elif receipt.dispatch_status == DispatchStatus.REJECTED:
            return VerificationClaim(
                claim_id=f"clm_disp_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.ActionWasDispatched,
                expected=DispatchStatus.DISPATCHED.value,
                actual=receipt.dispatch_status.value,
                status=VerificationVerdict.FAIL,
                confidence=1.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Action dispatch rejected: {receipt.error or receipt.precondition_summary}",
            )
        else:
            return VerificationClaim(
                claim_id=f"clm_disp_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.ActionWasDispatched,
                expected=DispatchStatus.DISPATCHED.value,
                actual=receipt.dispatch_status.value,
                status=VerificationVerdict.FAIL,
                confidence=1.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Action dispatch failed: {receipt.error}",
            )

    def _evaluate_claim_physical_visibility(
        self,
        session_id: str,
        action_id: str,
        epoch: int,
        native_obs: Optional[NativeObservation],
        proc_info: Optional[Dict[str, Any]],
        evidence: List[EvidenceItem],
    ) -> VerificationClaim:
        ev_refs = [e.evidence_id for e in evidence if e.evidence_type in (EvidenceType.NATIVE_WINDOW_STATE, EvidenceType.PROCESS_IDENTITY)]

        if not self.require_visible_gui:
            return VerificationClaim(
                claim_id=f"clm_vis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.TargetWasPhysicallyVisible,
                expected=True,
                actual=True,
                status=VerificationVerdict.PASS,
                confidence=0.8,
                evidence_refs=tuple(ev_refs),
                reason="Physical GUI visibility requirement waived by policy.",
            )

        if not native_obs:
            return VerificationClaim(
                claim_id=f"clm_vis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.TargetWasPhysicallyVisible,
                expected=True,
                actual=None,
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason="No native OS window forensics available; visible desktop GUI could not be proven.",
                unverified_reason=UnverifiedReason.PHYSICAL_STATE_UNKNOWN,
            )

        if not native_obs.hwnd:
            return VerificationClaim(
                claim_id=f"clm_vis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.TargetWasPhysicallyVisible,
                expected=True,
                actual=None,
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason="No top-level window handle (HWND) found for application process tree.",
                unverified_reason=UnverifiedReason.PHYSICAL_STATE_UNKNOWN,
            )

        if not native_obs.is_visible:
            return VerificationClaim(
                claim_id=f"clm_vis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.TargetWasPhysicallyVisible,
                expected=True,
                actual=False,
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Application window (HWND {hex(native_obs.hwnd)}) is not visible on desktop (IsWindowVisible=False).",
                unverified_reason=UnverifiedReason.PHYSICAL_STATE_UNKNOWN,
            )

        is_min = getattr(native_obs, "is_iconic", getattr(native_obs, "is_minimized", False))
        if is_min:
            return VerificationClaim(
                claim_id=f"clm_vis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.TargetWasPhysicallyVisible,
                expected=True,
                actual="minimized",
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Application window (HWND {hex(native_obs.hwnd)}) is minimized (IsIconic=True).",
                unverified_reason=UnverifiedReason.WINDOW_CLOAKED_OR_MINIMIZED,
            )

        if native_obs.is_cloaked:
            return VerificationClaim(
                claim_id=f"clm_vis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.TargetWasPhysicallyVisible,
                expected=True,
                actual="cloaked",
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Application window (HWND {hex(native_obs.hwnd)}) is cloaked by Windows DWM.",
                unverified_reason=UnverifiedReason.WINDOW_CLOAKED_OR_MINIMIZED,
            )

        width = native_obs.bounds.width
        height = native_obs.bounds.height
        if width < 30 or height < 30:
            return VerificationClaim(
                claim_id=f"clm_vis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.TargetWasPhysicallyVisible,
                expected="renderable geometry (>=30x30)",
                actual=f"{width}x{height}",
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Application window has non-renderable or zero geometry ({width}x{height}).",
                unverified_reason=UnverifiedReason.WINDOW_NON_RENDERABLE,
            )

        # PID verification
        if proc_info and proc_info.get("pid"):
            expected_pid = proc_info["pid"]
            if native_obs.pid and native_obs.pid != expected_pid:
                # PID tree check
                tree_pids = set(proc_info.get("process_tree", [expected_pid]))
                if native_obs.pid not in tree_pids:
                    return VerificationClaim(
                        claim_id=f"clm_vis_{uuid.uuid4().hex[:8]}",
                        session_id=session_id,
                        action_id=action_id,
                        observation_epoch=epoch,
                        claim_type=ClaimType.TargetWasPhysicallyVisible,
                        expected=f"PID in {tree_pids}",
                        actual=native_obs.pid,
                        status=VerificationVerdict.UNVERIFIED,
                        confidence=0.0,
                        evidence_refs=tuple(ev_refs),
                        reason=f"Window owning PID ({native_obs.pid}) does not match expected application process tree.",
                        unverified_reason=UnverifiedReason.PID_MISMATCH,
                    )

        return VerificationClaim(
            claim_id=f"clm_vis_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            action_id=action_id,
            observation_epoch=epoch,
            claim_type=ClaimType.TargetWasPhysicallyVisible,
            expected=True,
            actual=True,
            status=VerificationVerdict.PASS,
            confidence=1.0,
            evidence_refs=tuple(ev_refs),
            reason=f"Physical window HWND {hex(native_obs.hwnd)} confirmed visible, non-minimized, and uncloaked on desktop.",
        )

    def _evaluate_claim_input_reached_target(
        self,
        session_id: str,
        action_id: str,
        epoch: int,
        receipt: ActionReceipt,
        claim_dispatch: VerificationClaim,
        claim_visibility: VerificationClaim,
        native_obs: Optional[NativeObservation],
        contradictions: List[str],
        evidence: List[EvidenceItem],
    ) -> VerificationClaim:
        ev_refs = [claim_dispatch.claim_id, claim_visibility.claim_id]

        if claim_dispatch.status != VerificationVerdict.PASS:
            return VerificationClaim(
                claim_id=f"clm_in_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.InputReachedTarget,
                expected="Dispatch PASS",
                actual=f"Dispatch {claim_dispatch.status.value}",
                status=claim_dispatch.status,
                confidence=1.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Input could not reach target because dispatch failed: {claim_dispatch.reason}",
            )

        if self.require_visible_gui and claim_visibility.status != VerificationVerdict.PASS:
            return VerificationClaim(
                claim_id=f"clm_in_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.InputReachedTarget,
                expected="Physical GUI Visible",
                actual=f"Visibility {claim_visibility.status.value}",
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Input delivery cannot be proven because physical window is not visible: {claim_visibility.reason}",
                unverified_reason=claim_visibility.unverified_reason or UnverifiedReason.PHYSICAL_STATE_UNKNOWN,
            )

        if contradictions:
            return VerificationClaim(
                claim_id=f"clm_in_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.InputReachedTarget,
                expected="Uncontradicted delivery",
                actual="Contradictions present",
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Contradictory state detected: {'; '.join(contradictions)}",
                unverified_reason=UnverifiedReason.CONTRADICTORY_EVIDENCE,
            )

        return VerificationClaim(
            claim_id=f"clm_in_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            action_id=action_id,
            observation_epoch=epoch,
            claim_type=ClaimType.InputReachedTarget,
            expected="Delivered to target coordinates",
            actual=receipt.coordinates,
            status=VerificationVerdict.PASS,
            confidence=0.95,
            evidence_refs=tuple(ev_refs),
            reason=f"Input delivery proven: valid dispatch to {receipt.coordinates} while target window remained visible and responsive.",
        )

    def _evaluate_claim_expected_state(
        self,
        session_id: str,
        action_id: str,
        epoch: int,
        request: ActionRequest,
        outcome: ActionOutcome,
        pre_snapshot: Optional[DualPerspectiveSnapshot],
        post_snapshot: Optional[DualPerspectiveSnapshot],
        diff: Optional[ObservationDiffResult],
        contradictions: List[str],
        evidence: List[EvidenceItem],
    ) -> VerificationClaim:
        ev_refs = [e.evidence_id for e in evidence if e.evidence_type in (EvidenceType.ACTION_OUTCOME, EvidenceType.OBSERVATION_DIFF)]

        expected_effect = request.params.get("expect_change", True)

        if not pre_snapshot:
            return VerificationClaim(
                claim_id=f"clm_state_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.ExpectedStateOccurred,
                expected="Pre-state observation present",
                actual=None,
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason="Pre-state observation snapshot missing; cannot prove functional state mutation.",
                unverified_reason=UnverifiedReason.PRE_STATE_MISSING,
            )

        if not post_snapshot:
            return VerificationClaim(
                claim_id=f"clm_state_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.ExpectedStateOccurred,
                expected="Post-state observation present",
                actual=None,
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason="Post-state observation snapshot missing; cannot establish outcome state.",
                unverified_reason=UnverifiedReason.POST_STATE_MISSING,
            )

        if contradictions:
            return VerificationClaim(
                claim_id=f"clm_state_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.ExpectedStateOccurred,
                expected="Deterministic state without contradiction",
                actual="Contradictions present",
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Evidence contains contradictory observations: {'; '.join(contradictions)}",
                unverified_reason=UnverifiedReason.CONTRADICTORY_EVIDENCE,
            )

        # Check explicit state changes
        has_mutations = diff is not None and bool(diff.added or diff.removed or diff.modified)
        has_epoch_advance = (post_snapshot.epoch > pre_snapshot.epoch) if (post_snapshot and pre_snapshot) else (outcome.post_epoch > outcome.pre_epoch if outcome else False)

        if expected_effect:
            if outcome.state_change in (
                StateChangeClassification.STATE_CHANGED,
                StateChangeClassification.NAVIGATED,
                StateChangeClassification.MODAL_APPEARED,
                StateChangeClassification.TARGET_DISAPPEARED,
            ) or has_mutations or has_epoch_advance:
                diff_summary = f"{len(diff.added)} added, {len(diff.removed)} removed, {len(diff.modified)} modified" if diff else "epoch advanced"
                return VerificationClaim(
                    claim_id=f"clm_state_{uuid.uuid4().hex[:8]}",
                    session_id=session_id,
                    action_id=action_id,
                    observation_epoch=epoch,
                    claim_type=ClaimType.ExpectedStateOccurred,
                    expected="State change occurred",
                    actual=outcome.state_change.value,
                    status=VerificationVerdict.PASS,
                    confidence=1.0,
                    evidence_refs=tuple(ev_refs),
                    reason=f"Functional state mutation verified: {outcome.state_change.value} ({diff_summary}).",
                )
            else:
                # No change observed when a change was expected
                return VerificationClaim(
                    claim_id=f"clm_state_{uuid.uuid4().hex[:8]}",
                    session_id=session_id,
                    action_id=action_id,
                    observation_epoch=epoch,
                    claim_type=ClaimType.ExpectedStateOccurred,
                    expected="State change occurred",
                    actual=outcome.state_change.value,
                    status=VerificationVerdict.FAIL,
                    confidence=0.9,
                    evidence_refs=tuple(ev_refs),
                    reason="Action executed but zero functional state mutations or epoch transitions were observed.",
                )
        else:
            # Action was expected to have NO effect (e.g. read-only click or disabled button probe)
            if outcome.state_change == StateChangeClassification.NO_EFFECT and not has_mutations:
                return VerificationClaim(
                    claim_id=f"clm_state_{uuid.uuid4().hex[:8]}",
                    session_id=session_id,
                    action_id=action_id,
                    observation_epoch=epoch,
                    claim_type=ClaimType.ExpectedStateOccurred,
                    expected="NO_EFFECT",
                    actual=outcome.state_change.value,
                    status=VerificationVerdict.PASS,
                    confidence=1.0,
                    evidence_refs=tuple(ev_refs),
                    reason="Verified no-op expectation: UI remained quiescent.",
                )
            else:
                return VerificationClaim(
                    claim_id=f"clm_state_{uuid.uuid4().hex[:8]}",
                    session_id=session_id,
                    action_id=action_id,
                    observation_epoch=epoch,
                    claim_type=ClaimType.ExpectedStateOccurred,
                    expected="NO_EFFECT",
                    actual=outcome.state_change.value,
                    status=VerificationVerdict.FAIL,
                    confidence=0.9,
                    evidence_refs=tuple(ev_refs),
                    reason=f"Expected NO_EFFECT, but unexpected state change occurred ({outcome.state_change.value}).",
                )

    def _evaluate_claim_navigation(
        self,
        session_id: str,
        action_id: str,
        epoch: int,
        nav_url: Optional[str],
        pre_snap: Optional[DualPerspectiveSnapshot],
        post_snap: Optional[DualPerspectiveSnapshot],
        evidence: List[EvidenceItem],
        expected_url: Optional[str] = None,
    ) -> VerificationClaim:
        ev_refs = [e.evidence_id for e in evidence if e.evidence_type == EvidenceType.WEB_DOM_SNAPSHOT]
        pre_url = getattr(pre_snap.web_observation, "target_url", getattr(pre_snap.web_observation, "url", "")) if pre_snap and pre_snap.web_observation else ""
        post_url = getattr(post_snap.web_observation, "target_url", getattr(post_snap.web_observation, "url", nav_url or "")) if post_snap and post_snap.web_observation else (nav_url or "")

        if expected_url:
            if expected_url.lower() in post_url.lower():
                return VerificationClaim(
                    claim_id=f"clm_nav_{uuid.uuid4().hex[:8]}",
                    session_id=session_id,
                    action_id=action_id,
                    observation_epoch=epoch,
                    claim_type=ClaimType.NavigationOccurred,
                    expected=expected_url,
                    actual=post_url,
                    status=VerificationVerdict.PASS,
                    confidence=1.0,
                    evidence_refs=tuple(ev_refs),
                    reason=f"Navigation verified: transitioned to expected URL '{expected_url}'.",
                )
            else:
                return VerificationClaim(
                    claim_id=f"clm_nav_{uuid.uuid4().hex[:8]}",
                    session_id=session_id,
                    action_id=action_id,
                    observation_epoch=epoch,
                    claim_type=ClaimType.NavigationOccurred,
                    expected=expected_url,
                    actual=post_url,
                    status=VerificationVerdict.FAIL,
                    confidence=1.0,
                    evidence_refs=tuple(ev_refs),
                    reason=f"Navigation failed: expected '{expected_url}', but post-action URL was '{post_url}'.",
                )

        if pre_url != post_url or nav_url:
            return VerificationClaim(
                claim_id=f"clm_nav_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.NavigationOccurred,
                expected="URL transition",
                actual=f"{pre_url} -> {post_url}",
                status=VerificationVerdict.PASS,
                confidence=1.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Navigation verified: URL transitioned from '{pre_url}' to '{post_url}'.",
            )
        else:
            return VerificationClaim(
                claim_id=f"clm_nav_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.NavigationOccurred,
                expected="URL transition",
                actual=post_url,
                status=VerificationVerdict.FAIL,
                confidence=0.9,
                evidence_refs=tuple(ev_refs),
                reason="Navigation claimed but root frame URL did not change.",
            )

    def _evaluate_claim_modal(
        self,
        session_id: str,
        action_id: str,
        epoch: int,
        native_obs: Optional[NativeObservation],
        evidence: List[EvidenceItem],
    ) -> VerificationClaim:
        ev_refs = [e.evidence_id for e in evidence if e.evidence_type == EvidenceType.NATIVE_WINDOW_STATE]
        if native_obs and native_obs.modal_dialogs:
            titles = [m.get("title", str(m)) if isinstance(m, dict) else getattr(m, "title", str(m)) for m in native_obs.modal_dialogs]
            return VerificationClaim(
                claim_id=f"clm_mod_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.NativeModalAppeared,
                expected="Modal dialog appeared",
                actual=titles,
                status=VerificationVerdict.PASS,
                confidence=1.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Native modal dialog verified: {titles}",
            )
        return VerificationClaim(
            claim_id=f"clm_mod_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            action_id=action_id,
            observation_epoch=epoch,
            claim_type=ClaimType.NativeModalAppeared,
            expected="Modal dialog appeared",
            actual=None,
            status=VerificationVerdict.FAIL,
            confidence=0.9,
            evidence_refs=tuple(ev_refs),
            reason="Expected modal dialog was not detected in native window tree.",
        )

    def _evaluate_claim_element_disappeared(
        self,
        session_id: str,
        action_id: str,
        epoch: int,
        target_ref: str,
        pre_snap: Optional[DualPerspectiveSnapshot],
        post_snap: Optional[DualPerspectiveSnapshot],
        evidence: List[EvidenceItem],
    ) -> VerificationClaim:
        ev_refs = [e.evidence_id for e in evidence if e.evidence_type in (EvidenceType.OBSERVATION_DIFF, EvidenceType.WEB_DOM_SNAPSHOT)]
        was_in_pre = False
        is_in_post = False

        if pre_snap and pre_snap.web_observation:
            was_in_pre = any(e.reference == target_ref for e in pre_snap.web_observation.elements)

        if post_snap and post_snap.web_observation:
            is_in_post = any(e.reference == target_ref for e in post_snap.web_observation.elements)

        if was_in_pre and not is_in_post:
            return VerificationClaim(
                claim_id=f"clm_dis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.ElementDisappeared,
                expected=f"Element '{target_ref}' removed",
                actual="Removed from post-observation",
                status=VerificationVerdict.PASS,
                confidence=1.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Element '{target_ref}' confirmed removed from post-action observation tree.",
            )
        elif is_in_post:
            return VerificationClaim(
                claim_id=f"clm_dis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.ElementDisappeared,
                expected=f"Element '{target_ref}' removed",
                actual="Still present",
                status=VerificationVerdict.FAIL,
                confidence=0.95,
                evidence_refs=tuple(ev_refs),
                reason=f"Element '{target_ref}' is still present in post-action observation tree.",
            )
        else:
            return VerificationClaim(
                claim_id=f"clm_dis_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                action_id=action_id,
                observation_epoch=epoch,
                claim_type=ClaimType.ElementDisappeared,
                expected=f"Element '{target_ref}' removed",
                actual="Target was not present in pre-state",
                status=VerificationVerdict.UNVERIFIED,
                confidence=0.0,
                evidence_refs=tuple(ev_refs),
                reason=f"Target reference '{target_ref}' was not observed in pre-state snapshot.",
                unverified_reason=UnverifiedReason.TARGET_DISAPPEARED_WITHOUT_EXPECTATION,
            )

    # -------------------------------------------------------------------------
    # Verdict Synthesis
    # -------------------------------------------------------------------------

    def _synthesize_verdict(
        self,
        claims: List[VerificationClaim],
        contradictions: List[str],
        proof_level: ProofLevel,
        native_screenshot: Optional[ScreenshotEvidence],
        webview_screenshot: Optional[ScreenshotEvidence],
        execution_mode: str,
        user_confirmed: bool,
    ) -> Tuple[VerificationVerdict, str, Optional[UnverifiedReason]]:
        """
        Applies strict tripartite decision logic.
        PASS requires all applicable claims to PASS and all required proof levels satisfied.
        FAIL is triggered immediately by explicit negative proof.
        UNVERIFIED is returned whenever evidence is incomplete, contradictory, or unconfirmed in interactive mode.
        """
        # 1. Check for explicit FAIL in any evaluated claim
        failed_claims = [c for c in claims if c.status == VerificationVerdict.FAIL]
        if failed_claims:
            reasons = [f"{c.claim_type.value}: {c.reason}" for c in failed_claims]
            return VerificationVerdict.FAIL, f"Verification failed: {'; '.join(reasons)}", None

        # 2. Check for explicit contradictions
        if contradictions:
            return (
                VerificationVerdict.UNVERIFIED,
                f"Contradictory evidence detected across planes: {'; '.join(contradictions)}",
                UnverifiedReason.CONTRADICTORY_EVIDENCE,
            )

        # 3. Check for UNVERIFIED claims
        unverified_claims = [c for c in claims if c.status == VerificationVerdict.UNVERIFIED]
        if unverified_claims:
            first_uv = unverified_claims[0]
            reasons = [f"{c.claim_type.value}: {c.reason}" for c in unverified_claims]
            return (
                VerificationVerdict.UNVERIFIED,
                f"Incomplete proof: {'; '.join(reasons)}",
                first_uv.unverified_reason or UnverifiedReason.INSUFFICIENT_EVIDENCE,
            )

        # 4. Check Proof Level requirements
        if proof_level == ProofLevel.LEVEL_4_FORENSIC_COMPLETE:
            if not (native_screenshot and webview_screenshot):
                return (
                    VerificationVerdict.UNVERIFIED,
                    "Proof Level 4 requires dual screenshots (native and webview), but one or both are missing.",
                    UnverifiedReason.SCREENSHOT_UNAVAILABLE,
                )

        # 5. Interactive Mode Human Confirmation Check (Only if explicitly in interactive mode!)
        if execution_mode == "interactive" and not user_confirmed:
            return (
                VerificationVerdict.UNVERIFIED,
                "Automated dual-perspective proofs passed, but interactive human confirmation is pending.",
                UnverifiedReason.USER_CONFIRMATION_PENDING,
            )

        # 6. All requirements proven
        return (
            VerificationVerdict.PASS,
            "All mandatory verification proofs satisfied: physical visibility, input delivery, and functional state mutation confirmed.",
            None,
        )
