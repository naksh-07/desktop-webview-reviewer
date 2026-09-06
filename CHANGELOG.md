# Changelog

All notable changes to the `desktop-webview-reviewer` skill are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0b1] - 2026-09-06

### First Beta Release — Architecture H Frozen & Lifecycle Subsystem
- **First Beta Release Identity**:
  - Authoritative canonical version `2.0.0b1` (PEP 440 compliant) and Git / GitHub release tag `v2.0.0-beta.1`.
  - Reconciled package classifiers: `Development Status :: 4 - Beta` and `Operating System :: Microsoft :: Windows`.
  - Architecture H is frozen: exactly 12 primary MCP tools, decoupled supervisory daemon, zero hidden God-agent planning loops.
- **Product Lifecycle, Versioning, Update & Rollback System** (`runtime/lifecycle/`):
  - `core/version.py`: Single programmatic source of truth for product name, package version, git commit, installation source, runtime path, MCP executable, and skill path.
  - `InstallationRegistry`: Persistent JSON state at `~/.desktop_webview_reviewer/installation_state.json` with atomic writes, crash recovery, and corrupted-state backup.
  - `GitHubReleasesClient`: Native GitHub API client discovering releases with semver ordering, prerelease channel filtering, offline/rate-limit fail-soft tolerance, and mock release support.
  - `LifecycleUpdater`: Atomic transactional updater with pre-install release validation, known-good version tracking, post-install health checks (import, version consistency, MCP self-test), and automatic rollback on failure.
  - `SkillSynchronizer`: Bi-directional version synchronization and compatibility verification between installed Antigravity skill packages (`SKILL.md` frontmatter) and active Python runtimes.
  - `LifecycleDoctor`: 7-point deep consistency checker auditing package imports, state alignment, CLI/MCP executables, MCP self-test, skill compatibility, and stale installations.
  - Version pinning & rollback: explicit `pin <ver>`, `unpin`, and verified `rollback` restoring known-good packages without mutating state on failure.
- **Passive MCP Lifecycle Resources**:
  - `desktop://system/version`: Live VersionInfo contract payload.
  - `desktop://system/lifecycle`: Structured lifecycle state, pinning, and update availability.
- **Multi-Framework Live Certification Matrix**:
  - Live runtime verified on Windows 11 host across QtWebEngine (Anki Maths), Electron, and WebView2.
  - Generic Chromium/CEF verified at protocol capability level; honest capability attribution applied (`runtime_verified`, `protocol_verified`, `runtime_unavailable`).
- **Adversarial Security Hardening**:
  - Dedicated 28-category adversarial certification test suite (`tests/test_phase19_adversarial_certification.py`) passing 100%.
  - 6-domain production security audit passing with zero security findings.
- **Known Environmental Limitations**:
  - Windows 10/11 64-bit primary supported scope.
  - DWM composition checks require an active, unoccluded desktop window display.
  - WebKit minibrowser lacks standard CDP protocol support.
  - UIA3 sidecar binary uncompiled by default.

### Lifecycle, Versioning, Update & Rollback System
- **Authoritative Version Contract** (`core/version.py`):
  - Single source of truth for product name, version, package version, git commit, installation source, runtime path, MCP executable, and skill path.
  - Module-level `__version__` and structured `VersionInfo` dataclass.
  - Replaces all hardcoded version references across the codebase.
- **Product Lifecycle & Update Engine** (`runtime/lifecycle/`):
  - `InstallationRegistry`: Persistent JSON state at `~/.desktop_webview_reviewer/installation_state.json` with atomic writes, crash recovery, and corrupted state backup.
  - `GitHubReleasesClient`: GitHub API-based release discovery with semver ordering, offline/rate-limit fail-soft resilience, and mock file support for testing.
  - `LifecycleUpdater`: Safe transactional updater with pre/post-install validation gates (import check, version consistency, MCP self-test) and automatic rollback on failure.
  - `SkillSynchronizer`: Discovers Antigravity skill installations, parses YAML frontmatter for version/compatibility range, evaluates compatibility with active runtime.
  - `LifecycleDoctor`: 7-point deep consistency checker (package import, state alignment, CLI/MCP executable resolution, MCP self-test, skill compatibility, stale installation detection).
- **CLI Commands** (`scripts/update_cli.py`):
  - `desktop-reviewer version [--json]` — Authoritative version contract display.
  - `desktop-reviewer update check [--json]` — Check for compatible updates.
  - `desktop-reviewer update install <version> [--json]` — Safe atomic version installation.
  - `desktop-reviewer update status [--json]` — Full lifecycle status.
  - `desktop-reviewer update pin <version> [--json]` — Pin to known-good version.
  - `desktop-reviewer update unpin [--json]` — Resume normal release tracking.
  - `desktop-reviewer update rollback [--json]` — Roll back to previous known-good.
  - `desktop-reviewer update doctor [--json]` — Deep installation health check.
- **MCP Resources** (passive, read-only):
  - `desktop://system/version` — Full version contract payload.
  - `desktop://system/lifecycle` — Update status, pinning, and lifecycle state.
