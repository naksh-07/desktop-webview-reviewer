# Document 22: Antigravity Correlation Bridge & Agent Experience

## 1. Overview and Sovereignty Boundary

The **Antigravity Agent Experience Correlation Bridge** connects structured controlling agent activity (turns, tool calls, subagents, corrections, artifacts) with the persisted reality of Desktop WebView Reviewer (DWR) runtime experience (sessions, missions, actions, forensic evidence, failures, bounded recoveries, tripartite verdicts).

This milestone is strictly **correlation and descriptive historical observation only**:
- It is **NOT** an autonomous feedback loop.
- It is **NOT** an agent controller.
- It is **NOT** an Antigravity replacement.

### Architecture H Remains Frozen

```text
Antigravity Agent (Controlling Agent)
      │
      │  owns WHAT & WHY:
      │  - Mission intent & strategy
      │  - Reasoning & delegation
      │  - User interaction
      │  - Final interpretation
      │
      │ (optional structured events via lifecycle hooks)
      ▼
Antigravity Hook / Event Adapter
      │
      ▼
Privacy + Sanitization Boundary (Zero-Knowledge)
      │
      ▼
DWR Experience Correlation Bridge
      │
      ├────────────────────────┐
      ▼                        ▼
Experience Store (SQLite v3)   DWR Runtime
                               │
                               │  owns HOW:
                               │  - Desktop reality inspection
                               │  - Target resolution & physical input
                               │  - Settlement & verification
                               │  - Forensic evidence & diagnostics
                               │  - Bounded recovery
                               ▼
                      Trace / Evidence / Verification /
                      Failure / Recovery
```

---

## 2. Supported Event Contract

The bridge consumes a small, normalized, versioned event contract (`AgentEventEnvelope`, schema version `"1.0"`). It never attempts to capture everything Antigravity knows.

### Supported Event Types (`AgentEventType`)

| Event Type | Trigger Point | Mapped Antigravity Hook |
| :--- | :--- | :--- |
| `AGENT_SESSION_STARTED` | New agent session/conversation begins | Session start / PreInvocation |
| `AGENT_SESSION_COMPLETED` | Agent execution loop terminates | `Stop` |
| `AGENT_TURN_STARTED` | Turn step starts before model invocation | `PreInvocation` |
| `AGENT_TURN_COMPLETED` | Turn step finishes after model invocation | `PostInvocation` |
| `AGENT_TOOL_STARTED` | Tool execution initiated | `PreToolUse` |
| `AGENT_TOOL_COMPLETED` | Tool execution succeeded | `PostToolUse` |
| `AGENT_TOOL_FAILED` | Tool execution returned error | `PostToolUse` (with `error`) |
| `AGENT_SUBAGENT_STARTED` | Subagent specialist launched | Specialist lifecycle |
| `AGENT_SUBAGENT_COMPLETED` | Subagent specialist completed mandate | Specialist lifecycle |
| `AGENT_SUBAGENT_FAILED` | Subagent specialist failed | Specialist lifecycle |
| `AGENT_ARTIFACT_CREATED` | Artifact metadata registered | Artifact creation |
| `AGENT_CORRECTION` | Agent detected self-error | Error correction |
| `AGENT_USER_CORRECTION` | User corrected or retried request | User interaction |

### Conceptual Event Envelope

```json
{
  "event_id": "aevt_9b1a2c3d4e5f6071",
  "event_type": "AGENT_TOOL_COMPLETED",
  "event_schema_version": "1.0",
  "conversation_id": "037b7c49-c47d-4156-96db-2866cfd794a2",
  "turn_id": "turn_4",
  "agent_id": "lead_orchestrator",
  "parent_agent_id": null,
  "subagent_id": null,
  "tool_name": "desktop_click",
  "tool_category": "mcp",
  "success": true,
  "error_class": null,
  "duration_ms": 120.5,
  "timestamp": 1725624000.123,
  "iso_timestamp": "2026-09-06T12:00:00.123Z",
  "workspace_id": "C:/Projects/WebApp",
  "project_id": "WebApp",
  "artifact_reference": null,
  "correlation_id": "sess_dwr_001",
  "safe_summary": {
    "action_type": "CLICK",
    "target_role": "button",
    "plane": "NATIVE"
  }
}
```

