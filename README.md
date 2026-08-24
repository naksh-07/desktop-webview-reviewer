# Desktop WebView Reviewer

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/status-production--ready-green.svg)](README.md)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Universal desktop application webview testing, inspection, and verification capability for Google Antigravity.

---

## What It Is

**Desktop WebView Reviewer** is a production-grade, engine-agnostic toolchain designed to automate, inspect, and verify **actual running desktop applications containing embedded web surfaces**. 

Unlike standard browser automation frameworks that spin up simulated browser windows or headless mock servers, Desktop WebView Reviewer interacts directly with physical operating system process trees and communicates via raw, asynchronous Chrome DevTools Protocol (CDP) and WebKit Remote Inspector transports.

### Key Capabilities
- **Physical Process Truth**: Attaches to genuine desktop executables and window handles.
- **Universal Multi-Engine Routing**: Automatically routes frameworks (PyQt, PySide, Tauri, Wails, PyWebView, CefSharp, Electron, .NET) to their underlying native webview engine.
- **Intelligent Target Ranking**: Discovers and prioritizes application webview windows while ignoring DevTools windows, background service workers, and blank targets.
- **Ownership-Safe Process Teardown**: Strict separation between *Launch Mode* (reviewer-owned, recursive process tree cleanup with PID-reuse collision protection) and *Attach Mode* (externally-owned, zero-impact detachment).
- **Forensic Evidence Collection**: Produces deterministic screenshot artifacts validated with PNG magic bytes and SHA-256 integrity hashes alongside structured `evidence.json` reports.

---

## Supported Engines

Desktop WebView Reviewer encapsulates 5 specialized engine adapters behind a unified interface:

