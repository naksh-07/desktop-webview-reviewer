# Architecture Document 11: Final Architecture Decision

**Document ID:** `docs/architecture/11_FINAL_ARCHITECTURE_DECISION.md`  
**Status:** APPROVED (Phase 0 Deliverable)  
**Author:** Principal Software Architect  
**Target Repository:** `desktop-webview-reviewer`  
**Operating Environment:** Windows 10/11 Pro 64-bit, Python 3.11–3.13, .NET 9/10, Chromium Blink/V8  
**Audit Baseline:** Tracks 01–10 Technical Research, Forensic Audit, and Adversarial Review  

---

## 1. Executive Summary & Core Objective

The primary objective of this architecture is to evolve `desktop-webview-reviewer` from an experimental, partially-hardened script collection into:

> **A universal, production-grade desktop automation, inspection, testing, and forensic-audit platform featuring an AI-facing Model Context Protocol (MCP) control plane, backed by an out-of-process stateful daemon and an agent skill.**

The system must seamlessly bridge the deep semantic and physical divide between **Native Windows Desktop Applications** (Win32, WPF, WinUI 3, Qt) and **Embedded Webview Runtimes** (QtWebEngine, Edge WebView2, Electron, CEF) without collapsing into fragile universal abstractions or blind browser-only assumptions.

---

## 2. Evaluation of Candidate Architectures

Based on the 37 technical attack vectors and 15 failure scenarios stress-tested in `Research/10_ARCHITECTURE_ADVERSARIAL_REVIEW.md`, eight distinct architectural patterns were rigorously evaluated:

```
Candidate Architecture Comparison
┌───────────────────────────────────────┬────────────┬────────────────────────────────────────────────────────┐
│ Pattern                               │ Verdict    │ Primary Fatal Flaw / Structural Breaking Point          │
├───────────────────────────────────────┼────────────┼────────────────────────────────────────────────────────┤
│ Arch A: Pure MCP                      │ REJECT (P0)│ Motor-loop latency collapse; stdio pipe buffer deadlock│
│ Arch B: Skill + Ephemeral CLI Scripts │ REJECT (P1)│ Split state ownership; zombie processes & port locks   │
│ Arch C: MCP + Internal Monolithic Orch│ REJECT (P1)│ Giant-tool blindspot; autonomous prompt injection risk │
│ Arch D: MCP + Playwright Standalone   │ REJECT (P0)│ Total native desktop blindness; native modal deadlocks │
│ Arch E: MCP + Raw CDP                 │ REJECT (P0)│ Ghost Verification trap; blind input without physics   │
│ Arch F: MCP + Native Automation (UIA) │ REJECT (P0)│ Webviews appear as opaque black boxes; lazy a11y freeze│
│ Arch G: Universal Abstraction Layer   │ REJECT (P0)│ Lowest Common Denominator garbage; primitive mismatch  │
│ Arch H: Decoupled Dual-Perspective    │ DECIDED    │ Survives all 37 vectors under Physical Reality Primacy │
└───────────────────────────────────────┴────────────┴────────────────────────────────────────────────────────┘
```

### Detailed Rationale for Rejections

1. **Architecture A (Pure MCP - Single Server Directly Calling OS/CDP):**
   * *Fatal Defect:* Motor-loop latency collapse. Passing high-frequency tactile loops (hover, scroll settlement, frame stabilization) through turn-by-turn LLM reasoning incurs 1.5s–5.0s latency per event, burning 50k+ context tokens and causing target state to drift mid-action.
   * *Fatal Defect:* 64 KB Windows stdio pipe buffers deadlock when returning uncompressed Base64 screenshot payloads.
2. **Architecture D (MCP + Playwright Standalone):**
   * *Fatal Defect:* Playwright operates under the false axiom that *the browser window is the entire universe*. It captures images from Chromium compositor memory, returning pristine 1080p screenshots of webviews that are minimized, cloaked, or occluded by native windows.
   * *Fatal Defect:* A web action triggering a native Win32 file picker (`IFileDialog`) deadlocks Playwright permanently because it cannot inspect or interact with native OS dialogs.
