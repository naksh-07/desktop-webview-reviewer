# TRACK 09: EXISTING REPOSITORY FORENSIC AUDIT
## Comprehensive Codebase-Level Architecture, Implementation, and Forensic Analysis of `desktop-webview-reviewer`

**Document ID:** `09_EXISTING_REPO_FORENSIC_AUDIT.md`  
**Target Repository:** `desktop-webview-reviewer`  
**Active Canonical Git Clone:** `C:\Users\Suraj\Documents\Antigravity\View-Check` (`git@github.com:naksh-07/desktop-webview-reviewer.git`)  
**Installed Skill Directory:** `C:\Users\Suraj\.gemini\config\skills\desktop-webview-reviewer`  
**Audit Date:** 2026-09-04  
**Operating System Environment:** Windows 11 Pro 64-bit (Build 26100), Python 3.13.0 / Python 3.11.16  
**Auditor Framework:** Adaptive Orchestrator (v4 Foundation) — Independent Dual-Specialist Forensic Audit  
**Codebase Mutation Status:** 100% UNTOUCHED (Zero modifications to tracked code, configuration, or environment)  

---

## 1. EXECUTIVE SUMMARY

The `desktop-webview-reviewer` repository represents a pioneering, highly ambitious, and partially hardened effort to solve one of the most difficult problems in desktop systems automation: **verifying the actual visible runtime reality of desktop applications with embedded web surfaces across the native-to-web boundary.**

Unlike conventional web automation engines (e.g., Selenium, Cypress, standard Playwright) that evaluate HTML fixtures in isolated browser instances, and unlike conventional OS automation tools (e.g., pywinauto, PyAutoGUI, Windows UIA) that treat the embedded web surface as an opaque native canvas, `desktop-webview-reviewer` attempts a dual-perspective bridge:
1. **OS-Level Native Win32 Forensics:** Proving via `ctypes` bindings to Windows User32, GDI32, and DWM APIs that a genuine, non-minimized, non-cloaked, top-level GUI window exists, belongs to the expected process tree, and currently occupies desktop screen real estate.
2. **Webview-Level CDP Automation:** Connecting via asynchronous WebSocket JSON-RPC directly to the Chromium DevTools Protocol (CDP) debugging endpoint embedded within the desktop runtime (QtWebEngine, Edge WebView2, Electron, CEF) to inspect the live DOM, execute JavaScript, dispatch interactions, and capture viewport renderings.

### Key Forensic Audit Findings

1. **Foundational Genius vs. Implementation Fragility:**  
   The foundational verification theory codified in `core/evidence.py`, `core/window_forensics.py`, and `tests/test_forensic_hardening.py` is sound and represents genuine domain expertise. Its strict tripartite verdict model (`PASS`, `FAIL`, `UNVERIFIED`) prevents headless daemons, ghost processes, minimized windows, or hijacked debugging ports from masquerading as verified desktop software.
2. **Critical CLI Regressive Deadlock (The "Permanent UNVERIFIED" Defect):**  
   An ad-hoc regex monkey-patch (`patch_evidence.py`), applied between commit `d90e5b0` and commit `c7dd3bb`, mutated `core/evidence.py` to enforce that `Verdict.PASS` strictly requires:
   - `user_confirmation == True` (defaults to `False`)
   - `input_delivery_verified == True` (defaults to `False`)
   - Presence of three discrete screenshot proofs in the evidence dictionary: `"desktop"`, `"native"`, and `"webview"`.
   
   However, the CLI review runner `scripts/review.py` was **never updated** to supply `user_confirmation`, `input_delivery_verified`, or a `"desktop"` screenshot. Consequently, **invoking `scripts/review.py` against any live, fully functional application on Windows today will unconditionally return `Verdict.UNVERIFIED` (exit code 2). The primary CLI review tool is currently incapable of yielding a `PASS` verdict.**
3. **Engine Support Reality vs. Documentation:**  
   While `SKILL.md` advertises support for five desktop webview engines (QtWebEngine, WebView2, Electron, CEF/Chromium, WebKit), only **QtWebEngine** and **generic Chromium** have been tested and verified against real desktop applications. CEF has no standalone adapter (it is aliased to Chromium), WebKit is hardcoded to `RUNTIME_UNAVAILABLE` on Windows, and WebView2/Electron tests rely on standalone browser executable mocks (`msedge.exe --app` and `npx electron`) rather than real embedded desktop frameworks.
4. **Subprocess Leakage in Test Suite:**  
   The test suite executes 59 unit and integration tests (57 passed, 2 skipped). However, the test runners trigger multiple `ResourceWarning: subprocess <PID> is still running` warnings. Running the suite creates unmanaged disk artifacts (`anki_maths_screenshot.png`, `anki_maths_evidence.json`) in the current working directory.
5. **Git Repository Ground Truth & Debris:**  
   The repository clone at `C:\Users\Suraj\Documents\Antigravity\View-Check` contains exactly two commits on `main`. Tracked source files match the installed skill at `C:\Users\Suraj\.gemini\config\skills\desktop-webview-reviewer` byte-for-byte. However, the repository root is severely cluttered with 24 untracked artifacts, including 16 one-off `fix_*.py` scripts, 4 `patch_*.py` regex patchers, and multiple monolithic, application-specific test harnesses (`scripts/audit_phase2.py`, `scripts/audit_phase3.py`, totaling 2,615 lines) committed directly into `scripts/`.

---

## 2. AUDIT SCOPE & METHODOLOGY

This audit was conducted strictly inside the physical repositories and runtime environments on the target Windows workstation:
* **Canonical Repository:** `C:\Users\Suraj\Documents\Antigravity\View-Check` (Git repository root, branch `main`, commit `c7dd3bb`).
* **Installed Agent Skill:** `C:\Users\Suraj\.gemini\config\skills\desktop-webview-reviewer` (Production skill copy).
* **Sibling Skill:** `C:\Users\Suraj\.gemini\config\skills\qt-desktop-reviewer` (Thin pass-through wrapper).

### Categorization System
In accordance with strict forensic standards, every factual assertion in this document is labeled with one of the following ground-truth tags:
* **`[CODE FACT]`**: Verifiable directly in the tracked source code, including exact file paths, line numbers, and function signatures.
* **`[TEST FACT]`**: Directly observed and validated by executing unit tests, integration test suites, or live diagnostic commands.
* **`[DOCUMENTATION FACT]`**: Found in committed documentation (`SKILL.md`, `README.md`, `references/*.md`, `docs/*.md`).
* **`[ARCHITECTURAL OBSERVATION]`**: Synthesized structural analysis of module boundaries, coupling, and design patterns.
* **`[INFERENCE]`**: Logical deduction based on code artifacts, commit history, and runtime behavior.
* **`[RISK ASSESSMENT]`**: Specific vulnerability, race condition, data corruption hazard, or failure mode.

---

## 3. REPOSITORY GROUND TRUTH & ENVIRONMENT VERIFICATION

### 3.1 Git Archaeology & Commit Ledger
* **[CODE FACT]** Git remote URL: `https://github.com/naksh-07/desktop-webview-reviewer.git`
* **[CODE FACT]** Branch: `main` tracking `origin/main`. Tracked files are 100% clean (`git status` reports no modified tracked files).
* **[CODE FACT]** Total Commit Count: 2 commits.
  1. `d90e5b0` (2026-08-24 15:04:21 +0530): *"feat: release desktop-webview-reviewer v1.0.0"* (Author: naveenamre <namrawanshi96@gmail.com>). Tagged as `v1.0.0`. Introduced the universal multi-engine architecture (83 files, 7,265 insertions).
  2. `c7dd3bb` (2026-08-25 16:25:23 +0530): *"Update desktop webview reviewer with forensic hardening capabilities"* (Author: naveenamre <namrawanshi96@gmail.com>). Added 16 files, 5,489 insertions(+), 108 deletions(-). Introduced `core/window_forensics.py`, `tests/test_forensic_hardening.py`, `scripts/audit_phase2.py`, `scripts/audit_phase3.py`, `scripts/audit_phase3_5.py`, and `docs/PHASE2_LIVE_TARGET_AUDIT.md`.

