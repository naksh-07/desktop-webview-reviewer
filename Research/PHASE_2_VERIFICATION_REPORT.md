# Phase 2B Verification Gate: Forensic Architecture & Evidence Foundation Audit Report

> **Target Repository:** `https://github.com/naksh-07/desktop-webview-reviewer` (`c:\Users\Suraj\Documents\Antigravity\Desktop-priview`)  
> **Auditing Entity:** Antigravity Master Orchestrator & Specialist Workforce  
> **Specialists Engaged:**
> - `evidence-integrity-guardian` (`dcf922e7-5c31-4134-8f63-a661638b19af`)
> - `runtime-state-concurrency` (`5bb7d292-f2c6-4ffc-ac09-511c56c74a87`)
> - `database-forensics-engineer` (`b4a769de-f5f2-4fdb-bf15-6760495ebe53`)
> - `forensic-architecture-auditor` (`37f7477f-e44e-4a9f-86b5-0182b371d901`)  
> **Evaluation Date:** 2026-09-10  
> **Verification Mandate:** Zero assumptions; test-proven reality; strict gate enforcement.

---

## 1. Executive Summary & Final Gate Verdict

### GATE VERDICT: **BLOCKED**

Progression to **Phase 3 (Target Identity & Process Hardening)** is **STRICTLY BLOCKED**.

While Phase 2 implemented several structural foundations—including application-owned evidence storage, content-addressed SHA-256 artifact sealing, frozen dataclass immutability, and write-once collision guards—forensic verification revealed critical regressions, logical bypasses, and persistence gaps that render the foundation unsafe to serve as the dependency of Phase 3.

### Primary Blocking Findings:
1. **PID Recycling Protection is Bypassed in Production:**
   - In `runtime/mcp/tools/evidence.py:178-183`, `proc_info` completely omits `"create_time"`.
   - In `runtime/mcp/tools/lifecycle.py:132, 145, 181, 292, 305`, window identity reads `getattr(session.target_process, "create_time", 0.0)`. `ProcessIdentity` names the field `creation_time`, causing this to silently evaluate to `0.0`.
   - In `runtime/verification_engine.py:752-754`, `expected_creation = proc_info.get("create_time", 0.0)` evaluates to `0.0`. In Python, `bool(0.0) == False`, causing the creation timestamp mismatch check to be **silently skipped**, awarding `VerificationVerdict.PASS` to recycled PIDs.
   - In `runtime/native_supervisor.py:1012-1122`, `capture_authoritative_physical_desktop` merely reflects the input parameter rather than querying the OS.
2. **Attempt Isolation Failure & Test Suite Regression:**
   - In `runtime/mcp/tools/evidence.py:67`, `attempt_id` is generated but dropped at line 215 and never passed to `VerificationEngine.evaluate_transaction()`.
   - `evaluate_transaction` writes receipts to `action-{action_id}/receipts/action_receipt.json`. Because `ActionExecutionEngine.execute` already wrote that artifact during action dispatch, `EvidenceStore.store_bytes` detects `dest_path.exists()` and raises `EvidenceSecurityException: Cannot overwrite existing artifact`.
   - Furthermore, `desktop_collect_evidence_impl:228` calls `store.store_manifest(manifest)` a second time on the exact same unisolated path, throwing another `EvidenceSecurityException`.
   - This defect caused **4 out of 5 test failures** across the full test suite.
3. **Database Layer Lacks Phase 2 Entities & Overwrites History:**
   - The SQLite database (`runtime/experience/`) lacks tables for `process_incarnations`, `action_attempts`, `capture_artifacts`, `verification_claims`, `verification_evidence`, and `evidence_lifecycle_transitions`.
   - `ExperienceStore.record_action_reference` overwrites action states in-place via `UPDATE`, destroying transitional history and failed attempts.
   - `ExperienceStore.record_outcome` uses `ON CONFLICT DO UPDATE`, overwriting historical verdicts on retry.
4. **Data Model Syntax & Structural Errors:**
   - `ProcessIncarnation.to_dict()` in `runtime/evidence_models.py` references `self.attempt_id`, which is not a declared field, raising `AttributeError` at runtime.
   - `EvidenceManifest` and `VerificationClaim` contain duplicate field definitions and duplicate dictionary keys.
