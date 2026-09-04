# MCP Tools Reference — Desktop WebView Reviewer Control Plane

The MCP server provides **12 cohesive, high-level control tools**. Low-level implementation details (Win32 P/Invoke, CDP protocol packets, coordinate math) are encapsulated within the authoritative runtime.

## 1. Lifecycle Tools

### `desktop_launch`
Launches a target desktop application executable under supervised process monitoring.
- **Parameters**:
  - `executable_path` (str, required): Absolute path to the binary. Prohibited: shells (`cmd.exe`, `powershell.exe`), interpreters without script, UNC network paths, device namespaces.
  - `args` (list[str], optional): Command line arguments.
  - `cdp_port` (int, optional): Expected or injected CDP remote debugging port (1024-65535).
  - `lease_timeout_sec` (int, optional): Lease expiration time (default: 300s).
- **Returns**: `session_id`, `pid`, `hwnd`, `cdp_port`, `lifecycle_state`.

### `desktop_attach`
Attaches to an already-running desktop application process or window on the host.
- **Parameters**:
  - `pid` (int, optional): Process ID of the running target.
  - `hwnd` (int, optional): Top-level window handle.
  - `cdp_port` (int, optional): Discovered or configured CDP remote debugging port.
- **Process Safety**: On session close, attached processes are **never** terminated.

### `desktop_close`
Cleanly terminates or detaches from a session.
- **Parameters**:
  - `session_id` (str, required): Session ID.
  - `reason` (str, optional): Reason for closure.

### `desktop_list_sessions`
Lists all active or historical automation sessions managed by the local daemon.

---

## 2. Observation Tools

### `desktop_inspect`
Captures dual-perspective observation of the application and registers ephemeral semantic references.
- **Parameters**:
  - `session_id` (str, required).
  - `target_id` (str, optional): Specific CDP target or native window to inspect.
  - `depth` (int, optional): Traversal depth for element tree.
  - `include_styles` (bool, optional): Include computed style metrics.
- **Returns**: Element tree with semantic refs (`w1e1`, `n1e2`), bounding boxes, accessible roles, and untrusted UI text.

---

## 3. Action Tools

### `desktop_click`
Dispatches a click to the afford point of a referenced element.
- **Parameters**:
  - `session_id` (str, required).
  - `ref` (str, required): Active semantic reference (e.g. `w1e1`).
  - `button` (str, optional): `"left"`, `"right"`, `"middle"`.
  - `click_count` (int, optional): 1 for single, 2 for double click.

### `desktop_type`
Dispatches keyboard text entry to a referenced input element.
- **Parameters**:
  - `session_id` (str, required).
  - `ref` (str, required).
  - `text` (str, required): Text string to type (bounded, sanitized).
  - `clear_existing` (bool, optional): Select all and replace.

### `desktop_press_key`
Dispatches a special key press (e.g. `Enter`, `Tab`, `Escape`, `ArrowDown`).
- **Parameters**:
  - `session_id` (str, required).
  - `key` (str, required): Virtual key or key identifier.
  - `modifiers` (list[str], optional): `["Control", "Shift", "Alt"]`.

### `desktop_hover`
Moves mouse cursor to element afford point to trigger hover states or tooltips.

### `desktop_scroll`
Dispatches mouse wheel or scroll delta to scroll the document or element viewport.

---

## 4. Evaluation & Diagnostics

### `desktop_evaluate`
Executes bounded JavaScript in the target webview context.
- **Parameters**:
  - `session_id` (str, required).
  - `expression` (str, required): JavaScript snippet (max 10,000 chars, bounded timeout).
  - `in_main_world` (bool, optional): `False` runs in isolated `__utility_world__` (default). `True` runs in page's main JavaScript context.

---

## 5. Forensic Evidence Tools

### `desktop_collect_evidence`
Packages and cryptographically seals session state into an immutable audit manifest.
- **Parameters**:
  - `session_id` (str, required).
  - `action_id` (str, optional): Specific action to correlate.
- **Returns**: `evidence_id`, `manifest_uri`, `verdict` (`PASS`/`FAIL`/`UNVERIFIED`), `artifacts` list.