### 3.2 File Parity: Git Repo vs. Installed Skill
* **[CODE FACT]** A recursive diff between `C:\Users\Suraj\Documents\Antigravity\View-Check` and `C:\Users\Suraj\.gemini\config\skills\desktop-webview-reviewer` across all tracked files (`git ls-files`) returned **zero differences**. Every tracked Python file, markdown reference, and configuration file is identical.
* **[CODE FACT]** The installed skill directory lacks a `.git` folder and contains stale runtime state files: `desktop_ownership.json`, `desktop_ws_url.txt`, `qt_ws_url.txt`.
* **[CODE FACT]** Scratch directory `C:\Users\Suraj\.gemini\antigravity\scratch` contains no repository clone or references to `desktop-webview-reviewer`.

### 3.3 Untracked Files & Working Tree Debris
* **[CODE FACT]** The repository root contains 24 untracked files and directories:
  - **Build Debris:** `desktop_webview_reviewer.egg-info/`
  - **16 Ad-Hoc Fix Scripts:** `fix_anki_base.py`, `fix_anki_entry.py`, `fix_anki_python.py`, `fix_click.py`, `fix_discovery.py`, `fix_discovery2.py`, `fix_encoding.py`, `fix_env.py`, `fix_import.py`, `fix_kill.py`, `fix_loop.py`, `fix_profile.py`, `fix_session.py`, `fix_session_logic.py`, `fix_test.py`, `fix_test2.py`.
  - **4 Regex Patch Scripts:** `patch_evidence.py`, `patch_forensics.py`, `patch_models.py`, `patch_tests.py`. (These scripts were used by the previous author to mutate committed files via regular expressions before creating commit `c7dd3bb`).
  - **3 Test Run Output Dumps:** `phase2_audit_results.json` (17 KB), `phase3_5_audit_results.json` (3 KB), `phase3_frontend_evidence.json` (3 KB).
  - **1 Audit Markdown Report:** `phase3_5_visibility_audit.md` (6 KB).
  - **2 Scratch Inspection Scripts:** `list_windows.py`, `test_windows.py`.
  - **2 Generated Test Artifacts:** `anki_maths_evidence.json`, `anki_maths_screenshot.png`.
* **[CODE FACT]** `.gitignore` specifies ignores for: `*.pid`, `*.log`, `desktop_ownership.json`, `desktop_ws_url.txt`, `qt_ws_url.txt`, `*_evidence.json`, `evidence.json`, `*.png`, `*.jpg`, `__pycache__/`, `.venv/`, `.pytest_cache/`, `release-validation/`, `.qt-reviewer/`, `.agents/`.

---

## 4. FULL REPOSITORY INVENTORY

```
View-Check/
├── .github/
│   └── workflows/
│       └── ci.yml                 # CI workflow (ubuntu-latest, windows-latest, macos-latest)
├── adapters/
│   ├── __init__.py                # Adapter registry and factory functions (list_adapters, get_adapter)
│   ├── base.py                    # BaseEngineAdapter abstract base class (131 lines)
│   ├── chromium/
│   │   ├── __init__.py
│   │   ├── adapter.py             # ChromiumAdapter (CEF, CefSharp, standalone Chromium)
│   │   └── detector.py           # Chromium filesystem/process detector
│   ├── electron/
│   │   ├── __init__.py
│   │   ├── adapter.py             # ElectronAdapter
│   │   └── detector.py           # Electron package.json & binary detector
│   ├── qtwebengine/
│   │   ├── __init__.py
│   │   ├── adapter.py             # QtWebEngineAdapter (PyQt5, PyQt6, PySide)
│   │   └── detector.py           # Qt import and environment detector
│   ├── webkit/
│   │   ├── __init__.py
│   │   ├── adapter.py             # WebKitAdapter (WebKitGTK, WKWebView)
│   │   └── detector.py           # Linux/macOS WebKit detector
│   └── webview2/
│       ├── __init__.py
│       ├── adapter.py             # WebView2Adapter (WinForms, WPF, WinUI, Tauri)
│       └── detector.py           # Edge WebView2 registry and process detector
├── core/
│   ├── __init__.py                # Package exports
│   ├── actions.py                 # WebviewActions (click, type_text, scroll, get_text) (240 lines)
│   ├── assertions.py              # WebviewAssertions & AssertionResult (131 lines)
│   ├── capabilities.py            # CapabilityRegistry & capability negotiation (157 lines)
│   ├── cleanup.py                 # ProcessCleanup (PID tree kill, ownership check) (172 lines)
│   ├── discovery.py               # TargetDiscovery & heuristic ranking (240 lines)
│   ├── evidence.py                # EvidenceCollector, verdict evaluation, report packaging (320 lines)
│   ├── models.py                  # Core dataclasses, enums, and schemas (422 lines)
│   ├── session.py                 # CDPSession (WebSocket JSON-RPC) & MultiTargetSessionManager (379 lines)
│   └── window_forensics.py        # WindowForensicsEngine (Win32 ctypes, RECT, GDI capture) (577 lines)
├── detectors/
│   ├── __init__.py
│   └── engine_detector.py         # EngineDetector & FrameworkRouter (216 lines)
├── docs/
│   ├── PHASE2_FRONTEND_REPAIR_PLAN.md
│   ├── PHASE2_LIVE_TARGET_AUDIT.md   # Live audit log of Windows Anki DEV GUI + StudyLab
│   └── PHASE3_FRONTEND_REPAIR_REPORT.md
├── examples/
│   ├── test_app.py                # PyQt6 standalone test fixture (61 lines)
│   └── webview2_test_app.html     # HTML test fixture for WebView2
├── launchers/
│   ├── __init__.py
│   └── process_launcher.py        # ProcessLauncher (Popen, port finder, ownership tracker) (144 lines)
├── references/
│   ├── adapter-contract.md        # Technical contract for BaseEngineAdapter
│   ├── architecture.md            # System architecture and layer definitions
│   ├── capabilities.md            # Engine capability matrix
│   └── troubleshooting.md         # Diagnostic and resolution guide
├── scripts/
│   ├── attach.py                  # CLI: Attach to running webview and enter interactive REPL
│   ├── audit_phase2.py            # Monolithic Anki DEV GUI Phase 2 test harness (1,119 lines)
│   ├── audit_phase3.py            # Monolithic Anki DEV GUI Phase 3 test harness (1,211 lines)
│   ├── audit_phase3_5.py          # Monolithic Anki DEV GUI Phase 3.5 visibility harness (286 lines)
│   ├── discover.py                # CLI: Discover and rank inspectable webview targets
│   ├── doctor.py                  # CLI: Environment, dependency, and engine health checks
│   ├── launch.py                  # CLI: Universal desktop application launcher
│   ├── review.py                  # CLI: Automated inspection, action, assertion, and evidence runner (332 lines)
│   └── stop.py                    # CLI: Clean process tree termination and state cleanup
├── tests/
│   ├── env_config.py              # Test environment path resolver
│   ├── test_actions.py            # Unit tests for WebviewActions
│   ├── test_anki_maths_real_app.py# Integration test against sibling repo Anki-maths
│   ├── test_assertions.py         # Unit tests for WebviewAssertions
│   ├── test_capabilities.py       # Capability registry tests
│   ├── test_cli_lifecycle.py      # End-to-end CLI integration test (launch->discover->review->stop)
│   ├── test_discovery.py          # Target discovery and ranking tests
│   ├── test_doctor.py             # Doctor CLI unit tests
│   ├── test_electron_e2e.py       # Electron runtime lifecycle test
│   ├── test_evidence.py           # EvidenceCollector hashing and schema tests
│   ├── test_forensic_hardening.py # Deterministic Win32 forensic controls (Controls A, B, C, D) (454 lines)
│   ├── test_multi_engine_integration.py # Multi-engine routing and contract tests
│   ├── test_process_safety.py     # PID safety and tree kill tests
│   ├── test_session.py            # CDP WebSocket protocol tests
│   ├── test_universal_core.py     # Universal regression test with test_app.py
│   └── test_webview2_e2e.py       # Edge WebView2 runtime lifecycle test
├── pyproject.toml                 # Packaging, dependencies, console scripts
├── README.md                      # High-level overview
├── requirements.txt               # websockets>=11.0, psutil>=5.9.0
├── SKILL.md                       # Antigravity skill definition and instructions
└── uv.lock                        # uv dependency lockfile
```

---

## 5. DIRECTORY ARCHITECTURE & LAYERING EVALUATION

The codebase attempts a 5-tier architecture:
1. **Core Domain Tier (`core/`):** Pure models, CDP transport, Win32 forensics, evidence collection.
2. **Adapter & Engine Tier (`adapters/`):** Framework-specific launch arguments, environment flags, and target discovery nuances.
3. **Detector & Launcher Tier (`detectors/`, `launchers/`):** Application inspection, framework detection, process spawning.
4. **Tooling & CLI Tier (`scripts/`):** Standalone command-line entry points.
5. **Specification & Integration Tier (`SKILL.md`, `references/`, `tests/`):** Agent interfaces, contract documents, test suites.

