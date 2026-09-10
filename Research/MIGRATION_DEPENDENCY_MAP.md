# Migration Dependency Map (Phase 2B Reconciled)

> **Standard:** Architecture Rebuild Plan 2.0 (`Research/34_MASTER_ARCHITECTURE_REBUILD_PLAN.md`)  
> **Status:** FORENSICALLY RECONCILED (Phase 2B Verification Gate)  
> **Gate Status:** BLOCKED (Requires Phase 2 Remediation prior to Phase 3 admission)

---

## 1. Phase 2 Remediation Gate (Immediate Blocking Prerequisite)

Before Phase 3 can begin execution, the following foundational defects must be remediated and re-verified:

1. **Attempt Lineage Propagation (Fixes 4 Test Failures):**
   - Wire `attempt_id` through `desktop_collect_evidence_impl` into `VerificationEngine.evaluate_transaction(attempt_id=attempt_id)`.
   - Preserve `attempt_id` in `EvidenceManifest` construction.
   - Remove duplicate `store.store_manifest(manifest)` call in `runtime/mcp/tools/evidence.py:228`.
   - Update `EvidenceStore.verify_manifest_integrity` to pass `manifest.attempt_id` to `get_action_dir`.
2. **PID Recycling Pipeline Repair:**
   - Wire `session.target_process.creation_time` into `proc_info["create_time"]` in `desktop_collect_evidence_impl`.
   - Fix attribute name typo `create_time` -> `creation_time` in `runtime/mcp/tools/lifecycle.py`.
   - Guard against `0.0` or missing creation times in `VerificationEngine._evaluate_claim_physical_visibility` (fail closed with `UNVERIFIED`).
   - Query OS-level process creation time in `NativeSupervisor.capture_authoritative_physical_desktop`.
3. **Data Model Cleanup:**
   - Fix `ProcessIncarnation.to_dict()` by adding `attempt_id: str = ""` to the dataclass or removing it from `to_dict()`.
   - Remove duplicate field definitions and duplicate dict keys in `EvidenceManifest` and `VerificationClaim`.
4. **End-to-End Adversarial Test:**
   - Implement genuine PID recycling test: Process A (PID X, T1) exits -> Process B (PID X, T2) takes PID -> `desktop_collect_evidence` asserts `UNVERIFIED`.

---

## 2. Phase 3: Identity Hardening & Database Migration (Schema V5)

*Depends on:* Full completion of Phase 2 Remediation Gate.

1. **Database Migration V5 (`runtime/experience/`):**
   - Implement `process_incarnations` table to track native PID and creation timestamp.
   - Implement `targets` table for normalized target tracking (multi-window, child frames).
   - Implement `action_attempts` table with `UNIQUE(action_id, attempt_id)`.
   - Implement `capture_artifacts`, `verification_claims`, `verification_evidence`, and `evidence_lifecycle_transitions`.
   - Add `target_creation_time` to `review_sessions`.
   - Remove in-place `UPDATE` mutation in `ExperienceStore.record_action_reference()`.
   - Remove `ON CONFLICT DO UPDATE` in `ExperienceStore.record_outcome()`.
2. **Process Incarnation Runtime Integration:**
   - Bind `ProcessIncarnation` to `TargetManager` discovery and `SessionState`.
   - Bind Win32 HWND directly to `ProcessIncarnation` to prevent window re-parenting spoofing.

---

## 3. Phase 4: Authoritative Capture Architecture (WGC / DXGI)

*Depends on:* Phase 3 Target Identity Hardening.

1. **Hardware Capture Backends:**
   - Transition primary physical capture from GDI `BitBlt` to Windows Graphics Capture (WGC) and DXGI Desktop Duplication.
   - Demote GDI to diagnostic fallback only.
2. **Occlusion & Composition Engine:**
   - Implement DirectComposition tree inspection and occlusion ratio computation.
   - Close the `PhysicalDesktopEvidence` forgery surface in `VerificationEngine`.

---

## 4. Phase 5: Input Delivery & Forensic Settlement

*Depends on:* Phase 4 Capture Architecture.

1. **Forensic Input Pipeline:**
   - Correlate Win32 `SendInput` events with physical desktop state changes.
   - Multi-plane diffing between native window damage rects and DOM mutation records.

---

## 5. Phase 6: Rogue Pass Sink Deprecation & Real App Hardening

*Depends on:* Phase 5 Input Settlement.

1. **Rogue Certifier Elimination:**
   - Deprecate and remove `RealAppCertifier` in `runtime/certification.py`.
   - Remove CLI exit code 0 synthesis in `scripts/certify.py`.
   - Unify all verification reporting under canonical `VerificationEngine` (v2.0) and sealed `EvidenceManifest`.