- **Skill Metadata Synchronized**:
  - Both repository and global Antigravity skill (`~/.gemini/config/skills/desktop-webview-reviewer/SKILL.md`) updated with `version: 2.0.0` and `compatible_runtime_range: ">=2.0.0,<3.0.0"`.
- **Invariants Preserved**:
  - Exactly 12 primary MCP tools unchanged.
  - Architecture H frozen. No new agents, orchestration layers, or framework expansions.

---

## [2.0.0-phase17-18] - 2026-09-05

### Highlights: Phase 17–18 — Autonomous Review Missions & Host Integrations
- **Autonomous Review Missions**:
  - Canonical `ReviewMission` authority object with immutable SHA-256 authority digest sealing.
  - Deterministic 13-point `MissionAdmissionGate` rejecting malformed or unconstrained scopes.
  - Provenance-backed `GoalOrientedDiscoveryEngine` strictly bound to declared mission scope (zero general crawling).
  - Subordinate `ReviewPlanBuilder` and `ReviewMissionOrchestrator` enforcing hard action/delegation/recovery budgets.
- **Host & Presentation Integrations**:
  - Decoupled `AntigravityReviewerAdapter` streaming events and inert observation envelopes.
  - Read-only `TeamPreviewConsumer` strictly enforcing the Zero-Mutation Law.
  - Exposed mission resources (`desktop://missions/active`, `desktop://missions/{mission_id}`) and prompt (`desktop_autonomous_mission`).

---

## [2.0.0-phase15-16] - 2026-09-05

### Highlights: Phase 15–16 — Specialist Subagents, Diagnostics & Bounded Recovery
- **Specialist Subagent Runtimes**:
  - Bounded lifecycles for Explorer, Tester, Reality Inspector, Debugger, and Evidence Specialist.
  - Enforced frozen contract tool gates and immutable audit ledger (`ToolAuditRecord`).
- **Unified Diagnostics & Bounded Recovery**:
  - `DiagnosticAggregator` fusing multi-plane evidence into 19 canonical failure classifications.
  - `RecoveryEngine` and anti-retry-storm `CircuitBreaker` enforcing "NO BLIND RETRIES".

---

## [2.0.0-phase10-12] - 2026-09-05

### Highlights: Phase 10–12 — Desktop Eyes, Human-Equivalent Hands, Trace & Observability
- **Desktop Eyes**:
  - Implemented 64-bit multi-monitor topology discovery (`EnumDisplayMonitors`, DPI scale, primary monitor, virtual screen rect) exposed via `desktop://displays` and `scripts/diagnostics.py`.
  - Added full desktop and window screenshot capture with SHA-256 content addressing, element affordance cropping, and DWM window forensics (cloaked, iconic, focus, bounds).
- **Reality Reconciliation & Truth Hierarchy**:
  - Implemented multi-plane reconciliation unifying Native Win32/UIA, Chromium DOM/AX, DWM Compositor, and Visual framebuffers into canonical `RealityTarget` and `RealityReconciliationSnapshot`.
  - Enforced physical primacy: $\text{Physical Desktop Reality} > \text{Compositor Reality} > \text{DOM/Web Reality}$, disqualifying cloaked/minimized/modal-occluded elements from actionability even if DOM claims visibility.
- **Human-Equivalent Hands**:
  - Expanded interaction repertoire to cover complete human desktop interactions: `click`, `double_click`, `right_click`, `type`, `key_press`, `keyboard_shortcut`, `hover`, `scroll`, `focus`, `drag`, `drop`, `drag_and_drop`, `select`, `dialog_interaction`, `file_picker`.
  - Enforced 5-stage action milestone lifecycle (`ACTION_RECEIVED`, `ACTION_DISPATCHED`, `ACTION_COMPLETED`, `STATE_CHANGED`, `EXPECTED_STATE_VERIFIED`), eliminating the Dispatch Fallacy.
  - Added pre- and post-action visual evidence capture tied to the transaction receipt.
- **Unified Desktop Trace & Observability**:
  - Implemented `DesktopTraceEngine` and `BoundedTraceTimeline` with 18 canonical trace event types and universal correlation envelope.
  - Implemented causal action reconstruction (`get_action_lifecycle`, `query`) and automatic token/secret redaction (`[REDACTED]`).
  - Forwarded real-time CDP console events and exceptions to the session trace timeline.
- **MCP & CLI Integration**:
  - Strictly preserved Invariant D (exactly 12 primary MCP tools).
  - Added MCP resources: `desktop://displays`, `desktop://sessions/{session_id}/trace`, `desktop://sessions/{session_id}/reality`.
  - Added operator CLI commands: `scripts/desktop_inspect.py`, `scripts/screenshot.py`, `scripts/trace.py`, `scripts/diagnostics.py`.
  - Enhanced `scripts/doctor.py` with trace engine, reality reconciler, monitor topology, and win32 forensics health checks.
- **Validation**:
  - 429 total tests passed (0 failures, 0 errors, 4 skipped) across unit, integration, Phase 8 adversarial security, Phase 9 contracts, and live Anki Maths and Electron runtimes.

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