3. **Architecture E (MCP + Raw CDP):**
   * *Fatal Defect:* The Ghost Verification trap. Raw CDP confirms DOM mutations and evaluates JavaScript in processes running completely headless or minimized, producing fraudulent test passes for invisible software.
4. **Architecture F (MCP + Native Automation / FlaUI Only):**
   * *Fatal Defect:* Webview black box. Modern webviews collapse into a single UIA node (`ControlType.Document` / `RootWebArea`). Forcing Chromium to expose full internal DOM through UIA via `--force-renderer-accessibility` induces massive out-of-process COM latency (3,000ms–12,000ms) and UI thread freezes.
5. **Architecture G (Universal Abstraction + Pluggable Adapters):**
   * *Fatal Defect:* Semantic Primitive Mismatch. Unifying `click`, `type`, and `focus` across native and web fails fundamentally. In web, typing emits `keydown`, `input`, and `keyup` event streams. In Win32, typing uses `WM_SETTEXT`. In UIA, typing uses `ValuePattern.SetValue()`. Modern reactive frameworks (React, Vue, Qt Quick) ignore `WM_SETTEXT` and `SetValue` because they bypass synthetic event bubbling, leaving application state corrupted.

---

## 3. The Winning Architecture: Decoupled Dual-Perspective Bridge (Architecture H)

The system accepts the fundamental truth of desktop systems: **Native Desktop Shells and Embedded Webviews are two distinct runtime planes that cannot share a single flat abstraction.**

Instead, Architecture H decouples them into two specialized, synchronized engines coordinated by an out-of-process stateful daemon:
1. **Native OS Supervisor:** Manages Win32 window handles (`HWND`), process trees via Windows Job Objects, DWM cloaking/occlusion detection, hardware screen capture (PrintWindow / Windows.Graphics.Capture), and native OS modal dialogs.
2. **Webview Automation Core:** Manages embedded webview DOMs, the composite actionability pipeline, isolated script execution realms (`__utility_world__`), and ref-based accessibility trees via CDP.
3. **Cross-Layer Reconciliation Engine:** Enforces forensic correlation (matching PIDs to debugging ports, resolving native modal dialog deadlocks, and generating tripartite verdicts).

### The Doctrine of Physical Reality Primacy
To prevent split-brain states where DOM assertions claim an element is visible while the native window is minimized, hidden, or cloaked, the architecture enforces:
$$\text{Physical Visibility (DWM / Win32)} \succ \text{Compositor State (GPU)} \succ \text{DOM State (V8 / CSSOM)}$$
A test cannot achieve a `PASS` verdict unless physical desktop visibility is mathematically and visually confirmed.

---

## 4. Language & Runtime Decision

### Evaluation Matrix

```
Language & Automation Core Evaluation
┌──────────────────────┬─────────────┬────────────┬─────────────┬─────────────────┬──────────────────────┐
│ Runtime Stack        │ Traversal   │ COM Apts   │ 64-bit FFI  │ Webview / CDP   │ Maintenance & Ecosys │
├──────────────────────┼─────────────┼────────────┼─────────────┼─────────────────┼──────────────────────┤
│ Pure Python (UIA)    │ 500–5000ms  │ Crashes    │ Pointer bug │ Native AsyncIO  │ High maintenance     │
│ Pure .NET (C#)       │ 10–50ms     │ Clean MTA  │ Type safe   │ Heavy wrappers  │ Replaces 7k loc repo │
│ Pure Rust            │ <10ms       │ Manual COM │ Complex FFI │ Low CDP support │ Extreme rewrite cost │
│ Hybrid Python + .NET │ 10–50ms     │ Isolated   │ Type safe   │ Native AsyncIO  │ Maximum reuse & speed│
└──────────────────────┴─────────────┴────────────┴─────────────┴─────────────────┴──────────────────────┘
```

