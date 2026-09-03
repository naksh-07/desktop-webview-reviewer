# Architecture Document 18: Evidence & Forensic Model

**Document ID:** `docs/architecture/18_EVIDENCE_MODEL.md`  
**Status:** APPROVED (Phase 0 Deliverable)  
**Author:** Principal Software Architect  
**Target Repository:** `desktop-webview-reviewer`  
**Core Standard:** Tripartite Verdict Provenance & Cryptographic Audit Trails  

---

## 1. Forensic Auditing vs. Conventional Automation

Conventional UI automation operates under a binary paradigm: `PASS` (code finished without unhandled exception) or `FAIL` (assertion threw an exception).

In hybrid desktop-webview systems, this binary model is fatally flawed:
* An automation script can click a synthetic DOM element and evaluate JavaScript in a headless background daemon, an invisible offscreen surface, or a minimized window.
* A conventional test framework marks this `PASS`, yet **zero human users saw the application**, and **zero physical pixels were rendered**.

The `desktop-webview-reviewer` platform enforces a forensic standard: **Verification requires mathematical and visual proof that the software was physically rendered on a desktop display and that input traversed the operating system subsystem.**

---

## 2. The Tripartite Verdict Model

The platform strictly enforces a three-state verdict model:

```
Tripartite Verdict Model
┌───────────────┬────────────────────────────────────────────────────────────────────────────────────────┐
│ Verdict State │ Forensic Criteria & Mathematical Grounding                                             │
├───────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ PASS          │ All 4 Pillars of Physical Reality Proven:                                              │
│               │ 1. Native Window is physically visible, non-minimized, and non-cloaked by DWM.          │
│               │ 2. Window has non-zero area and renders non-black, valid GUI pixels.                   │
│               │ 3. Input was delivered and confirmed by subsequent UI state mutation.                  │
│               │ 4. Zero unhandled fatal console exceptions or process crashes occurred.                │
├───────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ FAIL          │ Unambiguous Negative Proof:                                                            │
│               │ 1. Target process crashed or terminated abnormally.                                    │
│               │ 2. An explicit assertion failed (e.g. expected text was absent after timeout).         │
│               │ 3. A blocking modal error dialog (#32770) or uncaught fatal exception appeared.        │
├───────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ UNVERIFIED    │ Incomplete, Ambiguous, or Compromised Proof:                                           │
│               │ 1. Application ran headless or without a valid top-level desktop HWND.                 │
│               │ 2. Window was minimized or cloaked by Windows Virtual Desktops during verification.    │
│               │ 3. Missing one or more required visual proofs (e.g. native screenshot failed).         │
│               │ 4. Actions were executed but target state mutation could not be conclusively verified. │
└───────────────┴────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Resolution of the "Permanent UNVERIFIED" Regression

### 3.1 Forensic Diagnosis from Track 09
Between commit `d90e5b0` and commit `c7dd3bb`, an ad-hoc regex patch (`patch_evidence.py`) mutated `core/evidence.py` to enforce that `Verdict.PASS` strictly requires:
```python
# The defect in core/evidence.py
if not (user_confirmation and input_delivery_verified and has_three_screenshots):
    return Verdict.UNVERIFIED
```
However, the CLI test runner (`scripts/review.py`) was never updated to supply `user_confirmation` or generate a three-point screenshot set. Consequently, **every invocation of the CLI tool returned `UNVERIFIED` (exit code 2)**, making automated testing impossible.

### 3.2 Architectural Remedy
The Evidence Engine decouples **Interactive Human Confirmation** from **Automated Dual-Perspective Proof**:

```python
def evaluate_verdict(
    window_forensics: WindowForensicReport,
    proof_metrics: ProofMetrics,
    assertions: List[AssertionResult],
    execution_mode: str = "automated" # "automated" | "interactive"
) -> tuple[Verdict, str]:
    # 1. Check for explicit failures
    if proof_metrics.process_crashed or any(not a.passed for a in assertions):
        return (Verdict.FAIL, "Target process crashed or one or more assertions failed.")

    # 2. Verify Physical Reality Primacy
    if not window_forensics.is_visible or window_forensics.is_iconic or window_forensics.is_cloaked:
        return (Verdict.UNVERIFIED, "Window was minimized, hidden, or cloaked by DWM during test execution.")

    # 3. Verify Dual Screenshots
    if not (proof_metrics.has_native_screenshot and proof_metrics.has_webview_screenshot):
        return (Verdict.UNVERIFIED, "Missing required dual-perspective visual proofs (native or webview capture missing).")

    # 4. Verify Input Delivery
    if not proof_metrics.input_delivery_verified:
        return (Verdict.UNVERIFIED, "Actions dispatched but state mutation could not be conclusively verified.")

    # 5. Interactive Mode Check (Only if explicitly running in interactive audit mode)
    if execution_mode == "interactive" and not proof_metrics.user_confirmation:
        return (Verdict.UNVERIFIED, "Automated proofs passed, but human reviewer confirmation is pending.")

    return (Verdict.PASS, "Dual-perspective physical visibility and functional state mutation verified successfully.")
