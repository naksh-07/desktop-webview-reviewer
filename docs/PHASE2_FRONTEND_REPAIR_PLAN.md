# Phase 2 Frontend Repair Plan: StudyLab Desktop Workspace
**Target Codebase:** `Anki-maths` (`ts/reviewer/`, `rslib/procedural/`, `qt/aqt/`)  
**Audit Baseline:** Phase 2 Live Target Audit (`docs/PHASE2_LIVE_TARGET_AUDIT.md`)  
**Status:** PLAN ONLY (Implementation explicitly deferred as mandated)  

---

## 1. Executive Summary & Priority Matrix

The Phase 2 Live Target Audit verified that the core Rust procedural engine, SQLite database schema, and Svelte/TypeScript component architecture are functional on a live visible Windows Anki DEV GUI. No product-breaking P0 crashes exist.

The repair backlog focuses on **P1 (Major UX / Interaction Mismatches)** and **P2 (Visual Polish & High-DPI Ergonomics)** to elevate the workspace from functional to production-grade.

| Priority Level | ID | Component / File | Description | Impact |
|---|---|---|---|---|
| **P0 (Product-Breaking)** | — | None | No fatal crashes, blank cards, or engine panics detected. | — |
| **P1 (Major Interaction)** | **P1-01** | `ts/reviewer/procedural.ts` | Synchronous DOM Mounting & Container Hydration | Eliminates race conditions on rapid card loading. |
| **P1 (Major Interaction)** | **P1-02** | `ts/reviewer/components/mistake_footer.ts` | Keyboard Shortcut Scope Isolation (`e.stopPropagation`) | Prevents Anki review ease keys (1-4) colliding with mistake taxonomy (1-4). |
| **P1 (Major Interaction)** | **P1-03** | `ts/reviewer/procedural.ts` | Automatic Wrong-Answer Remediation Routing | Directly transitions incorrect answer submissions to mistake self-diagnosis. |
| **P1 (Major Interaction)** | **P1-04** | `core/session.py` & `ts/reviewer/index.ts` | CDP Execution Context Resilience on Navigation | Prevents transient WebSocket command timeouts during card flips. |
| **P2 (Polish & Aesthetics)** | **P2-01** | `ts/reviewer/reviewer.scss` | High-DPI (1.5x / 144 DPI) Sub-pixel Layout Crispness | Refines border-radius, box shadows, and MathJax container spacing on Windows displays. |
| **P2 (Polish & Aesthetics)** | **P2-02** | `ts/reviewer/components/numerical_container.ts` | Unit Selector Auto-Complete & Keyboard Navigation | Allows learners to type `m/s^2` or `mol/L` directly with tab completion. |
| **P2 (Polish & Aesthetics)** | **P2-03** | `ts/reviewer/components/stepwise_container.ts` | MathJax Re-render Debounce on Stepwise Mode Toggle | Avoids momentary DOM flicker when expanding derivation steps. |

---

## 2. Detailed Technical Specifications

---

### P1-01: Synchronous DOM Mounting & Container Hydration
- **Target File:** `ts/reviewer/procedural.ts` (`ProceduralReviewer.bindElements`)
- **Problem Statement:** In `ProceduralReviewer` constructor, `bindElements()` queries `#proc-quick-input` immediately. If the Anki webview mounts the DOM template in microtask batches, `#proc-quick-input` can be temporarily null, causing input actions to miss focus.
- **Proposed Architectural Fix:**
  1. Add a MutationObserver or `requestAnimationFrame` gate in `bindElements()` ensuring all interactive targets (`#proc-quick-input`, `#proc-quick-submit`, `.proc-mcq-container`) are attached before declaring `state = 'solving'`.
  2. Implement an automatic retry hook (`ensureElementAttached`) with a 150ms fallback limit.

---

