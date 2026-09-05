# Architecture Document 21: Agent Sovereignty, Capability Architecture & Boundary Specifications

**Document ID:** `docs/architecture/21_AGENT_SOVEREIGNTY_AND_BOUNDARIES.md`  
**Status:** APPROVED (Phase 9 Milestone)  
**Author:** Principal System Architect & Antigravity Lead  
**Target Repository:** `desktop-webview-reviewer`  
**Applies To:** Desktop WebView Reviewer 2.0, Antigravity IDE, TeamPreview, Adaptive Orchestrator  
**Baseline:** Architecture H Foundation (Docs 11–20, Phase 0–8 Implementation)

---

## 1. The North Star

The long-term vision of Desktop WebView Reviewer 2.0 is:

> **An Antigravity-first, agent-controlled desktop capability and forensic-testing layer that provides eyes, hands, sensors, diagnostics and evidence for real Windows applications.**

Reviewer is **not** a general autonomous testing bot that wanders aimlessly across the operating system. It is **not** an independent mission authority. It is the sensory and motor cortex through which high-order AI reasoning agents perceive, manipulate, and authoritatively verify physical desktop reality.

---

## 2. The Constitutional Sovereignty Boundary

The foundation of the 2.0 architecture rests upon a strict constitutional division of responsibility:

```
┌─────────────────────────────────────────────────────────────┐
│                 MISSION AUTHORITY (WHAT & WHY)              │
│       Antigravity / TeamPreview / Adaptive Orchestrator     │
│                                                             │
│  - Decides user intent & target application                 │
│  - Decides which business workflow to exercise              │
│  - Decides acceptance criteria & domain significance        │
│  - Owns task planning, prioritization, and trade-offs       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                High-Level Delegated Directives
                (via MCP & Agent Skill Policy)
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               CAPABILITY LAYER (HOW & VERIFY)               │
│                  Desktop WebView Reviewer 2.0               │
│                                                             │
│  - Decides how to safely inspect the target window/webview  │
│  - Decides observation plane (Native, WebView, Visual)      │
│  - Decides coordinate transforms and DPI scale handling     │
│  - Decides pre-action actionability & settlement delays     │
│  - Decides physical vs DOM reconciliation                   │
│  - Decides cryptographic evidence capture & sealing         │
│  - Emits authoritative verdicts: PASS / FAIL / UNVERIFIED   │
└─────────────────────────────────────────────────────────────┘
```

### The Constitutional Axiom
> **The controlling agent decides WHAT should be done and WHY.**  
> **Desktop WebView Reviewer decides HOW it can be safely and reliably done.**

---

## 3. Boundary Matrix: Permitted vs. Prohibited Autonomous Decisions

To prevent architectural drift and operational ambiguity, Reviewer's autonomy is formally bounded:

| Domain | Reviewer MAY Autonomously Decide (HOW) | Reviewer MUST NOT Autonomously Decide (WHAT/WHY) |
|---|---|---|
| **Target Selection** | How to resolve a semantic selector to an active HWND, CDP target, or DOM node | What application binary to launch or attach to |
| **Observation Plane** | Whether Native Win32/UIA, WebView CDP, or Visual GDI capture is appropriate | What aspects of the application business domain matter to the user |
| **Actionability** | Whether an element is obscured, offscreen, disabled, cloaked, or physically clickable | Whether an unclickable button invalidates the overall user mission |
| **Coordinate Math** | How to transform Web CSS logical coordinates to Per-Monitor V2 physical screen pixels | Where the mouse *ought* to click outside the requested reference |
| **Settlement & Timing** | How long to wait for DWM frame presentation, layout recalculation, and UI thread quiescence | What workflows should follow if an action times out |
| **Stale Recovery** | How to re-observe and re-locate a target after an epoch shift or DOM mutation | Whether an altered UI layout warrants changing testing strategy |
| **Failure Classification** | Whether a fault is `TARGET_HUNG`, `OCCLUDED`, `MODAL_BLOCK`, or `ELEMENT_NOT_FOUND` | Whether to terminate testing or switch to an unrelated application |
| **Evidence & Proof** | How to compute SHA-256 hashes, capture DWM crops, and record structured traces | Whether evidence satisfies the user's business sign-off requirements |
| **Scope Boundary** | How to inspect within the caller's target process and child window tree | Autonomously exploring unrelated applications or desktop shortcuts |

---

## 4. Anti-God-Agent Mandate

A common anti-pattern in desktop testing systems is the creation of a "God Agent"—a monolithic runtime component that receives a vague prompt ("test my app"), secretly generates arbitrary test plans, clicks around at random, and outputs a superficial pass report.

Desktop WebView Reviewer 2.0 explicitly rejects this pattern:

1. **Deterministic Execution:** Every runtime action corresponds to an explicit, auditable MCP tool invocation or well-defined workflow step.
2. **Bounded Scope:** The runtime interacts exclusively with targets explicitly assigned by the controlling agent. It has no authority to scan arbitrary windows on the user's desktop.
3. **No Hidden Planning Loops:** The runtime engine contains zero autonomous planning loops. It does not decide what screen to navigate to next; it executes the requested directive, settles, verifies, and returns control to the agent.
4. **Observable State:** All decisions made by Reviewer (e.g., coordinate conversion, fallback from CDP to SendInput, settlement extensions) are emitted as structured trace events.
5. **Policy-Controlled Workflows:** Composite workflows such as `desktop_review_application` exist only as declarative agent skill workflows executed step-by-step under the orchestrator's oversight.

---

## 5. Antigravity & Orchestrator Integration

Desktop WebView Reviewer 2.0 is designed from the ground up to be orchestrated by Antigravity and its coordinating skills (such as Adaptive Orchestrator, TeamPreview, and custom Antigravity plugins).

### Communication Protocol
- **Control Interface:** Model Context Protocol (MCP) transport over stdio or local IPC.
- **Operational Policy:** Antigravity Agent Skill (`SKILL.md`), providing the mental model, failure trees, and verification protocols.
- **Data Exchange:** Strongly-typed JSON-RPC tool parameters and cryptographic resource URIs (`evidence://...`, `trace://...`).

### Delegated Execution Contract
When an Antigravity agent invokes Reviewer:
1. The agent passes a specific intent (e.g. `desktop_click(reference="w1e5", epoch=2)`).
2. Reviewer validates capabilities, checks actionability, dispatches physical or synthetic input, monitors settlement, re-observes physical reality, and evaluates verification claims.
3. Reviewer returns a structured outcome containing:
   - `verdict`: `PASS`, `FAIL`, or `UNVERIFIED`
   - `action_receipt`: Exactly what physical/synthetic events were sent
   - `state_change`: Detailed pre- vs. post-observation delta
   - `evidence_manifest`: Cryptographically verifiable SHA-256 artifacts
4. Control immediately yields back to the Antigravity agent to plan the next step.

---

## 6. Summary Architectural Rules

1. **Rule of Subordination:** Desktop WebView Reviewer is always subordinate to the controlling agent.
2. **Rule of Capability Honesty:** Reviewer never fakes support for missing OS or framework primitives.
3. **Rule of Physical Primacy:** Physical desktop state outranks compositor state, which outranks DOM/web state.
4. **Rule of Verification Integrity:** An action is only verified when post-state physical reality confirms it. Delivery of input never implies success.
