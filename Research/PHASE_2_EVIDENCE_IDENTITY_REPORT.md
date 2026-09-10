# Phase 2 Evidence Identity Forensic Audit Report

> **Status:** Forensic Architecture Audit Record  
> **Auditor:** Forensic Architecture Auditor (Phase 2B Verification)  
> **Workspace:** `naksh-07/desktop-webview-reviewer`  
> **Target Contracts:** `Research/34_MASTER_ARCHITECTURE_REBUILD_PLAN.md`, `Research/35_AGENT_WORKFORCE.md`, `Research/AUTHORITY_GRAPH.md`, `Research/PASS_SINKS.md`  

---

## 1. Physical Absence Discovery

Prior to this Phase 2B forensic verification, `Research/PHASE_2_EVIDENCE_IDENTITY_REPORT.md` **did not physically exist** in the repository. This report reconstructs the full evidence identity architecture, domain model reality, and forensic gaps directly from codebase facts.

---

## 2. Domain Model Architecture & Code Facts

The evidence identity domain is distributed across three primary modules:
1. `runtime/evidence_models.py`
2. `runtime/target_manager.py`
3. `runtime/reality_models.py`

### 2.1 `ProcessIncarnation` (`runtime/evidence_models.py#L86-L101`)
- **Code Fact:** Defined as a frozen dataclass:
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
              "attempt_id": self.attempt_id,
          }
  ```
- **Defect Identified:** `to_dict()` attempts to serialize `self.attempt_id`, but `attempt_id` is **not declared** as a dataclass field. Any call to `to_dict()` raises an `AttributeError`.
- **Architectural Detachment:** `ProcessIncarnation` is not instantiated or consumed by `TargetManager`, `NativeSupervisor`, `ActionExecutionEngine`, or `VerificationEngine`. It exists solely as an orphaned model.

### 2.2 `ProcessIdentity` (`runtime/target_manager.py#L38-L56`)
- **Code Fact:** Immutable dataclass anchoring native process identity:
  - Fields: `pid: int`, `creation_time: float`, `binary_path: str`, `command_line: List[str]`, `is_elevated: bool`, `job_handle: Optional[int]`.
  - Captured authoritatively at discovery via `psutil.Process(pid).create_time()` (`target_manager.py#L349`).
- **Defect Identified:** In `runtime/experience/adapter.py#L274`, telemetry code accesses `target_proc.executable`, raising:
  `AttributeError: 'ProcessIdentity' object has no attribute 'executable'` (which triggers logged warning `Graceful degradation: failed to update session...`).

### 2.3 `WindowIdentity` (`runtime/target_manager.py#L59-L70`)
- **Code Fact:** Immutable dataclass anchoring Win32 native window properties:
  - Fields: `hwnd: int`, `pid: int`, `title: str`, `class_name: str`, `bounds: Rect` (via `DwmGetWindowAttribute`), `is_visible: bool`, `is_cloaked: bool`, `is_minimized: bool`, `is_hung: bool`, `dpi_scaling: float`.
  - Authoritatively observed via `NativeOSSupervisor.inspect_window()`.

### 2.4 `TargetIdentity` (`runtime/reality_models.py#L29-L45`)
- **Code Fact:** Tracks element-level descriptors:
  - Fields: `session_id: str`, `target_id: str`, `reference: str`, `role: str`, `name: Optional[str]`.
  - **Gap:** Lacks binding to native HWND, process creation time, session creation timestamp, or attempt ID.

### 2.5 `PhysicalDesktopEvidence` (`runtime/evidence_models.py#L103-L146`)
- **Code Fact:** Captures physical desktop observations:
  - Fields: `evidence_id`, `session_id`, `target_hwnd`, `target_pid`, `foreground_hwnd`, `is_exact_foreground`, `dimensions`, `capture_timestamp`, `pixel_sha256`, `artifact_path`, `action_epoch`, `attempt_id`, `process_creation_time`, `occlusion_state`, `occlusion_ratio`, `physical_bounds`, `capture_method`, `is_authoritative`, `post_capture_validated`.
- **CRITICAL FORENSIC FLAW (Evidence Forgery Surface):**
  In `runtime/verification_engine.py#L785`:
  ```python
  if not physical_desktop_evidence and not (native_screenshot and getattr(native_screenshot, "is_certifying", False) and getattr(native_screenshot, "capture_method", "") == "REAL_DESKTOP_SURFACE"):
      return VerificationClaim(...)
  ```
  If an untrusted caller constructs a `PhysicalDesktopEvidence` instance and passes it directly to `VerificationEngine.evaluate_transaction(physical_desktop_evidence=...)`, the engine **never verifies** `is_authoritative`, `post_capture_validated`, or `capture_method == "REAL_DESKTOP_SURFACE"`. Ordinary callers can forge this structure to bypass physical desktop verification.

