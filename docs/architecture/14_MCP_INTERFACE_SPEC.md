# Architecture Document 14: MCP Interface Specification

**Document ID:** `docs/architecture/14_MCP_INTERFACE_SPEC.md`  
**Status:** APPROVED (Phase 0 Deliverable)  
**Author:** Principal Software Architect  
**Protocol Baseline:** Model Context Protocol (MCP) Normative Specification (2024–2026)  
**Target Repository:** `desktop-webview-reviewer`  

---

## 1. Architectural Philosophy & Boundaries

The MCP Control Plane operates strictly as a **Context and Control Gateway**, not an execution data plane:
1. **Tool Economy:** Bounded to exactly 12 high-level, action-observation fused tools to eliminate cognitive fatigue and context token bloat (resolving the Track 06 finding where 57 tools degraded model reasoning).
2. **Action-Observation Fusion:** Mutating tools default to `include_snapshot: true`, returning post-action accessibility state in the same turn to halve multi-turn latency.
3. **Dual-Modal Visual Payloads:** Immediate turn verification returns downscaled thumbnails or bounded element crops in `ImageContent`. High-resolution PNGs are saved to disk and referenced by immutable MCP Resource URIs to prevent the fatal 64 KB Windows stdio buffer deadlock identified in Track 10.
4. **Untrusted UI Text Envelope:** Text scraped from the target application (titles, DOM, buttons) is wrapped in structured JSON data objects and never merged into LLM instruction channels.

---

## 2. Complete MCP Tool Catalog (12 Cohesive Tools)

```
MCP Tool Surface Overview
┌────┬───────────────────────────┬──────────────┬────────────────────────────────────────────────────────┐
│ #  │ Tool Name                 │ Category     │ Primary Responsibility                                 │
├────┼───────────────────────────┼──────────────┼────────────────────────────────────────────────────────┤
│ 1  │ desktop_launch            │ Lifecycle    │ Launch application under Win32 Job Object supervision  │
│ 2  │ desktop_attach            │ Lifecycle    │ Attach to running app by PID, HWND, or CDP port        │
│ 3  │ desktop_inspect           │ Observation  │ Capture dual-perspective a11y snapshot annotated w/refs│
│ 4  │ desktop_click             │ Action       │ Click element ref with auto-waiting & actionability    │
│ 5  │ desktop_type              │ Action       │ Type text into element ref with full event bubbling    │
│ 6  │ desktop_press_key         │ Action       │ Dispatch navigation or shortcut key combinations       │
│ 7  │ desktop_hover             │ Action       │ Hover pointer over element ref with motion settlement  │
│ 8  │ desktop_scroll            │ Action       │ Scroll container or window to bring target into view   │
│ 9  │ desktop_handle_dialog     │ Action       │ Detect and interact with native/web modal dialogs      │
│ 10 │ desktop_evaluate          │ Inspection   │ Safely evaluate JS in isolated webview utility realm   │
│ 11 │ desktop_assert            │ Verification │ Auto-retrying assertion on element state or text       │
│ 12 │ desktop_collect_evidence  │ Forensics    │ Package cryptographic forensic bundle & verdict        │
└────┴───────────────────────────┴──────────────┴────────────────────────────────────────────────────────┘
```

---

## 3. Tool Specifications & Schemas

### 3.1 `desktop_launch`
Spawns a target desktop application within a managed Windows Job Object.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "executable_path": { "type": "string", "description": "Absolute path to executable (.exe)" },
    "args": { "type": "array", "items": { "type": "string" }, "default": [] },
    "working_directory": { "type": "string" },
    "engine_hint": { "type": "string", "enum": ["auto", "qtwebengine", "webview2", "electron", "chromium", "native_only"], "default": "auto" },
    "remote_debugging_port": { "type": "integer", "description": "Explicit CDP port if pre-configured" },
    "timeout_sec": { "type": "integer", "default": 30 }
  },
  "required": ["executable_path"]
}
```
* **Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "pid": { "type": "integer" },
    "hwnd": { "type": "integer" },
    "capabilities": { "type": "array", "items": { "type": "string" } },
    "active_plane": { "type": "string", "enum": ["WEBVIEW_DOM", "NATIVE_SHELL"] },
    "initial_snapshot": { "type": "string" },
    "observation_epoch": { "type": "integer" }
  },
  "required": ["session_id", "pid", "hwnd", "capabilities", "active_plane", "initial_snapshot"]
}
```

---

