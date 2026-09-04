# Workflow: collect_forensic_evidence

## Goal
Generate an immutable, cryptographically sealed forensic audit package representing the verified state of a running desktop application and its embedded webviews.

## Preconditions
1. Active or recently completed automation session.
2. Valid session ID exists with associated runtime state.

## Observation Strategy
1. Query full process and window hierarchy metadata (PID, HWND, window title, class name, bounds, DWM cloaked state).
2. Capture native OS window snapshot via Win32 `PrintWindow` or GDI DC bitblt.
3. Capture webview viewport snapshot via CDP `Page.captureScreenshot`.
4. Capture current DOM tree and accessibility snapshot.
5. Capture recent action history and console message logs.

## Decision Points
- **If native screenshot fails**: Record explicit reason in manifest (e.g. window minimized, hardware acceleration protection) and fallback to desktop screen crop if permitted.
- **If webview is disconnected**: Mark web plane evidence as `UNAVAILABLE` while preserving native OS window evidence.

## Allowed Actions
- `desktop_collect_evidence`
- Resource retrieval via `desktop://evidence/{evidence_id}/manifest`
- Resource retrieval via `desktop://evidence/{evidence_id}/screenshot_native`
- Resource retrieval via `desktop://evidence/{evidence_id}/screenshot_webview`

## Verification Strategy
- Compute SHA-256 digests across all captured binary artifacts.
- Verify that every claim in the manifest references a valid artifact hash.
- Confirm manifest signature and tripartite verdict computation (`PASS`, `FAIL`, or `UNVERIFIED`).

## Failure Handling
- If disk space is exhausted or write permissions fail, report explicit error without corrupting existing evidence stores.
- If hash verification fails, flag `EVIDENCE_INTEGRITY_ERROR`.

## Evidence Strategy
- Seal all files in session-scoped storage directory.
- Expose sealed artifacts strictly through read-only MCP URI scheme `desktop://evidence/...`.

## Stop Conditions
- Sealed manifest generated with calculated SHA-256 digests and accessible via MCP resource URI.
