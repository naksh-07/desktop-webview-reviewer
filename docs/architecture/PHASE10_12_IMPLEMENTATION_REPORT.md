# Desktop WebView Reviewer 2.0 — Phase 10–12 Implementation Report

**Milestone:** Phase 10–12: Desktop Eyes, Human-Equivalent Hands, Trace & Observability  
**Status:** COMPLETE & VERIFIED  
**Date:** 2026-09-05  
**Test Matrix:** 429 Passed / 0 Failures / 0 Errors / 4 Skipped (136.54s)  

---

## 1. Executive Summary

Phase 10–12 turns the Phase 9 constitutional and architectural contracts into concrete, verified runtime capabilities across four critical pillars:
1. **Desktop Eyes**: Full desktop topology discovery (`EnumDisplayMonitors`), multi-monitor coordinate spaces, deep native window forensics (DWM cloaking, minimization/iconic state, Z-order, focus, ownership), element crops, and visual evidence generation.
2. **Reality Reconciliation**: Unification of DOM, Accessibility, Native Win32/UIA, Compositor (DWM), and visual inspection under the inviolable **Truth Hierarchy**:
   $$\text{Physical Desktop Reality} > \text{Compositor Reality} > \text{DOM/Web Reality}$$
3. **Human-Equivalent Hands**: Expansion of physical and web dispatch to cover the complete human desktop interaction spectrum (`click`, `double_click`, `right_click`, `type`, `key_press`, `keyboard_shortcut`, `hover`, `scroll`, `focus`, `drag`, `drop`, `drag_and_drop`, `select`, `dialog_interaction`, `file_picker`), underpinned by a strict 5-stage action lifecycle avoiding the Dispatch Fallacy.
4. **Unified Desktop Trace & Observability**: High-throughput, bounded, in-memory `DesktopTraceEngine` implementing the 18 canonical trace event types, universal correlation envelope, causal action reconstruction, and automated stream/token redaction (`[REDACTED]`).

The controlling agent sovereignty boundary remains absolute:
- **Controlling Agent:** Owns WHAT & WHY (the mission, goal, evaluation).
- **Desktop WebView Reviewer:** Owns HOW (reconciled observation, actionability gating, input delivery, settlement, verification, forensic evidence).

---

## 2. Desktop Eyes Implementation

### 2.1 Multi-Monitor Geometry & Topology
- **Physical Display Enumeration:** Integrated 64-bit `MONITORENUMPROC` and `EnumDisplayMonitors` via Win32 ctypes into `CoordinateTransformer.get_system_multimonitor_topology()`.
- **Topological Metadata:** Identifies each display's device name (e.g. `\\.\DISPLAY1`), virtual desktop coordinates, resolution, primary status, and per-monitor DPI scale.
- **MCP Resource & CLI Exposure:** Registered `desktop://displays` as a dynamic JSON resource and provided topology inspection via `scripts/diagnostics.py`.

### 2.2 Deep Window Forensics
- **DWM Compositor Awareness:** Queries `DwmGetWindowAttribute` with `DWMWA_CLOAKED` and `DWMWA_EXTENDED_FRAME_BOUNDS`.
- **State Properties:** Evaluates `IsWindowVisible`, `IsIconic`, `GetWindowPlacement`, ownership, and focus status.
- **Forensic Guarantee:** Windows that are cloaked (e.g., virtual desktop switches, system trays) or minimized are explicitly identified and disqualified from physical actionability.

### 2.3 Visual Observation Primitives
- **Desktop & Window Screenshots:** `NativeSupervisor.capture_full_desktop_screenshot()` and `capture_window_screenshot()` return cryptographic SHA-256 digests and dimension metadata.
- **Element Affordance Crops:** `NativeSupervisor.capture_element_crop()` crops directly from window/desktop framebuffers given element screen coordinates, avoiding synthetic mocks.

---

## 3. Reality Reconciliation & Truth Hierarchy

### 3.1 Truth Hierarchy Enforcement
The runtime rigorously enforces physical primacy:
- If DOM claims an element is visible (`display != none`, `opacity > 0`), but the native window is **cloaked** or **minimized** by the DWM compositor, physical visibility is `False` and actionability is rejected.
- If a modal window covers the target element, `RealityReconciler` detects the occlusion and records an `OCCLUDED_BY_MODAL` contradiction.

### 3.2 Canonical `RealityTarget`
Synthesizes four distinct planes into one authoritative model:
- `identity`: Reference (`w1e1`, `n1e1`), role, name, target ID.
- `native`: Win32 HWND, class name, window title, visibility, focus.
- `web`: Tag name, CSS bounds, CDP node ID, frame ID.
- `compositor`: DWM bounds, `is_cloaked`, `is_minimized`, occlusion percentage.
- `visual`: Rendered status, crop SHA-256 hash.
- `actionability`: `is_actionable`, affordance point, explicit reasons.

---

## 4. Human-Equivalent Hands

### 4.1 Interaction Spectrum
Expanded `ActionType` and native/web action executors:
- **Mouse Inputs:** `CLICK`, `DOUBLE_CLICK`, `RIGHT_CLICK`, `HOVER`, `SCROLL`, `DRAG`, `DROP`, `DRAG_AND_DROP`. Linear coordinate interpolation and SendInput safety prevent sudden cursor teleports.
- **Keyboard Inputs:** `TYPE`, `KEY_PRESS`, `KEYBOARD_SHORTCUT` (supporting `Control`, `Shift`, `Alt`, `Meta` combinations).
- **Semantics & Dialogs:** `SELECT` (dropdown option choice), `DIALOG_INTERACTION` (`accept`, `dismiss`, `input_text`), `FILE_PICKER` (path submission).

