# Track 07: MCP Architecture Deep Research

## What Should Actually Be an MCP Tool, Resource, Prompt, or Something Else?

The complete architectural research deliverable has been compiled and exported as [07_MCP_ARCHITECTURE_DEEP_RESEARCH.md](https://docs.google.com/document/d/1x8pE-Gfi5jX4PzWpeS8Hbhqj6n4jvaYHnndSSEemroU/edit?usp=drivesdk&ouid=100150596005450321153).

This investigation was conducted across primary sources, including the normative [Model Context Protocol Specification](https://modelcontextprotocol.io/specification) (`2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`, and `2026-07-28`), official protocol schemas, and official SDK architectures ([MCP Architecture Overview](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture)).

---

### Core Architectural Finding

**MCP is architecturally designed as a Context and Control Plane, NOT as a universal execution engine, data plane, or operating system abstraction layer.**

Attempting to project every low-level OS API, Win32 handle, hardware mouse/keyboard event, or CDP command into an individual MCP tool creates an unmanageable context footprint, induces cognitive degradation in LLMs, and introduces severe security hazards. Conversely, concealing all capabilities behind an opaque monolithic tool (e.g., `execute_desktop_task`) destroys turn-by-turn auditability, prevents model-guided verification, and invalidates MCP’s granular safety model.

The optimal architecture establishes four decoupled layers:

1. **The Cognitive & Strategic Plane (Host Agent & Skills)**: Governs intent decomposition, multi-turn testing strategies, hypothesis generation, and error-recovery checklists.
2. **The Context & Control Plane (MCP Interface)**: Exposes a standardized, ergonomically bounded set of **Tools** (for model actions and structured queries), **Resources & Resource Templates** (for passive state inspection and durable forensic evidence), **Prompts** (for user-initiated entry points), and **Sampling** (sparingly, for localized semantic translation).
3. **The State & Session Plane (Desktop Automation Daemon)**: Manages independent application lifecycles, PID/HWND tracking, locator caches, and CDP connection pools decoupled from transient MCP transport sessions.
4. **The Execution & Data Plane (Automation Backends)**: Houses native C++/COM/ctypes drivers (UIA, Qt AT-SPI, CDP, OS Event Taps), low-level mouse trajectory interpolation, and heavy ETW/video trace buffers, entirely isolated from the protocol wire.

```
[1. AI Host Agent (Orchestrator)]
      | (Autonomous Task Decomposition, Verification, State Tracking)
      v
[2. Agent Skill (Strategy Layer: desktop-webview-reviewer)]
      | (Domain-Specific Heuristics, Task Checklists task.md, Recovery Rules)
      v
[3. MCP Client (Host Security & Protocol Engine)]
      | (Authorization Policy, Tool Approval Gates, Sampling & Token Budgeting)
      v
========================== PROTOCOL BOUNDARY ==========================
   (JSON-RPC 2.0 over stdio [Local] or Streamable HTTP [Remote])
=======================================================================
      v
[4. Desktop MCP Server (Control & Observability Plane)]
      | (Translates Tools -> Commands, Resources -> State URIs, Emits Progress)
      v
[5. Session & Target Manager Layer]
      | (Session GUIDs, HWND / Target Caches, Locator Resolvers, Evidence Store)
      v
======================== OS / PROCESS BOUNDARY ========================
   (Direct COM / Win32 / UIA / C++ / CDP WebSocket IPC)
=======================================================================
      v
[6. Automation & Inspection Runtime]
      | (Windows UIA Engine, Qt Accessibility Driver, Chrome DevTools Protocol)
      v
[7. Target Application & OS Subsystems]
      (Native Windows, Qt GUI, Electron WebViews, Display & Event Subsystems)

```

---

### Comprehensive Primitive Classification Matrix

| Subsystem / Capability | Assigned Layer | Primary MCP Primitive | Why? | State Mutation | Protocol Integrity Tag |
| --- | --- | --- | --- | --- | --- |
| **Desktop Connection** | Context / Control | **Tool** (`connect_desktop`) | Allocates session state and parameters. | Mutating | `[Protocol Fact]` |
| **Desktop Disconnection** | Context / Control | **Tool** (`disconnect_desktop`) | Releases session handles and closes debug ports. | Mutating | `[Protocol Fact]` |
| **Application Launch** | Context / Control | **Tool** (`launch_application`) | Spawns external OS process (high consequence). | **Destructive** | `[Protocol Fact]` |
| **Window Discovery** | Observability | **Resource** (`desktop://windows`) | Passive inventory of visible surfaces. | None | `[Protocol Fact]` |
| **Window Inspection** | Context / Control | **Tool** (`inspect_window`) | Parameterized metadata & bounds query. | None (Read-only) | `[Protocol Fact]` |
| **UI Hierarchy Tree** | Observability | **Resource** (`desktop://windows/{id}/tree`) | Read-only structural application state. | None | `[Official Design Intent]` |
| **Accessibility Tree** | Observability | **Resource** (`desktop://windows/{id}/a11y`) | Specialized WCAG / AT-SPI node tree. | None | `[Official Design Intent]` |
| **Element Search** | Context / Control | **Tool** (`find_elements`) | Requires complex dynamic search expressions. | None (Read-only) | `[Official Design Intent]` |
| **Click / Tap** | Control Plane | **Tool** (`click_element`) | Mutates UI focus and event queue. | **Mutating** | `[Protocol Fact]` |
| **Type Text** | Control Plane | **Tool** (`type_into_element`) | Injects text into target control buffer. | **Mutating** | `[Protocol Fact]` |
| **Key Press** | Control Plane | **Tool** (`send_keys`) | Injects navigation/action keys (Enter, Tab). | **Mutating** | `[Protocol Fact]` |
| **Drag & Drop** | Control Plane | **Tool** (`drag_element`) | Multi-point coordinate gesture. | **Mutating** | `[Protocol Fact]` |
| **Hardware Mouse Move** | Execution Plane | **Non-MCP Internal** | Micro-actions flood context; encapsulate in driver. | None | `[ASSUMPTION INVALIDATED]` |
| **Screenshot (Turn)** | Perception | **Tool** (`capture_screenshot`) | Ephemeral visual verification for model turn. | None (Read-only) | `[Protocol Fact]` |
| **Screenshot (Audit)** | Observability | **Resource** (`desktop://evidence/{id}/img`) | Heavy binary file; preserves context tokens. | None | `[Strong Inference]` |
| **Console Logs** | Observability | **Resource** (`desktop://targets/{id}/console`) | Passive ring buffer of stdout/stderr. | None | `[Official Design Intent]` |
| **Network Logs** | Observability | **Resource** (`desktop://targets/{id}/network`) | Passive ring buffer of HTTP/WS traffic. | None | `[Official Design Intent]` |
| **Performance Trace** | Control / Obs | **Tool** (`record_trace`) + **Resource** | Mutating action to record; Resource for URI. | Mutating | `[Strong Inference]` |
| **State Assertions** | Audit Plane | **Tool** (`assert_ui_state`) | Verification action logging formal pass/fail. | Mutating (Audit) | `[Strong Inference]` |
| **Accessibility Audit** | Control Plane | **Tool** (`audit_accessibility`) | Long-running engine using `progressToken`. | None (Read-only) | `[Protocol Fact]` |
| **Smoke Test Suite** | Control Plane | **Tool** (`run_smoke_test`) | Long-running test runner with progress stream. | **High Mutation** | `[Protocol Fact]` |
| **Process Logs** | Observability | **Resource** (`desktop://processes/{pid}/logs`) | File/pipe log access. | None | `[Protocol Fact]` |
| **Forensic Evidence** | Audit Plane | **Resource** (`desktop://evidence/{id}`) | Immutable, addressable audit artifact. | None | `[Protocol Fact]` |
| **Audit Slash Command** | User Interface | **MCP Prompt** (`/audit-application`) | User entry point seeding conversation. | None | `[Official Design Intent]` |
| **Debug Crash Command** | User Interface | **MCP Prompt** (`/debug-crash`) | User entry point injecting crash dumps. | None | `[Official Design Intent]` |
| **Autonomous Review** | Cognitive Plane | **Agent Skill** (`desktop-reviewer`) | Multi-turn planning, verification & recovery. | Cognitive Loop | `[ASSUMPTION INVALIDATED]` |
| **Desktop Session State** | State Plane | **Non-MCP Daemon** | Decoupled from transient transport lifecycles. | Persistent | `[ASSUMPTION INVALIDATED]` |
| **Win32 / COM Internals** | Execution Plane | **Non-MCP Internal** | Unsafe; prone to model hallucination. | None | `[ASSUMPTION INVALIDATED]` |
| **CDP Wire Protocols** | Execution Plane | **Non-MCP Internal** | Abstracted into clean semantic tools. | None | `[Strong Inference]` |

---

### Key Architectural Decision Records (ADRs)

* **ADR-01 (Tool vs Resource)**: Operations mutating system state or requiring complex search filters are **MCP Tools** ([MCP Tools Spec](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)). Passive application hierarchies, continuous log streams, and historic forensic evidence are **MCP Resources** ([MCP Resources Spec](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)).
* **ADR-02 (Tool vs Prompt)**: High-level workflows are exposed as user-facing **MCP Prompts** (`/audit-accessibility`), while operational execution steps remain granular **MCP Tools**.
* **ADR-03 (Agent Skill vs MCP Prompt)**: Agent Skills maintain autonomous multi-turn reasoning, plan tracking (`task.md`), and error recovery. MCP Prompts serve solely as stateless user entry points.
* **ADR-04 (MCP Session vs Desktop Session)**: Desktop automation sessions must exist independently in a background daemon, decoupled from the ephemeral MCP transport session.
* **ADR-05 (Structured Output vs Text Blobs)**: Diagnostic and assertion tools must return machine-validated `structuredContent` conforming to JSON Schema `outputSchema`, supplemented by a concise human-readable summary.
* **ADR-06 (Dual-Modal Screenshot Architecture)**: Ephemeral screenshots for immediate turn observation are returned directly in Tool results (`ImageContent`). Heavy visual diffs and historical records are saved to disk and referenced by Resource URIs.
* **ADR-07 (Universal Core with Extensions)**: Expose a single, universal core toolset across all desktop backends (Win32, UIA, Qt, Electron), supplemented by target capability inspection rather than backend-specific tool variants.
* **ADR-08 (Control Plane vs Execution Plane)**: The MCP server acts strictly as a protocol translation and security gateway. OS hook injection, ctypes wrappers, and CDP socket management reside in a dedicated automation runtime library.
* **ADR-09 (Restricted Server-Side Sampling)**: Forbid recursive server-side agentic loops via Sampling ([MCP Sampling Spec](https://modelcontextprotocol.io/specification/2026-07-28/client/sampling)). Restrict Sampling strictly to localized, non-mutating semantic disambiguation (e.g., heuristic locator repair).
* **ADR-10 (Transport Selection)**: Standardize on `stdio` for local single-user desktop inspection. Standardize on `Streamable HTTP` ([MCP Transports Spec](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)) for virtualized cloud grids and remote test runners.

---

### Final Verdict: Answers to the 25 Architectural Questions

1. **What is the actual architectural purpose of MCP?**
`[Protocol Fact]` & `[Official Design Intent]` A standardized protocol establishing context and control boundaries between LLMs and external systems, abstracting data discovery (Resources), parameterized user workflows (Prompts), and intentional actions (Tools).
2. **What exactly is a Tool?**
`[Protocol Fact]` A model-controlled, callable operation accepting structured arguments, performing computation or mutates external system state, and returning structured or multimodal results.
3. **What exactly is a Resource?**
`[Protocol Fact]` An application-controlled, URI-addressable data node representing read-only context (text or binary), providing passive grounding data without side effects.
4. **What exactly is a Prompt?**
`[Protocol Fact]` A user-controlled, reusable interaction template exposed to the Host UI to parameterize slash-commands and seed conversation context.
5. **What exactly is Sampling?**
`[Protocol Fact]` A server-initiated request for model inference (`sampling/createMessage`), allowing an MCP server to delegate bounded natural-language reasoning back to the Host's LLM under client security and budget governance.
6. **When should desktop state be a Resource rather than Tool output?**
`[Strong Inference]` When it represents passive, continuously available, or immutable topography (active window list, UI hierarchy, log buffers, historical evidence). It is a Tool output only when state is the immediate, ephemeral consequence of a parameterized action.
7. **When should an operation be a Tool rather than a Prompt?**
`[Strong Inference]` When it is invoked autonomously by the model to take action, query data, or mutate state. It is a Prompt when it serves as a human-facing entry point in the Host UI.
8. **Where does an Agent Skill fit relative to MCP Prompts?**
`[Strong Inference]` The Agent Skill lives in the Host Agent's cognitive layer, driving multi-turn strategy, planning, and recovery. The MCP Prompt lives in the Server, serving as a lightweight template that the user selects to initiate a workflow.
9. **Where should desktop session state live?**
`[Researcher Hypothesis]` In an independent Desktop Automation Daemon, completely decoupled from transient MCP transport connections.
10. **What belongs inside the MCP server?**
`[Researcher Hypothesis]` Protocol serialization/deserialization, capability negotiation, JSON Schema validation, tool/resource routing, session handle resolution, and translation to the internal runtime.
11. **What belongs inside backend automation libraries?**
`[Researcher Hypothesis]` Low-level OS APIs (Win32, UIA, COM), accessibility tree scrapers, CDP WebSocket dispatchers, virtual input injectors, window clipping calculations, and process monitors.
12. **What should never be exposed as an MCP Tool?**
`[Strong Inference]` Raw Win32 API functions (`SendMessage`, `VirtualAlloc`), low-level mouse hardware events (`mouse_down`, `mouse_up`), raw CDP protocol methods (`Page.enable`), unbounded shell commands, and pointer manipulation.
13. **How should screenshots be represented?**
`[Protocol Fact]` & `[Strong Inference]` Immediate visual verification returns as Tool results using `ImageContent` (base64 PNG). Audit-grade visual diffs and historical records are saved to disk and exposed as Resources via URI (`desktop://evidence/{id}/screenshot.png`).
14. **How should evidence artifacts be represented?**
`[Protocol Fact]` As MCP Resources identified by immutable, canonical URIs under `desktop://evidence/`.
15. **How should long-running audits work?**
`[Protocol Fact]` As Tools utilizing `_meta.progressToken` to stream `notifications/progress` updates, with support for cancellation via `notifications/cancelled`.
16. **How should capability negotiation work across Win32/UIA/CDP/Qt/WebView backends?**
`[Researcher Hypothesis]` The server advertises a universal core toolset during `initialize`, and dynamically exposes target-specific capabilities via a structured metadata Resource (`desktop://windows/{id}/info`).
17. **Should we expose a universal desktop abstraction or backend-specific capabilities?**
`[Strong Inference]` Expose a Universal Core Abstraction (`click_element`, `inspect_window`) for standard operations, supplemented by modular extension tools validated against target capability flags.
18. **When is Sampling actually useful?**
`[Official Design Intent]` & `[Strong Inference]` For isolated, server-side semantic tasks: recovering from broken locators, disambiguating unstructured accessibility labels, or classifying unexpected error dialogs.
19. **Should our server ever initiate model reasoning?**
`[Strong Inference]` Yes, but only via Sampling for bounded, localized sub-tasks. The server must never run autonomous agentic loops that bypass Host visibility.
20. **What security boundaries are required?**
`[Strong Inference]` Client-enforced tool authorization dialogs, window-scoped visual capture, strict path allowlisting for process launches, and sandbox containment of target execution environments.
21. **What transport model best fits local desktop automation?**
`[Protocol Fact]` **stdio**. Direct process inheritance, zero network latency, zero port exposure, and automatic lifecycle containment.
22. **What transport model fits remote desktop automation?**
`[Protocol Fact]` **Streamable HTTP** (over HTTPS). Multi-client multiplexing, session resumption via headers, SSE streaming, and OAuth 2.1 bearer authentication.
23. **What does MCP give us that a normal JSON-RPC API would not?**
`[Protocol Fact]` & `[Official Design Intent]` A standardized semantic contract recognized by major LLM hosts: standardized capability negotiation, automatic schema-to-model translation, unified resource discovery and subscriptions, progress tracking, cancellation signals, tool safety annotations, and vendor-neutral client interoperability.
24. **What should MCP NOT be responsible for?**
`[Official Design Intent]` It is not an operating system abstraction layer, not an automation driver, not a test execution harness, and not an autonomous planning framework.
25. **What does this research fundamentally change about our proposed architecture?**
`[ASSUMPTION INVALIDATED]` It invalidates the premise that *every desktop action, inspection, and log stream should be an individual MCP Tool*. The future architecture must be a **Layered Hybrid**: an autonomous Host Skill driving a lean, semantic MCP Control and Observability Plane backed by an independent Desktop Automation Runtime.

---

### Deliverable Document

The complete research document is available at [07_MCP_ARCHITECTURE_DEEP_RESEARCH.md](https://docs.google.com/document/d/1x8pE-Gfi5jX4PzWpeS8Hbhqj6n4jvaYHnndSSEemroU/edit?usp=drivesdk&ouid=100150596005450321153), structured across all 75 analytical sections with full JSON schemas, sequence diagrams, and security evaluation matrices.