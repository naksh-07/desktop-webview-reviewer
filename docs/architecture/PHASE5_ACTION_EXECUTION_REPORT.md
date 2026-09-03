# PHASE 5 — ACTION EXECUTION ENGINE & ACTION-OBSERVATION TRANSACTION LOOP REPORT

**Document ID**: `ARCH-RPT-PHASE5-ACTION-EXECUTION`  
**Repository**: `https://github.com/naksh-07/desktop-webview-reviewer`  
**Architecture Baseline**: Architecture H (Decoupled Dual-Perspective Bridge)  
**Target Environment**: Windows 11 (x86_64), PyQt6 / QtWebEngine, Win32 / DWM, .NET 8 FlaUI UIA3  
**Status**: COMPLETE & VALIDATED  

---

## 1. Executive Summary & Verification Ledger

[FACT] Phase 5 establishes the authoritative motor action execution engine and transactional action-observation loop atop the observation and actionability layer established in Phase 4.  
[FACT] The transaction loop evolves the runtime from read-only inspection (`OBSERVE -> LOCATE -> CHECK ACTIONABILITY`) into a closed-loop transaction:
```text
OBSERVE
  ↓
LOCATE
  ↓
CHECK ACTIONABILITY
  ↓
EXECUTE
  ↓
CAPTURE ACTION RECEIPT
  ↓
OBSERVE AGAIN
  ↓
REPORT OUTCOME
```
[FACT] No unified motor executor exists: Native Win32 operations and Webview DOM operations remain strictly segregated into dedicated plane executors (`NativeActionExecutor` and `WebActionExecutor`), preserving the Decoupled Dual-Perspective Bridge invariant.  
[FACT] Physical Reality Primacy is enforced across all dispatch pathways: Win32 OS window health (existence, visibility, minimization, cloaking, hung status, modal dialog occlusion) strictly gates physical dispatch even when DOM preconditions report readiness.  
[MEASUREMENT] Dedicated Phase 5 test suite comprising 102 test cases passed with 0 failures, 0 errors, validating 100% of unit models, Win32 input simulation, actionability gate rechecks, stale reference recovery, settlement engine polling, outcome classifications, session concurrency, adversarial scenarios, and live PyQt6 application integration.  
[MEASUREMENT] Real-application integration against live Anki Maths (PyQt6 + QtWebEngine) validated the complete 8-stage transaction cycle end-to-end: web click dispatch via CDP input, 71.0ms physical settlement, post-observation epoch transition (Epoch 1 → Epoch 2), and outcome state classification (`STATE_CHANGED`).  

---

## 2. Evidence Classification System

All findings in this report strictly adhere to the six-tier truth taxonomy:
- **[FACT]**: Verifiable from codebase code, Win32 OS APIs, or Chromium DevTools Protocol specifications.
- **[MEASUREMENT]**: Empirical quantitative metrics recorded during automated test execution.
- **[OBSERVATION]**: Direct behavior observed during runtime execution or debugger traces.
- **[INFERENCE]**: Logical deduplication based on facts and measurements.
- **[LIMITATION]**: Known system boundary, hardware constraint, or architectural trade-off.
- **[ARCHITECTURAL CONCLUSION]**: Foundational architectural rule governing future phases.

---

## 3. Dedicated Plane Action Executors