---

## 3. Identity Hardening & PID Recycling Defense

### 3.1 Verification Engine Implementation
In `runtime/verification_engine.py#L733-L767`:
1. **PID Tree Verification:** Checks `native_obs.pid in tree_pids`. Fails with `UnverifiedReason.PID_MISMATCH` if mismatched.
2. **Creation Time Verification:** Checks `physical_desktop_evidence.process_creation_time == expected_creation`. Fails with `UnverifiedReason.PROCESS_IDENTITY_MISMATCH` if mismatched.

### 3.2 Live Target Multi-Process Failure Mode
During live application execution (e.g. `tests/test_phase6_real_app.py`):
- Test launches Anki Maths (runner script) with PID 17484.
- Qt spawns GUI subprocess with PID 16228.
- Because `target_process_info` provided to the engine was not populated with the complete child process tree, the engine evaluated:
  `Claim ClaimType.TargetWasPhysicallyVisible: status=VerificationVerdict.UNVERIFIED, reason=Window owning PID (16228) does not match expected application process tree.`
- **Forensic Assessment:** The engine correctly preferred `UNVERIFIED` over a false `PASS`. The failure is in test fixture process tree enumeration, proving the verification engine's fail-closed design holds.

---

## 4. Storage Isolation & Overwrite Defense Audit

### 4.1 Canonical Storage Root
- `EvidenceStore` (`runtime/evidence_store.py#L61`):
  Defaults to application-owned path: `Path.home() / ".desktop-webview-reviewer" / "evidence"`.
- **Discrepancy:** `runtime/mcp/server.py#L84` checks `Path.home() / ".desktop_webview_reviewer" / "evidence"` (underscore vs hyphen).
- **Redefinition Vulnerability:** `EvidenceStore(base_dir=...)` accepts arbitrary caller paths without verifying against an allowed storage root.

### 4.2 Legacy Workspace Leaks
1. `runtime/certification.py#L144` (`RealAppCertifier`): Defaults `output_dir` to `(Path(__file__).resolve().parent.parent / "evidence" / "certification")` (workspace relative).
2. `core/evidence.py#L338` (`save_report_json`): Defaults to cwd `"evidence.json"`.
3. `scripts/review.py#L304`: Defaults `--evidence` to `"evidence.json"`.
4. `tests/test_phase6_real_app.py#L1015`: Defaults to `"evidence"`.

### 4.3 Immutability vs Attempt Lineage Regression
`EvidenceStore` enforces write-once immutability:
```python
if dest_path.exists():
    raise EvidenceSecurityException(f"Cannot overwrite existing artifact: {dest_path}")
```
However, `ActionExecutionEngine` and `VerificationEngine` write `receipts/action_receipt.json` without incrementing an `attempt_id`. When `desktop_collect_evidence` or test retries re-evaluate the same action, `dest_path.exists()` is true, raising `EvidenceSecurityException: Cannot overwrite existing artifact` and breaking 4 integration tests (`test_mcp_real_app_anki`, `test_phase8_agent_e2e`, and two `test_verification_engine` cases).

---

## 5. Architectural Correctness Summary

| Requirement (`Research/34_MASTER_ARCHITECTURE_REBUILD_PLAN.md`) | Code Status | Forensic Finding |
|---|---|---|
| Single Certifying Authority | Partially Met | `VerificationEngine` is primary; `RealAppCertifier` acts as secondary PASS sink |
| Process Incarnation / Creation Time Anchor | Implemented | `create_time` anchored in `TargetManager`, checked in `VerificationEngine` |
| PID Recycling Defense | Implemented | Fails closed with `UNVERIFIED` |
| `ProcessIncarnation` Domain Envelope | Broken | `AttributeError` on `attempt_id` in `to_dict()`, orphaned model |
| Isolated Evidence Storage | Partially Met | Defaults to `~/.desktop-webview-reviewer/evidence`; leaks in legacy scripts/certifier |
| Write-Once Immutability | Implemented | `dest_path.exists()` blocks overwrites |
| Attempt Lineage Tracking | Incomplete | Omission of `attempt_id` in action loop causes self-collision exceptions |
| Non-Forgeable Evidence | Unmet | `VerificationEngine` fails to validate `is_authoritative` or `capture_method` on `PhysicalDesktopEvidence` |