### The Hybrid Boundary Decision
1. **Daemon, MCP Server, Control Plane, and Webview Core: Python 3.11+**
   * *Rationale:* Preserves ~7,000 lines of hardened forensic and detection code in `core/window_forensics.py`, `core/evidence.py`, `detectors/engine_detector.py`, and `adapters/`. Integrates natively with the official Model Context Protocol Python SDK, FastMCP, and AsyncIO event loops.
2. **Native UIA3 Semantic Automation Worker: .NET 9/10 (`FlaUI.UIA3`)**
   * *Rationale:* Eliminates fatal Python COM apartment threading deadlocks (STA vs. MTA collisions) and `comtypes` memory leaks. Provides direct access to unmanaged COM `UIAutomationCore.dll` (`IUIAutomation2` through `IUIAutomation6`) with native `CacheRequest` bulk fetching.
   * *Boundary Form:* A compiled, lightweight out-of-process worker (`DesktopBridge.UIA3.exe`) communicating with the Python Daemon via standard Windows Named Pipes or stdio JSON-RPC.

---

## 5. Architecture Decision Records (ADR Catalog)

### ADR-001: Separation of MCP Control Plane from Runtime Daemon
* **Decision:** The MCP Server and the Stateful Desktop Daemon are strictly separated. The MCP server is a thin protocol gateway translating JSON-RPC 2.0 requests to the daemon.
* **Reasoning:** Prevents desktop sessions from being destroyed when LLM MCP transport connections reset, and prevents motor-loop latency from exhausting LLM context tokens.
* **Status:** `DECIDED`

### ADR-002: Bounded MCP Toolset (10–12 Cohesive Primitives)
* **Decision:** Expose exactly 12 high-level, action-observation fused tools rather than 50+ micro-tools or a single monolithic tool.
* **Reasoning:** Chrome DevTools MCP (Track 06) proved that 57 tools cause severe cognitive degradation in models. Twelve cohesive tools maximize token efficiency while preserving turn-by-turn auditability.
* **Status:** `DECIDED`

### ADR-003: Action-Observation Fusion via Dual Returns
* **Decision:** Every mutating action tool (`desktop_click`, `desktop_type`, etc.) includes `include_snapshot: true` by default, returning the post-action accessibility tree and action receipt in a single turn.
* **Reasoning:** Cuts multi-turn agent latency by 50%, saving millions of context tokens during desktop test workflows.
* **Status:** `DECIDED`

### ADR-004: Dual-Modal Visual Artifact Architecture
* **Decision:** Immediate visual verification returns as low-resolution, downscaled thumbnails or bounded crops in tool results (`ImageContent`). Full-resolution PNG screenshots are saved to disk and referenced by immutable MCP Resource URIs (`desktop://evidence/{id}/screenshot`).
* **Reasoning:** Completely eliminates the 64 KB Windows stdio pipe buffer deadlock and context token explosion caused by multi-megabyte Base64 images.
* **Status:** `DECIDED`

### ADR-005: Synthetic Epoch-Scoped Interaction References
* **Decision:** UI elements are exposed to the AI agent as opaque, sequential alphanumeric references (`[ref=w1e4]` for webview, `[ref=n1e2]` for native), valid only for the current observation epoch.
* **Reasoning:** Replaces volatile raw pointers (`nodeId`, `HWND`, COM pointers) with stable tokens. Invalidated automatically upon navigation or DOM re-rendering, with lazy locator fallback.
* **Status:** `DECIDED`

### ADR-006: Composite Actionability Pipeline
* **Decision:** No action is dispatched until a 5-point precondition check succeeds: Attachment, Computed Visibility, Motion Stability (rAF), Enabledness, and Hit-Test Un-occlusion.
* **Reasoning:** Adopts Playwright's core reliability engine, preventing clicks from landing on empty space during CSS animations or modal loading.
* **Status:** `DECIDED`

