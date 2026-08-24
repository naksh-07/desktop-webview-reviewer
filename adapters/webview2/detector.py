"""
Heuristic and signature detector for Microsoft Edge WebView2 applications.
"""

import os
import re
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None


class WebView2Detector:
    """Detects if an application, script, project, or process uses Microsoft Edge WebView2."""

    WEBVIEW2_MODULE_PATTERNS = [
        re.compile(r"Microsoft\.Web\.WebView2", re.IGNORECASE),
        re.compile(r"CoreWebView2", re.IGNORECASE),
        re.compile(r"EnsureCoreWebView2Async", re.IGNORECASE),
        re.compile(r"gui\s*=\s*['\"]edgechromium['\"]", re.IGNORECASE),
        re.compile(r"pywebview.*edgechromium", re.IGNORECASE),
        re.compile(r"WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", re.IGNORECASE),
    ]

    WEBVIEW2_BINARY_NAMES = [
        "msedgewebview2.exe",
        "WebView2Loader.dll",
        "EmbeddedBrowserWebView.dll",
    ]

    @classmethod
    def detect_file_or_dir(cls, path: str) -> bool:
        """Inspects file contents or directory structures for WebView2 signatures."""
        if not os.path.exists(path):
            return False

        if os.path.isfile(path):
            # Check script / project text
            if path.endswith((".py", ".pyw", ".cs", ".csproj", ".config", ".json", ".txt")):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(50000)
                        for pat in cls.WEBVIEW2_MODULE_PATTERNS:
                            if pat.search(content):
                                return True
                except Exception:
                    pass

            # Check binary directory
            base_dir = os.path.dirname(os.path.abspath(path))
            if os.path.isdir(base_dir):
                for fname in os.listdir(base_dir):
                    if any(bin_name.lower() in fname.lower() for bin_name in cls.WEBVIEW2_BINARY_NAMES):
                        return True

        elif os.path.isdir(path):
            for root, _, files in os.walk(path):
                for f in files:
                    if any(bin_name.lower() in f.lower() for bin_name in cls.WEBVIEW2_BINARY_NAMES):
                        return True
                    if f.endswith((".csproj", "packages.config", "tauri.conf.json", "wails.json")):
                        try:
                            with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as pf:
                                if "Microsoft.Web.WebView2" in pf.read():
                                    return True
                        except Exception:
                            pass

        return False

    @classmethod
    def detect_pid(cls, pid: int) -> bool:
        """Inspects a running process and its loaded modules or child processes for WebView2."""
        if psutil is None:
            return False
        try:
            p = psutil.Process(pid)
            p_name = p.name().lower()
            if "msedgewebview2" in p_name:
                return True

            for child in p.children(recursive=True):
                if "msedgewebview2" in child.name().lower():
                    return True

            try:
                for mm in p.memory_maps():
                    path_lower = mm.path.lower()
                    if any(dll.lower() in path_lower for dll in cls.WEBVIEW2_BINARY_NAMES):
                        return True
            except (psutil.AccessDenied, AttributeError, Exception):
                pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return False

    @classmethod
    def detect(cls, target_path_or_pid: Any) -> bool:
        if isinstance(target_path_or_pid, int):
            return cls.detect_pid(target_path_or_pid)
        elif isinstance(target_path_or_pid, str):
            return cls.detect_file_or_dir(target_path_or_pid)
        return False
