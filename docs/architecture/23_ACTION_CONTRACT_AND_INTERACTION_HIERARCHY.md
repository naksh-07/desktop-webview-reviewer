# Architecture Document 23: Action Contract & Human-Equivalent Interaction Hierarchy

**Document ID:** `docs/architecture/23_ACTION_CONTRACT_AND_INTERACTION_HIERARCHY.md`  
**Status:** APPROVED (Phase 9 Milestone)  
**Author:** Principal System Architect & Antigravity Lead  
**Target Repository:** `desktop-webview-reviewer`  
**Baseline:** Architecture H Foundation, Docs 11–20, Phase 5 Implementation

---

## 1. Executive Summary

In desktop automation, delivering synthetic keyboard or mouse events is trivial; proving that the application received, processed, and visually reflected those events is exceptionally hard.

A major flaw in legacy automation frameworks (e.g. Selenium, raw Playwright) is the **Dispatch Fallacy**: treating the successful dispatch of a click event as proof that the user action succeeded. In real desktop software:
- An application's UI thread may be blocked on a modal dialog.
- The window may be minimized or occluded by another application.
- The button may have moved between observation and click dispatch (spatial race condition).
- The click event may be dropped by the OS input queue.

Desktop WebView Reviewer 2.0 formalizes the **Action Contract**, establishing a 10-phase execution lifecycle, an explicit 5-event distinction, and a **Human-Equivalent Interaction Hierarchy**.

---

## 2. The Formal Action Lifecycle

Every interaction transaction executed by Reviewer transitions through 10 deterministic gates:

```
┌─────────────────────────────────────────────────────────────┐
│                   1. ACTION REQUEST                         │
│   Agent supplies intent (reference, action_type, params)    │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 2. CAPABILITY PRE-CHECK                     │
│   Verifies target engine supports requested interaction     │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  3. PRE-ACTION OBSERVE                      │
│   Captures baseline epoch, DOM/UIA tree, & screenshot       │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 4. RESOLVE REALITY TARGET                   │
│   Reconciles reference to active HWND, bounds, & CDP node   │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                5. ACTIONABILITY EVALUATION                  │
│   Checks visibility, occlusion, cloaking, modal dialogs     │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     6. ACT (DISPATCH)                       │
│   Delivers input via physical SendInput or CDP emulation    │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    7. SETTLE & STABILIZE                    │
│   Waits for DWM present, layout pass, & frame stability     │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  8. POST-ACTION RE-OBSERVE                  │
│   Captures post-epoch state, DOM delta, & post-screenshot   │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   9. VERIFY CLAIMS & DELTA                  │
│   Evaluates assertions against dual-perspective evidence    │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 10. AUTHORITATIVE RESULT                    │
│   Emits ActionOutcome (PASS / FAIL / UNVERIFIED) + Manifest │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. The Five Interaction Milestones

Reviewer's architecture strictly and explicitly distinguishes five events that legacy systems conflate into a single "click":

```
[1. Action Received]
        │
        ▼
[2. Action Dispatched] ─── (Operating system / CDP queue accepted events)
        │
        ▼
[3. Action Completed]  ─── (Input stream finished emitting events)
        │
        ▼
[4. Application State Changed] ─── (DOM mutated, HWND title changed, window closed)
        │
        ▼
[5. Expected State Verified]   ─── (Physical reality matches expected assertions)
```

### Critical Axiom:
> **Action Dispatched $\neq$ Action Completed $\neq$ Application State Changed $\neq$ Expected State Verified.**

- Merely placing an event into the Windows message queue (`SendInput`) satisfies **Milestone 2 (Dispatched)**, NOT Milestone 5.
- If an input is dispatched, but no state change occurs, the transaction produces **`UNVERIFIED`** or **`FAIL`**, never **`PASS`**.

---

## 4. Human-Equivalent Interaction Hierarchy

Reviewer defines human-like interaction as:
> **Using the same observable and actionable surfaces available to a human user, augmented by stronger machine verification.**

It does **not** mean arbitrary coordinate guessing. Interaction resolution follows a strict priority chain:

```
┌─────────────────────────────────────────────────────────────┐
│                    1. SEMANTIC TARGET                       │
│       Role, Name, Text, Accessibility Label, Selector       │
│                (e.g., role="button", name="Save")           │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               2. SEMANTIC TREE RESOLUTION                   │
│         UIA AutomationElement / Web AXNode / DOM Node       │
│               Derives precise logical geometry              │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              3. PHYSICAL COORDINATE COMPUTATION             │
│        Applies DPI scale, DWM client offset, viewport       │
│          Calculates guaranteed clickable affordance point   │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               4. CONTROLLED INPUT DISPATCH                  │
│       Primary: OS SendInput with cursor movement            │
│       Secondary: CDP Input.dispatchMouseEvent / KeyEvent    │
│       Fallback: Synthetic DOM event (marked DEGRADED)       │
└─────────────────────────────────────────────────────────────┘
```

### Abstraction Protection
The agent interacts strictly with the Semantic Target level (`reference="w1e5"` or `locator={'role': 'button', 'name': 'Submit'}`). The runtime internally handles coordinate conversion, DPI virtualization, and input routing without exposing OS-specific quirks to the controlling agent.

---

## 5. The Tripartite Verification Verdicts

Reviewer's verification engine evaluates results into three definitive categories:

```
┌─────────────────────────────────────────────────────────────┐
│                   VERIFICATION VERDICTS                     │
├───────────────┬─────────────────────────────────────────────┤
│ PASS          │ Post-action physical reality authoritatively│
│               │ proves the expected state occurred.         │
├───────────────┼─────────────────────────────────────────────┤
│ FAIL          │ Explicit proof that the operation failed or │
│               │ an invariant was violated (e.g. crash, hang,│
│               │ error dialog, negative assertion verified). │
├───────────────┼─────────────────────────────────────────────┤
│ UNVERIFIED    │ Action was delivered, but evidence is       │
│               │ insufficient, ambiguous, contradictory, or  │
│               │ state change did not occur.                 │
└───────────────┴─────────────────────────────────────────────┘
```

### Anti-Fraud Rules
1. **The Anti-Boolean Rule:** Verification outcomes must never be reduced to a simple boolean `success: true`. They must return the tripartite enum `PASS`, `FAIL`, or `UNVERIFIED`.
2. **The Delivery Rule:** Input delivery receipt alone yields `UNVERIFIED` unless accompanied by verified post-state changes.
3. **The Proof Level Hierarchy:** High-stakes assertions require Dual-Perspective proof (Physical Screenshot + DOM/UIA state change).