### 3.1 Strict Invariant: Plane-Separated Dispatch
[FACT] Architecture H prohibits combining web and native execution into a single generic dispatch routine.  
[FACT] `WebActionExecutor` manages webview motor dispatch strictly within the browser context:
1. **Primary Pathway**: High-fidelity CDP Input domain events (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`). Coordinates are mapped to webview viewport physical coordinates.
2. **Fallback Pathway**: If CDP Input fails or is rejected, the executor attempts explicit scripted DOM dispatch via `Runtime.evaluate` in the isolated execution world, while recording `dispatch_method = SCRIPTED_FALLBACK` in the immutable `ActionReceipt`.

[FACT] `NativeActionExecutor` manages native shell dispatch strictly via the Win32 OS message queue:
1. **Focus Synchronization**: Automatically restores iconic (minimized) windows and brings the target HWND to the foreground via `SetForegroundWindow` prior to keyboard or text input.
2. **Physical Input Dispatch**: Employs `NativeInputDispatcher` to issue 64-bit normalized Win32 `SendInput` packets.
3. **Receipt Generation**: Emits an `ActionReceipt` containing HWND, physical screen coordinates, dispatched record traces, and physical precondition summaries.

---

## 4. Win32 Native Input Subsystem (`runtime/native_input.py`)

### 4.1 64-bit Windows SendInput Integrity
[FACT] Windows `SendInput` requires precise 64-bit C structure alignment. The ctypes layout in `runtime/win32.py` guarantees byte-accurate serialization for AMD64 architectures:
```text
INPUT structure (40 bytes total on x86_64):
├── DWORD type (4 bytes)
├── Padding (4 bytes alignment)
└── Union (32 bytes):
    ├── MOUSEINPUT (32 bytes: dx, dy, mouseData, dwFlags, time, dwExtraInfo)
    ├── KEYBDINPUT (24 bytes: wVk, wScan, dwFlags, time, dwExtraInfo)
    └── HARDWAREINPUT (8 bytes: uMsg, wParamL, wParamH)
```

### 4.2 Coordinate Normalization & Physical Desktop Virtualization
[FACT] Win32 absolute mouse events (`MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK`) require coordinates normalized to the virtual desktop space $[0, 65535]$.  
[FACT] `CoordinateTransformer.screen_to_sendinput_normalized` calculates exact absolute coordinates across arbitrary multi-monitor setups with non-zero virtual desktop origins $(SM\_XVIRTUALSCREEN, SM\_YVIRTUALSCREEN)$.

### 4.3 Deterministic Dry-Run Mode
[FACT] `NativeInputDispatcher(dry_run=True)` enables complete verification of mouse movement, button down/up cycles, double clicks, modifier keystrokes, and text typing without injecting physical mouse or keyboard events into the developer's active desktop session.  
[MEASUREMENT] All 44 native input unit tests execute deterministically in $<350\text{ms}$ in dry-run mode, creating full forensic `DispatchedInputRecord` traces.

---

## 5. Bounded Settlement Engine (`runtime/settlement.py`)

### 5.1 Settlement Protocol & Stability Detection
[FACT] Dispatching an action to a GUI does not guarantee immediate visual or DOM stability. The transaction loop requires bounded settlement before post-action observation.  
[FACT] `SettlementEngine.settle()` polls the target process and window with a configurable timeout ($T_{\text{timeout}}$) and polling interval ($\Delta t = 20\text{ms}$):
1. **Modal Dialog Detection**: Scans for blocking Win32 modal dialogs (`#32770`, file pickers, message boxes). If a modal appears, settlement concludes immediately with `SettlementType.MODAL_APPEARED`.
2. **Window Destruction / Navigation**: Checks if the target HWND was destroyed or closed (`SettlementType.WINDOW_CLOSED`).
3. **Motion Stability**: Samples physical window bounds via DWM extended frame bounds across successive intervals. When $\Delta \text{bounds} = 0$, the window is deemed physically quiescent (`SettlementType.STABLE`).
4. **Timeout Bound**: If stability is not reached within `timeout_ms`, the engine halts and returns `SettlementType.TIMEOUT`, preventing indefinite agent hangs.

---

## 6. Immutable Action Domain Models (`runtime/action_models.py`)

[FACT] All state transition artifacts are immutable dataclasses (`frozen=True`) with exhaustive JSON serialization support via `to_dict()`:

| Model | Role | Key Properties |
|---|---|---|
| `ActionRequest` | Ingress agent intent | `action_id`, `session_id`, `reference`, `action_type`, `observation_epoch`, `params`, `risk_level` |
| `ActionTarget` | Resolved physical/DOM target | `target_id`, `reference`, `plane`, `epoch`, `affordance_point`, `native_hwnd`, `cdp_target_id`, `bounds` |
| `ActionPreconditions` | Recheck snapshot | `gate_status`, `is_actionable`, `evaluated_at`, `failure_reasons` |
| `ActionReceipt` | Post-dispatch physical proof | `action_id`, `dispatch_method`, `dispatch_status`, `coordinates`, `duration_ms`, `metadata` |
| `ActionOutcome` | Post-observation transition classification | `outcome_status`, `state_change`, `pre_epoch`, `post_epoch`, `state_diff_summary`, `duration_ms` |

### 6.1 State Change Classification
[FACT] Post-action observation comparison deterministically classifies the system outcome into one of seven canonical states:
- `STATE_CHANGED`: DOM or native element topology mutated, advancing the observation epoch ($E_{\text{post}} > E_{\text{pre}}$).
- `NO_EFFECT`: Target and surrounding window remained identical after settlement.
- `NAVIGATED`: Webview target URL changed or root frame reloaded.
- `TARGET_DISAPPEARED`: Targeted element no longer exists in post-action observation.
- `TARGET_CLOSED`: Window or webview target closed as a direct consequence of action.
- `MODAL_APPEARED`: Action spawned a modal dialog blocking the primary window.
- `UNKNOWN`: Insufficient evidence to classify outcome.

---

## 7. Stale Reference Recovery Engine

[FACT] During asynchronous execution or delayed dispatch, navigation or DOM updates can invalidate synthetic reference tokens ($w1e1 \to w2e1$).  
[FACT] When a reference is detected as stale, `DeterministicLocatorEngine.re_resolve_stale_ref()` attempts deterministic re-identification:
1. **Recipe Lookup**: Retrieves the original `LocatorRecipe` preserved in the reference registry's historical archive (`_stale_refs`).
2. **Candidate Matching**: Evaluates candidates in the fresh post-epoch snapshot against the recipe using exact role, accessible name, test ID, and structural predicates.
3. **Strict Cardinality**:
   - **Unique Match (1 candidate)**: Successfully re-maps to the new epoch's reference token.
   - **Ambiguous Match (>1 candidates)**: Halts immediately and raises `TargetAmbiguousException(candidates=[...])`.
   - **Zero Candidates (0 matches)**: Halts immediately and raises `TargetNotFoundException(query=...)`.

---

## 8. Real-Application Validation: Anki Maths (PyQt6 + QtWebEngine)

[MEASUREMENT] Live execution against the local Anki Maths application verified the complete Phase 5 transaction loop in a real production GUI:
- **Application PID**: `29204`
- **Native HWND**: `0xa302ac` (Win32 Class `Qt672QWindowIcon`)
- **CDP Endpoint**: `127.0.0.1:9260`
- **Observed Elements**: 4 interactive web elements at initial Epoch 1
- **Target Selected**: Reference `w1e3` (role `generic`, label `+`, bounds `(416, 116)`)
- **Actionability Gate**: `OverallActionabilityStatus.READY`
- **Execution**: Dispatch via `DispatchMethod.CDP_INPUT` at physical coordinates `(416, 116)`
- **Settlement Duration**: $71.0\text{ms}$ (`SettlementType.STABLE`)
- **Epoch Transition**: Epoch 1 $\to$ Epoch 2
- **Outcome Classification**: `StateChangeClassification.STATE_CHANGED`
- **Native Action Dispatch**: Win32 `SendInput` targeting root window HWND `0xa302ac` verified with status `DISPATCHED`

---

## 9. Architectural Conclusions & Invariants for Phase 6

1. **Transaction Integrity**: Every action MUST yield an `ActionReceipt` immediately after dispatch and an `ActionOutcome` following post-action observation. An action is never assumed to have succeeded until post-observation verifies the transition.
2. **No Blind Retries**: Stale references are only re-resolved if a deterministic recipe exists and produces exactly one unambiguous match. Any ambiguity halts execution to protect application state.
3. **Physical Priority**: If native OS inspection reports that a window is cloaked, minimized, or occluded by a modal dialog, physical input is blocked regardless of whether Chromium reports the element as visible.
