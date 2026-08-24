# CDP Compatibility & Quirks

## QtWebEngine CDP Peculiarities

1. **Remote Debugging Port Activation**:
   Qt applications must set `QTWEBENGINE_REMOTE_DEBUGGING=<port>` in their execution environment prior to initializing the Qt application object (`QApplication`).

2. **Absence of Browser Context Domain (`Browser.*`)**:
   QtWebEngine implements Chromium's content layer without the full Chrome browser scaffolding. Calling `Browser.setDownloadBehavior`, `Browser.getVersion`, or `Browser.createTarget` returns:
   `Protocol error (Browser.setDownloadBehavior): Browser context management is not supported.`

3. **Page-Level WebSocket Routing**:
   Always discover the target page ID by querying `http://127.0.0.1:<port>/json/list` and connect directly to `ws://127.0.0.1:<port>/devtools/page/<GUID>`.

4. **Multi-Process Architecture**:
   On Windows and Linux, the GUI host process spawns one or more helper processes (`QtWebEngineProcess.exe` / `QtWebEngineProcess`). Always terminate the process tree recursively via `psutil`.
