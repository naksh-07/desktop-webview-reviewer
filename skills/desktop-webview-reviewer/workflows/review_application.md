# Workflow: review_application

## Goal
Perform a comprehensive, end-to-end inspection, health evaluation, and baseline review of a desktop application containing embedded webviews.

## Preconditions
1. Target application binary is available on the local filesystem, or the application is already running on the Windows host.
2. If launching a new instance, remote debugging port or environment variables must be configured if required by the target engine.
3. Windows desktop is active and not locked.

## Observation Strategy
1. Discover the process identity and verify native window handle (`HWND`), geometry, and DWM visibility.
2. Attach to the CDP endpoint and list all active inspectable targets.
3. Perform a root observation (`desktop_inspect`) to acquire initial semantic references (`w1e1`, etc.).
4. Check both Native plane accessibility tree and Web plane DOM tree for structural completeness.

## Decision Points
- **If window is minimized or cloaked**: Bring window to foreground and verify geometry $\ge 30 \times 30$ before interacting.
- **If multiple webview targets exist**: Select the primary application frame by matching URL or window title; avoid background devtools or service workers.
- **If application reports an error banner**: Record the error in diagnostic state and inspect error details before continuing.

## Allowed Actions
- `desktop_launch` or `desktop_attach`
- `desktop_inspect`
- `desktop_scroll` (to inspect full document)
- `desktop_collect_evidence`
- `desktop_close`

## Verification Strategy
- Verify window is responsive via Win32 `SendMessageTimeoutW`.
- Verify DOM document ready state is `complete` or `interactive`.
- Verify key UI components (navigation bar, main content container, action buttons) are rendered with valid screen bounding boxes.

## Failure Handling
- **Launch timeout**: Verify executable path and check if a secondary launcher process spawned the main GUI process.
- **Target discovery failure**: Confirm application started with remote debugging enabled (e.g. `--remote-debugging-port` or `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`).

## Evidence Strategy
- Capture dual screenshot (native OS window + webview viewport).
- Record initial DOM accessibility snapshot and runtime capability matrix in sealed manifest.

## Stop Conditions
- Successful initial review with all primary UI surfaces inventoried and sealed in evidence.
- Fatal launch failure after diagnostic enumeration.
