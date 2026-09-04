# Workflow: inspect_dialog_block

## Goal
Detect, inspect, and handle blocking dialogs (native Win32 modal dialogs, JavaScript alerts, file pickers, or in-page HTML modal overlays) preventing interaction with the main desktop application.

## Preconditions
1. Active session in state `ACTIVE` or `DEGRADED`.
2. Actions on the primary webview fail or appear blocked, or a dialog opened unexpectedly.

## Observation Strategy
1. **Check Native Plane Modals**:
   - Enumerate top-level and child windows owned by target PID using Win32 `EnumThreadWindows` / `GetWindow`.
   - Check for window class `#32770` (standard Windows dialog box) or windows with `WS_POPUP` style.
   - Check if main window has `WS_DISABLED` (indicating a modal child dialog has disabled parent input).
2. **Check Web Plane Modals**:
   - Check for active JavaScript dialogs via CDP `Page.javascriptDialogOpening`.
   - Check DOM for `<dialog open>`, `<div role="dialog">`, or overlay backdrops with `position: fixed; z-index > 1000`.

## Decision Points
- **If native Win32 modal is present**:
  - The webview cannot process mouse or keyboard events until the modal is dismissed.
  - Action: Inspect the dialog window controls via Win32/UIA, locate the dismiss/confirm button, and click it via native input.
- **If CDP JavaScript dialog (`alert`, `confirm`, `prompt`) is open**:
  - Webview execution is suspended.
  - Action: Handle via CDP `Page.handleJavaScriptDialog` with appropriate action (`accept` or `dismiss`).
- **If HTML DOM modal overlay is present**:
  - Main content is covered by an element with higher stacking order.
  - Action: Inspect the modal container in the DOM; locate the close button (`w1e...`) or complete the dialog form.

## Allowed Actions
- `desktop_inspect`
- `desktop_click` (on dialog controls)
- `desktop_press_key` (e.g. `Escape` or `Enter` to dismiss)
- `desktop_collect_evidence`

## Verification Strategy
- Verify that dismissing the dialog removes the `WS_DISABLED` style from the parent window.
- Verify that webview event handling resumes and underlying elements become actionable.

## Failure Handling
- If dialog cannot be dismissed via standard keys or buttons, collect screenshot of dialog text and notify operator.

## Evidence Strategy
- Capture native screenshot of the dialog window with its parent window in the background.
- Record dialog title, text content, and button options in evidence manifest.

## Stop Conditions
- Dialog successfully handled and dismissed, with main application restored to interactive state.
- Unhandled modal blocked, requiring operator intervention.
