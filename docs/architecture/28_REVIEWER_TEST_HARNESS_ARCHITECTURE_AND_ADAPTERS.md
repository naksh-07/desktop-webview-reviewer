# Architecture Document 28: Reviewer Test Harness Architecture & Framework Adapters

**Document ID:** `docs/architecture/28_REVIEWER_TEST_HARNESS_ARCHITECTURE_AND_ADAPTERS.md`  
**Status:** APPROVED (Phases 13–14 Milestone — Prompt P3)  
**Author:** Principal System Architect & Antigravity Lead  
**Target Repository:** `desktop-webview-reviewer`  
**Baseline:** Phases 0–12 Architecture & Runtime (`docs/architecture/26_REVIEWER_TEST_HARNESS_SPECIFICATION.md`)

---

## 1. Executive Summary & Constitutional Principles

Phase 13–14 realizes the Reviewer Test Harness specified in Architecture Document 26 as an operational, framework-neutral diagnostic and test-support subsystem. The Harness bridges the application under test (AUT) and the Desktop WebView Reviewer runtime during development and review cycles without violating core constitutional boundaries.

```text
                  CONTROLLING AGENT
                     WHAT / WHY
                         │
                         ▼
              DESKTOP WEBVIEW REVIEWER
                         HOW
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
     EYES               HANDS          INSTRUMENTS
       │                 │                 │
       │                 │          Trace / Logs
       │                 │          Harness data
       ▼                 ▼                 │
 Physical Desktop    User-equivalent      │
    Reality             Input              │
       │                 │                 │
       └─────────────────┼─────────────────┘
                         ▼
                 VERIFIED RESULT
```

### 1.1 The Inviolable Golden Rule
> **Black-box physical reality validation outranks instrumented diagnosis.**

Harness signals (e.g. `SAVE_COMPLETED`, `APP_READY`) serve as diagnostic timing, settlement synchronization, and state hints. They are untrusted application data and cannot independently certify task success:
- $\text{Harness PASS} \land \text{Physical PASS} \implies \text{PASS}$
- $\text{Harness PASS} \land \text{Physical FAIL} \implies \text{FAIL}$
- $\text{Harness PASS} \land \text{Physical UNVERIFIED} \implies \text{UNVERIFIED}$
- $\text{Harness FAIL} \land \text{Physical PASS} \implies \text{Evaluated by Reviewer Verification Engine}$

### 1.2 The Non-Agency Invariant
The Harness is strictly an instrumentation layer:
- It **does not** become an agent.
- It **does not** decide what application workflows to test.
- It **does not** expand testing scope.
- It **does not** issue instructions or policies to the Reviewer.
- It **does not** execute unrequested side-effects.

---

## 2. Core Architecture & Wire Protocol

```text
Application Process (AUT)                       Reviewer Runtime
┌─────────────────────────┐               ┌───────────────────────────┐
│     Harness Client      │               │   HarnessTransportServer  │
│  (Electron/WV2/Qt SDK)  │               │   (Loopback 127.0.0.1)    │
│                         │               │                           │
│  ┌───────────────────┐  │ HTTP POST     │  ┌─────────────────────┐  │
│  │ Lifecycle Signals │──┼───────────────┼─▶│ /api/harness/event  │  │
│  │ Diagnostics State │  │ Bearer Token  │  └─────────────────────┘  │
│  │ Fixture Handlers  │◀─┼───────────────┼──│ Trace Ingestion Engine││
│  │ Fault Injection   │  │ Correlated ID │  │ (source="harness",     ││
│  └───────────────────┘  │ JSON Envelope │  │  trust="diagnostic")  ││
└─────────────────────────┘               └───────────────────────────┘
```

### 2.1 Wire Message Protocol (`runtime/harness/protocol.py`)
All communications between the Harness Client and Reviewer Runtime adhere to the canonical `HarnessMessage` envelope:

```json
{
  "protocol_version": "2.0",
  "message_type": "LIFECYCLE_EVENT",
  "session_id": "sess_1234567890ab",
  "application_id": "app_sample_target",
  "harness_instance_id": "inst_0987654321fe",
  "timestamp": 1725548400.123,
  "payload": {
    "lifecycle_state": "APP_READY",
    "screen": "MainDashboard",
    "route": "/dashboard"
  },
  "correlation_id": "act_click_save_btn",
  "error": null
}
```

#### Security Envelopes & Hard Limits
1. **Size Bounds:** Messages exceeding `MAX_MESSAGE_BYTES = 1,048,576` (1MB) are unconditionally rejected with `413 Payload Too Large`.
2. **Temporal Window:** Messages with timestamps deviating by more than $\pm 300$ seconds from the server's monotonic clock are rejected to prevent replay attacks.
3. **Session Binding:** Messages must supply an authentic session token matching `SessionState.session_id`.
4. **Instruction Immunity:** Payload strings containing prompt injection patterns (e.g., `Ignore previous instructions...`) remain strictly isolated within diagnostic data structures and are never evaluated as instructions.

---

## 3. Local Transport Layer (`runtime/harness/transport.py`)

The Harness transport is designed for lightweight, zero-dependency development IPC:
- **Binding:** Strictly loopback `127.0.0.1` (never `0.0.0.0` or public interfaces).
- **Protocol:** HTTP/1.1 REST endpoints (`/api/harness/handshake`, `/api/harness/event`, `/api/harness/diagnostic`, `/api/harness/command`, `/api/harness/health`).
- **Authentication:** Cryptographic bearer token (`auth_token`) generated per session.
- **Port Allocation:** Dynamic ephemeral port discovery with collision avoidance.

---

## 4. Framework Adapter Model (`runtime/harness/adapters/`)

