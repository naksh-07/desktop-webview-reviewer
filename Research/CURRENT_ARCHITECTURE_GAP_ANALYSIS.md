# Current Architecture Gap Analysis (Phase 2B Forensic Audit)

> **Standard:** Architecture Rebuild Plan 2.0 (`Research/34_MASTER_ARCHITECTURE_REBUILD_PLAN.md`)  
> **Status:** FORENSICALLY VERIFIED (Phase 2B Verification Gate)  
> **Gate Assessment:** BLOCKED — Foundational regressions and bypasses active in codebase.

---

## 1. Target Identity & PID Recycling Pipeline Disconnect (CRITICAL / VULNERABLE)
*   **Vulnerability:** PID recycling defense is completely bypassed during live MCP evidence collection and verification.
*   **Root Cause 1 (`runtime/mcp/tools/lifecycle.py`):** Window identity creation at lines 132, 145, 181, 292, 305 accesses `getattr(session.target_process, "create_time", 0.0)`. `ProcessIdentity` defines the field as `creation_time`, not `create_time`. Consequently, `creation_time` silently evaluates to `0.0`.
*   **Root Cause 2 (`runtime/mcp/tools/evidence.py`):** `desktop_collect_evidence_impl` builds `proc_info` (lines 178–183) containing only `pid`, `is_running`, `crashed`, `process_tree`. It completely omits `"create_time"`.
*   **Root Cause 3 (`runtime/verification_engine.py`):** In `_evaluate_claim_physical_visibility` (lines 752–754):
    ```python
    expected_creation = proc_info.get("create_time", 0.0)
    if physical_desktop_evidence and expected_creation and physical_desktop_evidence.process_creation_time != expected_creation:
        return VerificationClaim(..., unverified_reason=UnverifiedReason.PROCESS_IDENTITY_MISMATCH)
    ```
    Because `proc_info` lacks `"create_time"`, `expected_creation` defaults to `0.0`. In Python, `bool(0.0) == False`. The check `if physical_desktop_evidence and expected_creation` evaluates to `False`. The mismatch check is completely bypassed, awarding `VerificationVerdict.PASS`.
*   **Root Cause 4 (`runtime/native_supervisor.py`):** `capture_authoritative_physical_desktop` (lines 1012–1122) accepts `expected_creation_time` but never queries the OS for the actual process creation time of the window/PID. It simply reflects the parameter (`process_creation_time = expected_creation_time`).
*   **Test Masking:** The only test asserting `PROCESS_IDENTITY_MISMATCH` (`tests/test_physical_desktop_verification.py:150-158`) is a synthetic in-memory mock calling private methods directly. No genuine end-to-end PID recycling test exists.

---

## 2. Attempt Isolation & Immutability Collision (CRITICAL / REGRESSION)
*   **Vulnerability:** Write-once immutability in `EvidenceStore` triggers unhandled exceptions on legitimate operations due to missing attempt propagation.
*   **Root Cause 1 (`runtime/mcp/tools/evidence.py`):** Line 67 generates `attempt_id = f"attempt_{int(time.time())}_{uuid.uuid4().hex[:4]}"`, but lines 215–225 fail to pass `attempt_id` to `verifier.evaluate_transaction(...)`.
*   **Root Cause 2 (`runtime/verification_engine.py`):** `evaluate_transaction` receives `attempt_id=""`, resolving artifact directories to `action-{action_id}/` rather than `action-{action_id}/attempt-{attempt_id}/`.
*   **Root Cause 3 (`runtime/evidence_store.py`):** Lines 152 and 214 enforce write-once immutability:
    ```python
    if dest_path.exists():
        raise EvidenceSecurityException(f"Cannot overwrite existing artifact: {dest_path}")
    ```
    Because `ActionExecutionEngine.execute` previously wrote `action_receipt.json` to `action-{action_id}/receipts/action_receipt.json`, the call inside `evaluate_transaction` to write the receipt crashes immediately with `EvidenceSecurityException`.
*   **Root Cause 4 (Double Store):** Inside `evaluate_transaction:489`, `store.store_manifest(manifest)` is called. Then `desktop_collect_evidence_impl:228` calls `store.store_manifest(manifest)` again on the exact same unisolated path, throwing another `EvidenceSecurityException`.
*   **Impact:** Directly caused 4 of the 5 test failures across the test suite (`test_mcp_real_app_anki.py`, `test_phase8_agent_e2e.py`, `test_verification_engine.py`).

---

## 3. Evidence Models Inconsistencies & Runtime Errors (DEFECT)
*   **`ProcessIncarnation.to_dict()` AttributeError:** In `runtime/evidence_models.py#L86-L101`, `to_dict()` references `self.attempt_id`, but `attempt_id` is not declared as a field in `ProcessIncarnation`. Calling `to_dict()` raises an `AttributeError`.
*   **Model Orphanage:** `ProcessIncarnation` is not used anywhere in `TargetManager`, `NativeSupervisor`, `ActionExecutionEngine`, or `VerificationEngine`.
*   **Duplicate Fields:** `EvidenceManifest` defines `attempt_id: str = ""` twice; `VerificationClaim` duplicates `claim_type`, `expected`, `actual`, `status`, `confidence`, and `attempt_id`.

---

## 4. Concurrency Locking Inadequacy (PARTIAL IMPLEMENTATION)
*   **Vulnerability:** The claimed `session._evidence_lock` is an in-memory `asyncio.Lock` per `session` instance.
*   **Limitations:**
    - Only serializes async coroutines within a single Python process on that specific `session` object.
    - Does not isolate across separate sessions, which share the same desktop DC (`GetDC(0)`) and `GetForegroundWindow()`.
    - Does not survive daemon restarts or multi-process invocations.
    - Does not provide true persistence or filesystem immutability (enforced solely by `EvidenceStore.exists()` checks).

---

## 5. Persistence & Database Readiness Gap (MISSING / INCOMPLETE)
*   **Vulnerability:** SQLite persistence layer (`runtime/experience/`) lacks support for Phase 2 entities.
*   **Missing Entities:** No database tables exist for `process_incarnations`, `action_attempts`, `capture_artifacts`, `verification_claims`, `verification_evidence`, or `evidence_lifecycle_transitions`.
*   **In-Place Mutation:** `ExperienceStore.record_action_reference` uses `UPDATE action_references ... WHERE id = ?`, erasing prior states and failed attempts. `record_outcome` uses `ON CONFLICT DO UPDATE`, allowing subsequent retries to overwrite historical failed or unverified verdicts.
*   **Timestamp Missing:** Process creation timestamps are completely absent from `review_sessions`, `action_references`, and `evidence_references`.

---

## 6. Rogue Pass Sinks & Evidence Forgery Surfaces
*   **Rogue Certifier:** `RealAppCertifier` (`runtime/certification.py#L137`) synthesizes `overall = Verdict.PASS.value` (line 742) and writes `certification_matrix.json` outside the canonical verifier.
*   **Evidence Forgery Surface:** In `runtime/verification_engine.py#L785`, when `physical_desktop_evidence` is provided, the engine never verifies `is_authoritative`, `post_capture_validated`, or `capture_method == "REAL_DESKTOP_SURFACE"`. A caller can construct an unsealed `PhysicalDesktopEvidence` instance with arbitrary values to bypass capture validation.

---

## 7. Permanent UNVERIFIED Legacy Regression
*   CLI runner `scripts/review.py` is permanently locked to exit code 2 (`UNVERIFIED`) because it fails to pass `user_confirmation` or `input_delivery_verified`.