### 3.2 `desktop_attach`
Attaches to an existing running application window or process without re-launching.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "hwnd": { "type": "integer", "description": "Target window handle (HWND)" },
    "pid": { "type": "integer", "description": "Target process ID (PID)" },
    "window_title_pattern": { "type": "string", "description": "Regex or substring for window title" },
    "cdp_port": { "type": "integer", "description": "Embedded CDP debugging port if known" }
  }
}
```
* **Output Schema:** Identical to `desktop_launch`.

---

### 3.3 `desktop_inspect`
Captures the dual-perspective state of the active window and returns a compact, ref-annotated tree.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "perspective": { "type": "string", "enum": ["auto", "webview", "native", "both"], "default": "auto" },
    "diff_only": { "type": "boolean", "default": false, "description": "Return only mutated nodes since last epoch" },
    "max_depth": { "type": "integer", "default": 7 }
  },
  "required": ["session_id"]
}
```
* **Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "epoch_id": { "type": "integer" },
    "active_plane": { "type": "string" },
    "tree": { "type": "string", "description": "Compact YAML/Markdown accessibility tree with [ref=...]" },
    "is_diff": { "type": "boolean" },
    "element_count": { "type": "integer" },
    "window_forensics": {
      "type": "object",
      "properties": {
        "title": { "type": "string" },
        "is_visible": { "type": "boolean" },
        "is_cloaked": { "type": "boolean" },
        "bounds": { "type": "array", "items": { "type": "integer" } }
      }
    }
  },
  "required": ["epoch_id", "active_plane", "tree", "is_diff"]
}
```

---

### 3.4 `desktop_click`
Clicks an interactive affordance identified by an ephemeral reference.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "ref": { "type": "string", "description": "Interaction ref token (e.g. 'w1e4')" },
    "click_count": { "type": "integer", "default": 1 },
    "button": { "type": "string", "enum": ["left", "right", "middle"], "default": "left" },
    "include_snapshot": { "type": "boolean", "default": true, "description": "Fuse post-action snapshot in output" },
    "timeout_ms": { "type": "integer", "default": 5000 }
  },
  "required": ["session_id", "ref"]
}
```
* **Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "executed": { "type": "boolean" },
    "duration_ms": { "type": "number" },
    "action_receipt": { "type": "string" },
    "post_snapshot": { "type": "string", "description": "Fresh a11y tree if include_snapshot=true" },
    "new_epoch_id": { "type": "integer" }
  },
  "required": ["executed", "duration_ms"]
}
```

---

### 3.5 `desktop_type`
Types text into an input field with authentic event bubbling.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "ref": { "type": "string" },
    "text": { "type": "string" },
    "clear_existing": { "type": "boolean", "default": true },
    "press_enter": { "type": "boolean", "default": false },
    "include_snapshot": { "type": "boolean", "default": true }
  },
  "required": ["session_id", "ref", "text"]
}
```
* **Output Schema:** Identical to `desktop_click`.

---

### 3.6 `desktop_press_key`
Sends keyboard shortcuts or navigation keys.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "key": { "type": "string", "description": "e.g. 'Enter', 'Tab', 'Escape', 'Control+A'" },
    "include_snapshot": { "type": "boolean", "default": true }
  },
  "required": ["session_id", "key"]
}
```

---

### 3.7 `desktop_hover`
Hovers over an element to trigger tooltips or CSS hover states.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "ref": { "type": "string" },
    "include_snapshot": { "type": "boolean", "default": true }
  },
  "required": ["session_id", "ref"]
}
```

---

