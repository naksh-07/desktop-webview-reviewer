import os
import sys

# Ensure remote debugging flag is set for WebView2
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9222"

try:
    import webview
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "counter.html"))
    window = webview.create_window(
        title="Universal Webview Counter - WebView2",
        url=f"file:///{html_path}",
        width=600,
        height=500
    )
    webview.start(gui="edgechromium")
except ImportError:
    print("pywebview not installed; WebView2 fixture requires pywebview or native Windows host.")
    sys.exit(1)
