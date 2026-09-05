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

### 1.2 Milestones Completed (Phases 10–14 / Prompts P2–P3)
* **Prompt P2 (Phases 10–12):** Desktop Eyes (multi-monitor topology, DWM window forensics), Human-Equivalent Hands (15 interaction types), Reality Reconciliation, Settlement Engine, Desktop Trace Engine, Observability daemon.
* **Prompt P3 (Phases 13–14):** Reviewer Test Harness Core (wire protocol, local loopback HTTP transport, auth token security), Framework Adapters (Electron, WebView2, Qt), Project Detection & Surgical Injection (`desktop-reviewer harness init/remove`), Build Modes (`DEV`, `REVIEW`, `RELEASE`), and Release Security Validation Gate (`desktop-reviewer harness validate-release`).


### 1.3 Milestones Completed in Prompt P4 (Phases 15–16)
* **Specialist Subagent Runtimes:** Operationalized all five canonical specialists (`Explorer`, `Tester`, `RealityInspector`, `Debugger`, `EvidenceSpecialist`) under framework-neutral bounded execution containers. Enforced the Anti-God-Agent rule at runtime.
* **Delegation & Security Boundaries:** Formalized explicit delegation contracts (`SpecialistDelegation`, `DelegationScope`), runtime tool permission gates, untrusted application observation barriers, and tool call auditing (`ToolAuditRecord`).
* **Unified Multi-Source Diagnostics:** Built `DiagnosticAggregator` correlating Desktop Trace, process state, native DWM forensics, webview console exceptions, and Reviewer Test Harness telemetry into 19 canonical failure classifications, strictly distinguishing facts from inferences and hypotheses.
* **Bounded Recovery Engine & Reliability:** Implemented `RecoveryEngine` and anti-retry-storm `CircuitBreaker` (`CLOSED`, `OPEN`, `HALF_OPEN`), enforcing "NO BLIND RETRIES", deterministic recovery policies, timeout budget propagation, and failure preservation.
* **Architecture Invariants Preserved:** Preserved exact 12-primary-tool MCP surface without tool explosion. Added CLI subcommands `specialists`, `recovery`, `diagnostics`. Completed real-app live failure investigation validation and comprehensive test suites (46 new P4 tests, 0 regressions across 94 P1–P3 tests).

### 1.4 Milestones Completed in Prompt P5 (Phases 17–18)
* **Explicit Autonomous Review (Phase 17):** Implemented canonical `ReviewMission` authority envelope with immutable authority digest sealing. Built deterministic 13-point `MissionAdmissionGate` rejecting vague/unspecified scope without crawling. Implemented `GoalOrientedDiscoveryEngine` generating provenance-backed `DiscoveryCandidate`s. Built `ReviewPlanBuilder` and `ReviewMissionOrchestrator` enforcing hard budgets, deterministic lifecycle, physical reality primacy, and graceful cancellation.
* **Host & Presentation Integrations (Phase 18):** Built decoupled `AntigravityReviewerAdapter` with event streaming and untrusted UI data enveloping. Implemented strictly read-only `TeamPreviewConsumer` enforcing the Zero-Mutation Law.
* **Architecture Invariants Preserved:** Kept exact 12 primary MCP tools. Added `desktop://missions/active` and `desktop://missions/{mission_id}` MCP resources and `desktop_autonomous_mission` workflow prompt. Added developer CLI `desktop-reviewer mission {validate,run,status,cancel}`. Verified real-app QtWebEngine (Anki Maths) and Electron suites.