5. **Rogue Pass Sink & Evidence Forgery Surface Active:**
   - `RealAppCertifier` in `runtime/certification.py` synthesizes `overall = Verdict.PASS.value` outside the canonical verifier.
   - `VerificationEngine._evaluate_claim_physical_visibility` fails to validate `is_authoritative` or `capture_method` on `PhysicalDesktopEvidence`.

---

## 2. Comprehensive Area-by-Area Forensic Findings

### Area 1: Target Identity & PID Recycling Verification
*   **Claimed State:** PID recycling protection fixed; `expected_creation_time` propagated throughout capture and verification.
*   **Verified State:** **PARTIAL / VULNERABLE**.
*   **Forensic Evidence:**
    - `TargetManager.correlate_process` authoritatively queries `psutil.Process(pid).create_time()`, storing it in `ProcessIdentity.creation_time`.
    - However, `runtime/mcp/tools/lifecycle.py` queries `create_time` instead of `creation_time`, initializing `target_window.creation_time` to `0.0`.
    - `runtime/mcp/tools/evidence.py` builds `proc_info` without `"create_time"`.
    - `runtime/verification_engine.py` line 752 uses truthiness test `if physical_desktop_evidence and expected_creation and ...`. Because `0.0` is falsy, the creation time mismatch check is never triggered.
    - `NativeOSSupervisor.capture_authoritative_physical_desktop` line 1113 assigns `process_creation_time = expected_creation_time` without querying Win32 / `psutil`.
    - `tests/test_physical_desktop_verification.py:150-158` tests creation time mismatch via synthetic in-memory unit mock bypassing MCP tools. No end-to-end PID recycling test exists.

### Area 2: Attempt Isolation & Storage Immutability
*   **Claimed State:** Attempt ID based isolation implemented; `EvidenceStore` overwrite/clobbering fixed.
*   **Verified State:** **REGRESSION / DEFECTIVE**.
*   **Forensic Evidence:**
    - `EvidenceStore.store_bytes` (line 152) and `store_manifest` (line 214) added strict write-once checks: `if dest_path.exists(): raise EvidenceSecurityException(...)`.
    - However, `desktop_collect_evidence_impl` generates `attempt_id` (line 67) but never passes it to `verifier.evaluate_transaction(...)` (line 215).
    - `evaluate_transaction` writes `action_receipt.json` to the action root directory. Because `action_engine.execute` already wrote this artifact earlier, `store_bytes` crashes with `EvidenceSecurityException`.
    - In `desktop_collect_evidence_impl:228`, `store.store_manifest` is redundantly called after `evaluate_transaction` already stored it, crashing on live tool runs.
    - Caused 4 test suite failures (`test_mcp_real_app_anki.py`, `test_phase8_agent_e2e.py`, `test_verification_engine.py`).

### Area 3: Safe Defaults Repository-Wide Audit
*   **Claimed State:** Unsafe defaults hardened across all models and tools.
*   **Verified State:** **VERIFIED (With Timestamp Vulnerability)**.
*   **Forensic Evidence:**
    - Confirmed ZERO instances of silent default `PASS` in evidence models (`EvidenceReport.verdict = Verdict.UNVERIFIED`, `EvidenceManifest.verdict = VerificationVerdict.UNVERIFIED`, `CertificationMatrix.overall_verdict = "UNVERIFIED"`).
    - Confirmed ZERO silent True authority defaults (`is_authoritative = False`, `is_certifying = False`, `is_real_gui = False`).
    - Confirmed ZERO silent True validation defaults (`post_capture_validated = False`, `user_confirmation = False`, `input_delivery_verified = False`).
    - Confirmed ZERO non-zero default physical bounds (`physical_bounds = (0, 0, 0, 0)`).
    - **Vulnerability:** `process_creation_time` defaults to `0.0`. Because `0.0` is treated as falsy in `verification_engine.py`, missing or default timestamps bypass verification rather than failing closed.