Optional fields remain optional. No values are manufactured.

---

## 3. Privacy Boundary & Tool Argument Sanitization

The bridge enforces its own defensive sanitization before any data reaches the Experience Store (`AgentEventSanitizer`).

### Strictly Prohibited and Blocked

The following data categories are **never persisted** and cause immediate rejection or redaction:
- Raw chain-of-thought, model thinking, or hidden reasoning traces
- Unfiltered model transcripts and raw prompts
- Passwords, secret keys, private keys, and authorization headers
- API keys, Bearer tokens, GitHub tokens, Slack tokens, and JWTs
- Cookies (`cookie`, `cookies`, session tokens)
- Unrestricted filesystem dumps or DOM trees (>32KB strings)

### Tool Argument Sanitization (`sanitize_tool_args`)

Raw tool arguments are never stored verbatim. Instead, a safe structural summary is created:

1. **`desktop_type`**:
   - **CRITICAL**: The typed text itself is **NEVER** stored.
   - Preserved: `action_type = "TYPE_TEXT"`, `input_present = True`, `input_length = 14`.
2. **`desktop_click`**:
   - Preserved: `action_type = "CLICK"`, `target_role = "button"`, `target_kind = "element"`, `plane = "NATIVE"`.
   - Raw locators, page text, and private DOM snippets are stripped.
3. **`desktop_launch`**:
   - Preserved: `executable_name = "calc.exe"` (basename only), `args_count = 2`.
   - Full command-line flags and arguments that might contain secrets are stripped.
4. **`desktop_press_key`**:
   - Preserved: `key = "Enter"`.
5. **`run_command`**:
   - Preserved: `command_bin = "npm"` (binary basename only).

---

## 4. Correlation Model

Correlation maps between Antigravity identifiers and DWR runtime reality:

```text
Antigravity
   ├── conversation_id
   ├── turn_id
   ├── tool_call_id
   └── subagent_id
          │
          │ Relational Link (agent_dwr_correlations)
          ▼
DWR Runtime
   ├── session_id
   ├── mission_id
   ├── action_id
   └── evidence_id
```

Where a correlation can be established confidently, an explicit `AgentDwrCorrelationRecord` is persisted. Where it cannot, the agent event is preserved independently without fabricating relationships.

---

## 5. Correlation Confidence Taxonomy

Correlation uncertainty is explicitly modeled in SQLite:

| Confidence | Rule / Conditions | Example |
| :--- | :--- | :--- |
| `EXACT` | Explicit correlation ID matches DWR session or action; or tool call explicitly passes `session_id` argument; or direct DWR tool execution during an active DWR action. | MCP tool call `desktop_click` invoked on active review session. |
| `HIGH` | Same `conversation_id` during active DWR session, and tool call occurs within $\le 5.0$ seconds of action settlement. | Agent invokes tool immediately preceding DWR action. |
| `MEDIUM` | Same `conversation_id` or `project_id` matching active session within sliding window ($\le 60.0$ seconds), outside tight action window. | Agent turn step occurs while review session is active. |
| `LOW` | Same `project_id` or workspace context but loose temporal proximity ($> 60.0$ seconds or historical inference). | Historical review in same project without active session. |
| `UNKNOWN` | Insufficient matching parameters. | Unmatched background agent task. |

---

## 6. User Correction Model