```

---

## 4. Evidence Bundle Manifest & Provenance

Every completed test run or audit session compiles an immutable Evidence Bundle saved to disk at:
`<session_dir>/evidence/<evidence_id>/`

```
Evidence Bundle Directory Layout
┌────────────────────────────────────────────────────────┐
│ ev_20260904_104512_anki/                               │
│ ├── manifest.json            # Authoritative metadata  │
│ ├── native_screen.png        # Physical desktop crop   │
│ ├── webview_viewport.png     # Chromium compositor PNG │
│ ├── window_forensics.json    # DWM & Win32 geometry    │
│ ├── a11y_tree_initial.yaml   # Epoch 1 snapshot        │
│ ├── a11y_tree_final.yaml     # Epoch N snapshot        │
│ ├── console_logs.jsonl       # V8 console messages     │
│ ├── network_trace.jsonl      # HTTP/WS exchanges       │
│ ├── action_timeline.jsonl    # Chronological actions   │
│ └── checksums.sha256         # Cryptographic hashes    │
└────────────────────────────────────────────────────────┘
```

### 4.1 The Authoritative `manifest.json` Schema
```json
{
  "$schema": "https://desktop-webview-reviewer.org/schemas/evidence-manifest-v2.json",
  "evidence_id": "ev_20260904_104512_anki",
  "session_id": "sess_8829a1b0",
  "timestamp": "2026-09-04T05:15:32.412Z",
  "target_application": {
    "binary_path": "C:\\Program Files\\Anki\\anki.exe",
    "pid": 14208,
    "creation_time": "2026-09-04T05:14:10.000Z",
    "engine": "qtwebengine",
    "hwnd": 263490
  },
  "verdict": "PASS",
  "verdict_rationale": "Dual-perspective physical visibility and functional state mutation verified successfully.",
  "proof_matrix": {
    "native_visible": true,
    "dwm_uncloaked": true,
    "window_bounds": [120, 80, 1280, 800],
    "native_screenshot_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "webview_screenshot_sha256": "8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4",
    "input_delivered": true,
    "state_mutations_observed": 3,
    "uncaught_console_errors": 0
  },
  "artifacts": [
    { "filename": "native_screen.png", "type": "image/png", "sha256": "e3b0c44..." },
    { "filename": "webview_viewport.png", "type": "image/png", "sha256": "8f43434..." },
    { "filename": "action_timeline.jsonl", "type": "application/x-ndjson", "sha256": "4b22777..." }
  ]
}
```

---

## 5. Visual Proof Integrity & DWM Crop Normalization

### 5.1 The Drop-Shadow Crop Hazard
On Windows 10/11, calling standard Win32 `GetWindowRect()` returns a rectangle that includes **invisible DWM drop-shadow margins** (typically 7–10 pixels around borders). Calling `PrintWindow` or GDI screen copy using `GetWindowRect` introduces unsightly borders or misaligned coordinate offsets.

### 5.2 The True Geometry Solution
The Native Supervisor queries the extended frame bounds via DWM:
```c
RECT frame;
DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, &frame, sizeof(RECT));
```
This returns the exact physical pixel boundary rendered on screen, ensuring:
1. Native screenshots reflect the exact visible application boundary without black borders.
2. Viewport-to-screen coordinate normalization aligns with sub-pixel precision under multi-monitor Per-Monitor V2 DPI scaling.
