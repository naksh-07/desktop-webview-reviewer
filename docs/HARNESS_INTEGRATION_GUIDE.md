# Desktop WebView Reviewer — Harness Integration Guide

**Guide Version:** 2.0 (Prompt P3 / Phases 13–14)  
**Target Audience:** Application Developers, QA Engineers, CI/CD Pipeline Authors  
**Supported Frameworks:** Electron, WebView2 (C# / WinUI / WPF), Qt / QtWebEngine (PyQt / PySide)

---

## 1. Overview

The **Reviewer Test Harness** is an in-process diagnostic and test-support layer for desktop applications during development and review builds. It provides real-time lifecycle events, internal application diagnostics, fixture seeding/resetting, and simulated fault injection directly to the **Desktop WebView Reviewer Runtime**.

### Key Rules to Remember
1. **Physical Reality Wins:** Visual and native physical verification always outranks internal harness reports. A harness `SAVE_COMPLETED` does not replace visual verification of saved data on screen.
2. **Zero Production Backdoor:** The Harness is compiled/packaged into `DEV` and `REVIEW` builds only. It is strictly forbidden from `RELEASE` builds. There is no secret runtime flag to enable it in production.
3. **Surgical & Reversible:** Changes made by `desktop-reviewer harness init` are wrapped in clear markers and can be reversed cleanly with `desktop-reviewer harness remove`.

---

## 2. Developer Workflow at a Glance

```text
1. Open Application Project
        │
        ▼
2. Run: desktop-reviewer harness init [--dry-run]
        │
        ▼
3. Build DEV or REVIEW artifact
        │
        ▼
4. Launch application & start Reviewer Runtime
        │
        ▼
5. Reviewer drives Eyes, Hands & Physical Reality
   Harness provides Lifecycle Signals & Diagnostics
        │
        ▼
6. Build RELEASE artifact
        │
        ▼
7. Run: desktop-reviewer harness validate-release <artifact>
        │
        ▼
8. Ship to customers only if release validation PASSES
```

---

## 3. CLI Commands Reference

All commands are accessible via the `desktop-reviewer harness` CLI (or `desktop-webview-harness`):

### 3.1 `init` — Prepare Application for Review
Inspects the project, auto-detects the framework, determines the entry point, and applies minimal surgical integration:

```bash
# Preview modifications without touching files
desktop-reviewer harness init --path ./my-app --dry-run

# Apply surgical integration
desktop-reviewer harness init --path ./my-app

# Force a specific framework adapter if needed
desktop-reviewer harness init --path ./my-app --adapter electron
```

#### What `init` Does:
1. Detects framework (`Electron`, `WebView2`, `Qt`) and entry point files.
2. Generates an adapter file in the project (e.g. `ReviewerHarness.js`).
3. Inserts surgical initialization hooks into your entry point:
   ```javascript
   // >>> REVIEWER_HARNESS_START >>>
   // Added by Desktop WebView Reviewer Harness
   const { ReviewerHarness } = require('./ReviewerHarness');
   ReviewerHarness.init();
   // <<< REVIEWER_HARNESS_END <<<
   ```
4. Creates `.reviewer_harness.json` manifest recording added files and reversal checksums.

### 3.2 `inspect` — Check Integration Status
Inspects the project directory and reports current harness integration status and supported capabilities:

```bash
desktop-reviewer harness inspect --path ./my-app
```

Output:
```text
Reviewer Harness Status
────────────────────────────────────────
Project Path:    ./my-app
Integrated:      YES
Framework:       Electron (Confidence: 95.0%)
Adapter:         Electron
Harness Version: 2.0.0
Build Mode:      DEV
Files Added:     1
Files Modified:  1

Capabilities:
  • core: AVAILABLE
  • lifecycle: AVAILABLE
  • diagnostics: AVAILABLE
  • fixtures: AVAILABLE
  • fault_injection: AVAILABLE
```

### 3.3 `validate` — Verify Harness Integrity
Checks that all injected files and markers are intact and valid:

```bash
desktop-reviewer harness validate --path ./my-app
```

### 3.4 `remove` — Safely Revert Integration
Surgically removes the Reviewer Harness integration without touching unrelated developer code:

```bash
desktop-reviewer harness remove --path ./my-app
```

### 3.5 `validate-release` — Release Gate Validation
Scans a production build or release artifact to ensure zero harness code, endpoints, or backdoor flags leaked into production:

```bash
desktop-reviewer harness validate-release ./dist/production-release.zip
```

If any harness trace is detected, this command exits with a non-zero code and lists exact evidence found.

---

## 4. Framework-Specific Guidelines

### 4.1 Electron
- **Entry Points:** `main.js`, `index.js`, or `src/main/index.ts`.
- **Lifecycle Events:** Automatically emits `APP_STARTING`, `APP_READY`, and `SCREEN_READY` when windows are created and loaded.
- **Fixtures & Faults:** Supports seed/reset hooks and network delay injection through main-process IPC.
- **Release Packaging:** In `package.json`, ensure `ReviewerHarness.js` and development harness scripts are excluded in your `electron-builder` or `electron-packager` configuration:
  ```json
  "build": {
    "files": [
      "!ReviewerHarness.js",
      "!.reviewer_harness.json"
    ]
  }
  ```

### 4.2 WebView2 (C# / WinUI / WPF)
- **Entry Points:** `Program.cs`, `MainWindow.xaml.cs`, or `App.xaml.cs`.
- **Lifecycle Events:** Listens to `CoreWebView2InitializationCompleted` and navigation events.
- **Capabilities:** Core, lifecycle, diagnostics, and fixtures are fully supported. Network fault injection is reported as `DEGRADED` due to process isolation constraints.
- **Release Packaging:** Use `#if DEBUG` preprocessor directives around harness initialization so that `Release` builds completely strip the code:
  ```csharp
  #if DEBUG
  // >>> REVIEWER_HARNESS_START >>>
  ReviewerHarness.Init(this.webView);
  // <<< REVIEWER_HARNESS_END <<<
  #endif
  ```

### 4.3 Qt / QtWebEngine (PyQt / PySide)
- **Entry Points:** `main.py`, `app.py`.
- **Lifecycle Events:** Hooks into `QWebEngineView.loadFinished` and application event loop.
- **Capabilities:** Full support for lifecycle, diagnostics, fixtures, and fault injection.
- **Release Packaging:** When building packages via `pyinstaller` or `nuitka`, exclude harness modules from the distribution bundle.

---

## 5. Troubleshooting & FAQ

#### Q: The Reviewer says physical test failed even though the Harness said `SAVE_COMPLETED`. Why?
**A:** This is by design (The Harness Golden Rule). If the database save completed internally, but the UI failed to update or displayed an error dialog occluding the view, Desktop WebView Reviewer prioritizes the human user's visual reality and reports `FAIL`.

#### Q: `harness remove` warns of a checksum mismatch.
**A:** If you modified code inside the `// >>> REVIEWER_HARNESS_START >>>` markers, `remove` will protect your files from accidental damage. Check the markers in your entry point file, restore the original section, or remove the markers manually.

#### Q: How do I integrate the release validator in CI?
**A:** Add a step in your GitHub Actions, GitLab CI, or Azure Pipelines workflow:
```yaml
- name: Validate Release Artifact
  run: |
    desktop-reviewer harness validate-release ./artifacts/MyApp-Setup.exe
```
This step will fail closed if any development instrumentation or backdoor switches are present.
