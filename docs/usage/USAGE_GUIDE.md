# Desktop WebView Reviewer — Usage Guide

## 1. Overview
`desktop-webview-reviewer` is a production-grade, agent-native automation and forensic review system for hybrid Windows desktop applications hosting embedded webviews (QtWebEngine, WebView2, Electron, CEF/Chromium).

It couples **Native Windows OS supervision** (Win32, DWM, Job Objects) with **Webview DevTools Protocol (CDP)** control plane into a cohesive dual-perspective system governed by **Architecture H**.

---

## 2. Prerequisites & Installation

### System Requirements
- **Operating System:** Windows 10 (Build 19041+) or Windows 11 (64-bit).
- **Python:** Version 3.10, 3.11, 3.12, or 3.13.
- **.NET Runtime (Optional for UIA3 sidecar):** .NET 8.0 SDK / Runtime (pure Win32 / CDP operates out-of-the-box without .NET).

### Local Installation
```powershell
# From repository root using uv (recommended)
uv sync

# Or standard pip installation
pip install -e .
```

### Self-Test & Diagnostics
Verify that your local system capabilities and environment meet all requirements:
```powershell
# Run environment diagnostics
desktop-webview-mcp --diagnostics

# Run deterministic capability self-test
desktop-webview-mcp --self-test
```

---

## 3. MCP Server Configuration

To connect an AI coding agent or MCP client (such as Google Antigravity, Claude Desktop, Cursor) to `desktop-webview-reviewer`, configure the client's MCP configuration file:

### Antigravity (`mcp_config.json`)
```json
{
  "mcpServers": {
    "desktop-webview": {
      "command": "uv",
      "args": ["run", "desktop-webview-mcp", "--transport", "stdio"]
    }
  }
}
```

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "desktop-webview": {
      "command": "python",
      "args": ["-m", "runtime.mcp.server", "--transport", "stdio"],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

---

## 4. Standard Agent Review Workflow

When reviewing a desktop application, the agent should follow this canonical discipline:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Launch / Attach: desktop_launch / desktop_attach        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Dual-Perspective Inspect: desktop_inspect (max_depth=5)  │
│    Obtain ephemeral reference token (e.g. w1e5)            │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Semantic Action: desktop_click / desktop_type / ...      │
│    Receive ActionReceipt with dispatch_status and post_epoch│
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. State Verification: desktop_assert                       │
│    Validate post-state change (visible / enabled / text)    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Sealed Evidence Collection: desktop_collect_evidence     │
│    Receive sealed manifest URI (desktop://evidence/...)     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Forensic Manifest Retrieval: MCP read_resource           │
│    Retrieve sha256-verified manifest with PASS/FAIL/UNVERIFIED│
└─────────────────────────────────────────────────────────────┘
```

### Key Rules for Agents
1. **Physical Reality Primacy:** DOM element visibility does not imply physical visibility. DWM occlusion outranks DOM layout.
2. **Ephemeral References:** Reference tokens (`w1e5`, `n1e2`) expire upon state mutations. Never cache references across interactions.
3. **Dispatch != Success:** A successful action dispatch only records receipt of physical input; verify with `desktop_assert`.
4. **Tripartite Verdict:** An assertion can return `PASS`, `FAIL`, or `UNVERIFIED`. Never upgrade `UNVERIFIED` to `PASS`.

---

## 5. Standalone CLI Tools

For manual inspection or continuous integration pipelines, standalone CLI tools are available:

- `desktop-webview-doctor`: System and prerequisite health check.
- `desktop-webview-launch`: Spawns application with debugging port and Job Object supervision.
- `desktop-webview-discover`: Scans for running targets and open CDP ports.
- `desktop-webview-attach`: Attaches to active target by HWND, PID, or title.
- `desktop-webview-review`: Executes headless automated inspection session.
- `desktop-webview-stop`: Terminates supervised process tree cleanly via Job Objects.