1. **QtWebEngine**: PyQt5, PyQt6, PySide2, PySide6, and native C++ Qt applications (`QTWEBENGINE_REMOTE_DEBUGGING`).
2. **Microsoft Edge WebView2**: WinForms, WPF, WinUI, Tauri (Windows), Wails (Windows), PyWebView (Windows), and .NET (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`).
3. **Electron**: Cross-platform Chromium + Node.js desktop applications (`--remote-debugging-port`).
4. **Generic Chromium & CEF**: Chromium Embedded Framework, CefSharp, OBS Studio, and standalone Chromium embeds.
5. **WebKit**: WebKitGTK on Linux (`WEBKIT_INSPECTOR_SERVER`) and native WKWebView on macOS.

---

## Verification Matrix

We maintain strict verification integrity across all engines and platforms:

| Engine Adapter | Host Frameworks | Verification Level | Platform Notes |
|---|---|---|---|
| **QtWebEngine** | PyQt6, PyQt5, PySide6, C++ Qt | `RUNTIME_VERIFIED` | Verified on live PyQt6 test apps & real-world Anki Maths app. |
| **WebView2** | WPF, WinForms, Tauri (Win), Wails (Win) | `RUNTIME_VERIFIED` | Verified on Windows with Microsoft Edge & WebView2 Evergreen Runtime. |
| **Electron** | Electron Renderer | `RUNTIME_VERIFIED` | Verified on Windows with genuine Electron runtime fixture. |
| **Generic Chromium** | Chromium, Chrome, Brave, CEF Embeds | `RUNTIME_VERIFIED` | Verified with live CDP loopback endpoints. |
| **CEF** | CefSharp, cefpython3 | `PROTOCOL_VERIFIED` | CDP protocol translation verified; standalone host binary pending. |
| **WebKit** | WebKitGTK, WKWebView | `RUNTIME_UNAVAILABLE` | Platform constraint on Windows (Windows frameworks compile to WebView2). |

### Terminology Definitions
- `RUNTIME_VERIFIED`: An actual physical desktop application process was launched or attached on the host OS, exercised with DOM actions, verified with assertions, and validated via screenshot/evidence artifacts.
- `PROTOCOL_VERIFIED`: The protocol communication, packet translation, and JSON-RPC message layer have been rigorously unit and integration tested, but a live packaged binary of that specific variant was not executed in the test suite.
- `PROTOCOL_VERIFIED ≠ RUNTIME_VERIFIED`: Protocol verification confirms command correctness; runtime verification confirms live OS process execution.
- `Generic Chromium Runtime Verified ≠ CEF Runtime Verified`: Standalone Chromium execution does not substitute for dedicated CEF host verification.
- `RUNTIME_UNAVAILABLE`: The target engine runtime is not natively available on the host operating system (e.g. native WebKitGTK/WKWebView on Windows).

---

## Installation

### Prerequisites
- Python 3.9 or higher (64-bit recommended)
- Windows 10/11, Linux (Ubuntu/Debian), or macOS

### Minimal Installation (Stdlib-First)

```bash
# Clone or navigate to the skill repository
cd desktop-webview-reviewer

# Install minimal production runtime dependencies
pip install -r requirements.txt
```

Production dependencies are strictly minimal:
- `websockets>=11.0`: Async CDP WebSocket protocol transport.
- `psutil>=5.9.0`: Process tree tracking, anti-collision verification, and teardown.

---

## Doctor (Self-Check Diagnostic Tool)

Run the built-in diagnostic tool to verify environment health, dependency integrity, and available host webview engines:

```bash
python scripts/doctor.py
```

### Example Doctor Output
```text
=================================================================
        Desktop WebView Reviewer v1.0.0 - Doctor Check
=================================================================
Python Environment:   PASS       (3.13.1 64-bit on Windows)
Core Dependencies:    PASS       (websockets: 15.0.1, psutil: 7.0.0)
Core Subsystems:      PASS       (5 adapters registered)
CDP Transport:        PASS       (Async WebSocket 50MB payload)
-----------------------------------------------------------------
Host Engine Availability & Verification Status:
  QtWebEngine:        AVAILABLE       [RUNTIME_VERIFIED on Windows]
  WebView2:           AVAILABLE       [RUNTIME_VERIFIED on Windows]
  Electron:           AVAILABLE       [RUNTIME_VERIFIED on Windows]
  Generic Chromium:   AVAILABLE       [RUNTIME_VERIFIED on Windows]
  CEF:                PROTOCOL ONLY   [PROTOCOL_VERIFIED]
  WebKit:             UNAVAILABLE     [RUNTIME_UNAVAILABLE on Windows]
-----------------------------------------------------------------
Overall Health:       READY (v1.0.0)
=================================================================
```

### JSON Export Mode
```bash
python scripts/doctor.py --json
```

---

## Quick Start

Desktop WebView Reviewer automatically detects the underlying engine from project files, executable extensions, or process signatures.

### Example 1: QtWebEngine (PyQt6 / PySide6)
```text
"Launch the Qt desktop application and verify that clicking '#incrementButton' updates the counter."
```

```bash
# 1. Launch Qt app on remote debugging port 9222
python scripts/launch.py examples/test_app.py --port 9222

# 2. Discover active page target WebSocket URL
python scripts/discover.py --port 9222

# 3. Review, click, assert, and generate evidence
python scripts/review.py --click="#incrementButton" --assert-selector="#counter" --assert-text="1"

# 4. Clean process teardown
python scripts/stop.py
```

### Example 2: Electron Application
```text
"Launch the Electron app in development mode and run a frontend smoke test."
```

```bash
python scripts/launch.py "npx electron ./app" --engine electron --port 9234
python scripts/discover.py --port 9234
python scripts/review.py --type-selector="#search" --type-text="Antigravity" --screenshot="shot.png"
python scripts/stop.py
```

### Example 3: WebView2 / Tauri Application
```text
"Check the Tauri desktop app's login form and verify the submit flow."
```

```bash
# Framework routing automatically maps Tauri on Windows to WebView2
python scripts/launch.py "./src-tauri/target/debug/app.exe" --port 9222
python scripts/discover.py --port 9222 --title="Login"
python scripts/review.py --click="#submit-btn" --assert-selector="#status" --assert-text="Welcome"
python scripts/stop.py
```

---

## Real-World Example: Anki Maths

The reviewer was validated against the genuine, real-world application [Anki Maths](https://github.com/naksh-07/anki-maths):
- **Framework**: PyQt6
- **Engine**: QtWebEngine
- **Frontend**: Svelte 5 / Tailwind CSS
- **Runtime**: Genuine Windows desktop process (`python.exe run.py`)

### What the Reviewer Accomplished:
1. **Engine Detection**: Identified `PyQt6.QtWebEngineWidgets` from runtime AST imports.
2. **Target Disambiguation**: Filtered out auxiliary helper targets, selecting the primary Svelte UI window.
3. **DOM & JS Verification**: Evaluated runtime object structures (`typeof window === 'object'`).
4. **Screenshot & Integrity**: Captured rendered MathJax/Svelte interface with SHA-256 cryptographic verification.
5. **Ownership Safety**: Verified that external Anki Maths processes remain unharmed during Attach Mode.

---

## CLI Reference

| Command | Purpose | Key Arguments |
|---|---|---|
| `scripts/doctor.py` | Environment diagnostic check | `--json`, `--verbose` |
| `scripts/launch.py` | Spawns detached desktop process | `<executable>`, `[args]`, `--port`, `--engine`, `--cwd` |
| `scripts/discover.py` | Resolves target page WebSocket URL | `--port`, `--engine`, `--title`, `--url`, `--out-ws` |
| `scripts/attach.py` | Interactive raw CDP evaluation | `--eval="document.title"`, `--ws-url`, `--ws-file` |
| `scripts/review.py` | Automated interaction & assertions | `--click`, `--type-selector`, `--type-text`, `--assert-selector`, `--assert-text`, `--screenshot`, `--evidence` |
| `scripts/stop.py` | Safe process tree termination | `[pid]`, `--pid-file`, `--ownership-file` |

---

## Evidence & Forensic Schema

Every review execution creates a structured `evidence.json` conforming to the schema below:

```json
{
  "framework": "qt",
  "engine": "qtwebengine",
  "platform": "win32",
  "verification_level": "runtime_verified",
  "target": {
    "id": "A1B2C3D4...",
    "type": "page",
    "title": "Universal Desktop Webview",
    "url": "file:///path/to/counter.html",
    "engine": "qtwebengine"
  },
  "actions": [
    {
      "action_type": "click",
      "selector": "#incrementButton",
      "duration_ms": 42.5,
      "success": true,
      "before_state": { "textContent": "0" },
      "after_state": { "textContent": "1" }
    }
  ],
  "screenshot_path": "screenshot.png",
  "screenshot_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "state_assertions": [
    {
      "description": "Text of '#counter' should contain '1'",
      "passed": true,
      "expected": "1",
      "actual": "1"
    }
  ],
  "process_ownership": {
    "pid": 14220,
    "launched_by_reviewer": true,
    "port": 9222
  }
}
```

---

## Safety Model & Process Isolation

1. **Localhost Binding**: All debugging sockets strictly bind to `127.0.0.1`.
2. **PID Collision Immunity**: When terminating reviewer-spawned processes, `ProcessCleanup` compares the process `create_time` against the launch timestamp to prevent killing recycled PIDs.
3. **No Global Process Killing**: Blanket commands like `taskkill /IM ...` are strictly forbidden. Only the specific PID and its verified descendant tree are terminated.
4. **Attach Mode Preservation**: If the reviewer attaches to an existing running application, `desktop_ownership.json` marks `launched_by_reviewer = False`. When `stop.py` runs, the session is cleanly closed while the application remains alive.

---

## Limitations

1. **WebKit on Windows**: WebKitGTK and Apple WKWebView are not available on Windows. Windows desktop frameworks like Tauri and Wails compile against Microsoft Edge WebView2.
2. **Browser Domain Context**: Embedded webviews (QtWebEngine, WebView2, CEF) implement Chromium's content layer without full Chrome browser scaffolding. Commands in the `Browser.*` domain (e.g. `Browser.setDownloadBehavior`) are unsupported by engine design.

---

## Development & Testing

Run all 55+ regression and unit tests:

```bash
# 1. Run all unit & integration test suites
python -m unittest discover -s tests -p "test_*.py" -v

# 2. Run adversarial port conflict & timeout resilience suite
python tests/test_port_conflicts.py

# 3. Run individual live runtime E2E suites
python -m unittest tests/test_universal_core.py
python -m unittest tests/test_webview2_e2e.py
python -m unittest tests/test_electron_e2e.py
python -m unittest tests/test_anki_maths_real_app.py
```

---

## License

Desktop WebView Reviewer is released under the **Apache-2.0 License**.
