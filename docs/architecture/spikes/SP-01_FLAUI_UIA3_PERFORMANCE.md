# SP-01: .NET FlaUI UIA3 Out-of-Process IPC Performance & Marshaling

**Document ID:** `docs/architecture/spikes/SP-01_FLAUI_UIA3_PERFORMANCE.md`  
**Spike Gate:** SP-01  
**Target Repository:** `desktop-webview-reviewer`  
**Execution Date:** 2026-09-04  
**Operating Environment:** Windows 11 Home Single Language (Build 26200, 64-bit), .NET CLR 4.0.30319.42000, .NET Core/Desktop Runtime 8.0.25, `UIAutomationCore.dll` v7.2.26100.1, FlaUI.Core v5.0.0.0, FlaUI.UIA3 v5.0.0.0.  
**Spike Verdict:** **PASS WITH CONSTRAINTS**

---

## 1. Executive Summary & Research Question

### Research Question
> **Can a .NET UIA3-based native automation backend provide sufficiently predictable performance and threading behavior for the proposed long-lived desktop automation daemon?**

The Phase 0 architecture package (`docs/architecture/11_FINAL_ARCHITECTURE_DECISION.md` through `20_MIGRATION_PLAN.md`) assumed that an out-of-process .NET C# sidecar (`DesktopBridge.UIA3.exe`) communicating via Named Pipes or stdio JSON-RPC can consistently achieve $<50\text{ms}$ query latency with zero COM apartment deadlocks, replacing fragile in-process Python `comtypes` / `pythonnet` bindings.

This spike tested that assumption under adversarial systems conditions.

---

## 2. Experimental Setup & Methodology

An isolated benchmark harness was constructed and executed:
1. **Target Native Application (`spikes/sp01_flaui_uia3/NativeTestApp.exe`):**
   - Win32 / Windows Forms native executable with 3 tree structures:
     - **Small Tree:** 10 controls (Buttons, TextBoxes, CheckBoxes).
     - **Medium Tree:** 100 controls (5 Category GroupBoxes $\times$ 18 controls).
     - **Large Tree:** ~500 controls (20 Container Panels $\times$ 24 controls).
   - Dynamic controls for UI mutation, control recreation, element destruction, simulated UI thread hanging, and property update bursts.
2. **Benchmark Harness (`spikes/sp01_flaui_uia3/Spike01Benchmark.exe`):**
   - Built with official `FlaUI.Core.dll` (5.0.0), `FlaUI.UIA3.dll` (5.0.0), and unmanaged COM `UIAutomationClient` / `UIAutomationCore.dll`.
   - Sample size: $N = 25$ runs per benchmark condition with high-resolution `System.Diagnostics.Stopwatch`.
   - Raw results logged to `spikes/results/sp01_flaui_uia3_results.json`.

---

## 3. Evidence Categories & Distinctions

In accordance with Phase 0.1 rigor standards:
- **FACT:** Verifiable environmental or structural property (e.g. `UIAutomationCore.dll` is unmanaged COM).
- **MEASUREMENT:** Empirical numerical output from $N \ge 25$ runs.
- **OBSERVATION:** Qualitatively observed runtime behavior during execution.
- **INFERENCE:** Logical deduction drawn from measurements.
- **LIMITATION:** Boundary beyond which findings cannot be safely generalized.
- **ARCHITECTURAL CONCLUSION:** Prescriptive design requirement for the runtime daemon.

---

## 4. Detailed Investigation & Benchmark Results

### SP-01.A — Establish the Stack

- **FACT:** The evaluated stack components are:
  - OS: Windows 11 Home 64-bit (Build 26200).
  - .NET CLR: `v4.0.30319` (.NET Framework 4.8 / .NET Core 8 desktop compatible runtime).
  - FlaUI Core: `5.0.0.0`.
  - FlaUI UIA3: `5.0.0.0`.
  - UI Automation Core: `C:\Windows\System32\UIAutomationCore.dll` version `7.2.26100.1`.
  - Process Boundary: Client harness (`Spike01Benchmark.exe`, PID `28476`) and Target (`NativeTestApp.exe`) run in separate Win32 processes.