### 3.8 `desktop_scroll`
Scrolls an element or page container.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "ref": { "type": "string", "description": "Element to scroll or scroll into view" },
    "direction": { "type": "string", "enum": ["up", "down", "into_view"], "default": "into_view" },
    "delta_y": { "type": "integer", "default": 300 },
    "include_snapshot": { "type": "boolean", "default": true }
  },
  "required": ["session_id"]
}
```

---

### 3.9 `desktop_handle_dialog`
Inspects and interacts with blocking Win32 modal dialogs or browser JavaScript alerts.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "action": { "type": "string", "enum": ["accept", "cancel", "set_file_path", "inspect"] },
    "file_path": { "type": "string", "description": "Absolute file path for file picker dialogs" }
  },
  "required": ["session_id", "action"]
}
```
* **Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "handled": { "type": "boolean" },
    "dialog_type": { "type": "string", "enum": ["WIN32_FILE_PICKER", "WIN32_MESSAGEBOX", "WEB_JAVASCRIPT_DIALOG", "NONE"] },
    "dialog_title": { "type": "string" },
    "message": { "type": "string" }
  },
  "required": ["handled", "dialog_type"]
}
```

---

### 3.10 `desktop_evaluate`
Evaluates a JavaScript expression safely inside the webview's isolated utility realm.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "expression": { "type": "string", "description": "JavaScript expression to evaluate" },
    "in_main_world": { "type": "boolean", "default": false, "description": "Evaluate in app main world instead of utility world" }
  },
  "required": ["session_id", "expression"]
}
```
* **Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "result": { "description": "Serialized JSON evaluation result" },
    "exception_details": { "type": "string" }
  }
}
```

---

### 3.11 `desktop_assert`
Performs an auto-retrying polling assertion on UI state before proceeding.
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "ref": { "type": "string" },
    "assertion": { "type": "string", "enum": ["is_visible", "is_hidden", "has_text", "is_enabled"] },
    "expected_text": { "type": "string" },
    "timeout_ms": { "type": "integer", "default": 5000 }
  },
  "required": ["session_id", "ref", "assertion"]
}
```
* **Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "passed": { "type": "boolean" },
    "duration_ms": { "type": "number" },
    "actual_value": { "type": "string" },
    "error": { "type": "string" }
  },
  "required": ["passed", "duration_ms"]
}
```

---

### 3.12 `desktop_collect_evidence`
Packages an immutable forensic evidence bundle and evaluates the Tripartite Verdict (`PASS`, `FAIL`, `UNVERIFIED`).
* **Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "test_name": { "type": "string" },
    "expected_outcome_summary": { "type": "string" }
  },
  "required": ["session_id", "test_name"]
}
```
* **Output Schema:**
```json
{
  "type": "object",
  "properties": {
    "verdict": { "type": "string", "enum": ["PASS", "FAIL", "UNVERIFIED"] },
    "verdict_rationale": { "type": "string" },
    "evidence_id": { "type": "string" },
    "evidence_resource_uri": { "type": "string" },
    "proof_metrics": {
      "type": "object",
      "properties": {
        "native_window_visible": { "type": "boolean" },
        "input_delivered": { "type": "boolean" },
        "dom_mutations_verified": { "type": "boolean" },
        "fatal_console_errors": { "type": "integer" }
      }
    },
    "thumbnail_base64": { "type": "string", "description": "Downscaled visual preview" }
  },
  "required": ["verdict", "verdict_rationale", "evidence_id", "evidence_resource_uri", "proof_metrics"]
}
```

---

## 4. MCP Resources Specification

MCP Resources expose passive, read-only system and audit data:

```
MCP Resource Endpoints
┌───────────────────────────────────────────────────┬────────────────────────────────────────────────────────┐
│ Resource URI Pattern                              │ Content Returned                                       │
├───────────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ desktop://sessions                                │ JSON array of active session states and leasetime      │
│ desktop://windows                                 │ JSON inventory of all top-level desktop windows        │
│ desktop://evidence/{evidence_id}                  │ Complete JSON audit bundle manifest (evidence.json)    │
│ desktop://evidence/{evidence_id}/screenshot/{type}│ Binary PNG image (type: "native" or "webview")         │
│ desktop://targets/{target_id}/logs                │ Ring buffer of console messages and stderr logs        │
│ desktop://targets/{target_id}/network             │ HAR or JSON log of intercepted HTTP/WS traffic         │
└───────────────────────────────────────────────────┴────────────────────────────────────────────────────────┘
```

---

## 5. MCP Prompts Specification

High-level slash-command user entry points:
1. **`audit_desktop_application`**:
   * *Arguments:* `executable_path` (string), `test_criteria` (string).
   * *Purpose:* Seeds the conversational turn with recommended verification checklists and executes an automated launch-and-inspect sequence.
2. **`investigate_ui_anomaly`**:
   * *Arguments:* `session_id` (string), `description` (string).
   * *Purpose:* Invokes forensics to diagnose why an expected window is un-clickable, hung, or cloaked.

---

## 6. Server-Side Sampling Policy

* **Strict Constraint:** Server-side LLM Sampling (`sampling/createMessage`) is **prohibited** from running recursive agentic execution loops.
* **Permitted Use:** Strictly restricted to **localized, non-mutating semantic disambiguation**—for example, evaluating whether a mutated DOM button labeled "Confirm Order" matches the user's historical query recipe "Submit Order" when an exact ref fails.
