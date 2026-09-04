# Forensic Verdict Model — Tripartite Determination

The Desktop WebView Reviewer enforces an uncompromising tripartite forensic evaluation standard:

```text
               ┌──────────────────────┐
               │ Physical Application │
               │   Execution & State  │
               └──────────┬───────────┘
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
   [PASS CRITERIA]                  [DEFECT DETECTED]
   - OS Window Visible              - State Assertion Failed
   - Window Responsive              - Unexpected Error Shown
   - Target Hit-Testable            - Target Vanished / Failed
   - Input Delivered                
   - State Changed As Expected      
   - SHA-256 Dual Screenshots       
         │                                 │
         ▼                                 ▼
       PASS                               FAIL
         ▲
         │ (NEVER ALLOWED)
         │
   [INCOMPLETE PROOF]
   - Window minimized/cloaked
   - Headless / Ghost Port
   - Occluded afford point
   - CDP disconnected in settlement
         │
         ▼
     UNVERIFIED
```

## Verdict Rules
1. **`PASS` Requirements**:
   - The native OS window must be verified visible (`IsWindowVisible`, not iconic, not DWM-cloaked).
   - The target afford point must be within visible client coordinates.
   - Action dispatch receipt must indicate hardware/CDP delivery.
   - Settlement must complete without process hang or disconnect.
   - Post-state observation must corroborate expected state changes.
   - Cryptographic hashes of all artifacts must be sealed in the manifest.

2. **`FAIL` Requirements**:
   - The test environment was fully verified and actionable, but the application logic produced an incorrect result or error.

3. **`UNVERIFIED` Requirements**:
   - Any gap in the chain of physical custody prevents awarding `PASS`.
   - Examples: running in headless mode, window occluded by native dialog, CDP port connection without OS window, or missing post-state proof.

> **RULE OF TRUTH**: `UNVERIFIED` is never a defect in the application; it is an honest statement that physical proof was inconclusive. `UNVERIFIED` must NEVER be silently upgraded to `PASS`.
