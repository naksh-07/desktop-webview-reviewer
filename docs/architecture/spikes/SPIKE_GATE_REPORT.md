# Phase 0.1 Architecture Spike Gate Report

**Document ID:** `docs/architecture/spikes/SPIKE_GATE_REPORT.md`  
**Phase:** Phase 0.1 Final Gate Report  
**Date:** 2026-09-04  
**Status:** **CLOSED / VERIFIED**  
**Final Production Readiness Decision:** **READY FOR PHASE 1 IMPLEMENTATION**

---

## 1. Executive Summary

In Phase 0, the architecture evaluation established the **Decoupled Dual-Perspective Bridge (Architecture H)** as the optimal target design. However, the architecture gate rendered a provisional verdict:

```text
PROVISIONAL VERDICT (Phase 0):
NOT READY — ARCHITECTURE SPIKES REQUIRED
```

Three mandatory architecture spikes were commissioned to empirically prove or disprove foundational systems assumptions under adversarial Windows conditions before authoring production code:
- **SP-01:** .NET FlaUI UIA3 Out-of-Process IPC Performance & Marshaling
- **SP-02:** Chromium Lazy Accessibility Tree Freeze Mitigation
- **SP-03:** Per-Monitor V2 Fractional DPI Coordinate Translation

All three spikes have now been **fully executed, empirically measured, and documented** with concrete JSON evidence artifacts and comprehensive technical reports.

---

## 2. Gate Verification & Deliverable Checklist

| Gate Deliverable | Associated Artifacts | Status | Empirical Verdict |
| :--- | :--- | :--- | :--- |
| **SP-01 Benchmark & Document** | `spikes/results/sp01_flaui_uia3_results.json`<br>`docs/architecture/spikes/SP-01_FLAUI_UIA3_PERFORMANCE.md` | **COMPLETE** | **PASS WITH CONSTRAINTS** |
| **SP-02 Benchmark & Document** | `spikes/results/sp02_chromium_a11y_results.json`<br>`docs/architecture/spikes/SP-02_CHROMIUM_ACCESSIBILITY_FREEZE.md` | **COMPLETE** | **PASS WITH CONSTRAINTS** |
| **SP-03 Benchmark & Document** | `spikes/results/sp03_dpi_coordinate_results.json`<br>`docs/architecture/spikes/SP-03_DPI_COORDINATE_TRANSLATION.md` | **COMPLETE** | **PASS WITH CONSTRAINTS** |
| **Cross-Spike Analysis** | `docs/architecture/spikes/SPIKE_CROSS_ANALYSIS.md` | **COMPLETE** | **CONSTRAINTS INCORPORATED** |
| **Gate Report & Readiness Decision**| `docs/architecture/spikes/SPIKE_GATE_REPORT.md` | **COMPLETE** | **READY FOR PHASE 1** |
| **Production Code Hygiene** | `git status` check (Zero production files modified) | **VERIFIED** | **CLEAN** |

---

## 3. Spike Summary & Empirical Findings

### SP-01: .NET FlaUI UIA3 Out-of-Process IPC Performance & Marshaling
- **Hypothesis:** An out-of-process .NET C# worker querying unmanaged UIA3 COM can maintain $<50\text{ms}$ query latency across small, medium, and large control trees without COM apartment deadlocks.
- **Empirical Findings:**
  - Root discovery by HWND: **$2.80\text{ ms}$**.
  - 100-element medium tree traversal: **$4.31\text{ ms}$**; with bounded depth: **$1.88\text{ ms}$**.
  - `CacheRequest` pre-fetching drops query latency to **$1.27\text{ ms}$** (a **$4.1\times$ speedup**).
  - Multi-Threaded Apartment (MTA) is **$4.4\times$ faster** than STA ($2.25\text{ms}$ vs $9.96\text{ms}$).
  - Two concurrent sessions executed in parallel with zero race condition errors.
  - Standard WinForms controls dropped 100% of UIA events; proactive polling is required.
  - UI thread unresponsiveness is detected in $<1\text{ms}$ via `SendMessageTimeout(WM_NULL)`.
- **Verdict:** **PASS WITH CONSTRAINTS** (Constraints: Run worker in MTA; use polling instead of UIA events; mandate pre-flight `SendMessageTimeout`).

---