### P1-02: Keyboard Shortcut Scope Isolation
- **Target File:** `ts/reviewer/components/mistake_footer.ts` & `ts/reviewer/answering.ts`
- **Problem Statement:** Anki's host reviewer listens on `window.addEventListener('keydown')` to capture keys `1, 2, 3, 4` for answering cards (`Again, Hard, Good, Easy`). When StudyLab renders the mistake taxonomy panel (`1: Conceptual`, `2: Calculation`, `3: Reading`, `4: Strategy`), pressing `2` triggers Anki's global `Hard` shortcut rather than selecting the mistake tag.
- **Proposed Architectural Fix:**
  1. In `MistakeFooter.attachKeyboardListeners()`, bind a capturing `keydown` listener on `window` (`capture: true`).
  2. If the mistake modal/panel is visible and the key is `1, 2, 3, 4` or `Escape`, execute `e.stopPropagation()`, `e.preventDefault()`, and dispatch the mistake selection.
  3. Release shortcut capture immediately when transitioning to the next problem.

---

### P1-03: Automatic Wrong-Answer Remediation Routing
- **Target File:** `ts/reviewer/procedural.ts` (`ProceduralReviewer.handleSubmissionOutcome`)
- **Problem Statement:** When a learner enters an incorrect numerical or MCQ answer, the system currently requires navigating through standard answer reveal before showing the mistake taxonomy chips.
- **Proposed Architectural Fix:**
  1. In `handleSubmissionOutcome`, if `isCorrect === false`, immediately transition UI state to `'mistake_classification'`.
  2. Expand `#proc-mistake-panel` with a smooth CSS accordion transition, auto-focusing the taxonomy options while keeping the learner's submitted answer and canonical derivation visible for direct comparison.

---

### P1-04: CDP Execution Context Resilience on Navigation
- **Target File:** `core/session.py` & `View-Check/core/actions.py`
- **Problem Statement:** During rapid card transitions, Anki's QtWebEngine reloads the `_anki/legacyPageData` URL, destroying the active Chromium V8 execution context. Pending CDP commands (`Page.captureScreenshot`, `Runtime.evaluate`) encounter transient disconnections.
- **Proposed Architectural Fix:**
  1. In `CDPSession.send_command`, catch `TimeoutError` and check if a `Page.frameNavigated` or `Runtime.executionContextDestroyed` event occurred.
  2. Auto-reconnect to the new execution context without terminating the review session.

---

### P2-01: High-DPI (1.5x / 144 DPI) Sub-pixel Layout Crispness
- **Target File:** `ts/reviewer/reviewer.scss`
- **Problem Statement:** On Windows 1.5x display scaling, fractional borders (`0.5px`) and box shadows can exhibit sub-pixel blurriness.
- **Proposed Architectural Fix:**
  1. Standardize border widths to integer pixel values using CSS `min(1px, 0.0625rem)`.
  2. Add `-webkit-font-smoothing: antialiased` and `image-rendering: -webkit-optimize-contrast` to `.proc-workspace`.

---

### P2-02: Unit Selector Auto-Complete & Keyboard Ergonomics
- **Target File:** `ts/reviewer/components/numerical_container.ts`
- **Problem Statement:** In Physics and Chemistry problems requiring units (e.g. `m/s^2`, `J/(mol*K)`), selecting from a dropdown via mouse slows down the procedural problem-solving rhythm.
- **Proposed Architectural Fix:**
  1. Implement inline unit auto-complete directly inside the numerical input box (e.g. typing `15 m/s` auto-suggests `m/s^2`).
  2. Support spacebar or tab separation to commit magnitude and unit simultaneously.

---

### P2-03: MathJax Re-render Debounce on Stepwise Mode Toggle
- **Target File:** `ts/reviewer/components/stepwise_container.ts`
- **Problem Statement:** Toggling between Quick mode and Stepwise mode invokes full MathJax typesetting on all step nodes, causing a brief layout shift.
- **Proposed Architectural Fix:**
  1. Scope MathJax rendering to newly mounted step elements using `MathJax.typesetPromise([stepEl])`.
  2. Debounce re-render calls with `requestIdleCallback`.

---

## 3. Verification Protocol for Future Execution

When implementing the repairs in a future phase, execute the following verification gate:
```bash
# 1. Run unit tests
python -m unittest discover tests

# 2. Run real app verification test
python -m unittest tests/test_anki_maths_real_app.py

# 3. Run full Phase 2 Live Target Audit
python scripts/audit_phase2.py
```
**Acceptance Criterion:** `14/14` states PASS with verdict `🟢 LIVE TARGET VERIFIED`.
