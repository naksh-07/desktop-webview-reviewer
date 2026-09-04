# Workflow: diagnose_native_web_mismatch

## Goal
Detect, isolate, and explain discrepancies between what the native OS window manager observes (HWND, DWM, UIA) and what the embedded web engine reports (DOM, CDP, CSS).

## Preconditions
1. Active session with valid native window (`HWND`) and active webview CDP target.
2. Target application renders hybrid UI content (native shell surrounding webview content).

## Observation Strategy
1. **Compare Geometry**:
   - Query native client rect ($W_{native}, H_{native}$).
   - Query webview viewport size ($W_{web}, H_{web}$) and Device Pixel Ratio (DPR).
   - Reconcile expected web dimensions against native client area:
     $$\Delta W = |W_{native} - (W_{web} \times \text{DPR})|$$
2. **Compare Visibility**:
   - Check if DOM reports element visible (`display != none`, `opacity > 0`).
   - Check if DWM reports host window is cloaked (`DWMWA_CLOAKED`) or iconic (`IsIconic`).
   - Check if element screen coordinates fall outside native window clipping boundaries.
3. **Compare Accessibility Trees**:
   - Query Windows UIA tree for webview host control.
   - Query Chromium CDP accessibility tree for web document elements.

## Decision Points
- **Mismatch A: DOM says visible, but DWM says occluded/cloaked**:
  - Root Cause: Application is rendering in background or minimized.
  - Verdict: Cannot claim user visibility (`NOT_SAFE_TO_CLAIM_VISIBLE`).
- **Mismatch B: Coordinate offset / DPI scaling error**:
  - Root Cause: High-DPI virtualization or improper DPI awareness manifests in application manifest.
  - Action: Log DPI scaling ratio and calibrate afford points using OS monitor DPI.
- **Mismatch C: Native modal dialog blocks webview**:
  - Root Cause: Native Win32 message loop has taken over (e.g. File Open dialog, MessageBox).
  - Action: Shift active plane to `NATIVE_MODAL` and interact via Win32/UIA.

## Allowed Actions
- `desktop_inspect`
- `desktop_hover` (to test mouse coordinate hit-testing)
- `desktop_collect_evidence`

## Verification Strategy
- Compare transformed web coordinates with native screen hit-test results (`WindowFromPoint`).
- Confirm whether physical input clicks land on the expected native control or web element.

## Failure Handling
- If coordinate reconciliation cannot be established within $\pm 2$ pixels, mark afford points `UNVERIFIED_COORDINATES` and log geometry details.

## Evidence Strategy
- Capture dual side-by-side screenshot (native OS window capture with overlay bounding boxes + webview viewport capture).

## Stop Conditions
- Clear forensic explanation of mismatch documented with coordinate reconciliation ledger.
