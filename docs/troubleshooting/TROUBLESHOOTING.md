# Desktop WebView Reviewer — Troubleshooting Guide

## 1. Quick Diagnostic Check

Before deep debugging, run the integrated diagnostic self-test:
```powershell
desktop-webview-mcp --diagnostics
desktop-webview-mcp --self-test
```
This verifies:
- Win32 User32 and DWM API availability
- Python 3.10+ execution environment
- .NET runtime status
- Evidence directory writability
- Tool registrations and security sanitization

---

## 2. Common Issues and Resolutions

### A. Window is Occluded / Cloaked (`WindowCloakedException`)
- **Symptoms:** `desktop_assert` returns `UNVERIFIED` or logs warn `TargetWasPhysicallyVisible: No native OS window forensics available`.
- **Cause:** In Windows 10/11, minimized windows, virtual desktop switches, or UWP app suspensions "cloak" the window surface in Desktop Window Manager (DWM). Although the webview DOM reports `offsetParent != null` and `display != none`, the pixels are not physically rendered to the screen.
- **Resolution:**
  1. Restore the window using native window management (`ShowWindow(hwnd, SW_RESTORE)`).
  2. Bring the window to foreground using `SetForegroundWindow`.
  3. Ensure no full-screen opaque window is completely covering the target bounds.

---

### B. Stale References (`STALE_REFERENCE` / `w1e5 not found`)
- **Symptoms:** An action tool (`desktop_click`, `desktop_type`) fails with `STALE_REFERENCE`.
- **Cause:** Ephemeral references (`w1e5`, `n1e2`) are scoped to a specific observation epoch. Whenever an action mutates application state or navigation occurs, the epoch increments and invalidates old references.
- **Resolution:**
  1. Always follow the discipline: `desktop_inspect` -> acquire fresh reference -> dispatch action.
  2. In high-volatility animations, use deterministic re-resolution via the Agent Skill workflow (`skills/desktop-webview-reviewer/workflows/recover_stale_reference.md`).

---

### C. Application Hangs / Unresponsive UI (`TARGET_HUNG`)
- **Symptoms:** Actions or observations time out with `TARGET_HUNG`.
- **Cause:** The target application's main GUI thread is deadlocked, executing an intensive computation, or blocked on modal I/O.
- **Resolution:**
  1. Do NOT loop-retry physical actions blindly; this risks queueing stale inputs.
  2. Run `desktop_handle_dialog` to check if a native modal dialog (`#32770`) or file picker is blocking the message pump.
  3. Query `desktop_inspect` with `visible_only=False` to detect modal barriers.

---

### D. CDP Port Conflicts (`PortConflictException`)
- **Symptoms:** `Failed to bind remote debugging port: port already in use`.
- **Cause:** A previous unmanaged test run or orphaned process occupies the requested CDP port (e.g. 9222).
- **Resolution:**
  1. The system automatically searches for a free port within a configured range if 0 or dynamic allocation is requested.
  2. Run `desktop-webview-stop` or terminate orphaned processes using Windows Job Objects:
     ```powershell
     desktop-webview-stop --all
     ```

---

### E. UIA3 Sidecar Fallback
- **Symptoms:** Log note: `UIA3 sidecar not compiled, falling back to Native Win32 / FlaUI bridge`.
- **Cause:** The optional C# UIA3 sidecar binary (`FlaUIServer.exe`) is not compiled or .NET 8 SDK is absent.
- **Resolution:**
  - This is a non-blocking documented limitation. The authoritative Python NativeSupervisor handles Win32 window forensics, DWM occlusion checks, child process tree tracking, and input dispatch out-of-the-box.
  - To compile the optional high-speed UIA3 sidecar:
    ```powershell
    dotnet build sidecar/FlaUIServer.csproj -c Release
    ```