User corrections provide high-value signals for understanding why reviews failed:
- **Taxonomy** (`UserCorrectionType`):
  - `AGENT_MADE_ERROR`
  - `USER_CORRECTED_AGENT`
  - `USER_REJECTED_RESULT`
  - `USER_RETRIED_REQUEST`
  - `USER_CHANGED_TARGET`
- Captures sanitized metadata: `correction_type`, `agent_session_id`, `turn_id`, `related_dwr_session_id`, `related_action_id`, and `classification_details`.
- Raw user conversational dialogue is **not** stored by default.

---

## 7. Agent Artifact References

Antigravity artifacts (e.g. plans, research notes) are recorded as lightweight references in `agent_artifacts`:
- `artifact_id`, `artifact_type`, `safe_reference` (relative path), `timestamp`, `metadata`.
- DWR **never duplicates large artifact binaries** into SQLite.
- DWR does **not** manage external artifact lifecycle.

---

## 8. DWR ↔ Agent Outcome Linking & Historical Queries

The Experience Store enables historical descriptive queries answering:

1. **Preceding Activity**: Which agent tools preceded a DWR session?
   - `store.get_agent_tool_calls_for_session(dwr_session_id)`
2. **Action Causality**: Which agent tool call resulted in a physical DWR action?
   - `store.get_agent_activity_for_dwr_action(dwr_action_id)`
3. **Outcome Correlation**: Which tool categories correlate with PASS, FAIL, or UNVERIFIED reviews?
   - `store.get_agent_tool_calls_by_outcome(verdict)`
4. **Recovery Frequency**: How often did specific agent tool workflows require recovery?
   - `store.get_recovery_frequency_by_agent_tool_category()`
5. **Corrections After Failure**: Which user corrections followed DWR failures?
   - `store.get_user_corrections_for_failures()`

---

## 9. Standalone Operation & Failure Independence

The bridge is strictly optional and decoupled:
- **Antigravity Absent**: Reviewer executes normally with full inspection, verification, and forensic capabilities.
- **Bridge Disabled**: Set `DESKTOP_REVIEWER_ANTIGRAVITY_BRIDGE_ENABLED=false` or configure `enabled=False`; zero overhead, returns immediately.
- **Malformed Payloads**: Ingesting invalid or malicious payloads drops the event safely, increments `events_rejected`, and returns `None` without interrupting DWR.
- **Store Unavailable**: If SQLite encounters a disk lock or closed connection, the bridge handles it silently in fail-safe mode. Live desktop review continues uninterrupted.

---

## 10. CLI, Doctor, and Passive MCP Resource

### Doctor Diagnostic Check
`desktop_webview_reviewer doctor` includes Check 9: `antigravity_bridge`:
- Reports enabled state, event counts, correlation records, and blocked privacy violations.
- Never exposes raw event payloads or private arguments.

### Passive MCP Resource
`desktop://system/experience` exposes safe aggregate metadata:
- Total `agent_sessions`, `agent_tool_calls`, `correlations`, `corrections`, and `privacy_violations_blocked`.
- **Primary Tool Invariant**: Exactly 12 primary MCP tools preserved. Zero new tools added.

---

## 11. Proscription Against Scraping Internal Antigravity Storage

Desktop WebView Reviewer **strictly prohibits scraping Antigravity internal files**:
- No crawling of Antigravity transcript directories (`transcript.jsonl` / `transcript_full.jsonl`).
- No reading of private sidecar SQLite databases.
- No parsing of internal IDE configuration or hidden prompt logs.
- No tailing undocumented debug files.

The only integration contract is the **clean structured event boundary** provided via Antigravity lifecycle hooks (`PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation`, `Stop`).

---

## 12. No Autonomous Feedback Loops

Prompt 3 establishes correlation and observation only. It explicitly does **not** implement:
- Automatic prompt rewriting
- Automatic skill modification
- Automatic rule generation
- Automatic recovery policy modification
- Automatic model selection changes

Experience data remains an audit trail and historical ledger, never an authoritative or autonomous agent controller.
