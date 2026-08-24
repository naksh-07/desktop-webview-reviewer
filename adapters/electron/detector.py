"""
Heuristic detector for Electron desktop applications.
"""

import json
import os
import re
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None


class ElectronDetector:
    """Detects if an application, script, directory, or process is an Electron app."""

    ELECTRON_BINARY_NAMES = [
        "electron.exe",
        "electron",
        "node.dll",
        "ffmpeg.dll",
        "v8_context_snapshot.bin",
        "app.asar",
    ]

    @classmethod
    def detect_file_or_dir(cls, path: str) -> bool:
        if not os.path.exists(path):
            return False

        # If package.json exists in path or path's directory
        target_dir = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
        pkg_json = os.path.join(target_dir, "package.json")
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    deps = data.get("dependencies", {})
                    dev_deps = data.get("devDependencies", {})
                    if "electron" in deps or "electron" in dev_deps:
                        return True
                    main_file = data.get("main", "")
                    if main_file and any(kw in main_file.lower() for kw in ["main.js", "electron", "index.js"]):
                        # Check content of main_file
                        main_path = os.path.join(target_dir, main_file)
                        if os.path.isfile(main_path):
                            with open(main_path, "r", encoding="utf-8", errors="ignore") as mf:
                                if "require('electron')" in mf.read() or 'require("electron")' in mf.read():
                                    return True
            except Exception:
                pass

        # Check for resources/app.asar or resources/app
        resources_dir = os.path.join(target_dir, "resources")
        if os.path.isdir(resources_dir):
            if os.path.exists(os.path.join(resources_dir, "app.asar")) or os.path.exists(os.path.join(resources_dir, "app")):
                return True

        # Check for binary names
        if os.path.isfile(path):
            fname = os.path.basename(path).lower()
            if "electron" in fname:
                return True
            # Check for main.js or index.js with electron import
            if path.endswith((".js", ".ts", ".mjs")):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as jf:
                        content = jf.read(10000)
                        if "from 'electron'" in content or 'from "electron"' in content or 'require("electron")' in content or "require('electron')" in content:
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
            if "electron" in p_name:
                return True
            for child in p.children(recursive=True):
                if "--type=renderer" in " ".join(child.cmdline() if hasattr(child, 'cmdline') else []):
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            pass
        return False

    @classmethod
    def detect(cls, target_path_or_pid: Any) -> bool:
        if isinstance(target_path_or_pid, int):
            return cls.detect_pid(target_path_or_pid)
        elif isinstance(target_path_or_pid, str):
            return cls.detect_file_or_dir(target_path_or_pid)
        return False
