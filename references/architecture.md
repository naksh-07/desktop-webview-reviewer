# Universal Desktop WebView Reviewer Architecture

## 1. Design Principles

1. **Physical Reality Over Simulation**: The skill strictly inspects and automates real operating system desktop application processes. Browser mocks or emulated web servers are never substituted.
2. **Decoupled Engine Core**: Shared primitives (WebSocket JSON-RPC correlation, DOM queries, geometry calculations, screenshot extraction, hashing, process tree cleanup) are engine-agnostic.
3. **Adapter Isolation**: All engine-specific flags, environment variables, detection heuristics, and protocol quirks are strictly encapsulated inside dedicated engine adapters (`qtwebengine`, `webview2`, `electron`, `chromium`, `webkit`).
4. **Intelligent Framework Routing**: High-level frameworks (`tauri`, `wails`, `pywebview`, `cef`) automatically route to the appropriate underlying OS engine without duplicating CDP/session logic.
5. **Honest Platform Constraints**: Never fake an engine test on an unsupported host OS. WebKit verification on Windows honestly reports that Windows host frameworks compile against WebView2.

---

## 2. Component Layout

```text
desktop-webview-reviewer/
├── SKILL.md
├── core/
│   ├── models.py           # Target, EngineInfo, CapabilityStatus, EvidenceReport dataclasses
│   ├── capabilities.py     # Negotiation matrix & status checking
│   ├── session.py          # Asynchronous WebSocket CDP transport & JSON-RPC correlation
│   ├── discovery.py        # HTTP /json/list polling & multi-target ranking
│   ├── actions.py          # High-level DOM queries, bounding box clicks, typing, scroll
│   ├── assertions.py       # State assertions & structured result history
│   ├── evidence.py         # Screenshot PNG magic header validation, SHA-256, evidence.json
│   └── cleanup.py          # psutil recursive tree termination & state cleanup
├── adapters/
│   ├── base.py             # BaseEngineAdapter abstract contract
│   ├── __init__.py         # Adapter registry & framework alias router
│   ├── qtwebengine/        # QtWebEngine adapter (QTWEBENGINE_REMOTE_DEBUGGING)
│   ├── webview2/           # WebView2 adapter (WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS)
│   ├── electron/           # Electron adapter (--remote-debugging-port)
│   ├── chromium/           # Generic Chromium & CEF adapter
│   └── webkit/             # WebKit / WebKitGTK / WKWebView adapter
├── launchers/
│   └── process_launcher.py # Detached process spawning with platform flags
├── detectors/
│   └── engine_detector.py  # Multi-signal engine detector & FrameworkRouter
└── scripts/
    ├── launch.py           # CLI launcher
    ├── discover.py         # CLI target discovery
    ├── attach.py           # CLI interactive inspect
    ├── review.py           # CLI automated verification & evidence generation
    └── stop.py             # CLI process teardown
```
