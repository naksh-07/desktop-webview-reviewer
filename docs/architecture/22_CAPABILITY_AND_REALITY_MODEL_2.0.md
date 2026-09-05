# Architecture Document 22: Desktop WebView Reviewer 2.0 Capability & Reality Model

**Document ID:** `docs/architecture/22_CAPABILITY_AND_REALITY_MODEL_2.0.md`  
**Status:** APPROVED (Phase 9 Milestone)  
**Author:** Principal System Architect & Antigravity Lead  
**Target Repository:** `desktop-webview-reviewer`  
**Baseline:** Architecture H Foundation, Docs 11–20

---

## 1. Executive Summary

Desktop WebView Reviewer 2.0 replaces fragile single-perspective testing with a **Dual-Perspective Reality Model** and a **Formal Capability Matrix**. Instead of assuming that an element in the DOM is automatically visible and interactable on screen, Reviewer reconciles multiple independent sensory layers:
- Operating system window management (Win32 HWND, DWM)
- Embedded web engine state (Blink/V8, Chromium DevTools Protocol)
- Desktop compositor status (cloaked, minimized, occluded, off-screen)
- Physical screen framebuffers (GDI PrintWindow / BitBlt capture)
- OS process telemetry (Process IDs, creation timestamps, memory, UI thread responsiveness)

---

## 2. The 2.0 Capability Model

### 2.1 The Principle of Capability Truthfulness
Reviewer adheres to an unbending rule: **Do not pretend unsupported capabilities exist.**
If an application runs under a runtime that lacks CDP input emulation (e.g. legacy WebKit on Windows) or lacks UIA tree walkers, Reviewer explicitly marks that capability as `DEGRADED` or `UNAVAILABLE`. It never executes synthetic mocks and presents them as physical desktop success.

### 2.2 Canonical Capability Statuses
Every capability supported or tracked by Reviewer must evaluate to one of four honest states:

```
┌─────────────────────────────────────────────────────────────┐
│                    CAPABILITY STATES                        │
├───────────────┬─────────────────────────────────────────────┤
│ AVAILABLE     │ Fully functional, verified against OS/engine │
├───────────────┼─────────────────────────────────────────────┤
│ DEGRADED      │ Present but with known technical limits     │
│               │ (e.g. synthetic DOM events, partial UIA)    │
├───────────────┼─────────────────────────────────────────────┤
│ UNAVAILABLE   │ Unsupported by engine, platform, or security│
├───────────────┼─────────────────────────────────────────────┤
│ UNKNOWN       │ Unprobed or unverified for current target   │
└───────────────┴─────────────────────────────────────────────┘
```

*(Note for backward compatibility: In the underlying code, `AVAILABLE` and `SUPPORTED` are interchangeable aliases, as are `UNAVAILABLE` and `UNSUPPORTED`).*

### 2.3 Six Core Capability Domains

The 2.0 model organizes capabilities across six comprehensive domains:

#### 1. Visual Capabilities (`visual.*`)
* `visual.desktop_screenshot`: Full physical desktop capture across multiple monitors.
* `visual.application_screenshot`: Authoritative HWND client/frame capture via GDI BitBlt/PrintWindow.
* `visual.window_screenshot`: Individual top-level or popup window frame capture.
* `visual.element_crop`: Pixel-perfect bounding box crop of observed elements.
* `visual.before_after_capture`: Transactional paired screenshots captured before dispatch and after settlement.
* `visual.visual_difference`: Perceptual and pixel-level comparison identifying exact rendering changes.

#### 2. Native Capabilities (`native.*`)
* `native.win32`: 64-bit safe Win32 API interop (`GetWindowRect`, `SendMessageTimeout`, `IsWindowVisible`).
* `native.uia`: Windows UI Automation (UIA3) provider and element tree traversal.
* `native.window_discovery`: Top-level and owned window enumeration filtering ghost/tool windows.
* `native.hwnd`: Authoritative Win32 handle resolution, ownership chains, and class identification.
* `native.geometry`: Physical screen bounding boxes derived from `DWMWA_EXTENDED_FRAME_BOUNDS`.
* `native.visibility`: Multi-signal visibility (IsWindowVisible, IsIconic, Cloaked, zero-area guards).
* `native.focus`: OS-level keyboard focus via `GetForegroundWindow` and `GetGUIThreadInfo`.
* `native.z_order`: Top-down window stacking order traversal for precise occlusion calculation.
* `native.dwm_compositor`: Desktop Window Manager compositor state inspection.
* `native.dialogs`: Win32 modal dialog (`#32770`), file picker (`IFileDialog`), and prompt detection.