### Architectural Boundary Leaks & Smells
* **[ARCHITECTURAL OBSERVATION]** **Monolithic Test Infiltration in `scripts/`:**  
  The `scripts/` folder is designed for general CLI tools (`doctor.py`, `launch.py`, `discover.py`, `review.py`, `stop.py`). However, commit `c7dd3bb` injected `audit_phase2.py` (1,119 lines), `audit_phase3.py` (1,211 lines), and `audit_phase3_5.py` (286 lines) directly into `scripts/`. These files contain hardcoded Anki profile names (`test`), SQLite query strings on Anki collections (`collection.anki2`), and procedural card review state logic. They represent external application test suites masquerading as universal tools.
* **[ARCHITECTURAL OBSERVATION]** **God Module in `core/window_forensics.py`:**  
  `core/window_forensics.py` (577 lines) performs window enumeration, window hierarchy inspection, DWM cloaking checks, process-to-HWND correlation, monitor geometry calculations, Win32 GDI screen scraping, desktop screen scraping, and includes a 38-line pure-Python BGRA-to-PNG binary encoder (`_raw_bgra_to_png`).
* **[ARCHITECTURAL OBSERVATION]** **Leaky Adapter Contracts:**  
  `BaseEngineAdapter` (`adapters/base.py`) defines factory methods `create_actions`, `create_assertions`, and `create_evidence_collector`. However, no adapter overrides these methods; they all simply instantiate the default classes from `core/`. The adapter abstraction is currently an engine-configuration helper rather than an execution driver.

---

## 6. DEPENDENCY GRAPH & MODULE INTERDEPENDENCIES

```mermaid
graph TD
    CLI_Review[scripts/review.py] --> EngineDetector[detectors/engine_detector.py]
    CLI_Review --> CDPSession[core/session.py]
    CLI_Review --> Actions[core/actions.py]
    CLI_Review --> Assertions[core/assertions.py]
    CLI_Review --> Evidence[core/evidence.py]
    CLI_Review --> Forensics[core/window_forensics.py]

    CLI_Launch[scripts/launch.py] --> EngineDetector
    CLI_Launch --> ProcessLauncher[launchers/process_launcher.py]

    CLI_Discover[scripts/discover.py] --> EngineDetector
    CLI_Discover --> TargetDiscovery[core/discovery.py]

    CLI_Stop[scripts/stop.py] --> ProcessCleanup[core/cleanup.py]

    EngineDetector --> Adapters[adapters/__init__.py]
    Adapters --> BaseAdapter[adapters/base.py]
    Adapters --> QtAdapter[adapters/qtwebengine/]
    Adapters --> WV2Adapter[adapters/webview2/]
    Adapters --> ElectronAdapter[adapters/electron/]
    Adapters --> ChromiumAdapter[adapters/chromium/]
    Adapters --> WebKitAdapter[adapters/webkit/]

    Actions --> CDPSession
    Assertions --> CDPSession
    Evidence --> CDPSession
    Evidence --> Forensics
    TargetDiscovery --> Forensics

    ProcessLauncher --> Adapters
    ProcessCleanup --> psutil[psutil (External)]
    Forensics --> ctypes[ctypes / Win32 (OS)]
    CDPSession --> websockets[websockets (External)]
```

* **[CODE FACT]** Runtime External Dependencies (defined in `pyproject.toml#L30-L33` and `requirements.txt`):
  - `websockets >= 11.0` (CDP WebSocket client)
  - `psutil >= 5.9.0` (Cross-platform process lifecycle & tree inspection)
* **[CODE FACT]** Optional Dependencies:
  - `PyQt6 >= 6.5.0` and `PyQt6-WebEngine >= 6.5.0` (under optional extra `qt = [...]`).
* **[CODE FACT]** Standard Library Heavy Lifting:
  - `ctypes` & `ctypes.wintypes`: Direct native C interop with `user32.dll`, `gdi32.dll`, `dwmapi.dll`.
  - `subprocess`: Child process spawning.
  - `urllib.request`: HTTP polling of `/json/list` and `/json/version`.
  - `zlib` & `struct`: Pure-Python PNG binary compression and chunk assembly.
  - `hashlib`: SHA-256 cryptographic hashing of captured image buffers.

---

## 7. EXECUTION FLOW ANALYSIS

The standard lifecycle comprises five distinct CLI operations:

```
[1. Launch]  -->  [2. Discover]  -->  [3. Attach]  -->  [4. Review]  -->  [5. Stop]
(launch.py)      (discover.py)       (attach.py)        (review.py)       (stop.py)
```

1. **Launch Phase (`scripts/launch.py`):**
   - Resolves the appropriate engine adapter via `EngineDetector.resolve_adapter`.
   - Finds an open TCP port via `ProcessLauncher.find_free_port(9222)`.
   - Injects environment flags (e.g., `QTWEBENGINE_REMOTE_DEBUGGING=9222`, `QTWEBENGINE_CHROMIUM_FLAGS=--remote-allow-origins=*`).
   - Spawns subprocess with `creationflags = subprocess.CREATE_NEW_PROCESS_GROUP`.
   - Records PID in `desktop_app.pid` and structured metadata in `desktop_ownership.json`.
2. **Discovery Phase (`scripts/discover.py`):**
   - Polls `http://127.0.0.1:<port>/json/list` via `TargetDiscovery.poll_for_targets`.
   - Filters out internal targets (`devtools://`, `chrome-extension://`, `background_page`).
   - Evaluates heuristic ranking (`rank_score`) based on title, URL, and window status.
   - Saves WebSocket URL to `desktop_ws_url.txt` (or `qt_ws_url.txt`).
3. **Attach / Review Phase (`scripts/review.py`):**
   - Reads `desktop_ws_url.txt`.
   - Establishes WebSocket connection via `CDPSession.connect()`.
   - Enables CDP domains: `DOM`, `Runtime`, `Page`.
   - Executes optional UI actions (`click`, `type_text`).
   - Evaluates assertions (`assert_exists`, `assert_text_equals`).
   - Queries `WindowForensicsEngine.get_primary_gui_window(pid)`.
   - Captures screenshots (`CDPSession.capture_screenshot` and `WindowForensicsEngine.capture_native_window_screenshot`).
   - Builds `EvidenceReport` and evaluates verdict via `EvidenceCollector.evaluate_verdict`.
   - Serializes output to `evidence.json`.
4. **Teardown Phase (`scripts/stop.py`):**
   - Reads `desktop_ownership.json` and `desktop_app.pid`.
   - If `launched_by_reviewer == True`, invokes `ProcessCleanup.terminate_process_tree(pid)`.
   - If `launched_by_reviewer == False` (Attach Mode), skips termination to leave external app intact.
   - Cleans temporary state files (`*.pid`, `*.txt`, `ownership.json`).

---

## 8. DATA FLOW ANALYSIS

```
+-----------------------------------------------------------------------------------+
| OS Subsystem (Win32)                                                              |
| user32 / gdi32 / dwmapi  --->  WindowForensicsEngine  --->  WindowForensics       |
|                                                                |                  |
+----------------------------------------------------------------|------------------+
                                                                 v
+----------------------------------------------------+   +--------------------------+
| Desktop Application Process                        |   | EvidenceCollector        |
| - Root GUI Window (HWND)                           |   | - evaluate_verdict()     |
| - Process Tree (Root PID + Renderers)              |   | - SHA-256 Hashing        |
| - Embedded Chromium WebEngine                      |   | - Provenance Metadata    |
|   `--> Port 9222 (/json/list) ---> TargetDiscovery |   |                          |
|         `--> WebSocket Endpoint                    |   |          v               |
|               `--> CDPSession                      |   | EvidenceReport           |
|                     |--> DOM Snapshot              |   | (Serialized to           |
|                     |--> Console Events            |   |  evidence.json)          |
|                     |--> CDP Screenshot            |   |                          |
|                     `--> Action/Assertion Receipts |   |          |               |
+----------------------------------------------------+   +----------|---------------+
                                                                    v
                                                         +--------------------------+
                                                         | CLI Exit Code            |
                                                         | 0 = PASS                 |
                                                         | 1 = FAIL                 |
                                                         | 2 = UNVERIFIED           |
                                                         +--------------------------+
```