### Area 4: Concurrency & Lock Evaluation
*   **Claimed State:** `asyncio` evidence collection locking added.
*   **Verified State:** **PARTIAL / IN-PROCESS ONLY**.
*   **Forensic Evidence:**
    - Added `session._evidence_lock = asyncio.Lock()` in `runtime/mcp/tools/evidence.py:58`.
    - Protects only concurrent coroutines executing `desktop_collect_evidence_impl` within a single Python process on that exact `session` instance.
    - Does not protect across separate sessions, which share and contest the single Windows desktop DC (`GetDC(0)`) and `GetForegroundWindow()`.
    - Does not survive daemon restarts or multi-process invocations.
    - True immutability is provided by filesystem `exists()` assertions, not the lock.

### Area 5: Artifact Integrity & State Machine
*   **Claimed State:** SHA-256 cryptographic sealing; state machine lifecycle enforced.
*   **Verified State:** **VERIFIED (Hashing) / MISSING (State Machine)**.
*   **Forensic Evidence:**
    - `EvidenceStore.verify_manifest_integrity` computes canonical JSON SHA-256 digests.
    - Adversarial 1-byte file tampering test (`scratch/test_evidence_guardian.py` and `tests/test_evidence_store.py`) proved: modifying 1 byte causes verification to fail closed with `IntegrityVerificationException`. Tampered evidence NEVER yields `PASS`.
    - However, the claimed state machine (`RAW -> OBSERVED -> VALIDATED -> SEALED -> CERTIFIABLE`) is not an enforced state machine engine; it exists solely as conceptual steps in code without relational tracking.

### Area 6: Evidence Storage Isolation
*   **Claimed State:** Evidence storage moved out of CWD.
*   **Verified State:** **VERIFIED (With Minor Path Inconsistencies)**.
*   **Forensic Evidence:**
    - Default storage moved to `Path.home() / ".desktop-webview-reviewer" / "evidence"`.
    - Path traversal sandboxing enforced (`_sanitize_id` and `_validate_relative_path`).
    - Inconsistencies noted: `runtime/mcp/server.py:84` uses `.desktop_webview_reviewer` (underscore) while `runtime/evidence_store.py:61` uses `.desktop-webview-reviewer` (hyphen).
    - Legacy leaks remain in `runtime/certification.py` (`evidence/certification`) and `scripts/review.py` (`evidence.json`).

### Area 7: Database Readiness
*   **Claimed State:** Database readiness assessed for Phase 3.
*   **Verified State:** **INCOMPLETE (Schema Migration V5 Required)**.
*   **Forensic Evidence:**
    - Database is at SQLite Schema V4 (23 tables).
    - Missing 6 first-class entities: `process_incarnations`, `targets`, `action_attempts`, `capture_artifacts`, `verification_claims`, `evidence_lifecycle_transitions`.
    - Action references and outcomes mutate rows in-place, destroying auditability.
    - Full 10-section migration specification authored in `Research/PHASE_2_DB_READINESS.md`.

### Area 8: Pass-Sink Inventory & Authority Classification
*   **Claimed State:** Single canonical certifying authority; no rogue pass sinks.
*   **Verified State:** **VERIFIED INVENTORY (0 UNKNOWN) / ROGUE SINKS ACTIVE**.
*   **Forensic Evidence:**
    - 17 entities audited and classified into 7 canonical categories with **0 UNKNOWN** (documented in `Research/PASS_SINKS.md`).
    - Rogue sink active: `RealAppCertifier` (`runtime/certification.py#L137`) synthesizes `Verdict.PASS` and writes unsealed `certification_matrix.json`.
    - Forgery surface active: `PhysicalDesktopEvidence` accepted by `VerificationEngine` without validating `is_authoritative` or `capture_method`.

---

## 3. Full Test Suite Execution & Failure Forensic Analysis

### Execution Summary
*   **Total Items Collected:** 827
*   **Passed:** **811**
*   **Failed:** **5**
*   **Skipped:** **11**
*   **Warnings:** **2** (`PytestCollectionWarning` on `TesterSpecialist`)
*   **Subtests Passed:** **38**
*   **Execution Time:** 174.88s (02:54)

### Failure Breakdown