### 1.5 Milestones Completed in Prompt P6 (Phases 19–20)
* **Real-App Adversarial Certification (Phase 19):** Executed multi-framework live certification across QtWebEngine (Anki Maths), Electron, Microsoft Edge / WebView2, Chromium/CEF (`protocol_verified`), and WebKit (`runtime_unavailable`). Formulated 28 dedicated adversarial test categories covering window cloaking/minimization, ghost CDP endpoints, prompt injection, mission authority tampering, and recovery budget exhaustion (100% pass rate).
* **Production Security Audit & Stress Hardening (Phase 19):** Executed 6-domain security audit (Process, Network, Filesystem, Data, Authority, Release) with zero findings. Validated bounded sequential missions, monotonic trace budgets, and PID recycle safety.
* **Deterministic Release Validation Pipeline (Phase 20):** Implemented 8-gate release validation pipeline (`scripts/release_validator.py`) enforcing fail-closed release gates. Built clean `2.0.0` distribution wheel and sdist with test fixtures and harness code strictly segregated. Produced authoritative certification and release report (`docs/architecture/31_FINAL_2.0_CERTIFICATION_AND_RELEASE_REPORT.md`).
* **Final Release Verdict:** `PASS`. Desktop WebView Reviewer 2.0 is officially certified for production release.

### 1.6 Known Limitations
* **OS Platform:** Deep compositor inspection requires Windows 10/11 DWM (`dwmapi.dll`). Non-Windows platforms cannot enforce physical visibility outranking DOM state.
* **WebKit Engine:** WebKit on Windows lacks standard CDP and headless runtime binaries; honestly classified as `runtime_unavailable` / `UNVERIFIED`.
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

## 3. Desktop WebView Reviewer 2.0 Roadmap & Execution Plan

The project executes according to the **locked Minimum-Prompt Execution Plan**:

```text
Prompt P1 (Phase 9): Agent Sovereignty, Capability Architecture & Desktop Superpower Specification
         [COMPLETED & VERIFIED] Architecture Docs 21-27, Reality Model, Contracts & Base Schemas
   │
   ▼
Prompt P2 (Phases 10–12): Desktop Eyes, Human-Equivalent Hands, Trace & Observability
         [COMPLETED & VERIFIED] DWM Window Forensics, Multi-Monitor Topology, 15 Interaction Types,
         Reality Reconciliation, Desktop Trace Engine, Observability Daemon (429 tests passing)
   │
   ▼
Prompt P3 (Phases 13–14): Reviewer Harness, Framework Adapters & Dev/Review Build Pipeline
         [COMPLETED & VERIFIED] In-Process Harness Core, Loopback HTTP Transport, Electron/WV2/Qt Adapters,
         Project Detection, Surgical Injection (init/remove), Build Modes (DEV/REVIEW/RELEASE),
         Zero Production Backdoor & Release Security Validation (34 tests passing)
   │
   ▼
Prompt P4 (Phases 15–16): Specialist Subagents, Diagnostics & Recovery/Reliability
         [COMPLETED & VERIFIED] Explorer, Tester, Reality Inspector, Debugger, Evidence Specialist
         runtimes, delegation contracts, tool boundaries, untrusted data isolation, 19 failure
         classifications, circuit breaker, bounded recovery, and CLI diagnostics (46 tests passing)
   │
   ▼
Prompt P5 (Phases 17–18): Explicit Autonomous Review & Antigravity / TeamPreview Integration
         [COMPLETED & VERIFIED] Goal-oriented test discovery, canonical ReviewMission authority,
         MissionAdmissionGate, ReviewPlan, ReviewMissionOrchestrator, AntigravityReviewerAdapter,
         read-only TeamPreviewConsumer, hard budgets & recovery integration (40 tests passing)
   │
   ▼
Prompt P6 (Phases 19–20): Real-App Adversarial Certification & Production Release
         [COMPLETED & VERIFIED] Multi-framework live adversarial certification (QtWebEngine,
         Electron, WebView2), 28 adversarial categories, 6-domain security audit, end-to-end
         stress testing, 8-gate release validation pipeline, clean 2.0.0 packaging (580 tests passing)
```

### 3.1 Definitive Phase Status Summary

```text
Phase 1–2   (P1): [COMPLETED & VERIFIED]
Phase 3–8   (P2): [COMPLETED & VERIFIED]
Phase 9–14  (P3): [COMPLETED & VERIFIED]
Phase 15–16 (P4): [COMPLETED & VERIFIED]
Phase 17–18 (P5): [COMPLETED & VERIFIED]
Phase 19–20 (P6): [COMPLETED & VERIFIED]
```
