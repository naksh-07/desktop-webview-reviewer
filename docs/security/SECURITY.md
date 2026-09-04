# Security Model & Threat Mitigation

## 1. Core Threat Model

`desktop-webview-reviewer` operates at the boundary between untrusted desktop application environments and autonomous AI agents. Untrusted desktop applications, embedded webviews, and external web content may contain adversarial payloads designed to compromise the supervising agent or escape host process boundaries.

The system enforces six foundational security invariants:

1. **UI Content is Data, Never Instructions:** All text extracted from the DOM, accessibility trees, window titles, dialogs, and notifications is untrusted data.
2. **Filesystem Boundaries are Strictly Confined:** All file operations are subject to path normalization, directory containment, device namespace rejection, and UNC network path rejection.
3. **Process Identity is Non-Forgeable:** Process supervision tracks both OS PID and process creation timestamps to prevent PID reuse race conditions.
4. **References and Sessions are Cryptographically Scoped:** Semantic reference tokens and sessions are strictly isolated; cross-session reference poisoning is impossible.
5. **Execution Authority is Isolated:** MCP tools provide declarative control, not arbitrary code execution. JavaScript evaluation is restricted by default to isolated V8 utility realms (`__utility_world__`).
6. **Forensic Evidence is Immutable:** Generated evidence bundles are cryptographically sealed with SHA-256 manifests and stored in restricted directories.

---

## 2. Adversarial Protection Matrix

| Attack Class | Threat Vector | Mitigation Strategy | Implemented In |
|---|---|---|---|
| **Prompt Injection** | Hostile instructions embedded in web text, accessible names, or window titles | All UI text enveloped as untrusted data (`{"type": "untrusted_ui_data", "value": ...}`); never passed as system prompts | `runtime/mcp/security.py` |
| **Path Traversal** | `..\..\Windows\System32\...`, absolute paths, symlinks | Strict path resolution with canonicalization; rejection of traversals escaping working directory or evidence root | `runtime/mcp/security.py`, `resources.py` |
| **Device & UNC Paths** | `\\.\COM1`, `\\?\Volume...`, `\\evil.corp\share` | Explicit regex rejection of NT device namespaces (`\\.\`, `\\?\`), DOS device names (`CON`, `PRN`, `AUX`, `NUL`), and UNC network paths | `runtime/mcp/security.py` |
| **PID Reuse Attack** | Terminating a PID after original process exited and OS recycled PID | Double-token verification: PID + `expected_create_time` matched before sending Win32 signals or killing process trees | `core/cleanup.py`, `runtime/process.py` |
| **Cross-Session Poisoning** | Forged reference tokens (`w1e1`) passed across sessions | Reference tokens are strictly scoped to `(session_id, epoch)`. Unmapped tokens reject with `STALE_REFERENCE` or `INVALID_ARGUMENT` | `runtime/reference_registry.py` |
| **JS Evaluation Escape** | Infinite loops, giant object allocations, cyclic DOM graphs | Default evaluation in `__utility_world__`; expression length capped at 10k chars; timeout capped; cyclic graphs serialized to safe tokens; strings truncated | `runtime/mcp/tools/evaluation.py` |
| **Evidence Tampering** | Mutating screenshots or manifests post-test | SHA-256 byte-for-byte manifest sealing; read-only verification; tampering raises `EVIDENCE_INTEGRITY_ERROR` | `runtime/evidence_store.py` |
| **Resource URI Traversal** | `desktop://evidence/../../etc/passwd` | Resource URIs validated against strict regex (`^desktop://(evidence\|sessions\|session\|target)/...`) and verified to remain inside evidence root | `runtime/mcp/resources.py` |

---

## 3. Evaluation Sandboxing Semantics

The `desktop_evaluate` tool provides controlled script execution with explicit realm isolation:

- **Isolated Utility Realm (`in_main_world = False`, Default):**
  Executes in a dedicated V8 execution context (`__utility_world__`). It shares the same underlying DOM and layout tree as the application, but possesses a completely isolated `window` object. Application scripts cannot inspect, intercept, or tamper with objects created in this realm.
- **Main World Realm (`in_main_world = True`):**
  Executes in the application's primary context. Restricted for use cases where application-defined global variables (e.g. Redux stores, custom WebChannel interfaces) must be observed.

All evaluation outputs undergo recursive sanitization:
- Circular references are resolved to `[CIRCULAR_OR_DEEP_REFERENCE]`.
- Binary payloads are summarized as `[BINARY_DATA: N bytes]`.
- Strings exceeding 10,000 characters are safely truncated.
