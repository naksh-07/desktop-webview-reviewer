# Architecture Document 26: Reviewer Test Harness Specification & Security Boundary

**Document ID:** `docs/architecture/26_REVIEWER_TEST_HARNESS_SPECIFICATION.md`  
**Status:** APPROVED (Phase 9 Milestone)  
**Author:** Principal System Architect & Antigravity Lead  
**Target Repository:** `desktop-webview-reviewer`  
**Baseline:** Architecture H Foundation, Docs 11–20

---

## 1. Executive Summary

As desktop applications grow in complexity, black-box testing alone—while necessary for reality validation—can struggle with asynchronous operation timing (e.g. knowing exactly when a SQLite background transaction finishes or when a remote sync completes).

Desktop WebView Reviewer 2.0 introduces the **Reviewer Test Harness**: an optional, highly structured, in-process instrumentation interface designed specifically for **development and review builds**.

The Test Harness provides:
- Deterministic lifecycle synchronization signals
- Rich internal state diagnostics
- Controlled test fixture seeding and teardown
- Explicit fault injection (chaos testing)
- In-process telemetry correlation

---

## 2. The Harness Golden Rule

The most critical architectural principle governing the Test Harness is:

> **The Test Harness is supporting evidence. It must NEVER become the authoritative source of user-facing success.**

```
┌─────────────────────────────────────────────────────────────┐
│                    THE FORBIDDEN ANTI-PATTERN               │
│                                                             │
│       Harness reports: SAVE_COMPLETED                       │
│                     ↓                                       │
│       Reviewer declares: PASS (FRAUDULENT!)                 │
│                                                             │
│  Why fatal? The database may have saved the record, but     │
│  the UI thread could be frozen, the modal dialog crashed,   │
│  or the save button was never rendered to the user!         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   THE HARNESS GOLDEN RULE                   │
│                                                             │
│       1. Agent triggers Save via physical UI interaction    │
│       2. Reviewer delivers physical/CDP input               │
│       3. Application processes input                        │
│       4. Harness emits diagnostic: SAVE_COMPLETED           │
│       5. Reviewer independently inspects physical screen    │
│          and dual-perspective state delta                   │
│       6. Reviewer authoritatively verifies outcome: PASS    │
└─────────────────────────────────────────────────────────────┘
```

### The Core Duality:
- **BLACK-BOX TESTING = Reality Validation** (Answers: "Did the software physically work for a human user?")
- **INSTRUMENTED HARNESS = Forensic Diagnosis** (Answers: "What internal subsystem did what, when, and why did it fail?")

---

## 3. Harness Functional Capabilities

### 3.1 Lifecycle Synchronization Signals
The harness emits high-precision timing signals that allow Reviewer's settlement engine to wait deterministically rather than relying on arbitrary sleep timeouts:
* `APP_STARTING`: Process initialized, runtime bootstrapping.
* `APP_READY`: Framework loaded, main window initialized and accepting input.
* `SCREEN_READY`: Route loaded, virtual DOM hydrated, visual transition complete.
* `DATA_READY`: Background queries or REST fetches completed.
* `SAVE_STARTED`: Disk/database write transaction initiated.
* `SAVE_COMPLETED`: Disk/database write transaction committed.
* `NAVIGATION_STARTED`: Route transition initiated.
* `NAVIGATION_COMPLETED`: Target screen mounted and stable.

### 3.2 Internal State Diagnostics
Provides deep diagnostic visibility into the application runtime:
* `current_screen`: Logical screen or view name.
* `current_route`: URL path or navigation stack state.
* `active_operations`: List of currently executing async tasks or thread pools.
* `operation_duration_ms`: Execution time of active/completed tasks.
* `internal_errors`: Handled exceptions or internal log warnings.
* `pending_operations`: Count and IDs of queued background tasks.

### 3.3 Test Fixture Management
Enables reproducible, idempotent automated testing:
* `seed_data`: Injects mock database tables, local storage, or session states.
* `reset_state`: Clears caches, resets configuration to defaults.
* `create_fixture`: Creates specific temporary records (e.g. test deck in Anki).
* `clear_fixture`: Removes temporary test data without touching user profiles.

### 3.4 Fault Injection (Chaos Engineering)
Allows agents to test application resilience against hostile environments:
* `NETWORK_DELAY`: Injects synthetic latency into HTTP/WebSocket requests.
* `NETWORK_FAILURE`: Drops specific requests or simulates offline mode.
* `DATABASE_FAILURE`: Forces database queries to throw I/O or lock exceptions.
* `TIMEOUT`: Deliberately stalls specific background operations.
* `RENDER_DELAY`: Artificially throttles frame generation.
* `PERMISSION_FAILURE`: Simulates OS filesystem or camera permission denials.
* `SIMULATED_CRASH`: Forces application to abort to test recovery logic.

---

## 4. Harness Security Boundary & Release CI Exclusion

The Test Harness is **strictly forbidden from existing in production release binaries**. It must never become a hidden backdoor or an attack surface.

```
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│       REVIEW / DEV BUILD        │       │         RELEASE BUILD           │
│                                 │       │                                 │
│  - Test Harness compiled in     │       │  - Harness completely ABSENT    │
│  - Localhost IPC bridge open    │       │  - No test endpoints or sockets │
│  - Fault injection available    │       │  - No fault injection hooks     │
│  - Diagnostics enabled          │       │  - No debug symbols or bridges  │
└─────────────────────────────────┘       └─────────────────────────────────┘
```

### Mandatory CI Security Gates:
1. **Compilation Segregation:** In compiled languages (C++, C#, Rust, Go), the harness must be guarded by build preprocessor tags (e.g. `#if DEBUG || REVIEWER_HARNESS`). In JavaScript/TypeScript, it must be stripped by dead-code elimination / tree-shaking.
2. **Release Artifact Inspection:** Continuous Integration (CI) release pipelines must run binary grep and symbol analysis:
   - Must fail CI if `ReviewerHarness` symbols, endpoints, or IPC pipes are detected in production packages.
3. **No Secret Runtime Switches:** There must be **no runtime environment variable or command-line flag** that turns on the harness in a production binary. The code must simply not exist in the binary.
4. **Transport Confinement:** When present in dev builds, harness IPC is strictly confined to `127.0.0.1` or named pipes with user-only ACLs (`DACL: (A;;GRGW;;;OW)`).
