"""
Automatic engine detector and cross-platform framework router.
"""

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from adapters import list_adapters, get_adapter, get_default_adapter
from adapters.base import BaseEngineAdapter
from core.models import ConfidenceLevel, DetectionSignal, EngineInfo

logger = logging.getLogger("desktop_webview.detector")


class FrameworkRouter:
    """
    Routes high-level frameworks (Tauri, Wails, PyWebView, CEF) to the underlying native engine
    based on host operating system platform.
    """

    @classmethod
    def resolve_framework(cls, framework_name: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolves (framework_name, current_os) -> (engine_name, framework_tag).
        Example: ('tauri', 'win32') -> ('webview2', 'tauri')
        """
        fw = framework_name.strip().lower()
        platform = sys.platform

        if fw in ("tauri", "tauri-app"):
            if platform == "win32":
                return "webview2", "tauri"
            else:
                return "webkit", "tauri"

        if fw in ("wails", "wails-app"):
            if platform == "win32":
                return "webview2", "wails"
            else:
                return "webkit", "wails"

        if fw in ("pywebview",):
            if platform == "win32":
                return "webview2", "pywebview"
            elif platform == "darwin":
                return "webkit", "pywebview"
            else:
                return "webkit", "pywebview"

        if fw in ("cef", "cefsharp", "cefpython"):
            return "chromium", "cef"

        if fw in ("electron",):
            return "electron", "electron"

        if fw in ("qt", "qtwebengine", "pyqt", "pyside", "pyqt5", "pyqt6", "pyside2", "pyside6"):
            return "qtwebengine", "qt"

        if fw in ("winforms", "wpf", "dotnet-webview2", "webview2"):
            return "webview2", "dotnet"

        return None, None


class EngineDetector:
    """
    Multi-signal engine detector combining process inspection, project structure analysis,
    runtime DevTools querying, and platform framework routing.
    """

    @classmethod
    def detect_project_level(cls, target_dir_or_file: str) -> Optional[Tuple[str, str, str, List[DetectionSignal]]]:
        """
        Inspects directory files (package.json, Cargo.toml, tauri.conf.json, wails.json, .csproj, etc.)
        Returns (engine_name, framework_tag, reason, signals) if detected.
        """
        if not os.path.exists(target_dir_or_file):
            return None

        search_dir = target_dir_or_file if os.path.isdir(target_dir_or_file) else os.path.dirname(os.path.abspath(target_dir_or_file))
        signals: List[DetectionSignal] = []

        # 1. Check for Tauri config
        tauri_conf = os.path.join(search_dir, "src-tauri", "tauri.conf.json")
        alt_tauri_conf = os.path.join(search_dir, "tauri.conf.json")
        if os.path.isfile(tauri_conf) or os.path.isfile(alt_tauri_conf):
            engine, fw = FrameworkRouter.resolve_framework("tauri")
            sig = DetectionSignal(
                source="manifest",
                indicator="tauri.conf.json",
                confidence=ConfidenceLevel.HIGH,
                weight=1.0,
                details={"file": tauri_conf if os.path.isfile(tauri_conf) else alt_tauri_conf, "framework": fw}
            )
            signals.append(sig)
            return engine, fw, f"Found Tauri configuration ({fw}) -> mapped to '{engine}' on {sys.platform}", signals

        # 2. Check for Wails config
        wails_json = os.path.join(search_dir, "wails.json")
        if os.path.isfile(wails_json):
            engine, fw = FrameworkRouter.resolve_framework("wails")
            sig = DetectionSignal(
                source="manifest",
                indicator="wails.json",
                confidence=ConfidenceLevel.HIGH,
                weight=1.0,
                details={"file": wails_json, "framework": fw}
            )
            signals.append(sig)
            return engine, fw, f"Found Wails configuration ({fw}) -> mapped to '{engine}' on {sys.platform}", signals

        # 3. Check for .csproj / WebView2 packages
        try:
            for root, _, files in os.walk(search_dir):
                for f in files:
                    if f.endswith(".csproj"):
                        cpath = os.path.join(root, f)
                        with open(cpath, "r", encoding="utf-8", errors="ignore") as cfile:
                            ccontent = cfile.read()
                            if "Microsoft.Web.WebView2" in ccontent:
                                sig = DetectionSignal(
                                    source="manifest",
                                    indicator="csproj:Microsoft.Web.WebView2",
                                    confidence=ConfidenceLevel.HIGH,
                                    weight=1.0,
                                    details={"file": cpath, "framework": "dotnet"}
                                )
                                signals.append(sig)
                                return "webview2", "dotnet", f"Found WebView2 package in {f}", signals
                # Limit shallow search
                break
        except Exception:
            pass

        # 4. Check for package.json (Electron / Tauri / Wails)
        pkg_json = os.path.join(search_dir, "package.json")
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                    if "electron" in deps:
                        sig = DetectionSignal(
                            source="manifest",
                            indicator="package.json:dependencies:electron",
                            confidence=ConfidenceLevel.HIGH,
                            weight=1.0,
                            details={"dependencies": list(deps.keys()), "framework": "electron"}
                        )
                        signals.append(sig)
                        return "electron", "electron", "Found 'electron' dependency in package.json", signals
                    if "@tauri-apps/api" in deps or "@tauri-apps/cli" in deps:
                        engine, fw = FrameworkRouter.resolve_framework("tauri")
                        sig = DetectionSignal(
                            source="manifest",
                            indicator="package.json:dependencies:@tauri-apps",
                            confidence=ConfidenceLevel.HIGH,
                            weight=1.0,
                            details={"framework": fw}
                        )
                        signals.append(sig)
                        return engine, fw, f"Found Tauri npm dependencies -> mapped to '{engine}' on {sys.platform}", signals
            except Exception:
                pass

        # 5. Check Python project manifests (pyproject.toml, requirements.txt, setup.py)
        for conf_name in ("pyproject.toml", "requirements.txt", "setup.py", "qt/pyproject.toml"):
            conf_path = os.path.join(search_dir, conf_name)
            if os.path.isfile(conf_path):
                try:
                    with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
                        txt = f.read()
                        if any(k in txt for k in ("PyQt6", "PyQt5", "PySide6", "PySide2", "QtWebEngine", "PyQt6-WebEngine", "aqt")):
                            sig = DetectionSignal(
                                source="manifest",
                                indicator=f"{conf_name}:qt",
                                confidence=ConfidenceLevel.HIGH,
                                weight=1.0,
                                details={"file": conf_path, "framework": "qt"}
                            )
                            signals.append(sig)
                            return "qtwebengine", "qt", f"Found Qt/PyQt dependencies in {conf_name}", signals
                except Exception:
                    pass

        # 5. Check Python script imports if single file
        if os.path.isfile(target_dir_or_file) and target_dir_or_file.endswith(".py"):
            try:
                with open(target_dir_or_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if any(q in content for q in ("QWebEngineView", "PyQt6.QtWebEngineWidgets", "PyQt5.QtWebEngineWidgets", "PySide6.QtWebEngineWidgets")):
                        sig = DetectionSignal(
                            source="source_code",
                            indicator="python:import:QtWebEngineWidgets",
                            confidence=ConfidenceLevel.HIGH,
                            weight=1.0,
                            details={"file": target_dir_or_file, "framework": "qt"}
                        )
                        signals.append(sig)
                        return "qtwebengine", "qt", "Found QtWebEngine imports in Python script", signals
                    if "webview" in content and "create_window" in content:
                        engine, fw = FrameworkRouter.resolve_framework("pywebview")
                        sig = DetectionSignal(
                            source="source_code",
                            indicator="python:import:pywebview",
                            confidence=ConfidenceLevel.HIGH,
                            weight=1.0,
                            details={"file": target_dir_or_file, "framework": fw}
                        )
                        signals.append(sig)
                        return engine, fw, f"Found pywebview usage -> mapped to '{engine}' on {sys.platform}", signals
            except Exception:
                pass

        return None

    @classmethod
    def detect_adapter(cls, target_path_or_pid: Any) -> Tuple[Optional[BaseEngineAdapter], str, str]:
        """
        Performs multi-signal detection. Returns (adapter, confidence, reason).
        Maintains backward compatibility with string-based confidence.
        """
        adapter, engine_info = cls.detect_with_details(target_path_or_pid)
        if adapter and engine_info:
            conf_str = engine_info.confidence.value if isinstance(engine_info.confidence, ConfidenceLevel) else str(engine_info.confidence)
            reason = engine_info.notes[0] if engine_info.notes else f"Detected engine '{adapter.engine_name}'"
            return adapter, conf_str, reason
        return None, "low", "No specific engine signatures matched"

    @classmethod
    def detect_with_details(cls, target_path_or_pid: Any) -> Tuple[Optional[BaseEngineAdapter], Optional[EngineInfo]]:
        """
        Performs multi-signal detection returning (adapter, populated EngineInfo).
        """
        signals: List[DetectionSignal] = []

        # 1. Project level check if path
        if isinstance(target_path_or_pid, str):
            proj_result = cls.detect_project_level(target_path_or_pid)
            if proj_result:
                engine_name, framework, reason, proj_signals = proj_result
                adapter = get_adapter(engine_name)
                if adapter:
                    info = adapter.get_engine_info()
                    info.framework = framework
                    info.confidence = ConfidenceLevel.HIGH
                    info.signals = proj_signals
                    info.notes.append(reason)
                    return adapter, info

        # 2. Iterate registered adapters for runtime / binary detection
        for engine_name in list_adapters():
            adapter = get_adapter(engine_name)
            if adapter and adapter.detect(target_path_or_pid):
                sig = DetectionSignal(
                    source="runtime_signature",
                    indicator=f"adapter:{engine_name}:detect",
                    confidence=ConfidenceLevel.HIGH,
                    weight=1.0,
                    details={"target": str(target_path_or_pid)}
                )
                signals.append(sig)
                info = adapter.get_engine_info()
                info.confidence = ConfidenceLevel.HIGH
                info.signals = signals
                info.notes.append(f"Matched engine signatures for '{engine_name}'")
                return adapter, info

        return None, None

    @classmethod
    def resolve_adapter(
        cls,
        engine_name_or_hint: Optional[str] = None,
        target_path_or_pid: Any = None
    ) -> BaseEngineAdapter:
        """
        Resolves the appropriate adapter based on deterministic priority hierarchy:
        1. Explicit user override / alias
        2. Strong runtime / project detection
        3. Default fallback (qtwebengine)
        """
        # 1. Explicit override or alias
        if engine_name_or_hint and engine_name_or_hint.lower() not in ("auto", "none", ""):
            adapter = get_adapter(engine_name_or_hint)
            if adapter:
                logger.info(f"Resolved engine by explicit hint/alias '{engine_name_or_hint}' -> '{adapter.engine_name}'")
                return adapter
            logger.warning(f"Unknown engine hint '{engine_name_or_hint}'; falling back to detection.")

        # 2. Automatic detection from target path or PID
        if target_path_or_pid is not None:
            adapter, info = cls.detect_with_details(target_path_or_pid)
            if adapter:
                conf = info.confidence.value if info and hasattr(info.confidence, "value") else "high"
                reason = info.notes[0] if info and info.notes else "detected"
                logger.info(f"Auto-detected engine '{adapter.engine_name}' (Confidence: {conf}, Reason: {reason})")
                return adapter

        # 3. Default fallback
        logger.info("Using default adapter (qtwebengine).")
        return get_default_adapter()