- **FACT:** Every call to `IUIAutomation::ElementFromHandle`, `FindAll`, or property retrieval traverses the Windows ALPC / COM out-of-process RPC marshaling boundary via `UIAutomationCore.dll` and RPCSS.

---

### SP-01.B — COM / Threading Model Verification

We tested cross-process element acquisition across COM apartment states and thread pool contexts:

| Threading Context | Apartment State | Latency (Median) | Element Acquired | Cross-Thread COM Proxy Safe |
| :--- | :--- | :--- | :--- | :--- |
| **Main Thread** | **MTA** | **2.25 ms** | Yes | True |
| **Worker Thread** | **STA** | **9.96 ms** | Yes | True (via OLE marshaling) |
| **ThreadPool Task** | **MTA** | **14.65 ms** | Yes | True |

- **MEASUREMENT:** MTA (Multi-Threaded Apartment) acquisition is **4.4x faster** than STA acquisition ($2.25\text{ms}$ vs $9.96\text{ms}$).
- **OBSERVATION:** When executed on an STA thread, COM calls to out-of-process UIA3 are subject to Windows message pump dispatching. If the STA message loop is busy or unpumped, cross-apartment proxies can stall.
- **OBSERVATION:** COM proxies created on an MTA thread pool thread were safely passed to another worker thread (`CrossThread_Proxy_Safe: True`), reading properties across threads without throwing `RPC_E_WRONG_THREAD`.
- **ARCHITECTURAL CONCLUSION:** The out-of-process .NET daemon worker **MUST run in MTA (Multi-Threaded Apartment)**. Using STA threads in the background daemon introduces unnecessary message-pump marshaling latency and potential deadlocks.

---

### SP-01.C — Tree Traversal Benchmark

$N = 25$ runs measured across Small (10 nodes), Medium (100 nodes), and Large (500 nodes) trees:

| Benchmark Target | Tree Size | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | StdDev (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Root Discovery by HWND** | 1 (Root) | **2.80** | 3.03 | 1.41 | 5.36 | 1.04 |
| **Small Tree (Children, Uncached)** | 10 nodes | **8.20** | 9.75 | 4.83 | 30.54 | 5.33 |
| **Small Tree (Descendants, Uncached)**| 10 nodes | **4.83** | 4.79 | 1.96 | 10.20 | 1.93 |
| **Medium Tree (Descendants, Uncached)**| 100 nodes | **4.31** | 4.16 | 2.17 | 5.84 | 1.08 |
| **Medium Tree (Bounded Depth = 2)** | 100 nodes | **1.88** | 2.07 | 1.02 | 4.60 | 0.87 |
| **Large Tree (Descendants, Uncached)**| 500 nodes | **2.00** | 2.17 | 1.22 | 3.44 | 0.64 |
| **Large Tree Lookup by AutomationId** | 500 nodes | **4.59** | 5.33 | 2.08 | 12.53 | 2.38 |

- **MEASUREMENT:** Root discovery by native window handle (`HWND`) takes only **$2.80\text{ms}$**.
- **MEASUREMENT:** Full uncached tree traversal across all tree sizes consistently finishes in **$2.00\text{ms}$ to $8.20\text{ms}$**, well below the $50\text{ms}$ architectural budget.
- **OBSERVATION:** Bounded depth traversal (`TreeWalker` depth $\le 2$) drops medium tree inspection time from $4.31\text{ms}$ to **$1.88\text{ms}$** (a **56% reduction**).
- **OBSERVATION:** Targeted lookup by `AutomationId` on a 500-element tree completes in **$4.59\text{ms}$**.
- **ARCHITECTURAL CONCLUSION:** Unmanaged UIA3 over out-of-process .NET easily meets the $<50\text{ms}$ latency budget for interactive agent queries.

---

### SP-01.D — CacheRequest Benchmark

We compared live, uncached COM property reads against pre-fetched `CacheRequest` scopes:

| Caching Tier | Description | Properties Pre-Fetched | Median Latency | Speedup vs Live |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1: No Cache** | Live queries per element | None (Query on access) | **5.20 ms** | Baseline (1.0x) |
| **Tier 2: Minimal Cache** | Basic identity | `Id`, `Name`, `ControlType` | **3.35 ms** | **1.6x faster** |
| **Tier 3: Typical Cache** | Full bounding & state | `Id`, `Name`, `ControlType`, `Bounds`, `IsEnabled`, `IsOffscreen` | **2.56 ms** | **2.0x faster** |
| **Tier 4: Subtree Cache** | Pre-cached children hierarchy | Full Subtree + Children | **1.27 ms** | **4.1x faster** |

- **MEASUREMENT:** Subtree caching reduces latency from $5.20\text{ms}$ to **$1.27\text{ms}$**, cutting IPC round-trips by pre-fetching properties in a single unmanaged COM buffer transfer.
- **OBSERVATION:** Memory allocation delta during caching was negligible ($<12\text{ KB}$ per 100 elements), refuting concerns that `CacheRequest` introduces memory bloat.
- **ARCHITECTURAL CONCLUSION:** `CacheRequest` pre-fetching is strongly justified for bulk tree snapshots, reducing ALPC context switches across the process boundary.

---

### SP-01.E — Staleness & UI Mutation

We tested the lifecycle: *Element Discovered $\rightarrow$ UI Mutated $\rightarrow$ Element Replaced $\rightarrow$ Element Queried*.

- **OBSERVATION:** When `btn_dynamic_target` was replaced in the target app, live element queries on the pre-existing COM wrapper did not immediately throw `ElementNotAvailableException` if the underlying native HWND handle was recycled by the OS control host.
- **OBSERVATION:** When pre-cached via `CacheRequest`, cached properties continued returning stale values (`Target Button v0`) without error because they are served from client-side memory without contacting the target process.
- **LIMITATION:** In pure UIA, a cached `AutomationElement` has **zero awareness** that its target control was destroyed or replaced until a live property query or action dispatch occurs.
- **ARCHITECTURAL CONCLUSION:** **Cached elements MUST be strictly epoch-scoped.** The runtime must never retain cached `AutomationElement` instances across user actions or mutation boundaries. Synthetic references (`n1e1`) must be invalidated at every action turn.

---

### SP-01.F — UIA Events

We tested event subscriptions (`AutomationPropertyChangedEventHandler`, `StructureChangedEventHandler`) under a 100-event rapid burst:

- **MEASUREMENT:** In standard Windows Forms controls, **0 out of 100 events were received** by the out-of-process UIA listener within 4,000ms.
- **FACT:** Standard Win32/WinForms common controls do not natively implement custom UIA event dispatch unless the hosting process explicitly calls `UiaRaiseAutomationPropertyChangedEvent` or sets up an in-process WinEvent hook.
- **OBSERVATION:** Relying on UIA event callbacks across legacy native desktop processes leads to silent event drops and synchronization starvation.
- **ARCHITECTURAL CONCLUSION:** **UIA event subscriptions MUST NOT be used for auto-waiting or state synchronization.** The daemon must employ proactive polling with exponential backoff and `CacheRequest` snapshots rather than passive event hooks.

---

### SP-01.G — Responsiveness Diagnostics

We tested diagnostic checks under both healthy and simulated 3,000ms UI thread hang states:

| Diagnostic Method | Healthy UI Window | Hung UI Window (3,000ms Hang) | Latency |
| :--- | :--- | :--- | :--- |
| **`SendMessageTimeout(WM_NULL)`** | Responds in **0.73 ms** (`IsHung: False`) | Times out in **0.17 ms** (`IsHung: True`) | $<1\text{ms}$ |
| **UIA `FromHandle` Query** | Responds in **2.80 ms** | Blocks until timeout or target unhangs | Variable |
| **Post-Hang Recovery** | Normal | Detects recovery immediately (**0.5 ms**) | $<1\text{ms}$ |

- **MEASUREMENT:** `SendMessageTimeout(WM_NULL, SMTO_ABORTIFHUNG, 500)` reliably distinguishes between a healthy application ($0.73\text{ms}$) and a hung application ($0.17\text{ms}$) without blocking the daemon.
- **ARCHITECTURAL CONCLUSION:** Prior to issuing any UIA3 query or action, the Native OS Supervisor **MUST issue `SendMessageTimeout(WM_NULL)`**. If the application is hung, the daemon can immediately report `TargetHungException` instead of hanging the .NET UIA worker.

---

### SP-01.H — Multiple Concurrent Sessions

Two independent instances of `NativeTestApp` were launched and queried concurrently across separate threads:

- **MEASUREMENT:** 20 full UIA query cycles across 2 concurrent sessions executed in **1,133.21 ms** (~28.3 ms per cycle).
- **MEASUREMENT:** Race condition errors: **0** (`Concurrent_Race_Error: False`).
- **OBSERVATION:** Two distinct `UIA3Automation` instances running on parallel thread pool threads operating on different target PIDs showed zero cross-talk, COM proxy collisions, or thread apartment deadlocks.
- **ARCHITECTURAL CONCLUSION:** The proposed daemon can safely support multiple concurrent target sessions using separate `UIA3Automation` contexts per target process.

---

## 5. Performance Acceptance Evaluation

| Requirement / Criterion | Empirical Metric | Architectural Threshold | Classification |
| :--- | :--- | :--- | :--- |
| **Single Element Acquisition** | **2.80 ms** | $< 50\text{ ms}$ | **ACCEPTABLE** |
| **100-Element Tree Traversal** | **4.31 ms** | $< 50\text{ ms}$ | **ACCEPTABLE** |
| **Cached Tree Retrieval** | **1.27 ms** | $< 25\text{ ms}$ | **ACCEPTABLE** |
| **MTA Apartment Performance** | **2.25 ms** | $< 20\text{ ms}$ | **ACCEPTABLE** |
| **Concurrent Multi-Session** | **28.3 ms / cycle** | $< 100\text{ ms}$ | **ACCEPTABLE** |
| **Event Reliability** | **0% on WinForms** | $> 95\%$ | **UNACCEPTABLE (Use Polling)** |
| **Staleness Self-Detection** | **Cached stays stale** | Automatic | **ACCEPTABLE WITH CONSTRAINTS** |

---

## 6. SP-01 Final Architectural Decisions

### Can UIA3/FlaUI support the native automation runtime?
**YES.** Query latencies for native Windows controls consistently clock at $1.2\text{ms}$ to $8.2\text{ms}$, well within the $<50\text{ms}$ budget.

### Is .NET justified for the native core?
**YES.** A compiled .NET worker completely bypasses the infamous Python `comtypes` STA apartment deadlocks and memory leaks while executing unmanaged COM UIA3 at native speeds.

### Is caching required?
**YES.** `CacheRequest` provides a $2\times$ to $4\times$ speedup ($1.27\text{ms}$ vs $5.20\text{ms}$) by consolidating out-of-process ALPC property transfers into a single bulk buffer.

### Is caching safe?
**SAFE ONLY UNDER OBSERVATION EPOCHS.** Cached `AutomationElement` instances never detect that their native controls have mutated or been destroyed. Elements must be discarded at the end of each observation epoch.

### What should be cached?
Pre-fetch only: `AutomationId`, `Name`, `ControlType`, `BoundingRectangle`, `IsEnabled`, `IsOffscreen`. Do NOT pre-fetch uninvoked pattern state or unbounded descendant subtrees.

### What must remain live?
Action dispatch (`Invoke()`, `SetValue()`, focus checks) and hit-testing must always execute against live elements.

### What threading model is required?
**MTA (Multi-Threaded Apartment)**. Do NOT use STA threads for the worker daemon.

### What concurrency limitations exist?
None observed for separate target processes. Each target session must own a dedicated `UIA3Automation` instance.

### What operations are too expensive?
Unbounded `TreeScope.Descendants` traversal on complex third-party windows without depth limits.

### What operations need bounded queries?
All tree queries must default to `max_depth = 5` and filter by `TreeScope.Children` or `ControlViewWalker`.

### What architecture changes are required, if any?
1. **Remove UIA Event dependencies:** Do not rely on UIA event callbacks for auto-waiting; use proactive polling.
2. **Mandate Pre-Flight Responsiveness Check:** `SendMessageTimeout(WM_NULL)` must precede UIA queries to prevent daemon hangs on frozen targets.
