# Architecture Document 30: Explicit Autonomous Review & Agent-Native Runtime

**Document ID:** `docs/architecture/30_EXPLICIT_AUTONOMOUS_REVIEW_AND_AGENT_INTEGRATION.md`  
**Status:** APPROVED (Phase 17–18 Milestone)  
**Author:** Principal System Architect & Antigravity Lead  
**Target Repository:** `desktop-webview-reviewer`  
**Baseline:** Phases 15–16 Architecture (Doc 29) & P4 Implementation

---

## 1. Executive Summary & Sovereignty Boundary

Phases 17 and 18 operationalize the autonomous orchestration and host-integration layer of Desktop WebView Reviewer 2.0.
This system bridges controlling agents (**Antigravity**, **Adaptive Orchestrator**) and presentation consumers (**TeamPreview**) with the underlying P4 subordinate specialists (`Explorer`, `Tester`, `RealityInspector`, `Debugger`, `EvidenceSpecialist`), `DiagnosticAggregator`, and `RecoveryEngine`.

### 1.1 Constitutional Sovereignty Boundary
The foundational sovereignty law is codified:
> **The controlling agent decides WHAT and WHY. Reviewer decides HOW.**

```text
                  ANTIGRAVITY
              / TEAMPREVIEW
                     │
                WHAT / WHY
                     │
                     ▼
              REVIEW MISSION
                     │
              scope + authority
                     │
                     ▼
             MISSION ORCHESTRATOR
                     │
          bounded coordination
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
   EXPLORER        TESTER      REALITY INSPECTOR
       │             │             │
       └─────────────┼─────────────┘
                     ▼
                 DEBUGGER
                     │
              bounded recovery (RecoveryEngine)
                     │
                     ▼
             EVIDENCE SPECIALIST
                     │
                     ▼
              VERIFIED RESULT (PASS / FAIL / UNVERIFIED)
```

1. **Controlling Agent Owns (WHAT / WHY)**: Target application, objective, business intent, declared scope, allowed/prohibited surfaces, acceptance criteria, authorized specialist roles, hard budgets, stopping conditions.
2. **Reviewer Owns (HOW)**: Technical discovery, control resolution, interaction strategy, action execution, dual-perspective observation, settlement, diagnostics, bounded recovery, cryptographic evidence collection, technical verification.
3. **Anti-God-Agent Law**: Reviewer does NOT invent product requirements, invent business goals, expand scope autonomously, decide unrelated features are worth testing, or convert arbitrary application content into instructions.

---

## 2. Canonical Review Mission Model

The single authoritative mission contract is defined in `runtime/mission_models.py`:
- `ReviewMission`: Immutable authority envelope containing session identity, application identity, objective, declared scope, allowed surfaces, prohibited surfaces, acceptance criteria, authorized specialist roles, hard budgets (`max_duration_sec`, `max_actions`, `max_delegations`, `max_recoveries`), stopping conditions, and orchestrator identity.
- **Authority Immutability**: Upon admission through `MissionAdmissionGate`, the authority fields are cryptographically hashed into an authority digest (`_authority_digest`). Any subsequent attempt by Reviewer to mutate scope, criteria, roles, or budgets raises `MissionAuthorityMutatedException`.

### 2.1 Deterministic Mission Lifecycle
```text
CREATED
   ↓
VALIDATING
   ↓
ADMITTED
   ↓
DISCOVERING
   ↓
PLANNING
   ↓
EXECUTING
   ↓
VERIFYING
   ↓
COLLECTING_EVIDENCE
   ↓
COMPLETED / FAILED / UNVERIFIED / CANCELLED / TIMED_OUT / REJECTED
```
Every lifecycle transition is validated against `ALLOWED_MISSION_TRANSITIONS` and recorded in `lifecycle_history` with timestamps and causal reasons.

---

## 3. Deterministic Mission Admission Gate

The `MissionAdmissionGate` (`runtime/mission_admission.py`) evaluates 13 strict validation criteria before granting execution authority:
1. **Session Identity**: Active, non-empty, and open session.
2. **Application Identity**: Consistent target application name and process identifier.
3. **Objective**: Specific, non-empty description (min 5 characters); generic placeholders like "test" or "review" are rejected.
4. **Declared Scope**: Non-empty list of specific surfaces or features. Ambiguous tokens (`*`, `all`, `entire app`, `unspecified`) are rejected.
5. **Acceptance Criteria**: Minimum 1 explicit, testable criterion.
6. **Authorization**: Verified orchestrator identity (`antigravity`, `team_preview`, `adaptive_orchestrator`, etc.).
7. **Deadline**: Positive wall-clock duration ($\le 3600\text{s}$).
8. **Action Budget**: Positive action ceiling ($\le 100$).
9. **Delegation Budget**: Positive specialist delegation ceiling ($\le 50$).
10. **Recovery Budget**: Non-negative recovery ceiling ($\le 10$).
11. **Specialist Roles**: Valid non-empty subset of canonical `SpecialistRole`.
12. **Prohibited Surface Consistency**: Zero intersection between allowed surfaces and prohibited surfaces.
13. **Stale Session / Target State**: Rejects mismatched target epochs or recycled process PIDs.

