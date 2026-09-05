# Changelog

All notable changes to the `desktop-webview-reviewer` skill are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0-phase9] - 2026-09-05

### Highlights: Phase 9 — Agent Sovereignty, Capability Architecture & Desktop Superpower Specification
- **Constitutional Sovereignty Boundary**: Formalized the separation between the controlling agent's mission authority (**WHAT & WHY**) and Desktop WebView Reviewer's technical execution capability (**HOW & VERIFY**). Codified Anti-God-Agent constraints.
- **2.0 Capability Model & Negotiation**: Established a 6-domain capability model (Visual, Native, WebView, Interaction, Process, Diagnostics) with honest states (`AVAILABLE`, `DEGRADED`, `UNAVAILABLE`, `UNKNOWN`) and dynamic `CapabilityNegotiationProfile`.
- **Reality Model & Physical Primacy**: Formalized the `RealityTarget` schema reconciling Native HWND, Blink DOM, AXTree, DWM Compositor, and Visual framebuffers under the strict hierarchy: `Physical Desktop Reality > Compositor Reality > DOM/Web Reality`.
- **Action Contract 2.0**: Codified the 10-phase interaction lifecycle and explicitly segregated the five milestones (`Action Received != Dispatched != Completed != State Changed != Expected State Verified`).
- **Desktop Trace & Observability**: Specified the 17 canonical trace events with universal correlation envelopes and converged monotonic timeline.
- **Reviewer Test Harness & Golden Rule**: Specified optional development-build instrumentation (lifecycle signals, diagnostics, test fixtures, fault injection) and enforced the Golden Rule: Black-box reality validation outranks instrumented telemetry. Mandated release CI build-time stripping.
- **Subordinate Specialist Contracts**: Formulated operational boundaries for Explorer, Tester, Reality Inspector, Debugger, and Evidence Specialist subagents.
- **Architecture Documentation**: Added Docs 21–27 and the comprehensive Phase 9 Implementation Report in `docs/architecture/`.

---

## [1.0.0] - 2026-08-24

### Highlights
- **Universal Desktop Webview Support**: Standardized cross-engine testing for QtWebEngine, WebView2, Electron, Generic Chromium, CEF, and WebKit.
- **Physical Reality Focus**: Interacts directly with physical desktop operating system processes and genuine window targets without synthetic browser mocks.
- **Intelligent Target Disambiguation**: Multi-signal scoring heuristics rank application webview pages above DevTools, background workers, and blank windows.
- **Diagnostic Doctor Command (`scripts/doctor.py`)**: Instant environment and engine availability check with formatted dashboard and `--json` export.
- **Process Ownership Safety**: Bulletproof separation of Launch Mode (recursive child tree teardown with PID reuse protection) and Attach Mode (zero-kill detachment).
- **Forensic Evidence Collection**: SHA-256 screenshot hashing and structured `evidence.json` generation.

### Verification Matrix
- `QtWebEngine`: **RUNTIME_VERIFIED on Windows** (tested live against PyQt6 and Anki Maths desktop applications).
- `WebView2`: **RUNTIME_VERIFIED on Windows** (tested live with Microsoft Edge and WebView2 Evergreen Runtime).
- `Electron`: **RUNTIME_VERIFIED on Windows** (tested live with Electron renderer fixtures).
- `Generic Chromium`: **RUNTIME_VERIFIED on Windows** (tested live with standalone CDP endpoints).
- `CEF`: **PROTOCOL_VERIFIED** (CDP protocol communication verified; standalone CEF host binary pending).
- `WebKit`: **RUNTIME_UNAVAILABLE on Windows** (platform limitation documented; Windows frameworks route to WebView2).

### Added
- `scripts/doctor.py`: Self-check diagnostic tool inspecting Python (>=3.9), `websockets` (>=11.0), `psutil` (>=5.9.0), core subsystems, and engine discovery.
- `tests/test_doctor.py`: Dedicated unit test suite verifying doctor execution, report rendering, and JSON output.
- `pyproject.toml`: PEP 517/621 packaging metadata with console script entry points.
- `.gitignore`: Clean release ignore rules for ephemeral state, logs, and screenshots.
- Multi-engine capability negotiation matrix with per-domain fallback logic (e.g. synthetic DOM events for degraded input domains).

### Changed
- Sanitized all test suites (`test_port_conflicts.py`, `test_anki_maths_real_app.py`) to resolve paths dynamically from environment and relative parents without machine-specific usernames.
- Upgraded `core/__init__.py` to export `__version__ = "1.0.0"`.
- Consolidated documentation across `README.md`, `SKILL.md`, and technical specifications in `references/`.

### Process Safety & Security
- Debugging sockets strictly bound to `127.0.0.1`.
- Process tree termination verifies `psutil.Process(pid).create_time()` to prevent killing recycled PIDs.
- Detachment mode preserves external processes without invoking global process killing commands.
