# Workflow: recover_stale_reference

## Goal
Deterministically recover when an attempted interaction fails due to an invalid or stale semantic reference (`STALE_REFERENCE`), caused by navigation, dynamic DOM updates, or observation epoch progression.

## Preconditions
1. Active session in state `ACTIVE`.
2. An action was attempted using a reference `ref` (e.g. `w1e3`) that returned error code `STALE_REFERENCE` or `TARGET_REPLACED`.

## Observation Strategy
1. Retrieve the metadata of the expired reference from the agent's recent context (e.g. target role, accessible name, text content, CSS selector, relative position).
2. Execute a fresh `desktop_inspect` on the current target to advance to the latest observation epoch.
3. Search the newly returned element tree for candidate nodes matching the previous node's attributes:
   - Priority 1: Exact role + exact accessible name (`role="button"`, `name="Submit"`).
   - Priority 2: Exact role + unique CSS selector / test-id.
   - Priority 3: Element text content match within same parent container.

## Decision Points
- **If exactly ONE candidate node matches**:
  - Re-map the interaction to the new active reference (e.g. `w2e4`) and re-verify actionability before acting.
- **If MULTIPLE candidate nodes match**:
  - Ambiguous target. Do NOT guess. Inspect enclosing container or parent labels to disambiguate.
- **If ZERO candidate nodes match**:
  - Element was deleted or navigated away. Check if application transitioned to a success screen or error state.

## Allowed Actions
- `desktop_inspect`
- `desktop_click` (with verified newly re-mapped ref)
- `desktop_collect_evidence`

## Verification Strategy
- Verify that the newly selected reference has an afford point in the current viewport.
- Verify that the target epoch matches the current active session epoch.

## Failure Handling
- If re-resolution fails after 2 attempts, fail explicitly with `RECOVERY_FAILED` and notify the user rather than entering an infinite retry loop.

## Evidence Strategy
- Log the stale reference ID, target attributes, and the newly assigned active reference ID in the telemetry ledger.

## Stop Conditions
- Successful re-dispatch using re-resolved active reference.
- Deterministic abort if element genuinely disappeared from application DOM.