### 4.2 5-Stage Action Lifecycle
Eliminated the Dispatch Fallacy by enforcing five distinct milestones:
1. `ACTION_RECEIVED`: Request validated by security gate and recorded in trace.
2. `ACTION_DISPATCHED`: Input delivered via SendInput, CDP, or UIA.
3. `ACTION_COMPLETED`: Low-level physical/driver interaction finished.
4. `STATE_CHANGED`: Settled state difference computed (DOM diff, window rect change, navigation).
5. `EXPECTED_STATE_VERIFIED`: Post-observation verified by independent criteria.

### 4.3 Transactional Visual Evidence
- Every mutating action conditionally captures pre-action and post-action screenshots.
- Screenshots are stored as immutable, SHA-256 content-addressed artifacts in `EvidenceStore` and linked directly to the action trace envelope.

---

## 5. Unified Desktop Trace & Observability

### 5.1 Monotonic Converged Timeline
- **Event Types (18 Canonical):** `APP_LAUNCH`, `APP_ATTACH`, `WINDOW_DISCOVERED`, `PROCESS_STATE`, `WEBVIEW_CONNECTED`, `OBSERVATION`, `TARGET_RESOLVED`, `ACTION_REQUESTED`, `ACTION_DISPATCHED`, `ACTION_SETTLED`, `SCREENSHOT`, `DOM_CHANGE`, `UIA_CHANGE`, `CONSOLE_EVENT`, `LOG_EVENT`, `ASSERTION`, `RECOVERY`, `EVIDENCE_CREATED`.
- **Universal Correlation Envelope:** Every event carries `session_id`, `epoch_id`, `action_id`, `event_id`, `timestamp`, `plane`, and `details`.
- **Causal Reconstruction:** `DesktopTraceEngine.get_action_lifecycle(action_id)` and `DesktopTraceEngine.query(...)` allow agents to reconstruct the exact causal sequence before, during, and after an interaction.

### 5.2 Token Redaction & Safety
- Automated regex filtering replaces passwords, authorization tokens, bearer headers, and API keys with `[REDACTED]`.
- Content enveloping marks all page text and console strings as untrusted data (`is_untrusted_ui_data=True`).

### 5.3 CDP Console & Diagnostics Stream
- Real-time CDP `Runtime.consoleAPICalled` and `Runtime.exceptionThrown` events are captured and ingested into the session trace timeline.
- Application stdout/stderr streams are ingested via `ingest_log_line()`.

---

## 6. MCP Control Plane & Developer CLI

### 6.1 MCP Invariant Preservation
- **Invariant D (Strict Tool Count = 12):** The registered primary tool count remains exactly 12 (`desktop_launch`, `desktop_attach`, `desktop_inspect`, `desktop_click`, `desktop_type`, `desktop_press_key`, `desktop_hover`, `desktop_scroll`, `desktop_wait`, `desktop_assert`, `desktop_collect_evidence`, `desktop_close_session`).
- **Extended Tool Capabilities:** Modifier shortcuts and multi-click behaviors are exposed through existing tools (`desktop_press_key`, `desktop_click`).
- **MCP Resources:** Added `desktop://displays`, `desktop://sessions/{session_id}/trace`, and `desktop://sessions/{session_id}/reality`.

### 6.2 Developer CLI
- `scripts/doctor.py`: Full diagnostic self-check including trace engine, reality reconciler, monitor topology, and win32 forensics.
- `scripts/desktop_inspect.py`: Window hierarchy and multi-plane reality reconciliation inspector (`--reality`, `--json`).
- `scripts/screenshot.py`: Desktop and window screenshot capture utility (`--scope desktop|window`, `--json`).
- `scripts/trace.py`: Trace timeline query utility (`--session-id`, `--action-id`, `--limit`).
- `scripts/diagnostics.py`: Operator diagnostics for monitor topology, active windows, and DWM states.

---

## 7. Verification & Test Matrix

The full repository test suite was executed against active Windows runtime surfaces:
```text
Ran 429 tests in 136.541s
OK (skipped=4)
```

### Highlights:
- **Phase 10 (Trace & Observability):** `tests/test_phase10_trace_and_observability.py` — 4/4 Passed.
- **Phase 11 (Reality Reconciliation):** `tests/test_phase11_reality_reconciliation.py` — 4/4 Passed.
- **Phase 12 (Hands & Interaction):** `tests/test_phase12_hands_and_interaction.py` — 4/4 Passed.
- **Desktop Eyes (Topology & Forensics):** `tests/test_desktop_eyes_topology.py` — 4/4 Passed.
- **MCP Phase 10–12 Tools & Resources:** `tests/test_mcp_phase10_12_tools.py` — 5/5 Passed.
- **MCP Tool Registration & Invariant D:** `tests/test_mcp_tool_registration_and_schemas.py` — 8/8 Passed.
- **Phase 8 Adversarial Security:** `tests/test_phase8_adversarial_security.py` — 10/10 Passed.
- **Phase 9 Sovereignty & Contracts:** `tests/test_phase9_contracts.py` — 8/8 Passed.
- **Real Application (Anki Maths & Electron):**
  - Live Anki Maths QtWebEngine runtime: verified target discovery, AX snapshot (49 nodes), body geometry, and CDP transport.
  - Live Electron fixture runtime: verified full launch, inspection, and teardown lifecycle.
