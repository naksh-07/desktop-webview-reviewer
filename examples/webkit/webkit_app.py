import os
import sys

os.environ["WEBKIT_INSPECTOR_SERVER"] = "127.0.0.1:9222"

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.0")
    from gi.repository import Gtk, WebKit2

    window = Gtk.Window(title="Universal Webview Counter - WebKitGTK")
    window.set_default_size(600, 500)
    window.connect("destroy", Gtk.main_quit)

    webview = WebKit2.WebView()
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "counter.html"))
    webview.load_uri(f"file:///{html_path}")

    window.add(webview)
    window.show_all()
    Gtk.main()
except ImportError:
    print("WebKit2GTK/PyGObject not available on this host. WebKit fixtures require Linux/WSL or macOS environment.")
    sys.exit(1)