### SP-02: Chromium Lazy Accessibility Tree Freeze Mitigation
- **Hypothesis:** Chromium lazy accessibility tree initialization can be cleanly primed and monitored via CDP without freezing or desynchronizing from DOM mutations.
- **Empirical Findings:**
  - Querying via native Windows UIA black-boxes the webview (only 1 generic container node exposed in Anki QtWebEngine), and forcing full UIA tree creation causes UI thread freezing.
  - In contrast, querying via direct CDP `Accessibility.getFullAXTree` executes in **$1.66\text{ ms} - 3.50\text{ ms}$** (Chrome) and **$40.48\text{ ms}$** (Anki QtWebEngine).
  - Calling `Accessibility.enable` primes the subsystem in only **$0.70\text{ ms}$**.
  - Rapid bursts of 50 and 150 DOM mutations showed **$0\text{ ms}$ lag**; the AX tree reflected all 485 nodes immediately upon query.
  - Page navigation strictly invalidates DOM `nodeId` and `backendDOMNodeId`, throwing `Cannot find node with given id`.
  - Top-level AXTree does not inline `<iframe>` children; explicit frame piercing is required.
  - A lightweight signature detector ($\text{Ratio} = \text{AX Nodes} / \text{DOM Elements}$) reliably detects tree freeze.
- **Verdict:** **PASS WITH CONSTRAINTS** (Constraints: Automate webviews exclusively via direct CDP; enforce epoch-scoped references; implement frame piercing for iframes).

---

### SP-03: Per-Monitor V2 Fractional DPI Coordinate Translation
- **Hypothesis:** Coordinate translation between webview CSS, native client pixels, physical screen pixels, and normalized `SendInput` coordinates can be made deterministic under fractional DPI scaling.
- **Empirical Findings:**
  - Under `PER_MONITOR_DPI_AWARE_V2`, physical display resolution ($1920\times 1080$ at 144 DPI / 150% scaling) is accurately reported without Windows virtualization blur.
  - Windows 11 DWM adds a **$9\text{-pixel}$ invisible drop-shadow margin** to native windows. Using raw `GetWindowRect` introduces a $9\text{px}$ offset error; `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` provides true physical coordinates.
  - Fractional scaling introduces at most **$0.40\text{ px}$** logical rounding error, while standard interactive targets ($24\times 24\text{ px}$) provide a $\pm 12\text{ px}$ tolerance buffer.
  - Normalized `SendInput` coordinate mapping ($0..65535$) achieved **$0.0\text{ px}$ physical delta**.
- **Verdict:** **PASS WITH CONSTRAINTS** (Constraints: Enforce `PER_MONITOR_DPI_AWARE_V2`; use `DWMWA_EXTENDED_FRAME_BOUNDS`; always target affordance center points).

---

## 4. Architectural Refinements Incorporated for Phase 1

The following updates must be integrated into Phase 1 specifications:
1. **Sidecar Communication:** The .NET native bridge (`DesktopBridge.UIA3.exe`) must run in MTA mode and communicate with the Python daemon via Named Pipe JSON-RPC.
2. **Synchronization Architecture:** Replace any conceptual UIA event subscriptions with proactive polling using exponential backoff and cached snapshots.
3. **Pre-Flight Health Gate:** The Native OS Supervisor must execute `SendMessageTimeout(WM_NULL, SMTO_ABORTIFHUNG, 500)` before dispatching native UIA queries to avoid blocking on hung applications.
4. **Window Boundary Authority:** All native window bounds and screenshot crop rectangles must be calculated exclusively using `DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS)`.
5. **Centralized Coordinate Subsystem:** Implement `runtime/coordinate_transform.py` to own all DPR, client-to-screen, and `SendInput` normalized transformations.
6. **Iframe Piercing Engine:** The webview observation pipeline must use CDP target auto-attachment (`Target.setAutoAttach`) to crawl embedded subframes.
7. **Strict Epoch Invalidation:** Invalidate all synthetic references (`[ref=w1e1]`, `[ref=n1e1]`) upon page navigation or UI mutation.

---

## 5. Production Readiness Decision

Having verified all empirical benchmarks, documented all findings, logged JSON artifacts, and identified precise architectural constraints with zero regression to existing code:

```text
================================================================================
FINAL ARCHITECTURE SPIKE GATE DECISION:
READY FOR PHASE 1 IMPLEMENTATION
================================================================================
```

The system architecture is grounded in physical reality and backed by empirical evidence. The repository is cleared to proceed to **Phase 1: Foundation & Infrastructure**.
