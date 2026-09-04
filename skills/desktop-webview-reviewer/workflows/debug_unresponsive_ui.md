# Workflow: debug_unresponsive_ui

## Goal
Diagnose and isolate root causes when a desktop application with embedded webviews becomes unresponsive, freezes, or fails to acknowledge user inputs.

## Preconditions
1. Active session exists attached to the target process.
2. An interaction was attempted or the user reported an unresponsive interface.

## Observation Strategy
1. **Probe Native Window Responsiveness**:
   - Query Win32 message queue health via `IsHungAppWindow` / `SendMessageTimeoutW`.
2. **Probe CDP Protocol Responsiveness**:
   - Dispatch an evaluation heartbeat (`Runtime.evaluate` with trivial expression `1 + 1`).
3. **Probe AX Tree Freshness**:
   - Check if Chromium accessibility tree is responsive or frozen (`AXFreshnessStatus`).

## Decision Points
- **If Win32 reports HUNG**:
  - The main OS thread is blocked in native code. CDP cannot dispatch synthetic inputs because window message pump is stalled.
  - Action: Mark session `DEGRADED` or `TARGET_LOST`; do NOT retry physical inputs.
- **If Win32 reports HEALTHY but CDP times out**:
  - The webview renderer process is blocked (e.g. infinite JavaScript loop).
  - Action: Inspect CPU usage via process monitor; check console messages for unhandled runtime errors.
- **If both Win32 and CDP respond, but actions have no effect**:
  - The UI may be occluded by an invisible overlay, transparent modal backdrop, or `pointer-events: none` CSS rule.
  - Action: Check element actionability and hit-test at afford point coordinates.

## Allowed Actions
- `desktop_inspect`
- `desktop_evaluate` (bounded timeout $\le 2000$ms)
- `desktop_collect_evidence`
- `desktop_close`

## Verification Strategy
- Compare pre-state and post-probe responsiveness metrics.
- Verify whether the event loop resumes processing after a short debounce interval (up to 3000ms).

## Failure Handling
- If the application remains hung past 5000ms, collect diagnostic process dump metadata and abort interaction to prevent session deadlock.

## Evidence Strategy
- Capture window screenshot if possible; if `PrintWindow` fails due to hang, capture GDI DC fallback.
- Collect thread IDs, CPU percentage, and stack snapshot if available.

## Stop Conditions
- Application responsiveness restored and verified.
- Conclusive forensic determination of UI hang (Native hang vs Web renderer hang vs Overlay block).
