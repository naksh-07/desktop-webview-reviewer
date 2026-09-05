# Architecture Document 27: Desktop WebView Reviewer 2.0 Roadmap & Specialist Contracts

**Document ID:** `docs/architecture/27_DESKTOP_REVIEWER_2.0_ROADMAP.md`  
**Status:** APPROVED (Phase 9 Milestone)  
**Author:** Principal System Architect & Antigravity Lead  
**Target Repository:** `desktop-webview-reviewer`  
**Baseline:** Phases 0–9 Architecture & Implementation

---

## 1. Executive Status & Phase 9 Record

Phase 9 completes the architectural foundation, constitutional sovereignty boundary, capability taxonomy, reality model, action lifecycle, and test harness specifications for Desktop WebView Reviewer 2.0.

### 1.1 Completed in Phase 9
* **Constitutional Sovereignty Boundary (Doc 21):** Formalized the WHAT/WHY vs. HOW division between the controlling agent (Antigravity) and Reviewer. Enforced the Anti-God-Agent rule.
* **2.0 Capability & Reality Model (Doc 22):** Defined the 6-domain capability model with honest states (`AVAILABLE`, `DEGRADED`, `UNAVAILABLE`, `UNKNOWN`). Defined the `RealityTarget` schema and codified Physical Reality Primacy (`Physical Desktop > Compositor > DOM/Web`).
* **Action Contract 2.0 (Doc 23):** Formalized the 10-step action lifecycle, segregated the 5 interaction milestones (`Dispatched != Verified`), and defined the human-equivalent interaction hierarchy.
* **Desktop Trace & Observability Architecture (Doc 24):** Specified 17 canonical trace events with universal correlation envelopes and converged monotonic timeline.
* **Evidence Contract 2.0 (Doc 25):** Standardized immutable artifact manifests, SHA-256 chain-of-custody, and the tripartite proof levels.
* **Reviewer Test Harness Architecture (Doc 26):** Formulated the Harness Golden Rule (black-box validation vs. instrumented diagnosis), lifecycle signals, fault injection, and mandatory CI release exclusion.
* **Specialist Contracts (Doc 27):** Defined boundaries and contracts for future subordinate specialist agents.
* **Foundational Contracts & Schemas:** Added `runtime/reality_models.py`, `runtime/trace_models.py`, `runtime/harness_contracts.py`, `runtime/specialist_contracts.py`, updated `runtime/capability.py` and `runtime/action_models.py`, and created the comprehensive Phase 9 contract test suite.

### 1.2 Deferred Implementation (Phases 10–14)
* Full runtime implementation of the Desktop Trace ingestion engine (Phase 10).
* Multi-source log/console stream merge daemon (Phase 10).
* Autonomous specialist agent implementations (Phase 11).
* Client SDK and daemon bridge for Reviewer Test Harness (Phase 12).
* Advanced multi-frame spatial reconciliation and live cross-framework adapters (Phase 13).

### 1.3 Known Limitations
* **OS Platform:** Deep compositor inspection requires Windows 10/11 DWM (`dwmapi.dll`). Non-Windows platforms cannot enforce physical visibility outranking DOM state.
* **WebKit Engine:** Legacy WebKit runtimes on Windows lack standard CDP input emulation and operate in `DEGRADED` interaction mode.
* **Display Sleep:** In remote desktop disconnects or screen suspension, DWM cloaks surfaces; Reviewer correctly marks visual verification as `UNVERIFIED`.

---

## 2. Subordinate Specialist Agent Contracts

Reviewer 2.0 establishes contracts for five subordinate specialist agents. These specialists operate **strictly inside delegated technical boundaries** under the controlling orchestrator's direction:

```
                  CONTROLLING ORCHESTRATOR
         (Antigravity / TeamPreview / Adaptive Orchestrator)
                               │
       ┌───────────────┬───────┴───────┬───────────────┐
       ▼               ▼               ▼               ▼
   EXPLORER         TESTER      REALITY INSPECTOR   DEBUGGER
"What exists?"   "Did it work?"  "What is seen?"  "Why failed?"
                               ▲
                               │
                       EVIDENCE SPECIALIST
                        "Can we prove it?"
```

### 2.1 The Explorer Contract
* **Question:** *"What exists in the application right now?"*
* **Mandate:** Enumerates top-level windows, webview targets, frames, interactive controls, and current screen topology.
* **Boundaries:** Read-heavy. Does not dispatch state-modifying actions without explicit orchestrator approval.

### 2.2 The Tester Contract
* **Question:** *"Did the explicitly requested workflow work?"*
* **Mandate:** Executes the delegated sequence of interactions, monitors settlement, and applies specified acceptance assertions.
* **Boundaries:** Strictly confined to the requested workflow steps. Cannot invent new business journeys.

### 2.3 The Reality Inspector Contract
* **Question:** *"What does the human user physically see on screen?"*
* **Mandate:** Inspects DWM compositor state, calculates window occlusion, verifies focus, and analyzes visual screenshots for rendering glitches.
* **Boundaries:** Sensory validation only. Emits authoritative physical visibility verdicts.

### 2.4 The Debugger Contract
* **Question:** *"Why did this interaction or assertion fail?"*
* **Mandate:** Correlates trace events, inspects console errors, reviews application stderr, evaluates UI thread hang state, and classifies failure root causes.
* **Boundaries:** Diagnostic analysis. Does not perform speculative blind retries.

### 2.5 The Evidence Specialist Contract
* **Question:** *"Can we cryptographically prove what happened?"*
* **Mandate:** Assembles evidence packages, computes SHA-256 hashes, generates timeline manifests, and validates byte-level immutability.
* **Boundaries:** Forensic auditing and manifest sealing.

---

## 3. Desktop WebView Reviewer 2.0 Roadmap

```
Phase 9: Agent Sovereignty, Capability Architecture & Desktop Superpower Specification
         [COMPLETED] Architecture Docs 21-27, Foundational Schemas, Contracts & Tests
   │
   ▼
Phase 10: Desktop Trace Engine & Converged Observability
         Monotonic timeline collector, log stream multiplexer, console capture
   │
   ▼
Phase 11: Specialist Agents Implementation
         Explorer, Tester, Reality Inspector, Debugger, Evidence Specialist subagents
   │
   ▼
Phase 12: Reviewer Test Harness SDK & Build Tooling
         In-process dev instrumentation SDK, lifecycle signals, CI release stripper
   │
   ▼
Phase 13: Adversarial Hardening & Cross-Framework Adapters
         Live verification across Electron, WPF, WinUI 3, Qt, and Evergreen WebView2
   │
   ▼
Phase 14: Desktop WebView Reviewer 2.0 Production Release
         Final release audit, enterprise compliance validation, public documentation
```
