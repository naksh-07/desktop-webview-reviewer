# Desktop WebView Reviewer — Usage Guide

## 1. Overview
`desktop-webview-reviewer` is a production-grade, agent-native automation and forensic review system for hybrid Windows desktop applications hosting embedded webviews (QtWebEngine, WebView2, Electron, CEF/Chromium).

It couples **Native Windows OS supervision** (Win32, DWM, Job Objects) with **Webview DevTools Protocol (CDP)** control plane into a cohesive dual-perspective system governed by **Architecture H**.

---

## 2. Architecture & Installation Model

Desktop WebView Reviewer consists of four distinct architectural layers:
- **Skill** (`skills/desktop-webview-reviewer/`): The authoritative Antigravity capability containing foundational operational policies, 7 declarative workflows, and reference documents.
- **MCP Control Plane** (`desktop-webview-mcp`): The agent-facing interface exposing exactly 12 cohesive tools over JSON-RPC stdio.
- **Reviewer Runtime** (`runtime/`, `core/`, `adapters/`): The Python engine executing Win32/UIA and CDP automation, reconciliation, and cryptographic evidence sealing.
- **Wheel / sdist Packages**: Optional Python runtime distribution artifacts produced for environment packaging. **Installing a wheel is not the same as installing the Antigravity Skill.**

---

### Canonical Antigravity Installation (Standard Path)

To use Desktop WebView Reviewer inside Google Antigravity, follow this three-step installation:

#### Step 1: Install the Antigravity Skill
Copy the `skills/desktop-webview-reviewer/` directory into your Antigravity skills configuration root:

- **User-Global Customizations:**
  ```powershell
  Copy-Item -Recurse -Force skills/desktop-webview-reviewer "$HOME/.gemini/config/skills/desktop-webview-reviewer"
  ```
- **Workspace-Specific Customizations:**
  ```powershell
  Copy-Item -Recurse -Force skills/desktop-webview-reviewer ".agents/skills/desktop-webview-reviewer"
  ```

#### Step 2: Configure the MCP Server
Register the Reviewer MCP server in your Antigravity MCP configuration (`mcp_config.json`):

```json
{
  "mcpServers": {
    "desktop-webview-reviewer": {
      "command": "desktop-webview-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```
*(If the runtime is installed in a specific virtual environment, supply the full path to `desktop-webview-mcp.exe` or use `["<path-to-python>", "-m", "runtime.mcp.server", "--transport", "stdio"]`).*

#### Step 3: Manage the Python Reviewer Runtime
The MCP server and CLI commands execute the Python runtime. Requirements:
- **Operating System:** Windows 10 (Build 19041+) or Windows 11 (64-bit).
- **Python:** Version 3.10, 3.11, 3.12, or 3.13 (64-bit).
- **.NET Runtime (Optional for UIA3 sidecar):** .NET 8.0 SDK / Runtime (pure Win32 / CDP operates out-of-the-box without .NET).

Install the runtime in your active Python environment:
```powershell
# Standard pip installation
pip install desktop-webview-reviewer

# Or install from release distribution wheel artifact
pip install desktop_webview_reviewer-2.0.0b2-py3-none-any.whl
```

#### Step 4: Verify Installation Health
Run the comprehensive lifecycle doctor and MCP self-test:
```powershell
# Run 10-point lifecycle & skill synchronization health check
desktop-reviewer update doctor

# Run deterministic 7/7 MCP in-process self-test
desktop-webview-mcp --self-test

# Run environmental diagnostics
desktop-webview-mcp --diagnostics
```

---

### Developer & Source-Development Workflow (Developers Only)

> [!NOTE]
> Installing via `pip install -e .` or `uv sync` from a cloned source repository is strictly for **contributors developing the Reviewer codebase itself**, not normal Antigravity installation.

```powershell
# Clone repository
git clone https://github.com/naksh-07/desktop-webview-reviewer.git
cd desktop-webview-reviewer

# Developer environment setup with uv (recommended)
uv sync

# Or editable install with pip
pip install -e .
```

---

## 3. External MCP Client Configuration

For non-Antigravity MCP clients (e.g. Claude Desktop, Cursor), configure the client to invoke the installed runtime:

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "desktop-webview-reviewer": {
      "command": "desktop-webview-mcp",
      "args": ["--transport", "stdio"],
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
