"""
Heuristic detector for QtWebEngine desktop applications.
"""

import os
import re
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None


class QtWebEngineDetector:
    """Detects if an application, script, or process uses QtWebEngine."""

    QT_MODULE_PATTERNS = [
        re.compile(r"PyQt[56]\.QtWebEngine", re.IGNORECASE),
        re.compile(r"PySide[26]\.QtWebEngine", re.IGNORECASE),
        re.compile(r"QWebEngineView", re.IGNORECASE),
        re.compile(r"QWebEnginePage", re.IGNORECASE),
        re.compile(r"QtWebEngineCore", re.IGNORECASE),
    ]

    QT_BINARY_NAMES = [
        "QtWebEngineProcess.exe",
        "QtWebEngineProcess",
        "Qt6WebEngineCore.dll",
        "Qt5WebEngineCore.dll",
    ]

    @classmethod
    def detect_file(cls, path: str) -> bool:
        """Inspects file contents (for scripts) or name/directory for Qt indicators."""
        if not os.path.exists(path):
            return False

        # If it's a Python script or text file
        if path.endswith((".py", ".pyw", ".txt")):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(50000)  # Read initial chunk
                    for pat in cls.QT_MODULE_PATTERNS:
                        if pat.search(content):
                            return True
            except Exception:
                pass

        # Check binary directory / DLLs
        base_dir = os.path.dirname(os.path.abspath(path))
        if os.path.isdir(base_dir):
            for fname in os.listdir(base_dir):
                if any(bin_name.lower() in fname.lower() for bin_name in cls.QT_BINARY_NAMES):
                    return True

        return False

    @classmethod
    def detect_pid(cls, pid: int) -> bool:
        """Inspects running process and its loaded modules or child processes."""
        if psutil is None:
            return False
        try:
            p = psutil.Process(pid)
            p_name = p.name().lower()
            if "qtwebengine" in p_name:
                return True
            for child in p.children(recursive=True):
                if "qtwebengine" in child.name().lower():
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return False

    @classmethod
    def detect(cls, target_path_or_pid: Any) -> bool:
        if isinstance(target_path_or_pid, int):
            return cls.detect_pid(target_path_or_pid)
        elif isinstance(target_path_or_pid, str):
            return cls.detect_file(target_path_or_pid)
        return False