#### 3. WebView Capabilities (`webview.*`)
* `webview.discovery`: Multi-target CDP endpoint probing and intelligent page ranking.
* `webview.cdp`: Bi-directional Chromium DevTools Protocol transport over WebSockets.
* `webview.dom`: Remote DOM tree traversal, node resolution, and attribute inspection.
* `webview.accessibility_tree`: Blink Accessibility (`Accessibility.getFullAXTree`) semantic nodes.
* `webview.frames`: Multi-frame and iframe lifecycle tracking and context binding.
* `webview.navigation`: Document navigation lifecycle, history, and URL transition tracking.
* `webview.console`: Real-time capture of `console.log`, `warn`, `error`, and exceptions.
* `webview.network`: Network request tracking, status codes, and latency (where supported).

#### 4. Interaction Capabilities (`interaction.*`)
* `interaction.click`: Single mouse click (Physical `SendInput` or CDP `dispatchMouseEvent`).
* `interaction.double_click`: Rapid two-stroke click sequence with settlement.
* `interaction.right_click`: Context menu triggering click with modal loop protection.
* `interaction.type`: Human-like keystroke dispatch (handling virtual keycodes and text inputs).
* `interaction.key_press`: Single key press with modifier key orchestration (`Ctrl`, `Alt`, `Shift`).
* `interaction.keyboard_shortcuts`: Multi-key combinations (e.g., `Ctrl+S`, `Alt+F4`).
* `interaction.hover`: Cursor positioning without button depression for tooltip/hover activation.
* `interaction.scroll`: Vertical and horizontal mouse wheel dispatch.
* `interaction.drag_drop`: Coordinate drag-and-drop sequence with motion stabilization.
* `interaction.select`: Dropdown, combo box, and list selection.
* `interaction.focus`: Explicit focus acquisition via Win32 `SetForegroundWindow` and DOM `.focus()`.
* `interaction.dialog_interaction`: Safe dismissal, acceptance, or input delivery to native modal dialogs.
* `interaction.file_picker_interaction`: Automation of native open/save file selection dialogs.
* `interaction.window_interaction`: Window minimize, maximize, restore, move, and resize operations.

#### 5. Runtime / Process Capabilities (`process.*`)
* `process.identity`: Process ID (PID), executable name, path, command line arguments.
* `process.lifecycle`: Managed launch with Job Objects (`KILL_ON_JOB_CLOSE`) and zero orphan guarantee.
* `process.state`: Process execution status, CPU/memory consumption, thread counts.
* `process.exit_status`: Exit codes, normal termination vs. external kill tracking.
* `process.crash`: Crash detection, unhandled exception tracking, Dr. Watson dumps.
* `process.hang`: UI thread responsiveness checks (`SendMessageTimeoutW(WM_NULL, 500ms)`).
* `process.tree`: Multi-process tree tracking (e.g. browser parent + renderer processes + GPU process).

#### 6. Diagnostics Capabilities (`diagnostics.*`)
* `diagnostics.stdout`: Application standard output stream capture.
* `diagnostics.stderr`: Application standard error stream capture.
* `diagnostics.application_logs`: File-based application log ingestion and correlation.
* `diagnostics.structured_telemetry`: Machine-readable telemetry events with monotonic sequencing.
* `diagnostics.console_events`: CDP console event stream with redaction.
* `diagnostics.runtime_events`: Internal daemon lifecycle milestones and state transitions.

---

## 3. Capability Negotiation Profile

At session initialization or target attachment, Reviewer executes a **Capability Negotiation Handshake**. The resulting `CapabilityNegotiationProfile` informs the controlling agent of exact runtime constraints:

```yaml
session_id: "sess_01J8F"
target_id: "target_anki_maths"
engine_info:
  engine: "QtWebEngine"
  backend: "Chromium/Blink"
  version: "122.0.6261.128"
  framework: "PyQt6"

capabilities:
  native:
    win32: AVAILABLE
    uia: DEGRADED            # FlaUI bridge available; COM tree walker uncompiled
    dwm: AVAILABLE
    dialogs: AVAILABLE
  web:
    engine: AVAILABLE
    cdp: AVAILABLE
    dom: AVAILABLE
    accessibility: AVAILABLE
    network: DEGRADED        # Network domain requires security flag
  visual:
    screenshot: AVAILABLE
    element_crop: AVAILABLE
    visual_diff: AVAILABLE
  interaction:
    physical_input: AVAILABLE
    cdp_input: AVAILABLE
    file_picker: AVAILABLE
  process:
    supervision: AVAILABLE
    tree_tracking: AVAILABLE
    job_objects: AVAILABLE
  telemetry:
    stdout: AVAILABLE
    stderr: AVAILABLE
    structured: AVAILABLE

limitations:
  - "UIA semantic automation degraded; falling back to physical SendInput with DWM bounds"
  - "Network domain inspection degraded due to engine sandbox constraints"
confidence: 0.95
```

---

## 4. The Reality Model

### 4.1 The Fundamental Truth Hierarchy
When inspecting real Windows desktop applications, multiple data sources frequently offer contradictory assertions. Reviewer enforces an unambiguous, non-negotiable **Truth Hierarchy**:

```
        ▲
       ╱ ╲
      ╱   ╲      1. Physical Desktop Reality (GDI Framebuffer, Screen DC)
     ╱  1  ╲        - What is physically rendered on screen pixels
    ╱───────╲
   ╱    2    ╲   2. Compositor Reality (Windows DWM, HWND Occlusion)
  ╱───────────╲     - Whether the window is cloaked, minimized, or covered
 ╱      3      ╲
╱───────────────╲3. DOM / Web Reality (Blink DOM Tree, CSS Styles)
                    - What the web engine internally claims exists
```

#### Rule of Contradiction Resolution:
* If the DOM claims `<button id="save" style="display:block">` is visible, but DWM reports the native window is **cloaked** (`DWMWA_CLOAKED`), the button is **NOT VISIBLE**.
* If the DOM claims an element is visible, but the HWND is **minimized** (`IsIconic=True`), the element is **NOT VISIBLE**.
* If an element exists in the DOM, but another top-level native window completely **occludes** its screen coordinates, the element is **NOT ACTIONABLE**.

### 4.2 The Reconciled Target Representation Schema

Reviewer synthesizes native, web, compositor, and visual data into an authoritative `RealityTarget`:

```yaml
target:
  identity:
    session_id: "sess_01J8F"
    target_id: "w1e7"
    reference: "w1e7"
    role: "button"
    name: "Save Configuration"
  source:
    primary_plane: "WEBVIEW"
    frame_id: "F19A2B"
    cdp_node_id: 42
  native:
    hwnd: 0x000A0452
    class_name: "Qt672QWindowIcon"
    title: "Anki - User Preferences"
    visible: true
    focused: true
    bounds:
      left: 100
      top: 100
      right: 900
      bottom: 700
      width: 800
      height: 600
  web:
    exists: true
    enabled: true
    tag_name: "BUTTON"
    css_bounds:
      x: 350
      y: 520
      width: 120
      height: 36
  compositor:
    is_cloaked: false
    is_minimized: false
    is_occluded: false
    occlusion_percentage: 0.0
    dwm_bounds:
      left: 100
      top: 100
      right: 900
      bottom: 700
  visual:
    is_physically_rendered: true
    crop_hash: "a4f8...b72e"
  actionability:
    is_actionable: true
    reasons: []
    affordance_screen_point: [450, 638]
  provenance:
    observation_epoch: 3
    reconciled_at: 1725541800.124
    truth_rank: "PHYSICAL_DESKTOP_VERIFIED"
```

---

## 5. Architectural Invariants for Phase 10+

1. **No Single-Perspective Assertions:** No test result or state assertion may be declared based solely on DOM evaluation if native or compositor conditions contradict it.
2. **Deterministic Affordance Points:** Affordance points must be computed through the full multi-monitor coordinate pipeline (`Web CSS -> Webview Viewport -> Win32 Client -> Win32 Screen -> SendInput Normalized`).
3. **Traceability:** Every `RealityTarget` must maintain provenance linking back to its exact observation epoch and frame ID.
