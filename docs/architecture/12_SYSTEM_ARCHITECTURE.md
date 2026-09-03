# Architecture Document 12: System Architecture

**Document ID:** `docs/architecture/12_SYSTEM_ARCHITECTURE.md`  
**Status:** APPROVED (Phase 0 Deliverable)  
**Author:** Principal Software Architect  
**Target Repository:** `desktop-webview-reviewer`  
**Layering Paradigm:** Decoupled Dual-Perspective Bridge (Architecture H)  

---

## 1. System Topology Overview

The architecture divides responsibilities across five distinct execution planes:
1. **Cognitive & Strategic Plane:** The Host AI Agent and the Agent Skill (`desktop-webview-reviewer`).
2. **Context & Control Plane:** The Model Context Protocol (MCP) server gateway.
3. **State & Session Plane:** The persistent, out-of-process Stateful Desktop Daemon.
4. **Execution & Driver Plane:** Dedicated Native OS and Webview automation backends.
5. **Target Application Plane:** The heterogeneous native and embedded webview desktop targets.

```mermaid
graph TB
    subgraph Cognitive ["1. Cognitive & Strategic Plane"]
        Agent["AI Host Agent (Antigravity / Claude / Cursor)"]
        Skill["Agent Skill (Heuristics, Checklists, Task.md)"]
        Agent <--> Skill
    end

    subgraph ProtocolGateway ["2. Context & Control Plane (MCP Gateway)"]
        MCP["Desktop MCP Server (JSON-RPC 2.0 over stdio/HTTP)"]
        Tools["12 Cohesive Tools"]
        Resources["State & Evidence Resources"]
        Prompts["Workflow Prompts"]
        MCP --- Tools
        MCP --- Resources
        MCP --- Prompts
    end

    subgraph StatefulDaemon ["3. State & Session Plane (Desktop Daemon)"]
        SM["Session Manager"]
        TM["Target Manager"]
        CS["Capability System"]
        OE["Observation Engine"]
        LR["Locator & Ref Registry"]
        AE["Action & Actionability Engine"]
        VE["Assertion & Verification Engine"]
        EE["Evidence & Forensic Store"]
        Sec["Security & Policy Gate"]
        Diag["Diagnostics & Trace Collector"]
    end

    subgraph ExecutionPlane ["4. Execution & Driver Plane"]
        Win32["Native OS Supervisor (Win32 / DWM / WGC)"]
        FlaUI[".NET 9 FlaUI UIA3 Bridge Worker"]
        CDP["Webview CDP Multiplexer & Utility Realm"]
    end

    subgraph TargetPlane ["5. Target Application Plane"]
        NativeShell["Native Window (HWND / WPF / WinUI / Qt)"]
        ModalDialog["Native Modal Dialog (IFileDialog / MessageBox)"]
        WebviewDOM["Embedded Webview (QtWebEngine / WebView2 / Electron)"]
    end

    Cognitive <==>|MCP Protocol Wire| ProtocolGateway
    ProtocolGateway <==>|AsyncIO Local IPC / Sockets| StatefulDaemon
    
    StatefulDaemon -->|ctypes / Win32 API| Win32
    StatefulDaemon -->|Named Pipe IPC| FlaUI
    StatefulDaemon -->|WebSocket JSON-RPC| CDP

    Win32 --> NativeShell
    Win32 --> ModalDialog
    FlaUI --> NativeShell
    FlaUI --> ModalDialog
    CDP --> WebviewDOM
```

---

## 2. Component Responsibility Matrix

### 2.1 Host AI Agent
* **Responsibility:** High-level problem decomposition, test hypothesis formulation, workflow coordination, error evaluation, and final deliverable generation.
* **What It Owns:** Goal state, turn history, conversational context, strategic planning.
* **What It Must NOT Own:** Operating system handles (`HWND`), process IDs (`PID`), raw WebSocket sockets, low-level coordinate transformations, or motor control loops.
* **Dependencies:** Model Context Protocol Client SDK.
* **Communication Boundary:** Standardized JSON-RPC 2.0 over stdio or Streamable HTTP.

