"""
Heuristic detector for CEF (Chromium Embedded Framework) and generic Chromium embeds.
"""

import os
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None


class ChromiumDetector:
    """Detects CEF, CefSharp, Chromium Embedded Shells, and standalone Chromium embeds."""

    CEF_SIGNATURES = [
        "libcef.dll",
        "libcef.so",
        "cef.pak",
        "cef_100_percent.pak",
        "cef_200_percent.pak",
        "CefSharp.Core.Runtime.dll",
        "CefSharp.BrowserSubprocess.exe",
        "CefSharp.dll",
        "cefpython3",
    ]

    CHROMIUM_SIGNATURES = [
        "chrome_elf.dll",
        "chrome.dll",
        "resources.pak",
        "icudtl.dat",
        "v8_context_snapshot.bin",
    ]

    @classmethod
    def is_cef(cls, path_or_dir: str) -> bool:
        """Determines if the target is specifically a CEF embed."""
        if not os.path.exists(path_or_dir):
            return False
        target_dir = path_or_dir if os.path.isdir(path_or_dir) else os.path.dirname(os.path.abspath(path_or_dir))
        for fname in os.listdir(target_dir):
            if any(sig.lower() in fname.lower() for sig in cls.CEF_SIGNATURES):
                return True
        return False

    @classmethod
    def detect_file_or_dir(cls, path: str) -> bool:
        if not os.path.exists(path):
            return False

        if os.path.isfile(path):
            # Check script contents
            if path.endswith((".py", ".cs", ".cpp", ".txt")):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(50000)
                        if "cefpython" in content or "CefSharp" in content or "CefInitialize" in content:
                            return True
                except Exception:
                    pass

            target_dir = os.path.dirname(os.path.abspath(path))
        else:
            target_dir = path

        if os.path.isdir(target_dir):
            all_files = os.listdir(target_dir)
            if any(any(sig.lower() in f.lower() for sig in cls.CEF_SIGNATURES) for f in all_files):
                return True
            if any(any(sig.lower() in f.lower() for sig in cls.CHROMIUM_SIGNATURES) for f in all_files):
                return True

        return False

    @classmethod
    def detect_pid(cls, pid: int) -> bool:
        if psutil is None:
            return False
        try:
            p = psutil.Process(pid)
            p_name = p.name().lower()
            if "cef" in p_name or "chromium" in p_name:
                return True
            for child in p.children(recursive=True):
                if "cef" in child.name().lower():
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
