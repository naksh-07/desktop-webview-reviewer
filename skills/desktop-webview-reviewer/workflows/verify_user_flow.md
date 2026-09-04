# Workflow: verify_user_flow

## Goal
Execute and forensically verify a multi-step user interaction flow (e.g. form filling, card review, navigation) ensuring that each action produces confirmed physical and application state transitions.

## Preconditions
1. Active session in operational state `ACTIVE`.
2. Target application window is visible, foregrounded, and unoccluded.
3. Defined sequence of expected user actions and expected resulting states.

## Observation Strategy
1. Before every step: run `desktop_inspect` to obtain fresh, valid semantic references (`w1e1`, `w1e2`).
2. Verify target element exists, is visible in viewport, and satisfies actionability criteria (enabled, non-zero geometry, hit-testable).
3. After dispatch: wait for settlement (network idle, layout stable).
4. Run post-state observation and evaluate assertions.

## Decision Points
- **If target reference is missing from inspection**:
  - Re-examine the current screen to check if previous action triggered a view transition or navigation.
- **If actionability indicates element is obscured**:
  - Check if a modal dialog, tooltip, or cookie consent overlay needs to be dismissed first.
- **If state assertion fails**:
  - Stop immediately. Do NOT blindly continue to subsequent steps in the flow.

## Allowed Actions
- `desktop_inspect`
- `desktop_click`
- `desktop_type`
- `desktop_press_key`
- `desktop_hover`
- `desktop_scroll`
- `desktop_collect_evidence`

## Verification Strategy
- Every action must return a valid `ActionReceipt` with status `DISPATCHED`.
- State change must be verified against expected values (e.g. text matches, element appears/disappears).
- Verdict per step: `PASS`, `FAIL`, or `UNVERIFIED`.

## Failure Handling
- On assertion failure: collect immediate forensic evidence of the unexpected state and report failure with exact diff.
- On action dispatch failure: check window focus and afford point coordinates.

## Evidence Strategy
- Collect evidence at key milestone steps and upon final flow completion or any failure.
- Record all action receipts and pre/post epoch deltas in the evidence manifest.

## Stop Conditions
- All flow steps successfully executed and verified with `PASS`.
- Any step fails verification with `FAIL` or `UNVERIFIED`.
