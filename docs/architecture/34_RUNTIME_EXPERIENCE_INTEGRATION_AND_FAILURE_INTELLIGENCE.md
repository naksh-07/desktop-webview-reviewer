# Architecture Document 34: Runtime Experience Integration & Failure Intelligence (Milestone 2.1 Prompt 2)

## 1. Runtime → Experience Integration Boundary

Desktop WebView Reviewer 2.1 Prompt 2 establishes a thin, non-invasive integration adapter layer between the live authoritative runtime and the durable Experience Store:

```text
                                  AUTHORITATIVE RUNTIME
                                            │
        ┌───────────────────────────────────┼───────────────────────────────────┐
        │                                   │                                   │
  SessionManager               ReviewMissionOrchestrator             ActionExecutionEngine
  DesktopTraceEngine                  EvidenceStore                    VerificationEngine
  DiagnosticAggregator               RecoveryEngine                  McpRuntimeBridge (12 tools)
        │                                   │                                   │
        └───────────────────────────────────┼───────────────────────────────────┘
                                            │
                                            ▼  (Runtime Facts via Callbacks / Hooks)
                             ExperienceIntegrationAdapter
                                            │
                                            ▼  (Defensive Sanitization)
                                     PrivacyEnforcer
                                            │
                                            ▼  (Deterministic Normalization)
                                    FailureNormalizer
                                            │
                                            ▼  (Durable Persistence / WAL Mode)
                                     ExperienceStore
                                            │
                                            ▼
                                  Historical Intelligence
                             (Aggregates, Frequencies, Trends)
```

The adapter translates ephemeral in-memory runtime objects into strongly typed, durable experience records (`SessionExperienceRecord`, `MissionExperienceRecord`, `ActionReferenceRecord`, `TraceReferenceRecord`, `EvidenceReferenceRecord`, `OutcomeRecord`, `NormalizedFailureRecord`, `RecoveryExperienceRecord`).

## 2. Authoritative vs. Historical Data Ownership

The project enforces a strict boundary between runtime truth and historical persistence:

| Subsystem | Authority Layer | Responsibilities & Ownership |
| :--- | :--- | :--- |
| **SessionManager** | Runtime Truth | Owns live process lifetime, window tracking, plane switching, and session state. |
| **ReviewMissionOrchestrator** | Runtime Truth | Owns mission admission, goal validation, plan execution, and cancellation. |
| **ActionExecutionEngine** | Runtime Truth | Owns physical action dispatch, UI automation, and settlement timing. |
| **DesktopTraceEngine** | Runtime Truth | Owns monotonic canonical trace timeline, correlation IDs, and event bus. |
| **EvidenceStore** | Forensic Truth | Owns physical artifact binaries, PNG screenshots, DOM trees, and hash receipts. |
| **VerificationEngine** | Runtime Truth | Owns tripartite verdicts (`PASS`, `FAIL`, `UNVERIFIED`) and gate proofs. |
| **RecoveryEngine** | Runtime Truth | Owns bounded recovery policies, attempt counts, and circuit breakers. |
| **ExperienceStore** | Historical Consumer | **Consumer only.** Records historical facts, computes frequency aggregates, trends, and failure signatures. Never dictates reviewer decisions. |

Under **Architecture H**, the controlling agent owns the *WHAT* and *WHY*; Desktop WebView Reviewer owns the *HOW*. The Experience Store never assumes mission ownership and never acts as an autonomous decision-maker.

## 3. Failure Normalization

Runtime failures originate from heterogeneous sources: Python exceptions, Win32 HRESULT errors, CDP transport disconnections, diagnostic diagnoses, gate failures, and unverified verifier reasons.

The `FailureNormalizer` deterministically translates all runtime errors into the project's authoritative 19-category taxonomy (`FailureCategory` from `runtime/diagnostics.py`):

- `TARGET_NOT_FOUND`
- `TARGET_NOT_ACTIONABLE`
- `TARGET_OCCLUDED`
- `TARGET_OFFSCREEN`
- `SETTLEMENT_TIMEOUT`
- `INPUT_DISPATCH_FAILURE`
- `WEBVIEW_PROCESS_CRASHED`
- `NATIVE_WINDOW_DESTROYED`
- `COORDINATE_OUT_OF_BOUNDS`
- `STALE_SNAPSHOT`
- `CROSS_PLANE_DISCREPANCY`
- `INSUFFICIENT_EVIDENCE`
- `GATE_EVALUATION_FAILED`
- `ASSERTION_FAILED`
- `UNKNOWN`
- *(and remaining canonical runtime failure categories)*

Normalization preserves:
- `normalized_category`: Stable category enum value.
- `original_classification`: The raw exception class name, diagnosis summary, or gate name.
- `confidence`: Calibrated confidence in the classification (0.0 to 1.0).
- `safe_context`: Structured attributes (action type, plane, target role) with sensitive fields scrubbed.