### 2.2 Agent Skill (`desktop-webview-reviewer`)
* **Responsibility:** Domain-specific testing strategies, checklist management (`task.md`), heuristic recovery playbooks, application-type discovery guides (e.g., Qt vs. Electron setup).
* **What It Owns:** Procedural guidance documents, task templates, verification criteria checklists.
* **What It Must NOT Own:** Direct OS execution code, persistent session registries, socket connections.
* **Dependencies:** Host Agent file viewing capabilities.
* **Communication Boundary:** In-context markdown files and skill instruction injection.

### 2.3 MCP Control Plane (Protocol Gateway)
* **Responsibility:** Bounded protocol gateway. Deserializes tool arguments, enforces JSON Schema validation, authorizes operations through the Security Gate, formats structured output (`outputSchema`), manages progress tokens, and maps passive state to MCP Resource URIs.
* **What It Owns:** Tool definitions, Resource endpoints, Prompt templates, JSON Schema models.
* **What It Must NOT Own:** Long-lived desktop application session state, direct Win32 API bindings, raw CDP connections.
* **Dependencies:** `mcp` Python SDK, `pydantic`.
* **Communication Boundary:** Protocol wire to the client; AsyncIO IPC to the Desktop Daemon.

### 2.4 Stateful Desktop Daemon
* **Responsibility:** The centralized, out-of-process host process maintaining all active session lifecycles, target bindings, locator resolution caches, and event multiplexers across transient agent connections.
* **What It Owns:** Process lifecycles, background polling loops, session leases, target registries.
* **What It Must NOT Own:** LLM reasoning, conversational memory, user-facing prompt templates.
* **Dependencies:** Python 3.11+ `asyncio`, `multiprocessing`.
* **Communication Boundary:** AsyncIO domain socket / named pipe to MCP server; internal modules.

### 2.5 Session Manager
* **Responsibility:** Manages the lifecycle of automation sessions (`SessionId`). Enforces lease timeouts, allocates target processes, orchestrates clean shutdowns, and handles client reconnection.
* **What It Owns:** Session metadata table, session locks, heartbeat monitors.
* **What It Must NOT Own:** Low-level DOM evaluation, window rectangle geometry.
* **Dependencies:** Target Manager, Process Supervisor.
* **Communication Boundary:** Internal Daemon API.

### 2.6 Target Manager
* **Responsibility:** Detects, inventories, and maintains the authoritative mapping between Native Operating System windows (`HWND`), Process IDs (`PID`), and Webview Debugging Targets (`TargetID` / WebSocket URL).
* **What It Owns:** `TargetMap`, active target pointers, HWND-to-CDP port correlation tables.
* **What It Must NOT Own:** Element locator caching, keyboard dispatch.
* **Dependencies:** Native OS Supervisor, Webview CDP Multiplexer, Discovery Engine.
* **Communication Boundary:** Internal Daemon API.

### 2.7 Capability System
* **Responsibility:** Inspects connected targets and dynamically negotiates available feature matrices (`NATIVE_UIA3`, `WEB_CDP`, `HARDWARE_SCREENSHOT`, etc.), providing fallback guidance when specific capabilities are absent.
* **What It Owns:** Capability matrices, backend compatibility flags, degradation rules.
* **What It Must NOT Own:** Action execution, error logging.
* **Dependencies:** Native OS Supervisor, Webview CDP Multiplexer.
* **Communication Boundary:** Internal Daemon API.

### 2.8 Native Backend (Native OS Supervisor & Win32 Forensics)
* **Responsibility:** Direct interaction with the Windows desktop: top-level window discovery, z-order and bounding box verification, DWM cloaking/occlusion checks, Win32 Job Object process supervision, and hardware screen capture (`PrintWindow`, DXGI, WGC).
* **What It Owns:** Native `HWND` caches, Win32 Device Contexts (`HDC`), Job Object handles.
* **What It Must NOT Own:** Internal webview DOM nodes, CSS selectors, JavaScript execution.
* **Dependencies:** Windows User32, GDI32, DWM, Kernel32 via `ctypes`.
* **Communication Boundary:** Direct Win32 C ABI.

