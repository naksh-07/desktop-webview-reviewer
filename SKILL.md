---
name: desktop-webview-reviewer
description: >-
  Universal desktop webview testing, inspection, and forensic verification capability. Tests and verifies actual running desktop applications containing embedded web surfaces (QtWebEngine, WebView2, Electron, CEF/Chromium, WebKit/WKWebView) in development mode with native Windows GUI identity, dual screenshot provenance, and tripartite verdicts (PASS/FAIL/UNVERIFIED).
---

# Universal Desktop WebView Reviewer — Forensic Verification Engine

You are equipped to automate, inspect, and forensically verify **actual running desktop applications containing embedded web surfaces** across all major desktop webview engines:
- **QtWebEngine** (PyQt5, PyQt6, PySide2, PySide6, C++ Qt)
- **Microsoft Edge WebView2** (WinForms, WPF, WinUI, C++, Tauri Win, Wails Win, pywebview)
- **Electron** (Cross-platform Chromium + Node.js runtime)
- **Generic Chromium & CEF** (Chromium Embedded Framework, CefSharp, OBS, Spotify, standalone embeds)
- **WebKit** (WebKitGTK on Linux, WKWebView on macOS)

> **AGENT SKILL NOTICE**: The authoritative first-class Agent Skill and 7 declarative workflows are published under [skills/desktop-webview-reviewer/SKILL.md](file:///c:/Users/Suraj/Documents/Antigravity/Desktop-priview/skills/desktop-webview-reviewer/SKILL.md) and [workflows/](file:///c:/Users/Suraj/Documents/Antigravity/Desktop-priview/skills/desktop-webview-reviewer/workflows/). Always adhere to the Physical Reality Primacy, Reference Discipline, and Tripartite Verdict Model defined therein.

## 0. Constitutional Sovereignty Boundary & Anti-God-Agent Rule
Reviewer operates under an unbending constitutional doctrine:
> **The controlling agent decides WHAT should be done and WHY. Desktop WebView Reviewer decides HOW it can be safely and reliably done.**

```text
WHAT / WHY (Mission Authority)
    ↓  Antigravity / TeamPreview / Adaptive Orchestrator
HOW / VERIFY (Capability Layer)
    ↓  Desktop WebView Reviewer 2.0
```

1. **Reviewer Decides (HOW)**: Inspection planes, target resolution, coordinate math, pre-action actionability, settlement duration, stale recovery, evidence hashing, failure classification.
2. **Reviewer Must NOT Decides (WHAT/WHY)**: What app or workflow to test, what features matter to the business, what unrelated screens to explore, or expanding scope autonomously.
3. **Anti-God-Agent Mandate**: Reviewer contains zero hidden planning loops. Autonomy is strictly confined inside delegated technical capability boundaries.
4. **Subordinate Specialists Rule**: Specialists (`Explorer`, `Tester`, `RealityInspector`, `Debugger`, `EvidenceSpecialist`) diagnose and execute delegated technical work. They do not decide the mission.
5. **Bounded Recovery Rule**: Recovery restores testability. Recovery does not redefine the test. No blind retries without prior diagnosis.
6. **Harness Golden Rule**: The Reviewer Test Harness provides supporting internal diagnostics only. Black-box physical reality validation outranks instrumented telemetry. A harness signal never overrides failed physical reality verification.
7. **Autonomous Review Mission Rule (Phases 17–18)**: Autonomous review requires an explicit `ReviewMission` authority envelope admitted through the 13-point `MissionAdmissionGate`. Discovery is strictly bounded to declared scope with zero general crawling. Subordinate `ReviewPlan` execution is budget-capped and cancellable. Presentation layers (TeamPreview) are strictly read-only.

---

## 1. Golden Law & Forensic Guardrails

1. **The running desktop application is always the single source of truth.**
   - Never replace or fake a desktop test using standalone browser fixtures, web servers, or HTML mocks.
2. **HARD RULE: CDP / Webview Success != Visible Desktop GUI Proof.**
   - Connecting to a remote debugging port or querying DOM via CDP is NOT sufficient proof that a visible desktop application window is rendering on the host desktop.
   - The reviewer strictly verifies native OS window handles (`HWND`), visibility (`IsWindowVisible`), non-iconic state (`!IsIconic`), non-cloaked state (`!DWMWA_CLOAKED`), non-zero geometry ($\ge 30\times 30$), and process-tree correlation before awarding a `PASS` verdict.
3. **Tripartite Verdict Separation**:
   - **`PASS`**: Full forensic chain verified (Visible GUI window confirmed on desktop + PID matched + CDP port verified + target connected + assertions passed + screenshots hashed).
   - **`FAIL`**: Execution completed or attached, but one or more state assertions failed or an unhandled JS/runtime error occurred.
   - **`UNVERIFIED`**: Insufficient runtime identity or evidence (e.g. headless browser without GUI, ghost CDP port, mismatched PID/port, minimized/cloaked window, or screenshot without native GUI proof).
4. **Dual Screenshot Provenance**:
   - Every screenshot explicitly records whether it is:
     - `native_desktop`: Captured from OS window DC via Win32 GDI `PrintWindow` (proof of desktop reality).
     - `webview_viewport`: Captured from webview viewport.
     - `cdp_page_capture`: Captured via CDP `Page.captureScreenshot`.
   - Never describe a CDP webview screenshot as proof that the native GUI was visible.
5. **Attach Mode Process Safety**:
   - When running in **Launch Mode** (reviewer launched app), reviewer cleans up the spawned process tree upon completion.
   - When running in **Attach Mode** (app already running externally), reviewer **NEVER** terminates the application upon detachment.

---

## 2. Verification Matrix

| Engine Adapter | Windows | Linux | macOS | Status & Evidence |
|---|---|---|---|---|
| **QtWebEngine** | `RUNTIME_VERIFIED` | `Supported` | `Supported` | PyQt6 live runtime verified with remote debugging & CDP WebSocket |
| **WebView2** | `RUNTIME_VERIFIED` | N/A | N/A | Edge WebView2 live runtime verified with env injection |
| **Electron** | `RUNTIME_VERIFIED` | `Supported` | `Supported` | Electron live runtime verified with `--remote-debugging-port` |
| **Generic Chromium** | `RUNTIME_VERIFIED` | `Supported` | `Supported` | Standard Chromium / Chrome DevTools Protocol verified |
| **CEF (Chromium Embedded)** | `PROTOCOL_VERIFIED` | `PROTOCOL_VERIFIED` | `PROTOCOL_VERIFIED` | CDP protocol verified; standalone native CEF runtime pending host fixture |
| **WebKit / WKWebView** | `RUNTIME_UNAVAILABLE` | `Supported` | `Supported` | Windows compiles Tauri/Wails to WebView2. Linux/macOS requires WebKit host |

---

## 3. Universal Agent Workflow

When the user asks in natural language:
- *"Test this desktop application"*
- *"Run a smoke test on the UI"*
- *"Verify that clicking the increment button updates the counter"*
- *"Inspect and capture a screenshot of the running app"*

Execute the standard lifecycle sequence:

```text
Detect Framework & Engine
       ↓
Route to Adapter
       ↓
Launch (or Attach to Running App)
       ↓
Discover & Verify Port/Target Ownership
       ↓
Inspect Windows Native GUI Identity (HWND, Visibility, Geometry)
       ↓
Connect CDP Session & Probe Capabilities
       ↓
Act (Click / Type / Navigate)
       ↓
Re-observe & Assert State Changes
       ↓
Capture Dual Screenshots (Native OS HWND + CDP Webview) & Hash SHA-256
       ↓
Evaluate Forensic Verdict (PASS / FAIL / UNVERIFIED)
       ↓
Generate Hardened Evidence Report (evidence.json)
       ↓
Teardown / Detach Safely
```

---

## 4. CLI Tool Reference

### Step 0: Doctor Diagnostics
```bash
desktop-webview-doctor [--verbose] [--json]
```
- Performs instant environment, Win32 forensics engine, core integrity, and engine availability diagnostics.

### Step 1: Launch Application (or skip if already running)
```bash
desktop-webview-launch <executable_or_script> [app_args...] --engine auto --port 9222
```
- Injects engine-appropriate remote debugging flags/variables.
- Records PID and creates `desktop_ownership.json`.

### Step 2: Discover and Rank Webview Targets
```bash
desktop-webview-discover --engine auto --port 9222
```
- Queries `http://127.0.0.1:<port>/json/list`.
- Ranks candidate targets, filters out DevTools/workers, selects primary application page, and writes WebSocket URL to `desktop_ws_url.txt`.

### Step 3: Hardened Forensic Review & Assertion
```bash
desktop-webview-review --click="#my-button" --assert-selector="#result" --assert-text="Expected" --screenshot="screenshot.png" --evidence="evidence.json"
```
- Correlates HWND $\leftrightarrow$ PID $\leftrightarrow$ Process $\leftrightarrow$ Port $\leftrightarrow$ Target.
- Performs structured actions, before/after assertions, console log capture, and dual screenshot capture with SHA-256 hash.
- Produces extended `evidence.json` with explicit `PASS` / `FAIL` / `UNVERIFIED` verdict.

### Step 4: Cleanup & Teardown
```bash
desktop-webview-stop
```
- Safely terminates reviewer-owned process tree or detaches harmlessly if externally owned.

### Step 5: Subordinate Specialist Invocations & Diagnostics (Phase 15–16)
```bash
# List all 5 canonical specialist roles (Explorer, Tester, Reality Inspector, Debugger, Evidence Specialist)
desktop-reviewer specialists list

# Inspect canonical role contract (permitted tools, forbidden operations, read-only status)
desktop-reviewer specialists contract EXPLORER [--json]

# Run unified multi-source diagnostic correlation over trace, logs, and compositor state
desktop-reviewer diagnostics [--session <id>] [--action-id <id>] [--json]

# Inspect circuit breaker status and anti-retry-storm reliability state
desktop-reviewer recovery status [--json]

# Query deterministic recovery candidate actions for a failure category
desktop-reviewer recovery candidates WINDOW_CLOAKED [--json]
### Step 6: Multi-Framework Certification & Release Validation (Phase 19–20)
```bash
# Run multi-framework live adversarial certification matrix across QtWebEngine, Electron, WebView2
desktop-reviewer certify

# Run 6-domain production security audit (Process, Network, Filesystem, Data, Authority, Release)
desktop-reviewer security-audit

# Execute deterministic 8-gate production release pipeline
desktop-reviewer release-validate
```

---

## 5. Extended Evidence Schema (`evidence.json`)

```json
{
  "session_id": "session_8f3a9b1c",
  "verdict": "PASS",
  "verdict_reason": "Verified live visible desktop GUI window and matching CDP target with all assertions passing.",
  "hwnd": 65536,
  "pid": 12480,
  "executable": "C:\\Python311\\python.exe",
  "window_title": "StudyLab MainWindow",
  "window_visible": true,
  "window_geometry": { "x": 100, "y": 100, "width": 1024, "height": 768 },
  "cdp_port": 9222,
  "cdp_target": { "id": "target_01", "type": "page", "title": "StudyLab", "url": "about:blank" },
  "screenshot_type": "cdp_page_capture",
  "screenshot_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "window_forensics": {
    "hwnd": 65536,
    "pid": 12480,
    "window_visible": true,
    "is_iconic": false,
    "is_cloaked": false,
    "is_real_gui": true,
    "geometry": { "x": 100, "y": 100, "width": 1024, "height": 768 },
    "hwnd_pid_matched": true
  },
  "screenshots": {
    "webview": { "screenshot_type": "cdp_page_capture", "screenshot_hash": "...", "path": "screenshot.png" },
    "native": { "screenshot_type": "native_desktop", "screenshot_hash": "...", "path": "screenshot_native.png" }
  },
  "state_assertions": [
    { "description": "Header title", "passed": true, "expected": "StudyLab", "actual": "StudyLab" }
  ],
  "actions": [
    { "action_type": "click", "selector": "#btn", "success": true }
  ]
}
```

---

## 6. References

- Architecture Guide: `references/architecture.md`
- Capability Matrix: `references/capabilities.md`
- Adapter Contract: `references/adapter-contract.md`
- Troubleshooting: `references/troubleshooting.md`