## 4. Failure Signature Derivation

To recognize recurring failure modes across sessions without storing sensitive data, `FailureNormalizer` computes a deterministic SHA-256 failure signature.

### Fields Participating in Signature:
1. `normalized_category`: Stable failure category string.
2. `action_type`: Action verb (e.g., `CLICK`, `TYPE_TEXT`, `SCROLL`).
3. `plane`: Execution plane (e.g., `NATIVE`, `WEBVIEW_DOM`, `HYBRID`).
4. `target_class`: Semantic target role or control type (e.g., `button`, `edit`, `window`).
5. `verdict`: Final tripartite verdict (`FAIL`, `UNVERIFIED`).
6. `recovery_result`: Outcome of recovery attempt if applicable (`SUCCESS`, `FAILED`, `BLOCKED`, `NONE`).

### Fields Explicitly Excluded from Signature:
- Volatile process IDs (PIDs)
- Window handles (HWNDs)
- Timestamps and sequence numbers
- Text input strings and typed values
- URLs and query parameters
- Raw DOM snippets and accessibility tree dumps
- Cryptographic nonces and session UUIDs

This guarantees that identical failure conditions produce the exact same 64-character hex signature across different runs, systems, and timeframes.

## 5. Recovery History

Bounded recovery attempts executed by `RecoveryEngine` are recorded in `recovery_attempts`:
- Trigger failure category and recovery action executed (`REFRESH_OBSERVATION`, `RETRY_WITH_REACQUIRE`, `CLEAR_INPUT_AND_RETYPE`, `DISMISS_MODAL_AND_RETRY`, etc.).
- Attempt number and configured maximum attempts (budget never increased by experience).
- Execution result (`SUCCESS`, `FAILED`, `BLOCKED`, `CANCELLED`).
- Execution duration in milliseconds (`duration_ms`).
- Associated trace event ID and sealed evidence references.

Historical recovery metrics allow the reviewer to report empirical recovery effectiveness per category without altering recovery policy.

## 6. Historical Query Model

The Experience Store exposes lightweight, deterministic analytics APIs:
- `get_failure_category_counts(project_id=None)`: Category frequency breakdown.
- `get_failure_signature_counts(limit=20)`: Recurring failure signatures with sample sessions.
- `get_failures_by_action_type(action_type=None)`: Action-specific failure distributions.
- `get_recent_failure_trend(category=None, time_window_seconds=None)`: Time-windowed failure trends.
- `get_recovery_statistics(category=None)`: Total attempts, success counts, success rates, and mean duration.
- `get_verification_distribution(session_id=None)`: `PASS` / `FAIL` / `UNVERIFIED` distribution and rates.

These queries provide descriptive historical metrics only; they do not autonomously alter runtime execution.

## 7. Privacy Boundary

Every record entering the Experience Store passes through `PrivacyEnforcer`:
- Prohibited metadata keys (`password`, `secret`, `token`, `cookie`, `bearer`, `auth`, `credential`, `private_key`) are immediately rejected.
- String values matching credential patterns (Bearer tokens, API keys, private keys, passwords) are replaced with `[REDACTED]`.
- Forensic binary blobs (PNGs, video, full DOM trees) are strictly forbidden; only SHA-256 hashes and relative paths are stored.
- Raw LLM prompts, reasoning traces, and agent conversational transcripts are rejected at the gate.
- Individual metadata payloads are bounded to 32 KB.

## 8. Graceful Degradation

If SQLite encounters lock contention, I/O errors, disk exhaustion, or serialization issues:
1. An error is logged at `WARNING` or `ERROR` level.
2. The method returns `None` or degraded defaults.
3. **The live desktop review continues unaffected.**

The reviewer never halts, skips an action, or fails an assertion due to an Experience Store persistence failure.

## 9. Why Experience Store Does Not Replace Trace, Evidence, or Verification

- **TraceEngine** remains the real-time, in-memory event bus providing monotonic sequencing and live telemetry for specialists and observers.
- **EvidenceStore** remains the cryptographically sealed, content-addressed forensic repository storing actual artifact files and sha256 manifests.
- **VerificationEngine** remains the physical truth validator applying deterministic gate logic and emitting authoritative tripartite outcomes.
- **ExperienceStore** is a downstream historical consumer indexing facts after settlement for cross-session intelligence and trend analysis.

## 10. Deferral of Antigravity Bridge to Prompt 3

Antigravity IDE integration (slash commands, transcript ingestion, sidecar communication, and agent correction loops) is deliberately deferred to **Milestone 2.1 Prompt 3**. 

Prompt 2 strictly implements:
```text
Authoritative DWR Runtime ──► Experience Store
```
No Antigravity internal scraping or hooks are present in Prompt 2, ensuring clean separation of concerns and zero risk of IDE tight-coupling.