| Test Identifier | Failure Mode | Forensic Root Cause | Classification |
|---|---|---|---|
| `tests/test_mcp_real_app_anki.py::TestMcpRealAppAnkiMaths::test_real_anki_maths_mcp_control_plane_lifecycle` | `AssertionError: desktop_collect_evidence failed: SECURITY_BLOCKED: Cannot overwrite existing artifact: ...\receipts\action_receipt.json` | `desktop_collect_evidence_impl` omitted `attempt_id`. `EvidenceStore` write-once check crashed on re-storing receipt written during action dispatch. | **REGRESSION** (Phase 2 Attempt Isolation Defect) |
| `tests/test_phase8_agent_e2e.py::TestPhase8AgentE2E::test_agent_complete_review_lifecycle_via_mcp_only` | `AssertionError: desktop_collect_evidence failed: SECURITY_BLOCKED: Cannot overwrite existing artifact: ...\receipts\action_receipt.json` | Identical to above: omitted `attempt_id` in MCP tool caused collision between action execution and evidence collection. | **REGRESSION** (Phase 2 Attempt Isolation Defect) |
| `tests/test_verification_engine.py::TestVerificationEngine::test_interactive_mode_requires_user_confirmation` | `EvidenceSecurityException: Cannot overwrite existing artifact: ...\receipts\action_receipt.json` | Test calls `evaluate_transaction` twice sequentially with same `action_id`. Second call crashes on existing unisolated receipt. | **REGRESSION** (Phase 2 Immutability without Attempt ID) |
| `tests/test_verification_engine.py::TestVerificationEngine::test_proof_level_4_requires_dual_screenshots` | `EvidenceSecurityException: Cannot overwrite existing artifact: ...\receipts\action_receipt.json` | Test calls `evaluate_transaction` twice sequentially with same `action_id`. Second call crashes on existing unisolated receipt. | **REGRESSION** (Phase 2 Immutability without Attempt ID) |
| `tests/test_phase6_real_app.py::TestPhase6RealAppValidation::test_real_anki_maths_verification_lifecycle` | `AssertionError: 'UNVERIFIED' != 'PASS'` | Anki spawned Qt GUI via child PID 16228. Because child process tree was not correlated into target process info, engine rejected window ownership. | **EXPECTED FORENSIC BEHAVIOR** (Verifier correctly failed closed) |

---

## 4. Code Defects Catalog

### Defect 1: `ProcessIncarnation.to_dict()` AttributeError
*   **File:** `runtime/evidence_models.py` (lines 86–101)
*   **Code:**
    ```python
    @dataclass(frozen=True)
    class ProcessIncarnation:
        target_id: str
        pid: int
        process_creation_time: float
        session_id: str

        def to_dict(self) -> Dict[str, Any]:
            return {
                "target_id": self.target_id,
                "pid": self.pid,
                "process_creation_time": self.process_creation_time,
                "session_id": self.session_id,
                "attempt_id": self.attempt_id,  # <-- AttributeError: no attribute 'attempt_id'
            }
    ```

### Defect 2: Duplicate Field Declarations
*   **File:** `runtime/evidence_models.py`
    - `EvidenceManifest` (lines 405–406): `attempt_id: str = ""` duplicated.
    - `VerificationClaim` (lines 251–257): `claim_type`, `expected`, `actual`, `status`, `confidence`, `attempt_id` duplicated.
    - `EvidenceItem.to_dict()`, `VerificationClaim.to_dict()`, `EvidenceManifest.to_dict()`: duplicate dictionary keys for `"attempt_id"`.

### Defect 3: Lifecycle Window Creation Time Typo
*   **File:** `runtime/mcp/tools/lifecycle.py` (lines 132, 145, 181, 292, 305)
*   **Code:** `creation_time=getattr(session.target_process, "create_time", 0.0)`
*   **Error:** `ProcessIdentity` defines `.creation_time`. Calling `getattr(..., "create_time", 0.0)` silently returns `0.0`.