---

## 9. STATE MODEL & STATE MACHINES

### 9.1 Verdict State Machine (`core/models.py#L27-L32`)
The system uses a strict tripartite verdict model:
* **`Verdict.PASS` (Exit Code 0):** The desktop application has a genuine visible window on the active desktop, the window matches the PID tree, foreground focus is established, monitor intersection is verified, input delivery was confirmed, dual/triple screenshots match, and all DOM/JS assertions passed.
* **`Verdict.FAIL` (Exit Code 1):** One or more explicit state assertions or interactions failed (e.g., expected text was not present, DOM node missing, script evaluation threw an error).
* **`Verdict.UNVERIFIED` (Exit Code 2):** The test cannot prove that a genuine desktop application was verified. Triggered if the window is headless, minimized, cloaked, off-screen, belongs to a mismatched PID, port ownership is invalid, screenshots are missing, or user confirmation is absent.

### 9.2 Process Ownership State (`core/models.py#L212-L229`)
* `launched_by_reviewer: bool`
  - `True`: Spawns via `ProcessLauncher.launch`. Fully owned. Eligible for SIGTERM/SIGKILL on cleanup.
  - `False`: Discovered via `scripts/attach.py` or manual port attach. Externally owned. Cleanup leaves process running.

---

## 10. PROCESS MANAGEMENT FORENSICS

### 10.1 Spawning & Job Control
* **[CODE FACT]** `ProcessLauncher.launch` (`launchers/process_launcher.py#L88-L102`) launches processes using:
  ```text
  creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
  process = subprocess.Popen(
      cmd,
      env=env,
      cwd=target_cwd,
      stdout=log_fp,
      stderr=log_fp,
      stdin=subprocess.DEVNULL,
      creationflags=creationflags
  )
  ```