The framework adapter abstraction isolates framework-specific lifecycle hooks, IPC bridges, and runtime entry points behind a unified contract (`HarnessAdapterBase`):

```text
                   HarnessAdapterBase
              (Common Contract & Protocol)
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
 ElectronAdapter     WebView2Adapter       QtAdapter
```

### 4.1 Adapter Capability Matrix

| Capability | Electron | WebView2 | Qt / QtWebEngine |
| :--- | :---: | :---: | :---: |
| **Core Connection** | `AVAILABLE` | `AVAILABLE` | `AVAILABLE` |
| **Lifecycle Events** | `AVAILABLE` | `AVAILABLE` | `AVAILABLE` |
| **Diagnostics State** | `AVAILABLE` | `AVAILABLE` | `AVAILABLE` |
| **Fixtures (Seed/Reset)**| `AVAILABLE` | `AVAILABLE` | `AVAILABLE` |
| **Fault Injection** | `AVAILABLE` | `DEGRADED` (Host IPC bounded) | `AVAILABLE` |

*Note on WebView2 Fault Injection:* WebView2 process isolation prevents safe out-of-process network fault simulation without elevated network filter drivers; therefore, its capability is honestly reported as `DEGRADED` rather than faking support.

### 4.2 Adapter Details

#### 1. Electron Adapter (`runtime/harness/adapters/electron.py`)
- **Integration Target:** Main process entry point (`main.js`, `index.js`, `src/main/index.ts`).
- **Lifecycle Hooking:** Attaches to `app.whenReady()`, `BrowserWindow` focus/ready events, and `did-finish-load`.
- **Diagnostic Collection:** Queries process memory metrics (`process.memoryUsage()`), active window counts, and navigation URLs.
- **Security Posture:** Operates via a dedicated development IPC channel (`__reviewer_harness__`), avoiding unsafe Node integration in renderers.

#### 2. WebView2 Adapter (`runtime/harness/adapters/webview2.py`)
- **Integration Target:** Host application entry (`Program.cs`, `MainWindow.xaml.cs`).
- **Lifecycle Hooking:** Listens to `CoreWebView2.NavigationStarting`, `NavigationCompleted`, and `CoreWebView2InitializationCompleted`.
- **Diagnostic Collection:** Transmits host window handle, WebView2 runtime version, and navigation state.

#### 3. Qt Adapter (`runtime/harness/adapters/qt.py`)
- **Integration Target:** Application entry (`main.py`, `app.py`).
- **Lifecycle Hooking:** Integrates with `QWebEngineView.loadStarted`, `loadFinished`, and `QApplication` event loop hooks.
- **Diagnostic Collection:** Surfaces QWebEngine page title, active geometry, and process identifiers.

---

## 5. Surgical Project Injection & Removal

The developer workflow operates via `desktop-reviewer harness init` and `desktop-reviewer harness remove`:

```text
Target Project Directory
           │
           ▼
ProjectDetector (Electron / WebView2 / Qt heuristics)
           │
           ▼
HarnessInjector.plan() ──[--dry-run]──▶ Inspect planned changes
           │
           ▼
HarnessInjector.apply()
  ├── Injects ReviewerHarness.js / .cs / .py module
  ├── Wraps entry-point hooks with surgical comment markers:
  │     // >>> REVIEWER_HARNESS_START >>>
  │     ... dev integration ...
  │     // <<< REVIEWER_HARNESS_END <<<
  └── Writes .reviewer_harness.json integration manifest
```

### 5.1 Reversibility & Auditability (`runtime/harness/manifest.py`)
- Every modification records the pre-modification SHA-256 hash.
- `desktop-reviewer harness remove` surgically extracts code enclosed within the markers and deletes injected auxiliary files.
- If manual edits corrupt the boundary markers, removal aborts safely without destructive file overwrites.

---

## 6. Build Modes & Release Security Pipeline

Three mutually exclusive build modes govern harness existence:

```text
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│       DEV       │       │     REVIEW      │       │     RELEASE     │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ Harness: ALLOWED│       │ Harness: ALLOWED│       │Harness:FORBIDDEN│
│ Purpose: Local  │       │ Purpose: CI / QA│       │ Purpose: Ship to│
│ testing & debug │       │ certification   │       │ end customers   │
└─────────────────┘       └─────────────────┘       └─────────────────┘
```

### 6.1 The Zero Production Backdoor Invariant
- Harness code must **never** be included in release binaries.
- No runtime flags (e.g. `ENABLE_HARNESS=true` or `--enable-reviewer-harness`) are permitted to reactivate dormant harness code.
- Exclusion must occur at build/compilation time via bundler tree-shaking, package exclusion, or compiler preprocessor directives (`#if DEBUG`).

### 6.2 Release Security Validation Gate (`runtime/harness/build_pipeline.py`)
The validator inspects release artifacts for unauthorized harness traces:
1. **Module Artifacts:** Prohibits `ReviewerHarness.*` or `reviewer_harness.*` files.
2. **Boundary Markers:** Scans for lingering `REVIEWER_HARNESS_START` blocks.
3. **Loopback Endpoints:** Flags hardcoded `/api/harness/*` string literals.
4. **Symbol Audit:** Scans binary/source for `ReviewerHarnessClient`, `__reviewer_harness__`, or backdoor activation flags.

If any violation is detected, `validate-release` fails closed with detailed audit evidence.

---

## 7. Trace & Observability Integration

Harness events feed directly into the existing `DesktopTraceEngine` (`runtime/trace_engine.py`):
- **Trace Source:** Marked explicitly as `source="harness"`.
- **Trust Class:** Tagged as `trust_class="diagnostic"`.
- **Event Correlation:** Every event carries the enclosing action's `correlation_id`, synchronizing with native window focus, input dispatch, settlement polling, and visual evidence captures.
