# Capability Negotiation Matrix

Desktop webview engines vary considerably in their Chrome DevTools Protocol compliance and available feature domains.

The capability matrix tracks operational support per domain:

| Capability | QtWebEngine | WebView2 | Electron | Chromium / CEF | WebKit / WebKitGTK |
|---|---|---|---|---|---|
| **DOM** | `supported` | `supported` | `supported` | `supported` | `supported` |
| **INPUT** | `supported` | `supported` | `supported` | `supported` | `degraded` (Synthetic DOM dispatch) |
| **KEYBOARD** | `supported` | `supported` | `supported` | `supported` | `degraded` |
| **MOUSE** | `supported` | `supported` | `supported` | `supported` | `degraded` |
| **RUNTIME** | `supported` | `supported` | `supported` | `supported` | `supported` |
| **SCREENSHOT** | `supported` | `supported` | `supported` | `supported` | `supported` |
| **CONSOLE** | `supported` | `supported` | `supported` | `supported` | `supported` |
| **NETWORK** | `degraded` | `supported` | `supported` | `supported` | `degraded` |
| **TARGETS** | `degraded` | `degraded` | `supported` | `degraded` | `degraded` |
| **MULTI_TARGET** | `supported` | `supported` | `supported` | `supported` | `degraded` |
| **NAVIGATION** | `supported` | `supported` | `supported` | `supported` | `supported` |
| **JS** | `supported` | `supported` | `supported` | `supported` | `supported` |

---

## Status Definitions

- **`supported`**: The domain and standard protocol commands operate reliably without known deviations.
- **`degraded`**: The domain functions with specific caveats, workarounds, or reduced sub-features (e.g. QtWebEngine/CEF/WebView2 lack full Chrome `Browser.*` profile context management; WebKit uses synthetic DOM event dispatch).
- **`unsupported`**: The engine crashes or returns an explicit protocol error when this domain is queried.
- **`unknown`**: Capability status has not yet been evaluated against real runtime targets.
