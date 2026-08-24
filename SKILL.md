---
name: desktop-webview-reviewer
description: >-
  Universal desktop webview testing, inspection, and verification capability. Tests actual running desktop applications containing embedded web surfaces (QtWebEngine, WebView2, Electron, CEF/Chromium, WebKit/WKWebView) in development mode via engine adapters without browser recreation or fake mocks.
---

# Universal Desktop WebView Reviewer

You are equipped to automate, inspect, and verify **actual running desktop applications containing embedded web surfaces** across all major desktop webview engines:
- **QtWebEngine** (PyQt5, PyQt6, PySide2, PySide6, C++ Qt)
- **Microsoft Edge WebView2** (WinForms, WPF, WinUI, C++, Tauri Win, Wails Win, pywebview)
- **Electron** (Cross-platform Chromium + Node.js runtime)
- **Generic Chromium & CEF** (Chromium Embedded Framework, CefSharp, OBS, Spotify, standalone embeds)
- **WebKit** (WebKitGTK on Linux, WKWebView on macOS)

---

## 1. Golden Law & Agent Guardrails

1. **The running desktop application is always the single source of truth.**
   - Never replace or fake a desktop test using standalone browser fixtures, web servers, or HTML mocks.
2. **Honest Verification Claims**:
   - Never report `"Desktop UI verified"` unless the actual application was attached and interacted with.
   - If attachment or execution fails, report: `"Actual desktop application could not be attached; desktop UI remains unverified."`
3. **Attach Mode Process Safety**:
   - When running in **Launch Mode** (reviewer launched app), reviewer cleans up the spawned process tree upon completion.
   - When running in **Attach Mode** (app already running externally), reviewer **NEVER** terminates the application upon detachment.
4. **Localhost Binding & Security**:
   - Debugging endpoints bind strictly to `127.0.0.1`.
   - Commands are passed as structured argument lists (`shell=False`) to prevent injection.

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
Discover & Rank Targets
       ↓
Select Target Page
       ↓
Observe Initial DOM / State
       ↓
Act (Click / Type / Navigate)
       ↓
Re-observe & Assert State Changes
       ↓
Capture Verified Screenshot & Console Logs
       ↓
Generate Evidence Report (evidence.json)
       ↓
Teardown / Detach Safely
```

---

## 4. CLI Tool Reference

### Step 0: Doctor Diagnostics (Optional Pre-Check)
```bash
python scripts/doctor.py [--verbose] [--json]
```
- Performs instant environment, core integrity, and engine availability diagnostics.

### Step 1: Launch Application (or skip if already running)
```bash
python scripts/launch.py <executable_or_script> [app_args...] --engine auto --port 9222
```
- Injects engine-appropriate remote debugging flags/variables.
- Records PID and creates `desktop_ownership.json`.

### Step 2: Discover and Rank Webview Targets
```bash
python scripts/discover.py --engine auto --port 9222
```
- Queries `http://127.0.0.1:<port>/json/list`.
- Ranks candidate targets, filters out DevTools/workers, selects primary application page, and writes WebSocket URL to `desktop_ws_url.txt`.

### Step 3: Inspect, Interact, and Assert
```bash
python scripts/review.py --click="#my-button" --assert-selector="#result" --assert-text="Expected" --screenshot="screenshot.png" --evidence="evidence.json"
```
- Connects via CDP over WebSocket.
- Performs structured actions, before/after assertions, console log capture, and screenshot capture with SHA-256 hash.

### Step 4: Cleanup & Teardown
```bash
python scripts/stop.py
```
- Safely terminates reviewer-owned process tree or detaches harmlessly if externally owned.

---

## 5. Self-Diagnostic Failure Reporting

When discovery, attachment, or assertions fail, the tools automatically output structured diagnostic reports:

```text
======================================================
=== Webview Review Diagnostic Report [FAILURE] ===
======================================================
Framework:           <framework>
Engine:              <engine>
Confidence:          <confidence>
Platform:            <platform>
Launch mode:         <launched_by_reviewer | attached_external>
Candidate targets:   <candidate targets if discovered>
Selected target:     <selected target>
Connection method:   CDP WebSocket / HTTP Poll
Failure stage:       <launch | discovery | attach | inspection | interaction | assertion>
Reason:              <exception message>
Suggested next diagnostic: <actionable troubleshooting tip>
======================================================
```

---

## 6. References

- Architecture Guide: `references/architecture.md`
- Capability Matrix: `references/capabilities.md`
- Adapter Contract: `references/adapter-contract.md`
- Troubleshooting: `references/troubleshooting.md`