### 2.9 Native UIA3 Bridge Worker (.NET 9 FlaUI Sidecar)
* **Responsibility:** High-speed unmanaged COM UI Automation (UIA3) inspection and control pattern invocation (`InvokePattern`, `ValuePattern`, `SelectionItemPattern`) for native desktop controls (WPF, WinUI 3, classic Win32 dialogs).
* **What It Owns:** COM `IUIAutomation` instances, MTA thread pools, native `CacheRequest` definitions.
* **What It Must NOT Own:** Webview DOM trees, CDP sockets, MCP protocol serialization.
* **Dependencies:** .NET 9/10 Runtime, `FlaUI.Core`, `FlaUI.UIA3`.
* **Communication Boundary:** Named Pipe IPC (JSON-RPC) with the Python Daemon.

### 2.10 Web Backend (CDP Multiplexer & Utility Realm)
* **Responsibility:** Manages asynchronous WebSocket connections to Chromium DevTools Protocol endpoints. Injects isolated script realms (`__utility_world__`), evaluates expressions, captures viewport composited images, and manages network/console event listeners.
* **What It Owns:** WebSocket connection pool, CDP target sessions, injected script bundles.
* **What It Must NOT Own:** Native window occlusion detection, desktop hardware coordinate translation.
* **Dependencies:** `websockets`, `aiohttp`.
* **Communication Boundary:** WebSocket RFC 6455 over TCP.

### 2.11 Observation Engine
* **Responsibility:** Captures dual-perspective application state. Serializes webview accessibility trees into compact Markdown/YAML; serializes native UIA controls into structured nodes; generates synthetic, epoch-scoped interaction references (`[ref=w1e4]`, `[ref=n1e2]`); calculates incremental UI diffs (`kind=diff`).
* **What It Owns:** Snapshot token buffers, reference mapping dictionaries, diff engines.
* **What It Must NOT Own:** Event dispatch, disk evidence storage.
* **Dependencies:** Native OS Supervisor, Webview CDP Multiplexer, Locator Registry.
* **Communication Boundary:** Internal Daemon API.

### 2.12 Locator & Reference Registry
* **Responsibility:** Maintains the authoritative mapping between ephemeral synthetic references (`ref=w1e4`) and immutable query recipes (Locators) or live target node pointers for the active observation epoch. Re-evaluates locators dynamically if a reference expires.
* **What It Owns:** `RefTable`, `LocatorCache`, epoch version counter.
* **What It Must NOT Own:** Input hardware dispatch, screenshot capture.
* **Dependencies:** Observation Engine.
* **Communication Boundary:** Internal Daemon API.

### 2.13 Action & Actionability Engine
* **Responsibility:** Executes input actions (clicks, typing, keyboard navigation, scrolling) against resolved targets. Prior to dispatch, runs the Composite Actionability Pipeline (verifying attachment, visibility, stability, enabledness, and hit-testing un-occlusion).
* **What It Owns:** Actionability verification loops, retry backoff timers, input event builders.
* **What It Must NOT Own:** Formal verdict assignment, long-term evidence archiving.
* **Dependencies:** Locator Registry, Native Backend, Web Backend.
* **Communication Boundary:** Internal Daemon API.

### 2.14 Assertion & Verification Engine
* **Responsibility:** Implements auto-retrying synchronization assertions (e.g., waiting for text, visibility, or attributes) and evaluates overall mission integrity against the Tripartite Verdict Model (`PASS`, `FAIL`, `UNVERIFIED`).
* **What It Owns:** Assertion polling loops, verdict evaluation rules, proof check ledgers.
* **What It Must NOT Own:** Motor input generation, protocol routing.
* **Dependencies:** Actionability Engine, Evidence System.
* **Communication Boundary:** Internal Daemon API.

### 2.15 Evidence System
* **Responsibility:** Collects, verifies, hashes (SHA-256), and packages immutable forensic proof bundles (native screenshots, webview screenshots, DOM snapshots, action receipts, console/network logs, trace timelines).
* **What It Owns:** Evidence directory layouts, cryptographic manifest generators, bundle zip packagers.
* **What It Must NOT Own:** Transient memory caches, target session state.
* **Dependencies:** Native OS Supervisor, Web Backend, Filesystem.
* **Communication Boundary:** Internal Daemon API; exposes read-only MCP Resource URIs.

