"""
Heuristic detector for WebKit, WebKitGTK, and Apple WKWebView desktop applications.
"""

import os
import sys
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None


class WebKitDetector:
    """Detects if an application, script, or process uses WebKit / WebKitGTK / WKWebView."""

    WEBKIT_SIGNATURES = [
        "webkit2gtk",
        "libwebkit2gtk",
        "WebKit2",
        "WebKitGTK",
        "WKWebView",
        "WEBKIT_INSPECTOR_SERVER",
    ]

    @classmethod
    def detect_file_or_dir(cls, path: str) -> bool:
        if not os.path.exists(path):
            return False

        if os.path.isfile(path):
            if path.endswith((".py", ".c", ".cpp", ".rs", ".go", ".txt")):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(50000)
                        if any(sig in content for sig in cls.WEBKIT_SIGNATURES):
                            return True
                except Exception:
                    pass

        return False

    @classmethod
    def detect_pid(cls, pid: int) -> bool:
        if psutil is None:
            return False
        try:
            p = psutil.Process(pid)
            p_name = p.name().lower()
            if "webkit" in p_name:
                return True
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