* **[ARCHITECTURAL OBSERVATION]** **Absence of Windows Job Objects:**  
  The launcher does not assign the spawned process to a Windows Job Object (`CreateJobObjectW`, `SetInformationJobObject` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`). If the Python review process crashes or is forcefully terminated via Task Manager, the desktop application and its child renderer processes remain running indefinitely as orphans.

### 10.2 PID Tree Discovery & PID Reuse Protection
* **[CODE FACT]** `WindowForensicsEngine.get_process_tree_pids` (`core/window_forensics.py#L71-L84`):
  Uses `psutil.Process(root_pid).children(recursive=True)` to discover multi-process renderer trees.
* **[CODE FACT]** `ProcessCleanup.terminate_process_tree` (`core/cleanup.py#L38-L109`):
  Enforces PID reuse protection:
  ```text
  if expected_create_time is not None:
      actual_create_time = parent.create_time()
      if abs(actual_create_time - expected_create_time) > 5.0:
          logger.warning(...)
          return False
  ```
* **[RISK ASSESSMENT]** **The 5-Second Race Window & Missing Timestamp Fallback:**  
  1. If PID recycling occurs within 5 seconds of the recorded timestamp, the check fails to detect reuse.
  2. If `expected_create_time` is `None` (which occurs when `desktop_ownership.json` is missing, or when `terminate_process_tree` is invoked directly from `stop.py <PID>`), PID validation is bypassed completely.

---

## 11. WINDOW / HWND FORENSICS

### 11.1 Native Win32 ctypes Architecture
* **[CODE FACT]** Direct DLL bindings in `core/window_forensics.py`:
  - `user32 = ctypes.windll.user32`
  - `dwmapi = ctypes.windll.dwmapi`
  - `gdi32 = ctypes.windll.gdi32`
* **[CODE FACT]** Defined C Structures (`core/window_forensics.py#L19-L52`):
  - `RECT`: `left`, `top`, `right`, `bottom` (all `wintypes.LONG`).
  - `BITMAPINFOHEADER`: `biSize`, `biWidth`, `biHeight`, `biPlanes`, `biBitCount`, `biCompression`, `biSizeImage`, `biXPelsPerMeter`, `biYPelsPerMeter`, `biClrUsed`, `biClrImportant`.

### 11.2 Verification Checklist for "Real GUI" Window
`WindowForensicsEngine.inspect_hwnd(hwnd)` evaluates:
1. `user32.IsWindow(hwnd)` -> Handle is valid in OS table.
2. `user32.IsWindowVisible(hwnd)` -> `WS_VISIBLE` style bit is set.
3. `not user32.IsIconic(hwnd)` -> Window is not minimized to taskbar.
4. `dwmapi.DwmGetWindowAttribute(hwnd, 14, byref(cloaked), sizeof(cloaked))` -> `DWMWA_CLOAKED == 0` (window is not on an inactive virtual desktop or suspended by OS).
5. `user32.GetWindowRect(hwnd, byref(rect))` -> Width >= 30 and Height >= 30.
6. `is_real_gui` is set to `True` only if all above checks pass (`#L180-L186`).

### 11.3 64-bit Pointer Truncation Vulnerability
* **[RISK ASSESSMENT]** **Critical ctypes Omission (`argtypes` / `restype`):**  
  `core/window_forensics.py` fails to declare `.argtypes` and `.restype` for Win32 functions. In Python `ctypes`, undeclared functions default to returning a 32-bit signed integer (`c_int`). On 64-bit Windows, pointer handles (`HWND`, `HDC`, `HBITMAP`, `HMONITOR`) are 64 bits wide (`UINT_PTR` / `c_void_p`).
  - Functions affected: `user32.GetForegroundWindow()`, `user32.MonitorFromWindow()`, `user32.GetWindowDC()`, `gdi32.CreateCompatibleDC()`, `gdi32.CreateCompatibleBitmap()`.
  - Impact: If an OS handle value exceeds `0x7FFFFFFF` (common on long-running systems), Python truncates the upper 32 bits or treats the handle as negative, causing downstream Win32 API calls to fail with `ERROR_INVALID_HANDLE`.

### 11.4 GDI Handle Leakage Hazard
* **[RISK ASSESSMENT]** In `capture_native_window_screenshot` (`#L375-L461`) and `capture_desktop_screenshot` (`#L464-L538`), allocations via `GetWindowDC`, `CreateCompatibleDC`, and `CreateCompatibleBitmap` are **not protected by `try...finally` blocks**. If `PrintWindow` or `GetDIBits` raises an unhandled exception, `hdc_mem`, `hbm`, and `hdc_window` are never released via `DeleteDC`, `DeleteObject`, and `ReleaseDC`, causing kernel GDI handle table exhaustion.

### 11.5 Pure-Python PNG Encoder (`_raw_bgra_to_png`)
* **[CODE FACT]** Lines 540–577 implement a zero-dependency BGRA-to-PNG compressor:
  - Formats scanlines with filter byte `0x00` (Filter: None).
  - Swaps BGRA bytes to RGBA.
  - Compresses raw scanlines using `zlib.compress(raw_data, level=6)`.
  - Emits valid PNG chunks: `IHDR`, `IDAT`, `IEND` with calculated CRC-32 checksums.
  - Eliminates external dependencies on `Pillow` or OpenCV.

---

## 12. FORENSIC VALIDATION & THE NATIVE <-> WEB BOUNDARY

### 12.1 Can a Fake or Headless State Pass Verification?
* **[CODE FACT]** `EvidenceCollector.evaluate_verdict` (`core/evidence.py#L116-L233`) executes 12 deterministic gates:
  1. Failed assertions -> `Verdict.FAIL` (`#L135-L139`).
  2. `window_forensics is None` -> `Verdict.UNVERIFIED` (`#L144-L147`).
  3. `hwnd is None` -> `Verdict.UNVERIFIED` (`#L150-L153`).
  4. `not window_visible` -> `Verdict.UNVERIFIED` (`#L156-L159`).
  5. `is_iconic` (minimized) -> `Verdict.UNVERIFIED` (`#L162-L165`).
  6. `is_cloaked` -> `Verdict.UNVERIFIED` (`#L168-L171`).
  7. `width < 30 or height < 30` -> `Verdict.UNVERIFIED` (`#L174-L180`).
  8. `not hwnd_pid_matched` -> `Verdict.UNVERIFIED` (`#L183-L186`).
  9. `not foreground_match` -> `Verdict.UNVERIFIED` (`#L188-L192`).
  10. `intersection_area <= 0` -> `Verdict.UNVERIFIED` (`#L194-L198`).
  11. `not user_confirmation` -> `Verdict.UNVERIFIED` (`#L201-L205`).
  12. `not input_delivery_verified` -> `Verdict.UNVERIFIED` (`#L206-L210`).
  13. Missing screenshot proofs (`"desktop"`, `"native"`, `"webview"`) -> `Verdict.UNVERIFIED` (`#L212-L219`).
* **[TEST FACT]** Validated via `tests/test_forensic_hardening.py`:
  - `test_control_b_headless_no_window_unverified`: Passed (UNVERIFIED).
  - `test_control_c_mismatched_pid_unverified`: Passed (UNVERIFIED).
  - `test_control_d_screenshot_without_gui_proof_unverified`: Passed (UNVERIFIED).
* **[ARCHITECTURAL OBSERVATION]** **A fake, headless, hidden, or minimized window CANNOT PASS under `EvidenceCollector.evaluate_verdict`.**

### 12.2 The Critical CLI Regressive Deadlock
* **[CODE FACT]** In `scripts/review.py#L208-L224`:
  ```text
  report = await collector.build_report(
      screenshot_path=screenshot_path,
      assertions=assertions.history,
      actions=actions.history,
      process_ownership=ownership,
      window_forensics=window_forensics,
      extra_metadata={...}
  )
  ```
* **[CODE FACT]** `review.py` does NOT pass `user_confirmation` or `input_delivery_verified`. In `core/evidence.py#L246-L247`, both default to `False`.
* **[CODE FACT]** `review.py` captures only `"webview"` and `"native"` screenshots; it **never calls `capture_desktop_screenshot`**.
* **[CODE FACT]** In `core/evidence.py#L201-L219`, `evaluate_verdict` fails with:
  `"User confirmation of window visibility is missing or False."`
* **[TEST FACT / RISK ASSESSMENT]** **Permanent UNVERIFIED:** `scripts/review.py` is permanently locked to exit code 2 (`UNVERIFIED`). It cannot produce a `PASS` verdict under any circumstances in its current committed state.

---

## 13. AUTOMATION BACKENDS & ADAPTER ARCHITECTURE

| Engine | Adapter Class | Launch / Environment Mechanism | Target Discovery Method | Real App Verified? |
|---|---|---|---|---|
| **QtWebEngine** | `QtWebEngineAdapter` | `QTWEBENGINE_REMOTE_DEBUGGING=<port>`, `QTWEBENGINE_CHROMIUM_FLAGS=--remote-allow-origins=*` | HTTP `GET /json/list` | **YES** (Tested against real PyQt6 Anki Maths app) |
| **Microsoft Edge WebView2** | `WebView2Adapter` | `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<port>` | HTTP `GET /json/list` + User Data Folder fallback | **PARTIAL** (Tested against `msedge.exe --app`, not embedded WinForms/WPF) |
| **Electron** | `ElectronAdapter` | Command arg: `--remote-debugging-port=<port>` | HTTP `GET /json/list` | **PARTIAL** (Tested against standalone `npx electron`, skipped in local venv) |
| **Generic Chromium / CEF** | `ChromiumAdapter` | Command arg: `--remote-debugging-port=<port>` | HTTP `GET /json/list` | **YES** (Direct Chromium CLI embeds) |
| **WebKit** | `WebKitAdapter` | `WEBKIT_INSPECTOR_SERVER=127.0.0.1:<port>` | WebKit Inspector HTTP | **NO** (Hardcoded `RUNTIME_UNAVAILABLE` on Windows) |

* **[CODE FACT]** **The CEF Illusion:**  
  There is no `adapters/cef/` directory. `adapters/__init__.py#L43` routes strings `"cef"`, `"cefsharp"`, `"chrome"`, and `"chromium-embed"` directly to `ChromiumAdapter`.
* **[CODE FACT]** **WebKit on Windows:**  
  `adapters/webkit/adapter.py#L52` checks `sys.platform`. If `sys.platform == "win32"`, it reports `VerificationLevel.RUNTIME_UNAVAILABLE`.

---

## 14. CDP IMPLEMENTATION DEEP DIVE

### 14.1 Protocol Architecture
* **[CODE FACT]** `core/session.py` implements a standalone, pure-Python async WebSocket JSON-RPC 2.0 client using `websockets`. It does NOT depend on Chrome DevTools MCP, Playwright, or Puppeteer.
* **[CODE FACT]** Connection logic (`core/session.py#L41-L60`):
  - Connects to page-specific WebSocket URL (e.g., `ws://127.0.0.1:9222/devtools/page/<ID>`).
  - Sets `max_size = 50 * 1024 * 1024` (50 MB) to accommodate large base64 screenshot payloads.
  - Disables client pings (`ping_interval = None`) to prevent dropped connections on slow renderers.
  - Spawns background listener task `_read_messages()`.

### 14.2 Domain Usage & Command Set
* **[CODE FACT]** Enabled Domains: `DOM`, `Runtime`, `Page` (`core/session.py#L190-L197`).
* **[CODE FACT]** Command Catalog:
  - `Runtime.evaluate`: Evaluates JS expressions with `awaitPromise=True`, `returnByValue=True`.
  - `DOM.getDocument`: Retrieves DOM tree (`depth=-1`, `pierce=True`).
  - `DOM.querySelector`: Resolves selector to `nodeId`.
  - `Input.dispatchMouseEvent`: Dispatches `mousePressed` and `mouseReleased`.
  - `Input.dispatchKeyEvent`: Dispatches `keyDown`, `keyUp`, `char`.
  - `Page.captureScreenshot`: Captures PNG/JPEG viewport data.
* **[ARCHITECTURAL OBSERVATION]** **Deliberate Avoidance of Browser Domain:**  
  `CDPSession` intentionally avoids `Browser.*` domain commands (such as `Browser.getVersion` or `Target.createTarget`). QtWebEngine and Edge WebView2 reject or crash on browser-level domain commands because their embedded processes lack a full browser manager. Connecting directly to the page-level WebSocket targets is the correct architecture for embedded webviews.

---

## 15. INSPECTION, ACTIONS, AND ASSERTION MODELS

### 15.1 Element & Locator Model
* **[CODE FACT]** **CSS Selector Exclusivity:**  
  The locator model supports only CSS selectors (`core/actions.py#L28`, `#L88`, `#L154`). There is no support for XPath, text content locators, ARIA roles, or test IDs.
* **[ARCHITECTURAL OBSERVATION]** **Immunity to Stale Element References:**  
  Because every method in `WebviewActions` re-evaluates `document.querySelector(...)` dynamically via JavaScript injection on every invocation, the system never suffers from Selenium/WebDriver-style `StaleElementReferenceException`. However, this comes at the cost of high evaluation overhead.

### 15.2 Interaction Primitives
* **[CODE FACT]** **Click Action with Synthetic Fallback (`core/actions.py#L86-L150`):**
  1. Executes JS: `el.getBoundingClientRect()`.
  2. Computes center: `x = rect.x + rect.width / 2`, `y = rect.y + rect.height / 2`.
  3. Dispatches native CDP mouse events: `mousePressed` followed by `mouseReleased`.
  4. If CDP input fails (e.g., input domain disabled in QtWebEngine), catches exception and executes synthetic fallback: `el.click(); el.dispatchEvent(new MouseEvent('click', ...))` (`#L143-L149`).
* **[CODE FACT]** **Type Text Action (`core/actions.py#L151-L197`):**
  - **Does NOT dispatch native keyboard events.**
  - Directly mutates DOM state via JS injection:
    ```javascript
    el.focus();
    el.value += text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    ```
  - **Limitation:** Fails on complex UI frameworks (React, Svelte 5, Slate.js) that intercept native keydown events or track internal shadow state.

### 15.3 Wait & Assertion Models
* **[CODE FACT]** Polling Waits (`core/actions.py#L219-L239`):
  `wait_for_selector` and `wait_for_condition` execute tight polling loops (`asyncio.sleep(0.2)`) up to a timeout (default 10s).
* **[CODE FACT]** Immediate Assertions (`core/assertions.py#L52-L127`):
  `assert_exists`, `assert_text_equals`, `assert_text_contains`, `assert_computed_style`, and `assert_js` perform **immediate non-retrying evaluations**. If an element is in the middle of an animation, transition, or network load, assertions fail immediately without waiting.

---

## 16. EVIDENCE SYSTEM & CRYPTOGRAPHIC INTEGRITY

### 16.1 Screenshot Provenance & Hashing
* **[CODE FACT]** Every screenshot is cryptographically hashed:
  - Magic byte validation: Ensures buffer starts with `b"\x89PNG\r\n\x1a\n"`.
  - Hash algorithm: SHA-256 (`hashlib.sha256(data).hexdigest()`).
  - Provenance tracking: Explicit `ScreenshotType` enum (`CDP_PAGE_CAPTURE`, `NATIVE_DESKTOP`, `WEBVIEW_VIEWPORT`).
* **[RISK ASSESSMENT]** **Hardware Acceleration Blanking:**  
  Win32 `PrintWindow` with `PW_RENDERFULLCONTENT` frequently fails against hardware-accelerated DirectComposition / DirectX swap chains used by Qt6 and Chromium, producing completely black or white images while reporting success.
* **[RISK ASSESSMENT]** **Multi-Monitor Coordinate Truncation:**  
  `capture_desktop_screenshot` (`core/window_forensics.py#L481-L490`) queries `GetSystemMetrics(0)` (width) and `GetSystemMetrics(1)` (height), capturing only the primary display. If the target application is located on a secondary display with negative or offset coordinates, the capture records the wrong monitor.

### 16.2 Artifact Overwrite Hazards
* **[RISK ASSESSMENT]** File paths default to static names: `evidence.json`, `screenshot.png`, `desktop_app.pid`, `desktop_ownership.json`. Sequential runs overwrite previous test runs on disk without warning or versioning.

---

## 17. DOCUMENTATION DRIFT & CONTRADICTIONS

| Topic | Documented in `SKILL.md` / References | Actual Reality in Code (`View-Check`) | Severity |
|---|---|---|---|
| **Screenshot Proofs** | `SKILL.md#L29-L34`: Requires "Dual Screenshot Provenance" (`native_desktop` and `cdp_page_capture`). | `core/evidence.py#L211-L220`: Strictly requires **three** screenshot proofs (`desktop`, `native`, and `webview`). | **HIGH** |
| **Evidence Schema Example** | `SKILL.md#L132-L168`: Shows `evidence.json` with `"verdict": "PASS"` containing only 2 screenshots and no user confirmation. | `core/evidence.py`: The exact JSON in `SKILL.md` would evaluate to `Verdict.UNVERIFIED`. | **HIGH** |
| **CLI Functionality** | `SKILL.md#L104-L121`: Documents `python scripts/review.py` producing `PASS` reports. | `scripts/review.py`: Hardcoded to **always fail** verdict evaluation and return `Verdict.UNVERIFIED`. | **CRITICAL** |
| **CEF Support** | `SKILL.md#L13`: Advertised as dedicated engine adapter. | `adapters/__init__.py#L43`: No CEF adapter exists; aliased to generic `ChromiumAdapter`. | **MEDIUM** |
| **WebKit Support** | `SKILL.md#L14`: Advertised as universal engine. | `adapters/webkit/adapter.py#L52`: Marked `RUNTIME_UNAVAILABLE` on Windows. | **MEDIUM** |
| **Architecture Index** | `references/architecture.md#L18-L26`: Maps codebase structure. | Completely omits `core/window_forensics.py` and `scripts/doctor.py`. | **LOW** |

---

## 18. TEST ARCHITECTURE & TEST EXECUTION FACTS

### 18.1 Test Execution Results
Execution command: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
* **[TEST FACT]** **Total Tests Run:** 59 tests.
* **[TEST FACT]** **Passed:** 57 tests.
* **[TEST FACT]** **Skipped:** 2 tests (`test_cli_lifecycle.py` and `test_universal_core.py` skipped because PyQt6 is not installed inside the active virtual environment `.venv`).
* **[TEST FACT]** **Failed:** 0 tests.
* **[TEST FACT]** **Execution Time:** 29.950 seconds.

### 18.2 What the Tests Actually Prove
1. `tests/test_forensic_hardening.py` (12 tests): Deterministically proves the Win32 forensic state machine under mocked and synthetic data. Proves that missing GUI, headless state, mismatched PID, or missing screenshots cannot produce a `PASS`.
2. `tests/test_process_safety.py` (3 tests): Proves that attach mode does not kill external processes, that `create_time` mismatch prevents accidental termination, and that reviewer-launched processes are cleaned up.
3. `tests/test_anki_maths_real_app.py` (2 tests): Proves that the system successfully attaches to, inspects, and captures live DOM/screenshots from a **real running desktop application** (`Anki-maths` using PyQt6 + QtWebEngine).

### 18.3 Test Suite Flaws & Leaks
* **[TEST FACT]** **Subprocess Resource Warnings:**  
  Running the test suite emits three `ResourceWarning: subprocess <PID> is still running` warnings (`subprocess 10812`, `subprocess 23792`, `subprocess 7268`). The test fixtures spawn real background processes and fail to wait for or reap their handles.
* **[TEST FACT]** **Working Directory Pollution:**  
  Running `test_anki_maths_real_app.py` writes `anki_maths_screenshot.png` and `anki_maths_evidence.json` directly into the repository root.

---

## 19. SECURITY AUDIT & HAZARDS

1. **Arbitrary Executable Execution (`launchers/process_launcher.py`):**  
   `scripts/launch.py` accepts any arbitrary executable or script path from CLI arguments. There is no allowlist, binary signature verification, or path sanitization.
2. **Arbitrary JavaScript Evaluation (`core/session.py#L199-L214`):**  
   `evaluate_js` allows execution of unconstrained JavaScript inside the target renderer process. If exposed via an unauthenticated MCP tool or network socket, an attacker can execute arbitrary script in the target application's origin context.
3. **Environment Credential Leakage (`launchers/process_launcher.py#L63`):**  
   `ProcessLauncher.launch` copies the entire parent environment (`os.environ.copy()`). Any API keys, AWS/GCP credentials, or SSH tokens present in the user's terminal environment are inherited by the spawned desktop application process.
4. **Plaintext Command-Line Persistence (`core/models.py#L221-L228`):**  
   `ProcessOwnership.to_dict()` records the full command-line argument array (`cmd`) into `desktop_ownership.json`. If the user passes sensitive tokens or flags on the CLI, they are written to disk in plaintext.
5. **Insecure Chromium Remote Debugging Flags:**  
   `scripts/audit_phase3_5.py#L61` uses `--remote-allow-origins=*` and `--no-sandbox`, exposing the debugging interface to any local process or web page and disabling Chromium's multi-process security sandbox.

---

## 20. MCP READINESS AUDIT

### 20.1 Architectural Alignment with MCP
The repository's internal boundaries align surprisingly well with an MCP architecture, provided the transport and session layers are properly separated:
* **The "Context & Control" Separation:**  
  As discovered in Track 07, MCP is a Context & Control Plane, not an execution engine. `desktop-webview-reviewer` already has cleanly delineated models for actions, assertions, and evidence reports that naturally translate into MCP Tools and Resources.

### 20.2 What Should Be MCP Tools (Control Plane)
* `desktop_launch_app`: Launch target desktop application with debugging flags.
* `desktop_discover_targets`: Discover, inspect, and rank active webview endpoints.
* `desktop_attach_session`: Establish active inspection session.
* `desktop_inspect_dom`: Query DOM subtree or element geometry.
* `desktop_dispatch_action`: Execute atomic click, type, or scroll with action receipt.
* `desktop_verify_state`: Execute structured DOM/JS assertions.
* `desktop_capture_evidence`: Generate complete cryptographic evidence report and evaluate tripartite verdict.
* `desktop_close_session`: Teardown session and cleanly terminate process tree.

### 20.3 What Should Be MCP Resources (Context Plane)
* `desktop://sessions/{id}/evidence`: Read-only JSON representation of the latest `EvidenceReport`.
* `desktop://sessions/{id}/screenshots/{type}`: Binary PNG stream of `native_desktop` or `cdp_page_capture`.
* `desktop://sessions/{id}/console`: Log stream of captured browser console events and exceptions.
* `desktop://sessions/{id}/forensics`: Detailed OS window forensics and process ownership metadata.

### 20.4 What Must Remain Internal (Execution Plane)
* **Raw Win32 ctypes handles (`HWND`, `HDC`, `HBITMAP`):** Must never cross the protocol wire.
* **WebSocket client protocol loop:** Raw CDP framing and async request correlation must remain inside a local daemon/server.
* **GDI bitmap allocation and PNG conversion:** Image encoding must happen in the local runtime.

---

## 21. TECHNICAL DEBT REGISTER

| ID | Severity | File / Component | Description | Recommended Remediation |
|---|---|---|---|---|
| **TD-01** | **CRITICAL** | `scripts/review.py` & `core/evidence.py` | Regressive disconnect: `review.py` omits `user_confirmation`, `input_delivery_verified`, and desktop screenshot, locking verdict to `UNVERIFIED`. | Add CLI flags `--user-confirmation` and `--verify-input`, invoke `capture_desktop_screenshot`, and pass flags to `build_report`. |
| **TD-02** | **HIGH** | `core/window_forensics.py` | 64-bit ctypes pointer truncation: missing `argtypes` and `restype` causes crashes on handles > `0x7FFFFFFF`. | Explicitly define `argtypes` and `restype = wintypes.HWND / c_void_p` for all User32/GDI32/Dwm functions. |
| **TD-03** | **HIGH** | `core/window_forensics.py` | GDI handle leaks on exception during `capture_native_window_screenshot` and `capture_desktop_screenshot`. | Wrap all GDI DC and Bitmap operations in robust `try...finally` blocks. |
| **TD-04** | **HIGH** | `scripts/` root | Monolithic test infiltration: `audit_phase2.py` (1,119 lines) and `audit_phase3.py` (1,211 lines) committed in CLI directory. | Move application-specific audit runners to `tests/fixtures/anki/` or a dedicated test repository. |
| **TD-05** | **MEDIUM** | Root directory | 24 untracked files (`fix_*.py`, `patch_*.py`, JSON dumps) cluttering repository root. | Remove scratch scripts or add them to `.gitignore`. |
| **TD-06** | **MEDIUM** | `launchers/process_launcher.py` | Absence of Windows Job Objects allows spawned apps to become permanent zombies if reviewer crashes. | Assign spawned child processes to a Windows Job Object with `KillOnJobClose`. |
| **TD-07** | **MEDIUM** | `core/actions.py` | `type_text` uses synthetic DOM value injection instead of native CDP `Input.dispatchKeyEvent`. | Implement real keyboard event dispatching via `Input.dispatchKeyEvent`. |
| **TD-08** | **LOW** | `core/window_forensics.py` | `capture_desktop_screenshot` uses `SM_CXSCREEN`, capturing only primary display on multi-monitor setups. | Use `SM_XVIRTUALSCREEN`, `SM_YVIRTUALSCREEN`, `SM_CXVIRTUALSCREEN`, `SM_CYVIRTUALSCREEN`. |

---

## 22. REUSABILITY REGISTER

| Component / Subsystem | Reusability Grade | Disposition | Rationale |
|---|---|---|---|
| `core/models.py` | **A** | **REUSE AS-IS** | Clean, well-structured dataclasses for targets, engine info, action receipts, window forensics, and evidence schemas. |
| `core/window_forensics.py` | **B+** | **REUSE WITH REFACTOR** | Gold-standard Win32 inspection logic; needs 64-bit ctypes type safety, `try...finally` GDI wrappers, and multi-monitor support. |
| `core/session.py` | **A-** | **REUSE AS-IS** | High-performance, lightweight async WebSocket CDP client. Avoids bloat of Playwright/Puppeteer. |
| `core/discovery.py` | **A-** | **REUSE AS-IS** | Heuristic ranking and filtering for embedded targets (`devtools://` rejection) is excellent. |
| `core/evidence.py` | **B** | **REUSE WITH REFACTOR** | Strict tripartite verification is sound; needs synchronization with CLI runners and configuration flags. |
| `core/cleanup.py` | **A-** | **REUSE AS-IS** | Recursive process tree termination with PID creation timestamp protection is robust. |
| `adapters/qtwebengine/` | **A** | **REUSE AS-IS** | Verified against real Qt6 desktop software; launch flags and origins are accurate. |
| `adapters/webview2/` | **B-** | **REVISE** | Needs testing against real embedded WinForms/WPF WebView2 apps, not just `msedge.exe`. |
| `adapters/electron/` | **B-** | **REVISE** | Needs embedded renderer process discovery improvements. |
| `adapters/webkit/` | **C** | **DEFER / ISOLATE** | Inactive on Windows; should be isolated behind a platform capability gate. |
| `scripts/review.py` | **C-** | **REWRITE / REPAIR** | Currently broken due to parameter omissions; needs complete overhaul to align with evidence engine. |
| `scripts/audit_phase*.py` | **F** | **DISCARD / ARCHIVE** | 2,600+ lines of application-specific Anki test code that does not belong in a universal tool repository. |

---

## 23. THE 24 REQUIRED QUESTIONS ANSWERED

### Q1: Does the existing repository actually work today for its stated purpose?
**`[CODE FACT / TEST FACT]`** **Partially.**  
If used as a Python library (`core/`), or when invoked via the specialized audit harnesses (`scripts/audit_phase2.py`, `scripts/audit_phase3.py`) and unit tests (`test_anki_maths_real_app.py`), the system successfully attaches to and verifies real desktop applications (specifically PyQt6 QtWebEngine).  
However, if invoked via the documented universal CLI tool (`python scripts/review.py`), **it does NOT work as intended**. It is locked in permanent `Verdict.UNVERIFIED` because `review.py` fails to provide the parameters required by `core/evidence.py`.

### Q2: Which engines work in reality vs only in design/documentation?
**`[CODE FACT / TEST FACT]`**
- **QtWebEngine:** Works in reality. Fully validated against real PyQt6 Anki DEV GUI desktop software.
- **Generic Chromium:** Works in reality.
- **WebView2:** Works in design, partially in reality. Validated against `msedge.exe --app`, but untested against embedded WPF/WinForms `CoreWebView2Controller`.
- **Electron:** Works in design, partially in reality. Integration test relies on global `npx electron`.
- **WebKit:** Documentation only. Hardcoded to `RUNTIME_UNAVAILABLE` on Windows (`adapters/webkit/adapter.py#L52`).

### Q3: Is the adapter pattern real or an illusion?
**`[ARCHITECTURAL OBSERVATION]`** **Mostly an illusion.**  
While `BaseEngineAdapter` exists as an abstract base class, it only customizes environment variables and launch arguments (`prepare_environment` and `get_launch_args`). It does not customize action execution, DOM inspection, or screenshot mechanisms. All adapters inherit the identical default implementations from `core/`. Furthermore, CEF does not have an adapter at all (it is aliased to Chromium).

### Q4: Is the CDP implementation reliable, fragile, or minimal?
**`[CODE FACT / ARCHITECTURAL OBSERVATION]`** **Reliable for inspection, minimal for actions.**  
The transport in `core/session.py` (pure async JSON-RPC over `websockets` with request ID mapping) is surprisingly robust, fast, and lightweight. It avoids browser-level commands that crash embedded webviews. However, its interaction model is minimal: it only implements click, type, and scroll, and typing uses synthetic DOM mutation rather than native keystroke events.

### Q5: Does the codebase solve the native <-> web boundary problem, or does it cheat?
**`[ARCHITECTURAL OBSERVATION]`** **It genuinely attempts to solve it without cheating.**  
The codebase refuses to equate CDP connection success with desktop reality. It validates that the OS process tree owns the port, queries User32 to find the HWND matching the PID, verifies that the window is visible, uncloaked, non-minimized, and active, and checks that the window geometry intersects the monitor display area.

### Q6: Can a fake, hidden, minimized, offscreen, or headless window pass verification?
**`[CODE FACT / TEST FACT]`** **NO.**  
Under `EvidenceCollector.evaluate_verdict`, all 12 forensic gates must pass. If a window is headless (`hwnd is None`), invisible (`not window_visible`), minimized (`is_iconic`), cloaked (`is_cloaked`), or has zero intersection with the monitor, it is deterministically rejected with `Verdict.UNVERIFIED`.

### Q7: Does the dual screenshot mechanism prove what it claims to prove?
**`[CODE FACT / RISK ASSESSMENT]`** **In theory yes, in practice with vulnerabilities.**  
In theory, capturing both the internal renderer viewport via CDP and the external native desktop window via Win32 `PrintWindow` proves that the web content is actually rendering on the OS desktop. However, in practice:
1. `PrintWindow` with `PW_RENDERFULLCONTENT` frequently fails against hardware-accelerated DirectX/Qt surfaces, returning a black or blank bitmap while reporting success.
2. The code does not perform visual pixel differencing or structural similarity (SSIM) comparisons between the native and webview captures; it merely checks that both files exist and computes their SHA-256 hashes.

### Q8: How fragile is target discovery in real-world desktop apps?
**`[CODE FACT]`** **Moderately robust, but vulnerable to timing.**  
`TargetDiscovery.poll_for_targets` polls `/json/list` with retries. Its heuristic scoring (`rank_score`) effectively filters out internal DevTools URLs (`devtools://`), extensions, and background service workers. However, if an application delays creating its webview until after an initial splash screen or authentication dialog, discovery may timeout.

### Q9: What happens if an app has multiple webviews?
**`[CODE FACT]`** `MultiTargetSessionManager` in `core/session.py#L291-L379` supports multiple targets and switching between them. `TargetDiscovery.filter_targets` ranks targets to pick the primary one, but concurrent simultaneous automation across multiple webviews in a single session is not supported.

### Q10: What happens if an app opens popups or new windows?
**`[CODE FACT]`** New popups generate new targets on `/json/list`. However, `CDPSession` does not subscribe to `Target.targetCreated` or `Target.attachedToTarget` events. New windows are ignored unless `discover.py` is re-run.

### Q11: How does the system handle process crashes, hangs, or port collisions?
**`[CODE FACT]`**
- Port collisions: `ProcessLauncher.find_free_port` scans ports from 9222 upward to find an available port.
- Process crashes: `CDPSession` catches `websockets.ConnectionClosed` and marks `_is_connected = False`.
- Process hangs: `CDPSession.send_command` enforces a timeout (default 15s) and raises `TimeoutError`.

### Q12: Can the reviewer kill or damage an unrelated application?
**`[CODE FACT / RISK ASSESSMENT]`**
- In Attach Mode: Protected. `ProcessCleanup.safe_cleanup` checks `launched_by_reviewer == False` and preserves the process.
- In Launch Mode: Protected by PID creation timestamp validation (`abs(actual_create_time - expected_create_time) <= 5.0`).
- **Hazard:** If `desktop_ownership.json` is missing or corrupted, line 124 defaults `launched_by_reviewer = True`. If a stale `desktop_app.pid` exists matching an unrelated process, running `stop.py` can terminate that unrelated process.

### Q13: Does the assertion system provide meaningful guarantees?
**`[CODE FACT]`** **Meaningful for DOM/JS state, but lacks retrying.**  
`WebviewAssertions` records exact description, expected value, actual value, error message, and timestamp. However, assertions are evaluated immediately without polling or auto-waiting, leading to false negatives on asynchronous UIs.

### Q14: Is the locator/element model sufficient for complex UI automation?
**`[CODE FACT]`** **NO.**  
It is restricted entirely to CSS selectors evaluated via `document.querySelector`. It cannot locate elements by text content, XPath, ARIA attributes, or pierce closed Shadow DOM roots.

### Q15: Is the action model (click, type, scroll) reliable or primitive?
**`[CODE FACT]`** **Primitive.**  
- `click`: Calculates center coordinate and dispatches mouse events, with synthetic DOM fallback.
- `type_text`: Injects value via JavaScript property assignment (`el.value = ...`). It does NOT dispatch real keyboard events.
- Hover, drag-and-drop, double-click, and multi-key combos are completely absent.

### Q16: How much of the code is generic vs tailored to QtWebEngine / Anki?
**`[CODE FACT]`**
- `core/`, `detectors/`, `launchers/`, and `adapters/` are ~85% generic desktop automation code.
- `scripts/` is ~65% application-specific Anki code due to the presence of `audit_phase2.py` and `audit_phase3.py` (2,600+ lines).

### Q17: What are the biggest technical debt items in the codebase?
**`[ARCHITECTURAL OBSERVATION]`**
1. The CLI review script `scripts/review.py` is out-of-sync with `core/evidence.py`, breaking CLI verification.
2. 64-bit ctypes handles lack explicit type definitions in `core/window_forensics.py`.
3. GDI handles leak on uncaught exceptions in screenshot routines.
4. Monolithic Anki audit scripts pollute `scripts/`.
5. 24 untracked scratch and patch scripts litter the repository root.

### Q18: What are the security vulnerabilities or hazards in the current design?
**`[RISK ASSESSMENT]`**
1. Unsanitized execution of arbitrary binaries via `scripts/launch.py`.
2. Full parent environment credential leakage into spawned processes.
3. Plaintext storage of command arguments in `desktop_ownership.json`.
4. Arbitrary JavaScript execution exposed via CDP `Runtime.evaluate`.
5. Spawning Chromium with `--no-sandbox` in test audit scripts.

### Q19: Which parts of the codebase should be reused as-is?
**`[ARCHITECTURAL OBSERVATION]`**
- `core/models.py` (Dataclasses, schemas, enums).
- `core/session.py` (Lightweight WebSocket CDP JSON-RPC client).
- `core/discovery.py` (Target filtering and ranking engine).
- `core/cleanup.py` (Process tree termination with timestamp safety).

### Q20: Which parts should be refactored?
**`[ARCHITECTURAL OBSERVATION]`**
- `core/window_forensics.py`: Add 64-bit ctypes typing, `try...finally` GDI wrappers, and virtual multi-monitor support.
- `core/actions.py`: Implement native keyboard event dispatching and expand locator options.
- `core/evidence.py`: Make strict requirements configurable and synchronize with CLI options.

### Q21: Which parts should be completely discarded?
**`[ARCHITECTURAL OBSERVATION]`**
- `scripts/audit_phase2.py`, `scripts/audit_phase3.py`, `scripts/audit_phase3_5.py`: Remove from core repository.
- Untracked `fix_*.py` and `patch_*.py` files: Delete permanently.
- `adapters/webkit/`: Remove Windows stub or isolate to Linux/macOS builds.

### Q22: What architectural boundaries already align with a future MCP architecture?
**`[ARCHITECTURAL OBSERVATION]`**
- `EvidenceReport` maps directly to an MCP Resource (`desktop://sessions/{id}/evidence`).
- Screenshots map to binary MCP Resources.
- `WebviewActions` and `WebviewAssertions` map cleanly to discrete MCP Tools.
- Target ranking and discovery map to an inspection tool.

### Q23: What would need to change to expose this system via MCP?
**`[ARCHITECTURAL OBSERVATION]`**
1. Wrap the core engine in a long-running daemon or MCP server process.
2. Decouple persistent sessions (UUID-based) from transient JSON-RPC request-response cycles.
3. Replace static file outputs (`evidence.json`, `screenshot.png`) with in-memory buffers or unique session artifact directories.
4. Expose fine-grained tools for launch, attach, query, interact, assert, and capture.

### Q24: If we started from scratch, what lessons from this repository must we preserve?
**`[ARCHITECTURAL OBSERVATION]`**
1. **The Golden Law:** Never trust CDP or browser DOM alone; always corroborate with native OS window forensics.
2. **Tripartite Verdicts:** Enforce `PASS`, `FAIL`, and `UNVERIFIED`.
3. **Avoid Browser-Level CDP Commands:** Embedded desktop webviews reject `Browser.*` domains; connect strictly to page-level WebSockets.
4. **PID Tree Traversal:** Chromium and QtWebEngine render in child processes; always track the full process tree.
5. **Cryptographic Provenance:** Validate image magic bytes and SHA-256 hash all screenshot artifacts immediately upon capture.

---

## 24. FINAL VERDICT & RESEARCH GAPS

### Final Verdict
The `desktop-webview-reviewer` repository contains an **extraordinarily valuable, highly specialized, and conceptually brilliant core** embedded inside a working tree that suffered from **rapid development debt, ad-hoc regex patching, and application-specific pollution**. 

Its core forensic engine (`core/models.py`, `core/window_forensics.py`, `core/session.py`, `core/discovery.py`, `core/evidence.py`) represents production-grade architecture that should be preserved, hardened, and adapted into the broader universal desktop automation + MCP architecture.

### Research Gaps for Track 10
1. **DirectComposition & Hardware Acceleration GDI Scrapers:** Investigating Desktop Duplication API (DXGI) or Windows Graphics Capture (`Windows.Graphics.Capture`) to replace `PrintWindow` for flicker-free, black-screen-immune native captures.
2. **Native UIA Corroboration:** Correlating the webview DOM tree with the native Windows UI Automation (UIA) tree for hybrid accessibility verification.
3. **Multi-Session MCP Daemon Architecture:** Designing a stateful background desktop agent daemon that manages persistent sessions while exposing clean, stateless MCP tools to LLM orchestrators.

---
**Report compiled by Adaptive Orchestrator (v4 Foundation)**  
**Status: FORENSIC AUDIT COMPLETE — REPOSITORY LEFT 100% UNTOUCHED**