### Defect 4: Creation Time Omission in Evidence MCP Tool
*   **File:** `runtime/mcp/tools/evidence.py` (lines 178–183)
*   **Code:**
    ```python
    proc_info = {
        "pid": window_pid or target_pid,
        "is_running": True,
        "crashed": False,
        "process_tree": proc_tree,
    }  # <-- Completely omits 'create_time'!
    ```

### Defect 5: PID Recycling Check Bypassed by Falsy 0.0
*   **File:** `runtime/verification_engine.py` (lines 752–754)
*   **Code:**
    ```python
    expected_creation = proc_info.get("create_time", 0.0)
    if physical_desktop_evidence and expected_creation and physical_desktop_evidence.process_creation_time != expected_creation:
        return VerificationClaim(..., unverified_reason=UnverifiedReason.PROCESS_IDENTITY_MISMATCH)
    ```
*   **Error:** Because `expected_creation` is `0.0`, `and expected_creation` evaluates to `False`, bypassing the check entirely.

### Defect 6: Dropped `attempt_id` in Evidence MCP Tool
*   **File:** `runtime/mcp/tools/evidence.py` (lines 67, 215–225)
*   **Code:** `attempt_id` is computed at line 67 but never passed to `verifier.evaluate_transaction(...)`.

### Defect 7: Redundant `store_manifest` Call Crashing on Overwrite Guard
*   **File:** `runtime/mcp/tools/evidence.py` (line 228)
*   **Code:** `store.store_manifest(manifest)` is called after `evaluate_transaction` already stored it.

### Defect 8: Process Identity Telemetry AttributeError
*   **File:** `runtime/experience/adapter.py` (line 274)
*   **Code:** Accesses `target_proc.executable` on `ProcessIdentity` (which only defines `.binary_path`), generating telemetry errors.

---

## 5. Required Remediation Plan for Phase 2 (Unblocking Criteria)

To unblock progression to Phase 3, the following remediation tasks must be completed and re-verified:

1. **Attempt Lineage Unification:**
   - Add `attempt_id: str = ""` to `ActionRequest`, `ActionReceipt`, and `ActionOutcome`.
   - Pass `attempt_id` from `desktop_collect_evidence_impl` into `evaluate_transaction(attempt_id=attempt_id)`.
   - Store receipts and artifacts under `action-{action_id}/attempt-{attempt_id}/`.
   - Remove the redundant `store.store_manifest(manifest)` call in `desktop_collect_evidence_impl:228`.
   - Update `EvidenceStore.verify_manifest_integrity` to pass `manifest.attempt_id` to `get_action_dir`.
2. **PID Recycling Pipeline Repair:**
   - Fix attribute typo in `runtime/mcp/tools/lifecycle.py`: `getattr(session.target_process, "creation_time", 0.0)`.
   - Include `"create_time": session.target_process.creation_time` in `proc_info` inside `desktop_collect_evidence_impl`.
   - In `runtime/verification_engine.py:752`, reject missing/zero creation timestamps:
     ```python
     if not expected_creation or expected_creation == 0.0:
         return VerificationClaim(..., status=VerificationVerdict.UNVERIFIED, unverified_reason=UnverifiedReason.PROCESS_IDENTITY_MISMATCH)
     if physical_desktop_evidence and physical_desktop_evidence.process_creation_time != expected_creation:
         return VerificationClaim(..., status=VerificationVerdict.UNVERIFIED, unverified_reason=UnverifiedReason.PROCESS_IDENTITY_MISMATCH)
     ```
   - In `NativeOSSupervisor.capture_authoritative_physical_desktop`, query `psutil.Process(pid).create_time()` from the OS and verify before capture.
3. **Data Model Fixes:**
   - Fix `ProcessIncarnation.to_dict()` and remove duplicate fields in `EvidenceManifest` and `VerificationClaim`.
   - Fix `runtime/experience/adapter.py:274` to access `target_proc.binary_path`.
4. **End-to-End Adversarial PID Recycling Test:**
   - Author a test in `tests/test_phase8_adversarial_security.py` that spawns Process A (PID X, T1), terminates it, spawns Process B with different creation time, and proves that `desktop_collect_evidence` returns `UNVERIFIED`.
5. **Re-Run Full Test Suite:**
   - All 827 tests must run with **0 failures**.
