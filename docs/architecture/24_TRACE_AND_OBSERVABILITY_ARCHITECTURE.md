# Architecture Document 24: Desktop Trace & Observability Architecture

**Document ID:** `docs/architecture/24_TRACE_AND_OBSERVABILITY_ARCHITECTURE.md`  
**Status:** APPROVED (Phase 9 Milestone)  
**Author:** Principal System Architect & Antigravity Lead  
**Target Repository:** `desktop-webview-reviewer`  
**Baseline:** Architecture H Foundation, Docs 11–20, Phase 7 Implementation

---

## 1. Executive Summary

Debugging desktop software failure requires answering a fundamental question: **What actually happened across the entire system when this action occurred?**

In complex hybrid desktop applications (such as QtWebEngine, Electron, or WebView2), diagnosing failures cannot be achieved by looking at browser console logs in isolation, nor by looking solely at Windows event logs. Reviewer 2.0 introduces a unified **Desktop Trace Architecture** and a **Converged Observability Engine** that synchronizes native OS events, web engine DOM mutations, console output, physical screenshots, process lifecycle markers, and application logs into a single, cryptographically correlated timeline.

---

## 2. Canonical Desktop Trace Event Taxonomy

The 2.0 trace model establishes 17 first-class canonical event types:

```
┌─────────────────────────┬────────────────────────────────────────────────────────┐
│ Trace Event Type        │ Description                                            │
├─────────────────────────┼────────────────────────────────────────────────────────┤
│ APP_LAUNCH              │ Application process spawned by supervisor              │
│ WINDOW_DISCOVERED       │ Target HWND enumerated, filtered, or bound             │
│ PROCESS_STATE           │ OS process metrics, CPU, memory, thread health checked │
│ WEBVIEW_CONNECTED       │ CDP WebSocket connection established to webview target │
│ OBSERVATION             │ Synchronous dual-perspective observation epoch captured│
│ TARGET_RESOLVED         │ Semantic reference/locator resolved to physical target │
│ ACTION_REQUESTED        │ Agent requested an interaction transaction             │
│ ACTION_DISPATCHED       │ Input delivered to OS input queue or CDP transport     │
│ ACTION_SETTLED          │ Layout stabilized, DWM frame presented, UI quiescent   │
│ SCREENSHOT              │ GDI or DWM screen capture stored to disk               │
│ DOM_CHANGE              │ Chromium DOM mutation, subtree modification observed   │
│ UIA_CHANGE              │ Windows UI Automation property or structure change     │
│ CONSOLE_EVENT           │ Embedded web engine console message emitted            │
│ LOG_EVENT               │ Application stdout/stderr or file log entry parsed     │
│ ASSERTION               │ Verification engine evaluated a specific claim         │
│ RECOVERY                │ Stale reference re-resolved or degraded input retried  │
│ EVIDENCE_CREATED        │ Cryptographic evidence artifact hashed and sealed      │
└─────────────────────────┴────────────────────────────────────────────────────────┘
```

---

## 3. Universal Correlation Envelope

To guarantee that any event can be traced back to its root cause, every trace event carries a standard correlation envelope:

```yaml
trace_event:
  event_id: "evt_01J8F9X"
  event_type: "ACTION_DISPATCHED"
  timestamp: 1725541800.412
  sequence_monotonic: 1042

  correlation:
    session_id: "sess_anki_01"
    epoch_id: 4
    action_id: "act_click_save_99"
    request_id: "mcp_req_8812"

  context:
    plane: "WEBVIEW"
    target_reference: "w1e7"
    native_hwnd: "0x000A0452"
    cdp_target_id: "target_page_1"
    process_id: 18240

  payload:
    action_type: "CLICK"
    coordinates_screen: [450, 638]
    dispatch_method: "PHYSICAL_INPUT"
    preconditions_passed: true

  result:
    status: "DISPATCHED"
    duration_ms: 18.4

  artifacts:
    screenshot_pre_hash: "sha256:7f83...10b9"
```

---

## 4. Converged Observability Timeline

The Observability Engine converges multi-source telemetry into a synchronized timeline:

```
                  CONVERGED TIMELINE
────────────────────────────────────────────────────────► Time (ms)
T+000ms:  [USER ACTION]        desktop_click(reference="w1e7")
T+012ms:  [PHYSICAL STATE]     Window brought to foreground (HWND 0x000A0452)
T+025ms:  [DISPATCH]           SendInput(MOUSEEVENTF_LEFTDOWN | UP) at (450, 638)
T+065ms:  [WEB/NATIVE STATE]   DOM click handler fired; button disabled
T+110ms:  [APPLICATION EVENT]  PyQt backend signal `on_save_clicked()` triggered
T+145ms:  [LOG / CONSOLE]      Application stdout: "Saved config to sqlite db in 24ms"
T+150ms:  [CONSOLE EVENT]      CDP console: "Saved status: OK"
T+320ms:  [SETTLEMENT]         DWM frame stable; layout delta zero
T+340ms:  [VISUAL STATE]       Post-action screenshot captured; green checkmark rendered
T+355ms:  [VERIFICATION]       Assert "CheckmarkVisible" -> PASS
```

### Future Harness Correlation Point
When the Reviewer Test Harness is enabled in development builds (see Doc 26), harness lifecycle markers (e.g. `SAVE_STARTED`, `SAVE_COMPLETED`) are ingested directly into this identical timeline, providing precise causality linking without altering the black-box verification outcome.

---

## 5. Security & Sensitive Data Redaction

Trace and log events frequently touch sensitive information (user passwords in text fields, bearer tokens in network responses, private keys). The Observability layer enforces:
1. **Regex-Based Redaction:** Automatically masks credentials, tokens, and authorization headers (`[REDACTED]`).
2. **Payload Bounds:** Restricts arbitrary string dumps to 500 characters (`[TRUNCATED_FOR_TELEMETRY]`).
3. **Untrusted UI Enveloping:** Marks window titles, DOM text, and error strings as untrusted data envelopes to neutralize indirect prompt injection against controlling agents.
