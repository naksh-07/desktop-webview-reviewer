import os
import sys

try:
    from cefpython3 import cefpython as cef
    sys.excepthook = cef.ExceptHook
    settings = {
        "remote_debugging_port": 9222,
        "cache_path": os.path.abspath(".cef_cache"),
        "multi_threaded_message_loop": False
    }
    cef.Initialize(settings=settings)
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "counter.html"))
    browser = cef.CreateBrowserSync(
        url=f"file:///{html_path}",
        window_title="Universal Webview Counter - Chromium/CEF"
    )
    cef.MessageLoop()
    cef.Shutdown()
except ImportError:
    print("CEF Python not installed; generic Chromium fixture is available for CEF/Chromium embeds.")
    sys.exit(1)
