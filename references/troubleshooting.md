# Troubleshooting & Diagnostics

## 1. Remote Debugging Port Conflicts
- **Symptom**: `OSError: [Errno 10048] address already in use` or stale targets appearing.
- **Resolution**: Run `python scripts/stop.py` or specify an alternative port `--port 9223`.
- **WebView2 Specific**: If port 9222 is busy, use dynamic port discovery via `DevToolsActivePort` in the application User Data Folder.

## 2. Multi-Renderer / DevTools False Attachments
- **Symptom**: Reviewer attaches to DevTools window or background service worker instead of application UI.
- **Resolution**: `core/discovery.py` automatically filters targets matching `devtools://`, `chrome://`, `edge://`, `chrome-extension://`, or `type == "background_page"`. Pass `--title="<expected>"` to explicitly target the main window.

## 3. Platform Framework Routing
- **Tauri / Wails on Windows**: Compiles to Microsoft Edge WebView2. Debugging is activated via `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222`.
- **Tauri / Wails on Linux**: Uses WebKitGTK. Debugging is activated via `WEBKIT_INSPECTOR_SERVER=127.0.0.1:9222`.

## 4. Teardown Orphan Processes
- Qt applications spawn `QtWebEngineProcess.exe`.
- WebView2 applications spawn `msedgewebview2.exe`.
- Electron applications spawn multiple `App.exe --type=renderer` helpers.
- Always use `ProcessCleanup.terminate_process_tree(pid)` which recursively kills all child processes.