### ADR-007: Tripartite Verdict Preservation (`PASS`, `FAIL`, `UNVERIFIED`)
* **Decision:** The three-state verdict model is strictly preserved. `PASS` requires mathematical proof of physical visibility, input delivery, and expected state. Ambiguities default to `UNVERIFIED`.
* **Reasoning:** Prevents ghost processes, minimized windows, or hijacked debugging ports from masquerading as verified desktop software.
* **Status:** `DECIDED`

### ADR-008: Resolution of the "Permanent UNVERIFIED" CLI Regression
* **Decision:** Decouple optional user confirmation and progressive proof tiers in `core/evidence.py`. Automated test runs achieve `PASS` when automated dual-perspective proofs succeed, without blocking on interactive human prompts.
* **Reasoning:** Restores the primary CLI review runner (`scripts/review.py`) to operational readiness.
* **Status:** `DECIDED`

### ADR-009: Strict Untrusted Data Boundary for UI Text
* **Decision:** All window titles, DOM text, and UIA control names are encapsulated in structured data containers and escaped. They are never merged into system instruction channels.
* **Reasoning:** Neutralizes indirect prompt injection attacks originating from untrusted web or desktop content.
* **Status:** `DECIDED`

### ADR-010: Windows Job Object Lifecycle Management
* **Decision:** All launched target application processes are assigned to a Win32 Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
* **Reasoning:** Permanently solves the orphaned subprocess leakage observed in Track 09, guaranteeing 100% clean process teardown on daemon exit.
* **Status:** `DECIDED`

---

## 6. Architecture Decisions Status Table

```
Architecture Decisions Matrix
┌─────────┬───────────────────────────────────────────┬───────────────┬────────────┬─────────────────────────────┐
│ ID      │ Topic                                     │ Decision      │ Confidence │ Revisit Condition           │
├─────────┼───────────────────────────────────────────┼───────────────┼────────────┼─────────────────────────────┤
│ DEC-001 │ System Architecture Pattern               │ Architecture H│ DECIDED    │ Cross-layer latency > 500ms │
│ DEC-002 │ Primary Control Plane Language            │ Python 3.11+  │ DECIDED    │ FastMCP / AsyncIO defect    │
│ DEC-003 │ Native UIA3 Semantic Worker               │ .NET 9 FlaUI  │ DECIDED    │ IPC Spike fails latency <50ms│
│ DEC-004 │ Win32 OS Supervision                      │ Python ctypes │ DECIDED    │ 64-bit pointer issues persist│
│ DEC-005 │ Webview Driver Protocol                   │ Direct CDP WS │ DECIDED    │ Non-Chromium webview needed │
│ DEC-006 │ MCP Tool Surface Count                    │ 12 Tools      │ DECIDED    │ Agent cognitive evaluation  │
│ DEC-007 │ Interaction Reference Format              │ Epoch Ref UID │ DECIDED    │ Cache invalidation mismatch │
│ DEC-008 │ Visual Payload Wire Format                │ Dual-Modal    │ DECIDED    │ Client lacks Resource spec  │
│ DEC-009 │ Process Lifecycle Supervision             │ Win32 Job Obj │ DECIDED    │ Privilege elevation boundary│
│ DEC-010 │ Verdict Model                             │ Tripartite    │ DECIDED    │ Industry standard mandate   │
│ DEC-011 │ UIA Worker IPC Transport                  │ Named Pipe    │ LIKELY     │ Spike 1 benchmarks          │
│ DEC-012 │ Webview Script Realm Isolation            │ Utility World │ LIKELY     │ CDP Page.createIsolatedWorld│
│ DEC-013 │ WebKit Adapter Support                    │ Prune/Delete  │ DECIDED    │ WebKit for Windows revives  │
│ DEC-014 │ CEF / Chromium Adapter Consolidation      │ Unified Blink │ DECIDED    │ Divergent CEF flags emerge  │
│ DEC-015 │ Auto-Wait Synchronization                 │ Hybrid Poll   │ DECIDED    │ rAF injection unviable      │
└─────────┴───────────────────────────────────────────┴───────────────┴────────────┴─────────────────────────────┘
```