### 2.16 Security Layer & Policy Gate
* **Responsibility:** Enforces process execution allowlists, prevents filesystem directory traversal, validates input parameters, detects UIPI elevation barriers, and strictly isolates untrusted application UI text from model system prompts.
* **What It Owns:** Execution allowlists, path normalization rules, UIPI integrity analyzers.
* **What It Must NOT Own:** Domain automation logic.
* **Dependencies:** Windows Security APIs, Pathlib.
* **Communication Boundary:** Intercepts all incoming MCP tool calls prior to Daemon routing.

---

## 3. Core Interaction Sequence Diagrams

### 3.1 Application Launch and Dual-Perspective Attachment

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Host AI Agent
    participant MCP as MCP Control Plane
    participant Daemon as Desktop Daemon
    participant Win32 as Native OS Supervisor
    participant CDP as Web Backend (CDP)
    participant Target as Target Application

    Agent->>MCP: desktop_launch(executable_path, args, engine_hint)
    MCP->>Daemon: launch_and_attach(params)
    Daemon->>Win32: spawn_process_in_job(executable_path, args)
    Win32->>Target: CreateProcessW() + AssignProcessToJobObject()
    Target-->>Win32: Process Spawned (PID)
    
    loop Port & Window Discovery
        Win32->>Win32: poll_main_window(PID, timeout=10s)
        Win32->>Win32: verify_window_visible(HWND)
        Daemon->>CDP: discover_cdp_endpoint(PID, port_hint)
    end
    
    Win32-->>Daemon: HWND Confirmed (DWM Cloaked=False, Visible=True)
    CDP-->>Daemon: WebSocket Endpoint Bound (ws://127.0.0.1:port/devtools/page/...)
    
    Daemon->>CDP: connect_and_initialize()
    CDP->>Target: Page.enable, Runtime.enable, DOM.enable
    CDP->>Target: Page.createIsolatedWorld("__utility_world__")
    Target-->>CDP: Realm Initialized (ExecutionContextId)
    
    Daemon->>Daemon: register_session(SessionId, PID, HWND, TargetId)
    Daemon-->>MCP: LaunchReceipt (SessionId, Capabilities, InitialSnapshot)
    MCP-->>Agent: Tool Result (SessionId, Bounded A11y Tree with Refs)
```

---

### 3.2 Action-Observation Fused Turn Execution

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Host AI Agent
    participant MCP as MCP Control Plane
    participant Daemon as Desktop Daemon
    participant ActionEngine as Actionability Engine
    participant CDP as Web Backend (CDP)
    participant Target as Target DOM

    Agent->>MCP: desktop_click(session_id, ref="w1e4", include_snapshot=true)
    MCP->>Daemon: execute_click(session_id, "w1e4")
    Daemon->>Daemon: resolve_ref("w1e4") -> (TargetId, BoundingBox, NodeId)
    
    Daemon->>ActionEngine: verify_actionability(TargetId, NodeId)
    ActionEngine->>CDP: evaluate_in_utility_world(isActionableScript)
    CDP->>Target: Check attached, visible, stable rAF, unoccluded
    Target-->>CDP: Actionable = True (Center Point: x=245, y=180)
    CDP-->>ActionEngine: Ready
    
    ActionEngine->>CDP: dispatch_mouse_events(click, x=245, y=180)
    CDP->>Target: Input.dispatchMouseEvent(mousePressed, mouseReleased)
    Target-->>CDP: Events Queued in Blink
    
    Daemon->>ActionEngine: wait_for_settled(timeout=500ms)
    ActionEngine->>CDP: wait_mutation_and_raf()
    CDP-->>ActionEngine: Layout Settled
    
    Daemon->>Daemon: capture_fresh_observation(SessionId)
    Daemon->>CDP: fetch_compact_ax_tree(interesting_only=true)
    CDP-->>Daemon: Raw AX Nodes
    Daemon->>Daemon: assign_sequential_refs(epoch=2) -> [ref=w2e1, ref=w2e2...]
    
    Daemon-->>MCP: ActionReceipt(executed=true, post_snapshot=Tree, epoch=2)
    MCP-->>Agent: Tool Result (Single Turn: Confirmation + Fresh A11y Tree)
```

---

### 3.3 Native Modal Dialog Detection & Hand-Off

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Host AI Agent
    participant MCP as MCP Control Plane
    participant Daemon as Desktop Daemon
    participant CDP as Web Backend (CDP)
    participant Win32 as Native OS Supervisor
    participant FlaUI as FlaUI UIA3 Worker
    participant Dialog as Native Win32 Dialog

    Note over Agent,Dialog: Webview click triggers native Open File dialog
    CDP-->>Daemon: Renderer Thread Paused (Modal Event Pump Active)
    Daemon->>Win32: scan_for_modal_dialogs(PID)
    Win32-->>Daemon: Modal HWND Detected (Class="#32770", Text="Open File")
    
    Daemon->>Daemon: set_active_target_plane(NATIVE_MODAL)
    Daemon->>FlaUI: inspect_dialog_tree(ModalHWND)
    FlaUI->>Dialog: Walk UIA Tree (Edit control, Open button)
    FlaUI-->>Daemon: Dialog A11y Tree (EditRef="n1e1", OpenRef="n1e2")
    
    Daemon-->>MCP: Observation (Warning: Native Modal Active, Refs=Native)
    MCP-->>Agent: Action Output: Native Modal Dialog Detected (Edit="n1e1", Open="n1e2")
    
    Agent->>MCP: desktop_type(session_id, ref="n1e1", text="C:\\data\\test.csv")
    MCP->>Daemon: native_type("n1e1", "C:\\data\\test.csv")
    Daemon->>FlaUI: ValuePattern.SetValue("n1e1", path)
    FlaUI->>Dialog: Send text via UIA
    FlaUI-->>Daemon: Text Set
    
    Agent->>MCP: desktop_click(session_id, ref="n1e2")
    MCP->>Daemon: native_click("n1e2")
    Daemon->>FlaUI: InvokePattern.Invoke("n1e2")
    FlaUI->>Dialog: Click Open Button
    Dialog-->>Win32: Dialog Closed (WM_DESTROY)
    
    Win32-->>Daemon: Modal Dismissed
    Daemon->>Daemon: set_active_target_plane(WEBVIEW)
    Daemon-->>MCP: Modal Handled. Resumed Webview Context.
    MCP-->>Agent: Tool Result: File Loaded in Webview.
```

---

### 3.4 Evidence Collation & Tripartite Verdict Generation

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Host AI Agent
    participant MCP as MCP Control Plane
    participant Daemon as Desktop Daemon
    participant Win32 as Native OS Supervisor
    participant CDP as Web Backend (CDP)
    participant Evidence as Evidence Store

    Agent->>MCP: desktop_collect_evidence(session_id, test_name="anki_review")
    MCP->>Daemon: package_evidence(session_id, test_name)
    
    par Dual-Perspective Capture
        Daemon->>Win32: capture_desktop_crop(HWND)
        Win32->>Win32: PrintWindow(PW_RENDERFULLCONTENT) or WGC
        Win32-->>Daemon: Native Screen PNG Buffer (Physical Proof)
    and
        Daemon->>CDP: capture_viewport()
        CDP->>CDP: Page.captureScreenshot(format=png)
        CDP-->>Daemon: Webview Viewport PNG Buffer
    and
        Daemon->>Win32: verify_window_forensics(HWND)
        Win32-->>Daemon: Forensics (Cloaked=False, Visible=True, Rect=[100,100,1200,800])
    and
        Daemon->>CDP: fetch_runtime_logs()
        CDP-->>Daemon: Console Logs, Network Logs, Uncaught Exceptions
    end
    
    Daemon->>Evidence: compile_bundle(screenshots, forensics, logs, timeline)
    Evidence->>Evidence: generate_sha256_hashes()
    Evidence->>Evidence: write_artifacts_to_disk(evidence_dir)
    
    Daemon->>Daemon: evaluate_tripartite_verdict()
    Note over Daemon: Rules: Physical Visible AND Input Verified AND Zero Fatal Errors
    Daemon-->>Daemon: Verdict = PASS
    
    Evidence->>Evidence: finalize_manifest("evidence.json", Verdict=PASS)
    Evidence-->>Daemon: EvidenceBundle(id="ev_8731", path=..., verdict="PASS")
    
    Daemon-->>MCP: Result(verdict="PASS", summary="Verified", resource_uri="desktop://evidence/ev_8731")
    MCP-->>Agent: Tool Result: PASS (Summary + Evidence URI + Downscaled Thumbnail)
```