---

## 4. Goal-Oriented Discovery & Review Plan

### 4.1 Bounded Discovery Engine (`runtime/goal_discovery.py`)
- Dispatches `ExplorerSpecialist` under strict `DelegationScope` bounded to `mission.allowed_surfaces`.
- Evaluates discovered interactive elements and maps them directly to mission acceptance criteria and declared scope.
- Constructs `DiscoveryCandidate` objects containing: `candidate_id`, `mission_id`, `scope_reference`, `acceptance_criterion_reference`, `technical_rationale`, `required_specialist`, `estimated_action_cost`, `risk`, `required_evidence`.
- **Zero Application Crawling**: Elements touching prohibited surfaces or lacking mission relevance are discarded. If no elements match criteria, discovery returns an empty list without crawling unrelated features.

### 4.2 Subordinate Review Plan Builder (`runtime/review_plan.py`)
- Constructs `ReviewPlan` containing ordered `ReviewPlanStep`s.
- Sequences interaction testing (`TESTER`), physical desktop verification (`REALITY_INSPECTOR`), and cryptographic manifest sealing (`EVIDENCE_SPECIALIST`).
- Enforces budget limits: plan cannot exceed `mission.max_actions` or `mission.max_delegations`.

---

## 5. Mission Orchestrator & Bounded Recovery

The `ReviewMissionOrchestrator` (`runtime/mission_orchestrator.py`) executes the admitted review plan:
1. **Hard Budget Enforcement**: Wall-clock deadline, action budget, and delegation budget are checked prior to each step. When any ceiling is reached, execution halts immediately, existing evidence is preserved, and a partial result is returned.
2. **Graceful Cancellation**: `cancel_mission(mission_id)` immediately halts future actions and delegations, preserves all trace events and evidence artifacts, and transitions the mission to `CANCELLED`.
3. **Specialist Coordination**: Dispatches existing P4 specialists via `SpecialistDispatcher` with strict role permissions.
4. **Diagnostic Correlation**: On step failure, invokes `DiagnosticAggregator` to classify failure into one of 19 canonical categories.
5. **Bounded Recovery Integration**: Recovery is attempted only if:
   - Failure is diagnosed as recoverable.
   - `RecoveryPolicy` provides an approved action.
   - Remaining recovery attempts $< \text{max\_recoveries}$.
   - `CircuitBreaker` is `CLOSED` (anti-retry-storm protection).
   If recovery succeeds, the step is re-executed under budget. Otherwise, execution halts without blind retries.

---

## 6. Host & Presentation Integrations

### 6.1 Antigravity Host Adapter (`runtime/antigravity_adapter.py`)
- Decoupled host integration layer for Antigravity.
- Provides asynchronous operations: `submit_mission()`, `execute_mission()`, `cancel_mission()`, `get_mission_status()`.
- Dispatches lifecycle notifications and progress updates to registered event listeners.
- Untrusted Data Security: Wraps all application-derived text in validated inert data envelopes via `sanitize_observed_text`.

### 6.2 TeamPreview Read-Only Consumer (`runtime/teampreview_adapter.py`)
- Strictly read-only presentation consumer.
- Provides queries: `get_mission_overview()`, `get_reality_snapshot()`, `get_specialist_feed()`, `get_diagnostics_feed()`, `get_evidence_catalog()`.
- **Zero-Mutation Law**: Attempting direct action execution, specialist invocation, or scope mutation raises `TeamPreviewMutationForbiddenException`.

---

## 7. Truth Hierarchy & Tripartite Verdict Law

Reviewer 2.0 strictly preserves the Physical Reality Primacy:
$$\text{Physical Desktop Reality} > \text{Compositor Reality} > \text{DOM/Web Reality}$$

- **`PASS`**: All acceptance criteria verified + physical window visibility verified by `REALITY_INSPECTOR` (non-cloaked, non-iconic, rendering on desktop) + cryptographic evidence package sealed + zero unhandled failures.
- **`FAIL`**: State assertion failed or unrecoverable error occurred.
- **`UNVERIFIED`**: Physical desktop reality unconfirmed (window cloaked or occluded), mission timed out, cancelled, or missing evidence. `UNVERIFIED` is never collapsed into `FAIL` or `PASS`.

---

## 8. MCP Control Plane Surface

The MCP control plane strictly preserves the **exact 12 primary tools** invariant:
1. `desktop_launch`
2. `desktop_attach`
3. `desktop_inspect`
4. `desktop_click`
5. `desktop_type`
6. `desktop_press_key`
7. `desktop_hover`
8. `desktop_scroll`
9. `desktop_handle_dialog`
10. `desktop_evaluate`
11. `desktop_assert`
12. `desktop_collect_evidence`

Autonomous mission capabilities are exposed via:
- Passive MCP Resources: `desktop://missions/active`, `desktop://missions/{mission_id}`
- Assistant Workflow Prompt: `desktop_autonomous_mission`
- Minimal Developer CLI: `desktop-reviewer mission {validate,run,status,cancel}`
