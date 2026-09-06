# Desktop WebView Reviewer

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](pyproject.toml)
[![Verdict](https://img.shields.io/badge/verdict-PASS-brightgreen.svg)](docs/architecture/31_FINAL_2.0_CERTIFICATION_AND_RELEASE_REPORT.md)
[![Status](https://img.shields.io/badge/status-production--released-green.svg)](docs/architecture/31_FINAL_2.0_CERTIFICATION_AND_RELEASE_REPORT.md)
[![Architecture](https://img.shields.io/badge/architecture-Architecture%20H-purple.svg)](docs/architecture/11_FINAL_ARCHITECTURE_DECISION.md)
[![MCP](https://img.shields.io/badge/mcp-control--plane-orange.svg)](docs/architecture/14_MCP_INTERFACE_SPEC.md)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-red.svg)](LICENSE)

**Desktop WebView Reviewer** is a production-grade, agent-native automation and forensic-review system for hybrid Windows desktop applications hosting embedded web surfaces (QtWebEngine, Microsoft Edge WebView2, Electron, CEF/Chromium).

---

## Why Hybrid Desktop + WebView Automation is Different

Traditional web testing tools assume that DOM presence equates to physical visibility. In real desktop applications, this assumption causes false positives:
- **Physical Reality Primacy:** An embedded webview DOM may report an element as visible (`offsetParent != null`), but the host native window may be minimized, cloaked by Desktop Window Manager (DWM), obscured behind another window, or off-screen.
- **Dual Perspectives:** The application lives in two distinct planes: the **Native Plane** (Win32, UIA, DWM) and the **Web Plane** (DOM, AX, CDP). Neither plane alone possesses complete truth.
- **Action Receipt != Success:** Dispatching a physical click or keyboard event is only proof that input was delivered to the window; it is not proof that application state mutated. State changes must be authoritatively verified.
- **Tripartite Verdicts:** State assertions and test reviews must produce `PASS`, `FAIL`, or `UNVERIFIED`. `UNVERIFIED` (e.g. occluded window, missing evidence) is never silently upgraded to `PASS`.

---

## Architecture H Overview

The system implements **Architecture H (Decoupled Daemon & Unified Supervisory Bridge)**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                              AI AGENT                                  │
│             Operates strictly via public agent interfaces              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        AGENT SKILL & WORKFLOWS                         │
│   skills/desktop-webview-reviewer/SKILL.md & declarative workflows     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (JSON-RPC / stdio)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           MCP CONTROL PLANE                            │
│           desktop-webview-mcp (Exactly 12 cohesive tools)              │
│       desktop_launch, desktop_attach, desktop_inspect, actions,        │
│       desktop_handle_dialog, desktop_evaluate, desktop_assert,         │
│       desktop_collect_evidence                                         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         RUNTIMEDAEMON BRIDGE                           │
│                 runtime/mcp/runtime_bridge.py                          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         AUTHORITATIVE RUNTIME                          │
│   ┌───────────────────────────────────┐ ┌───────────────────────────┐  │
│   │           Native Plane            │ │         Web Plane         │  │
│   │ Win32 / UIA / DWM Visibility /    │ │ DOM / AX / CDP Transport /│  │
│   │ Job Objects / Supervisor          │ │ Utility Realm Isolation   │  │
│   └─────────────────┬─────────────────┘ └─────────────┬─────────────┘  │
│                     └────────────────┬────────────────┘                │
│                                      ▼                                 │
│                         Reconciliation Engine                          │
│                                      ▼                                 │
│                   Observation Epochs & Ephemeral Refs                  │
│                                      ▼                                 │
│              Composite Actionability & Settlement Engine               │
│                                      ▼                                 │
│              Verification Engine (PASS/FAIL/UNVERIFIED)                │
│                                      ▼                                 │
│               Evidence Store (SHA-256 Sealed Bundles)                  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Agent-Facing MCP Surface

The MCP server exposes exactly **12 cohesive, architecture-approved tools**:

| Category | Tool Name | Description |
|---|---|---|
| **Lifecycle** | `desktop_launch` | Spawns target under Windows Job Object supervision with CDP allocation. |
| | `desktop_attach` | Attaches to existing running target by HWND, PID, title pattern, or CDP port. |
| **Observation** | `desktop_inspect` | Dual-perspective state observation returning compact YAML tree with refs. |
| **Semantic Actions** | `desktop_click` | Clicks affordance with actionability waiting and fused post-observation. |
| | `desktop_type` | Types text with authentic event bubbling across native and web planes. |
| | `desktop_press_key` | Sends keyboard shortcuts ('Enter', 'Tab', 'Control+A', etc.). |
| | `desktop_hover` | Hovers pointer with motion settlement. |
| | `desktop_scroll` | Scrolls element container into physical view. |
| **Dialogs** | `desktop_handle_dialog` | Inspects and dismisses Win32 modal dialogs (`#32770`) or JS alerts. |
| **Evaluation** | `desktop_evaluate` | Evaluates JS safely in isolated `__utility_world__` realm. |
| **Verification** | `desktop_assert` | Polling assertion on element state (`visible`, `enabled`, `text`). |
| **Evidence** | `desktop_collect_evidence` | Seals cryptographic evidence bundle with tripartite verdict. |

---

## MCP Resources & Prompts

- **Evidence Manifests:** `desktop://evidence/{evidence_id}` — Byte-for-byte SHA-256 sealed test manifest.
- **Forensic Screenshots:** `desktop://evidence/{evidence_id}/screenshot` — PNG screenshot artifact.
- **Session Registry:** `desktop://sessions` & `desktop://session/{id}` — Active session diagnostics.
- **Agent Prompts:** `desktop_review` — Seed prompt for autonomous application review.

---

## First-Class Agent Skill

The project includes a first-class agent instruction skill located at:
`skills/desktop-webview-reviewer/`
- **`SKILL.md`**: Foundational operational policy (Physical Primacy, Dual Perspectives, Reference Discipline, Action Semantics, Verification Discipline, Security Invariants).
- **Declarative Workflows (`workflows/`)**:
  - `review_application.md`
  - `debug_unresponsive_ui.md`
  - `verify_user_flow.md`
  - `collect_forensic_evidence.md`
  - `diagnose_native_web_mismatch.md`
  - `recover_stale_reference.md`
  - `inspect_dialog_block.md`
- **Technical References (`references/`)**:
  - `mcp_tools_reference.md`
  - `forensic_verdict_model.md`
  - `security_discipline.md`

---

## Security Model & Adversarial Hardening

1. **UI Text is Data, Not Instructions:** Text from DOM, accessible names, window titles, and dialogs is marked untrusted data.
2. **Path Sanitization:** Device namespaces (`\\.\`, `\\?\`), DOS device names (`CON`, `NUL`), and UNC network paths are rejected.
3. **Process Identity:** Process cleanup requires matching both PID and `expected_create_time` to prevent PID reuse attacks.
4. **JS Evaluation Sandbox:** Default execution runs in isolated `__utility_world__`; expressions capped at 10k chars; circular references and binary data neutralized.
5. **Evidence Immutability:** Evidence artifacts are sealed with SHA-256 hashes and confined to strict directory boundaries.

---

## Installation & CLI Usage

### Requirements
- **OS:** Windows 10 (Build 19041+) or Windows 11 (64-bit)
- **Python:** 3.10 to 3.13 (64-bit)

### Installation
```powershell
# Install via pip
pip install desktop-webview-reviewer
```

### Antigravity-Native Integration (Model B)
Desktop WebView Reviewer is designed to operate as a native capability within Google Antigravity. By installing the Python package globally (or in your active virtual environment), Antigravity can directly invoke the `desktop-webview-mcp` transport and `desktop-reviewer` CLI. 

1. Install the package via `pip install desktop-webview-reviewer`.
2. Add the `desktop-webview-reviewer` skill to your `.gemini/config/skills/` directory.
3. The Antigravity agent will automatically discover and use the globally available CLI to orchestrate review missions without requiring a local source clone.

### CLI Commands
```powershell
# Production Release Pipeline (8 deterministic gates)
desktop-reviewer release-validate

# Multi-Framework Live Adversarial Certification
desktop-reviewer certify

# 6-Domain Production Security Audit
desktop-reviewer security-audit

# Autonomous Review Missions (Phase 17–18)
desktop-reviewer mission --help

# Subordinate Specialist Subagents (Phase 15–16)
desktop-reviewer specialists list

# Diagnostics & Recovery
desktop-reviewer diagnostics
desktop-reviewer recovery status

# Self-Test (7/7 deterministic checks)
desktop-webview-mcp --self-test

# Environment Diagnostics
desktop-webview-mcp --diagnostics

# Start MCP Server on stdio (for agent integration)
desktop-webview-mcp --transport stdio
```

---

## Release Status & Documentation

For complete documentation:
- [Final 2.0 Certification & Production Release Report (Doc 31)](docs/architecture/31_FINAL_2.0_CERTIFICATION_AND_RELEASE_REPORT.md)
- [2.0 Architecture Roadmap (Doc 27)](docs/architecture/27_DESKTOP_REVIEWER_2.0_ROADMAP.md)
- [System Architecture](docs/architecture/12_SYSTEM_ARCHITECTURE.md)
- [MCP Interface Specification](docs/architecture/14_MCP_INTERFACE_SPEC.md)
- [Usage Guide](docs/usage/USAGE_GUIDE.md)
- [Security Model](docs/security/SECURITY.md)
- [Troubleshooting](docs/troubleshooting/TROUBLESHOOTING.md)

**Status:** `2.0.0 PRODUCTION RELEASE CERTIFIED (VERDICT: PASS)`  
(Limitations: UIA3 sidecar binary uncompiled by default; Windows WebKit lacks standard CDP input; DWM composition requires active display).

---

## License & Permitted Use

This project is licensed under the **PolyForm Noncommercial License 1.0.0**. See the [LICENSE](LICENSE) file for the full legal text.

- **Personal & Non-Commercial Use (Allowed):** Anyone is welcome to use, run, test, and experiment with this project for personal workflows (including inside Google Antigravity, local personal workstations, educational, or research purposes).
- **Commercial Monetization & Sale (Strictly Prohibited):** Selling, charging fees, sublicensing, or offering this software as part of a paid commercial product or SaaS is strictly forbidden.
- **Anti-Plagiarism / Derivative Monetization (Strictly Prohibited):** No individual or company may copy, clone, white-label, or make minor modifications to this project in order to sell it, monetize it, or profit financially from it.
